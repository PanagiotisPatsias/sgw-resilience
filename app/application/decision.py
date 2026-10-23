from datetime import datetime, timezone
from uuid import uuid4

from app.domain.errors import Conflict, InvalidEvidence, NotFound
from app.domain.models import ActionPlan, Alert, AuditEntry, Evidence, GroundedAnswer, Task
from app.domain.policies import ACTION_CATALOG, supported_action_catalog
from app.domain.ports import (
    AlertStore,
    AnswerGenerator,
    AssetReader,
    EventStore,
    Retriever,
    WorkStore,
)


class DecisionWorkflow:
    def __init__(
        self,
        assets: AssetReader,
        alerts: AlertStore,
        events: EventStore,
        work: WorkStore,
        retriever: Retriever,
        generator: AnswerGenerator,
    ):
        self.assets = assets
        self.alerts = alerts
        self.events = events
        self.work = work
        self.retriever = retriever
        self.generator = generator

    def context(self, alert_id: str):
        """Collect current operational facts for one alert and its asset."""
        alert = self.alerts.alert(alert_id)
        if alert is None:
            raise NotFound("alert not found")
        asset = self.assets.asset(alert.asset_id)
        if asset is None:
            raise NotFound("asset not found")
        event = None
        if alert.event_id:
            event = self.events.event(alert.event_id)

        related_alerts = []
        for candidate in self.alerts.alerts(asset.id):
            if candidate.id != alert.id and candidate.status != "closed":
                related_alerts.append(candidate.model_dump(mode="json"))

        context = {
            "asset": asset.model_dump(mode="json"),
            "alert": alert.model_dump(mode="json"),
            "event": event.model_dump(mode="json") if event else None,
            "maintenance": [
                record.model_dump(mode="json") for record in self.assets.maintenance(asset.id)
            ],
            "existing_tasks": [task.model_dump(mode="json") for task in self.work.tasks(asset.id)],
            "related_alerts": related_alerts,
        }
        return alert, asset, context

    def draft(self, alert_id: str, question: str, actor: str):
        """Retrieve guidance, validate the generated answer and save a reviewable draft."""
        alert, asset, context = self.context(alert_id)
        if alert.status == "closed":
            raise Conflict("closed alerts cannot create new action plans")
        hazard = "equipment"
        if context["event"]:
            hazard = context["event"]["hazard"]
        evidence = self.retriever.retrieve(question, hazard, asset.asset_type)
        if not evidence:
            raise InvalidEvidence("no sufficiently relevant policy evidence; no plan was created")
        answer = self.generator.generate(question, context, evidence)
        self._validate_generated_answer(answer, evidence)
        plan = ActionPlan(
            id=str(uuid4()),
            alert_id=alert.id,
            alert_version=alert.version,
            answer=answer,
            evidence=evidence,
            context=context,
            generation_mode=self.generator.mode,
            created_at=datetime.now(timezone.utc),
        )
        self.work.save_plan(plan)
        self.work.add_audit(
            AuditEntry(
                id=str(uuid4()),
                action="plan_drafted",
                entity_id=plan.id,
                actor=actor,
                at=plan.created_at,
                details={"alert_version": alert.version, "mode": plan.generation_mode},
            )
        )
        return plan

    def _validate_generated_answer(self, answer: GroundedAnswer, evidence: list[Evidence]) -> None:
        allowed_source_ids = {source.id for source in evidence}
        if answer.insufficient_evidence and answer.actions:
            raise InvalidEvidence("insufficient evidence cannot authorize proposed actions")

        summary_sources_valid = (
            bool(answer.source_ids) and set(answer.source_ids) <= allowed_source_ids
        )
        if not summary_sources_valid:
            raise InvalidEvidence("answer contains missing or invalid source identifiers")

        for action in answer.actions:
            known_action = action.action_code in ACTION_CATALOG
            valid_sources = set(action.source_ids) <= allowed_source_ids
            if not known_action or not valid_sources:
                raise InvalidEvidence("action is outside the catalog or cites unavailable evidence")
            cited_evidence = [source for source in evidence if source.id in action.source_ids]
            if action.action_code not in supported_action_catalog(cited_evidence):
                raise InvalidEvidence(
                    "action is not supported by its cited procedure; retrieve relevant guidance and draft again"
                )

        action_codes = [action.action_code for action in answer.actions]
        if len(set(action_codes)) != len(action_codes):
            raise InvalidEvidence("duplicate action codes are not allowed")

    def approve(self, plan_id: str, codes: list[str], assignee: str, actor: str, due_at: datetime):
        """Approve selected draft actions only while their supporting situation is current."""
        plan = self.work.plan(plan_id)
        if plan is None:
            raise NotFound("plan not found")
        if plan.state == "approved":
            return {
                "idempotent": True,
                "tasks": [task for task in self.work.tasks() if task.id in plan.approved_task_ids],
            }

        alert = self._validate_plan_for_approval(plan)
        now = datetime.now(timezone.utc)
        self._validate_approval_selection(plan, codes, due_at, now)

        approved_tasks = self._create_or_reuse_tasks(
            plan=plan,
            alert=alert,
            codes=codes,
            assignee=assignee,
            actor=actor,
            due_at=due_at,
            now=now,
        )

        plan.state = "approved"
        plan.approved_task_ids = [task.id for task in approved_tasks]
        self.work.save_plan(plan)
        self.work.add_audit(
            AuditEntry(
                id=str(uuid4()),
                action="plan_approved",
                entity_id=plan.id,
                actor=actor,
                at=now,
                details={"task_ids": plan.approved_task_ids},
            )
        )
        return {"idempotent": False, "tasks": approved_tasks}

    def _validate_plan_for_approval(self, plan: ActionPlan) -> Alert:
        """Require a valid draft whose alert and related signals are still current."""
        if plan.state != "draft":
            raise Conflict("only draft plans can be approved")
        self._validate_generated_answer(plan.answer, plan.evidence)
        alert = self.alerts.alert(plan.alert_id)
        if alert is None or alert.version != plan.alert_version or alert.status == "closed":
            raise Conflict("alert changed since drafting; review a fresh plan")
        previous_signals = {
            (related_alert["id"], related_alert["version"])
            for related_alert in plan.context.get("related_alerts", [])
        }
        current_signals = {
            (related_alert.id, related_alert.version)
            for related_alert in self.alerts.alerts(alert.asset_id)
            if related_alert.id != alert.id and related_alert.status != "closed"
        }
        if previous_signals != current_signals:
            raise Conflict("related asset signals changed; review a fresh plan")
        if alert.details.get("outside_current_area") or alert.details.get("expired"):
            raise Conflict("warning no longer applies; review the current situation")
        event = self.events.event(alert.event_id) if alert.event_id else None
        if event and event.valid_until <= datetime.now(timezone.utc):
            raise Conflict("the warning has expired")
        return alert

    def _validate_approval_selection(
        self, plan: ActionPlan, codes: list[str], due_at: datetime, now: datetime
    ) -> None:
        """Require a future deadline and distinct supported actions from the draft."""
        if due_at.tzinfo is None or due_at <= now:
            raise Conflict("task deadline must be a future timezone-aware timestamp")
        proposed_codes = {action.action_code for action in plan.answer.actions}
        selected_codes = set(codes)
        duplicate_codes = len(codes) != len(selected_codes)
        unknown_codes = not selected_codes <= proposed_codes
        if not codes or duplicate_codes or unknown_codes:
            raise InvalidEvidence("select distinct actions from this plan")
        if plan.answer.insufficient_evidence:
            raise InvalidEvidence("this plan has insufficient evidence")

    def _create_or_reuse_tasks(
        self,
        plan: ActionPlan,
        alert: Alert,
        codes: list[str],
        assignee: str,
        actor: str,
        due_at: datetime,
        now: datetime,
    ) -> list[Task]:
        """Reuse active work for the asset or create tasks for approved actions."""
        proposed_actions = {action.action_code: action for action in plan.answer.actions}
        approved_tasks = []
        existing_tasks = self.work.tasks(alert.asset_id)
        for code in codes:
            existing_task = None
            for candidate in existing_tasks:
                if candidate.action_code == code and candidate.status != "completed":
                    existing_task = candidate
                    break

            if existing_task is not None:
                # reuse the existing assignment and deadline rather than creating duplicate work
                approved_tasks.append(existing_task)
                continue
            task = Task(
                id=str(uuid4()),
                plan_id=plan.id,
                alert_id=alert.id,
                asset_id=alert.asset_id,
                action_code=code,
                description=ACTION_CATALOG[code] + ": " + proposed_actions[code].rationale,
                assignee=assignee,
                approved_by=actor,
                due_at=due_at,
                updated_at=now,
            )
            self.work.save_task(task)
            approved_tasks.append(task)
        return approved_tasks

    def disposition(self, alert_id: str, status: str, reason: str, actor: str):
        """Record an operator decision; linked work must be complete before closure."""
        alert = self.alerts.alert(alert_id)
        if alert is None:
            raise NotFound("alert not found")
        linked_task_ids = set()
        for plan in self.work.plans():
            if plan.alert_id == alert.id:
                linked_task_ids.update(plan.approved_task_ids)

        if status == "closed":
            for task in self.work.tasks(alert.asset_id):
                linked_to_alert = task.alert_id == alert.id or task.id in linked_task_ids
                if linked_to_alert and task.status != "completed":
                    raise Conflict("complete linked work before closing the alert")
        alert.status = status
        alert.version += 1
        alert.updated_at = datetime.now(timezone.utc)
        alert.details["operator_disposition"] = reason
        self.alerts.save_alert(alert)
        self.work.add_audit(
            AuditEntry(
                id=str(uuid4()),
                action="alert_" + status,
                entity_id=alert.id,
                actor=actor,
                at=alert.updated_at,
                details={"reason": reason},
            )
        )
        return alert

    def update_task(self, task_id: str, status: str, outcome: str | None, actor: str):
        """Apply a permitted task transition and require an outcome on completion."""
        task = self.work.task(task_id)
        if task is None:
            raise NotFound("task not found")
        allowed_transitions = {
            "pending": {"pending", "in_progress"},
            "in_progress": {"in_progress", "completed"},
            "completed": {"completed"},
        }
        if status not in allowed_transitions[task.status]:
            raise Conflict("invalid task status transition")
        if status == "completed" and not (outcome or "").strip():
            raise InvalidEvidence("completion requires an outcome")
        task.status = status
        task.outcome = outcome
        task.updated_at = datetime.now(timezone.utc)
        self.work.save_task(task)
        self.work.add_audit(
            AuditEntry(
                id=str(uuid4()),
                action="task_" + status,
                entity_id=task.id,
                actor=actor,
                at=task.updated_at,
                details={"outcome": outcome},
            )
        )
        return task
