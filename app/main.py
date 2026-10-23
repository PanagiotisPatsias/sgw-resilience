import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from app.config import Settings
from app.container import Container
from app.domain.errors import DomainError, InvalidEvidence, NotFound
from app.domain.models import Model, TelemetryPoint, WeatherEvent
from app.infrastructure.fixtures import seed_repository, weather_fixture
from app.infrastructure.simulation import pump_run

logger = logging.getLogger(__name__)


class DraftInput(Model):
    alert_id: str
    question: str = Field(min_length=3, max_length=1000)
    actor: str = Field(min_length=1, max_length=100)


class ApprovalInput(Model):
    action_codes: list[str] = Field(min_length=1, max_length=6)
    assignee: str = Field(min_length=1, max_length=100)
    actor: str = Field(min_length=1, max_length=100)
    due_at: datetime


class TaskUpdate(Model):
    status: Literal["pending", "in_progress", "completed"]
    outcome: str | None = Field(default=None, max_length=2000)
    actor: str = Field(min_length=1, max_length=100)


class DispositionInput(Model):
    status: Literal["acknowledged", "closed"]
    reason: str = Field(min_length=3, max_length=1000)
    actor: str = Field(min_length=1, max_length=100)


class TelemetryBatch(Model):
    points: list[TelemetryPoint] = Field(min_length=15, max_length=500)
    actor: str = Field(min_length=1, max_length=100)


class DemoResetInput(Model):
    confirm: Literal[True]


def create_app(settings: Settings | None = None, container: Container | None = None):
    settings = settings or Settings()
    container = container or Container(settings)

    @asynccontextmanager
    async def lifespan(app):
        container.database.initialize()
        if settings.auto_seed:
            with container.database.transaction() as repo:
                repo.lock("seed")
                seed_repository(repo)
        yield
        container.database.engine.dispose()

    app = FastAPI(title="SGW Resilience", version="1.0.0", lifespan=lifespan)
    app.state.container = container

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        start = time.monotonic()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            1000 * (time.monotonic() - start),
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    def authorized(x_api_key: str = Header(default="")):
        if not settings.demo_api_token or not secrets.compare_digest(
            x_api_key, settings.demo_api_token
        ):
            from fastapi import HTTPException

            raise HTTPException(401, "invalid demo API token")

    def repository(_=Depends(authorized)):
        with container.database.transaction() as repo:
            yield repo

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "synthetic_demo", "llm_mode": container.generator.mode}

    @app.get("/assets")
    def assets(repo=Depends(repository)):
        return repo.assets()

    @app.get("/assets/{asset_id}/context")
    def asset_context(asset_id: str, repo=Depends(repository)):
        asset = repo.asset(asset_id)
        if asset is None:
            raise NotFound("asset not found")
        return {
            "asset": asset,
            "maintenance": repo.maintenance(asset_id),
            "alerts": repo.alerts(asset_id),
            "tasks": repo.tasks(asset_id),
        }

    @app.get("/events")
    def events(repo=Depends(repository)):
        return repo.events()

    @app.post("/events")
    def ingest_event(event: WeatherEvent, actor: str = "feed_adapter", repo=Depends(repository)):
        repo.lock("weather:" + event.id)
        workflows = container.services(repo)
        return workflows.weather.ingest(event=event, actor=actor)

    @app.post("/demo/weather/{scenario}")
    def demo_weather(scenario: Literal["initial", "update"], repo=Depends(repository)):
        repo.lock("weather:DEMO-FLOOD-001")
        previous_event = repo.event("DEMO-FLOOD-001")
        event = weather_fixture(name=scenario, previous=previous_event)
        workflows = container.services(repo)
        return workflows.weather.ingest(event=event, actor="demo_feed")

    @app.post("/demo/reset")
    def reset_demo(data: DemoResetInput, repo=Depends(repository)):
        repo.lock("seed")
        repo.clear_demo_data()
        seed_repository(repo)
        return {"status": "reset", "assets": len(repo.assets()), "tasks": len(repo.tasks())}

    @app.get("/demo/telemetry/{scenario}")
    def demo_telemetry(scenario: Literal["normal", "anomaly"], _=Depends(authorized)):
        end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        end -= timedelta(minutes=end.minute % 5)
        if scenario == "normal":
            end -= timedelta(hours=3)
        start = end - timedelta(minutes=119)
        return {
            "points": pump_run(888, start=start, anomalous=scenario == "anomaly"),
            "synthetic": True,
            "asset_id": "P-02",
        }

    @app.post("/telemetry/evaluate")
    def evaluate_telemetry(data: TelemetryBatch, repo=Depends(repository)):
        repo.lock("telemetry:" + data.points[0].asset_id)
        now = datetime.now(timezone.utc)
        if any(p.timestamp > now for p in data.points):
            raise InvalidEvidence("future telemetry timestamps are not accepted")
        workflows = container.services(repo)
        return workflows.condition.evaluate(points=data.points, actor=data.actor)

    @app.get("/telemetry/{asset_id}/observations")
    def observations(asset_id: str, repo=Depends(repository)):
        return repo.observations(asset_id)

    @app.get("/model/card")
    def model_card(_=Depends(authorized)):
        return container.detector.info()

    @app.get("/alerts")
    def alerts(repo=Depends(repository)):
        return sorted(repo.alerts(), key=lambda a: a.updated_at, reverse=True)

    @app.patch("/alerts/{alert_id}")
    def disposition(alert_id: str, data: DispositionInput, repo=Depends(repository)):
        workflows = container.services(repo)
        return workflows.decision.disposition(
            alert_id=alert_id, status=data.status, reason=data.reason, actor=data.actor
        )

    @app.post("/evidence")
    def evidence(data: DraftInput, repo=Depends(repository)):
        workflows = container.services(repo)
        _, asset, context = workflows.decision.context(data.alert_id)
        hazard = context["event"]["hazard"] if context["event"] else "equipment"
        return container.retriever.retrieve(data.question, hazard, asset.asset_type)

    @app.post("/plans")
    def draft(data: DraftInput, repo=Depends(repository)):
        workflows = container.services(repo)
        return workflows.decision.draft(
            alert_id=data.alert_id, question=data.question, actor=data.actor
        )

    @app.get("/plans")
    def plans(repo=Depends(repository)):
        return repo.plans()

    @app.post("/plans/{plan_id}/approve")
    def approve(plan_id: str, data: ApprovalInput, repo=Depends(repository)):
        repo.lock("approve:" + plan_id)
        workflows = container.services(repo)
        return workflows.decision.approve(
            plan_id=plan_id,
            codes=data.action_codes,
            assignee=data.assignee,
            actor=data.actor,
            due_at=data.due_at,
        )

    @app.get("/tasks")
    def tasks(repo=Depends(repository)):
        return repo.tasks()

    @app.patch("/tasks/{task_id}")
    def update_task(task_id: str, data: TaskUpdate, repo=Depends(repository)):
        workflows = container.services(repo)
        return workflows.decision.update_task(
            task_id=task_id, status=data.status, outcome=data.outcome, actor=data.actor
        )

    @app.get("/audit")
    def audit(repo=Depends(repository)):
        return sorted(repo.audit(), key=lambda a: a.at, reverse=True)

    def snapshot(repo):
        now = datetime.now(timezone.utc)
        active = [a for a in repo.alerts() if a.status != "closed"]
        return {
            "as_of": now.isoformat(),
            "assets": len(repo.assets()),
            "active_alerts": [a.model_dump(mode="json") for a in active],
            "tasks": [t.model_dump(mode="json") for t in repo.tasks()],
            "events": [e.model_dump(mode="json") for e in repo.events()],
            "limitations": [
                "synthetic sources",
                "illustrative priority rules",
                "anomaly scores are not failure forecasts",
            ],
        }

    @app.get("/overview")
    def overview(repo=Depends(repository)):
        return snapshot(repo)

    @app.post("/briefing")
    def briefing(repo=Depends(repository)):
        facts = snapshot(repo)
        evidence = container.retriever.retrieve(
            "leadership briefing report open work owners uncertainty latest warning", "all", "all"
        )
        if not evidence:
            raise InvalidEvidence("no briefing guidance found")
        answer = container.generator.generate(
            "Summarize the supplied operational snapshot for leadership. Do not propose new actions.",
            facts,
            evidence,
        )
        if (
            not set(answer.source_ids) <= {e.id for e in evidence}
            or not answer.source_ids
            or answer.actions
        ):
            raise InvalidEvidence("invalid briefing citations or unexpected operational actions")
        return {
            "answer": answer,
            "evidence": evidence,
            "snapshot": facts,
            "mode": container.generator.mode,
        }

    return app


app = create_app()
