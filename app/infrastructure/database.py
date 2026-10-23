import hashlib
from contextlib import contextmanager

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    select,
    text,
)
from sqlalchemy.orm import Session, sessionmaker

from app.domain.models import (
    ActionPlan,
    Alert,
    AnomalyResult,
    Asset,
    AuditEntry,
    MaintenanceFact,
    Task,
    WeatherEvent,
)

metadata = MetaData()
assets = Table(
    "assets",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("payload", JSON, nullable=False),
)
maintenance = Table(
    "maintenance",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("asset_id", String(100), index=True),
    Column("payload", JSON, nullable=False),
)
events = Table(
    "weather_events",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("payload", JSON, nullable=False),
)
alerts = Table(
    "alerts",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("dedupe_key", String(250), unique=True, nullable=False),
    Column("asset_id", String(100), index=True),
    Column("payload", JSON, nullable=False),
)
plans = Table(
    "action_plans",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("payload", JSON, nullable=False),
)
tasks = Table(
    "tasks",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("asset_id", String(100), index=True),
    Column("plan_id", String(100)),
    Column("action_code", String(100)),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("plan_id", "action_code", name="uq_plan_action"),
)
audit = Table(
    "audit_entries",
    metadata,
    Column("id", String(100), primary_key=True),
    Column("payload", JSON, nullable=False),
)
observations = Table(
    "observations",
    metadata,
    Column("id", String(250), primary_key=True),
    Column("asset_id", String(100), index=True),
    Column("at", DateTime(timezone=True)),
    Column("payload", JSON, nullable=False),
)


class Database:
    def __init__(self, url: str):
        self.engine = create_engine(url, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self):
        metadata.create_all(self.engine)

    @contextmanager
    def transaction(self):
        with self.sessions.begin() as session:
            yield SqlRepository(session)


class SqlRepository:
    def __init__(self, session: Session):
        self.session = session

    def clear_demo_data(self):
        """Clear prototype records within the caller's transaction."""
        for table in reversed(metadata.sorted_tables):
            self.session.execute(table.delete())

    def lock(self, key: str):
        if self.session.bind.dialect.name == "postgresql":
            value = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
            self.session.execute(text("select pg_advisory_xact_lock(:key)"), {"key": value})

    def _one(self, table, identifier, model, lock=False):
        query = select(table.c.payload).where(table.c.id == identifier)
        if lock:
            query = query.with_for_update()
        payload = self.session.execute(query).scalar_one_or_none()
        return model.model_validate(payload) if payload is not None else None

    def _all(self, table, model, asset_id=None):
        query = select(table.c.payload).order_by(table.c.id)
        if asset_id is not None:
            query = query.where(table.c.asset_id == asset_id)
        return [model.model_validate(row) for row in self.session.execute(query).scalars()]

    def _save(self, table, item, **columns):
        values = {"payload": item.model_dump(mode="json"), **columns}
        exists = self.session.execute(select(table.c.id).where(table.c.id == item.id)).first()
        if exists:
            self.session.execute(table.update().where(table.c.id == item.id).values(**values))
        else:
            self.session.execute(table.insert().values(id=item.id, **values))

    def assets(self):
        return self._all(assets, Asset)

    def asset(self, asset_id):
        return self._one(assets, asset_id, Asset)

    def save_asset(self, asset):
        self._save(assets, asset)

    def maintenance(self, asset_id):
        return self._all(maintenance, MaintenanceFact, asset_id)

    def save_maintenance(self, fact):
        self._save(maintenance, fact, asset_id=fact.asset_id)

    def event(self, event_id):
        return self._one(events, event_id, WeatherEvent, lock=True)

    def events(self):
        return self._all(events, WeatherEvent)

    def save_event(self, event):
        self._save(events, event)

    def alert(self, alert_id):
        return self._one(alerts, alert_id, Alert, lock=True)

    def alerts(self, asset_id=None):
        return self._all(alerts, Alert, asset_id)

    def by_dedupe_key(self, key):
        identifier = self.session.execute(
            select(alerts.c.id).where(alerts.c.dedupe_key == key)
        ).scalar_one_or_none()
        return self.alert(identifier) if identifier else None

    def save_alert(self, alert):
        self._save(alerts, alert, dedupe_key=alert.dedupe_key, asset_id=alert.asset_id)

    def plan(self, plan_id):
        return self._one(plans, plan_id, ActionPlan, lock=True)

    def plans(self):
        return self._all(plans, ActionPlan)

    def save_plan(self, plan):
        self._save(plans, plan)

    def tasks(self, asset_id=None):
        return self._all(tasks, Task, asset_id)

    def task(self, task_id):
        return self._one(tasks, task_id, Task, lock=True)

    def save_task(self, task):
        self._save(
            tasks, task, asset_id=task.asset_id, plan_id=task.plan_id, action_code=task.action_code
        )

    def add_audit(self, entry):
        self._save(audit, entry)

    def audit(self):
        return self._all(audit, AuditEntry)

    def observation(self, asset_id, at, version):
        identifier = f"{asset_id}:{at.isoformat()}:{version}"
        return self._one(observations, identifier, AnomalyResult)

    def observations(self, asset_id):
        return sorted(self._all(observations, AnomalyResult, asset_id), key=lambda r: r.window_end)

    def save_observation(self, result):
        identifier = f"{result.asset_id}:{result.window_end.isoformat()}:{result.model_version}"
        self.session.execute(
            observations.insert().values(
                id=identifier,
                asset_id=result.asset_id,
                at=result.window_end,
                payload=result.model_dump(mode="json"),
            )
        )
