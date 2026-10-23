from datetime import datetime, timezone
from uuid import uuid4

from app.domain.errors import Conflict
from app.domain.models import Alert, AuditEntry, Priority, RiskAssessment, WeatherEvent
from app.domain.policies import RiskPolicy, is_current
from app.domain.ports import AlertStore, AssetReader, EventStore, WorkStore


class WeatherWorkflow:
    def __init__(
        self,
        assets: AssetReader,
        events: EventStore,
        alerts: AlertStore,
        audit: WorkStore,
        policy: RiskPolicy,
    ):
        self.assets = assets
        self.events = events
        self.alerts = alerts
        self.audit = audit
        self.policy = policy

    def ingest(self, event: WeatherEvent, actor: str, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        previous_event = self.events.event(event.id)
        self._validate_event_revision(event, previous_event)
        if event == previous_event:
            return {
                "event": previous_event,
                "idempotent": True,
                "alerts": [a for a in self.alerts.alerts() if a.event_id == event.id],
            }

        self.events.save_event(event)
        processed_alerts = []
        for asset in self.assets.assets():
            assessment = self.policy.assess(
                asset=asset, event=event, maintenance=self.assets.maintenance(asset.id)
            )
            dedupe_key = f"weather:{event.id}:{asset.id}"
            existing_alert = self.alerts.by_dedupe_key(dedupe_key)
            if assessment is None and existing_alert is None:
                continue
            alert = self._build_weather_alert(
                event=event,
                asset_id=asset.id,
                assessment=assessment,
                existing_alert=existing_alert,
                dedupe_key=dedupe_key,
                now=now,
            )
            self.alerts.save_alert(alert)
            processed_alerts.append(alert)
        self.audit.add_audit(
            AuditEntry(
                id=str(uuid4()),
                action="weather_revision_ingested",
                entity_id=event.id,
                actor=actor,
                at=now,
                details={"revision": event.revision, "affected_alerts": len(processed_alerts)},
            )
        )
        return {"event": event, "idempotent": False, "alerts": processed_alerts}

    def _validate_event_revision(
        self, event: WeatherEvent, previous_event: WeatherEvent | None
    ) -> None:
        """Accept identical replays and reject stale or conflicting revisions."""
        if previous_event is None:
            return
        if event.revision <= previous_event.revision:
            if event != previous_event:
                raise Conflict("event revision is stale or conflicts with an existing revision")
            return
        if event.issued_at < previous_event.issued_at:
            raise Conflict("a newer revision cannot have an older issue time")

    def _build_weather_alert(
        self,
        event: WeatherEvent,
        asset_id: str,
        assessment: RiskAssessment | None,
        existing_alert: Alert | None,
        dedupe_key: str,
        now: datetime,
    ) -> Alert:
        """Build the alert details and preserve or reopen its recorded status."""
        details = {
            "event_revision": event.revision,
            "source": event.source,
            "forecast_valid_until": event.valid_until.isoformat(),
            "outside_current_area": assessment is None,
            "expired": not is_current(event, now),
        }
        if assessment:
            details.update(assessment.model_dump(mode="json"))
        else:
            details.update(
                score=None,
                reasons=["asset is outside the updated warning area"],
                data_quality=[],
            )
        alert = Alert(
            id=existing_alert.id if existing_alert else str(uuid4()),
            dedupe_key=dedupe_key,
            asset_id=asset_id,
            event_id=event.id,
            kind="weather",
            version=existing_alert.version + 1 if existing_alert else 1,
            priority=assessment.priority if assessment else Priority.LOW,
            status=existing_alert.status if existing_alert else "open",
            updated_at=now,
            details=details,
        )
        if (
            existing_alert
            and existing_alert.status == "closed"
            and assessment
            and is_current(event, now)
        ):
            alert.status = "open"
        return alert
