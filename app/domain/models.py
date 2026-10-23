from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Asset(Model):
    id: str
    name: str
    asset_type: Literal["pump", "substation"]
    region: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    criticality: int = Field(ge=1, le=5)
    backup_available: bool
    hazard_exposure: dict[str, Annotated[float, Field(ge=0, le=1)]]
    updated_at: datetime


class MaintenanceFact(Model):
    id: str
    asset_id: str
    description: str
    state: Literal["open", "completed"]
    priority: Priority
    updated_at: datetime


class WeatherEvent(Model):
    id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)
    hazard: Literal["flood", "heatwave", "wildfire", "hurricane"]
    region: str
    severity: Priority
    issued_at: datetime
    valid_from: datetime
    valid_until: datetime
    bbox: tuple[float, float, float, float]
    source: str
    synthetic: bool = True

    @field_validator("issued_at", "valid_from", "valid_until")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def check_interval(self):
        west, south, east, north = self.bbox
        if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
            raise ValueError("invalid bounding box")
        if self.valid_until <= self.valid_from or self.issued_at > self.valid_until:
            raise ValueError("invalid event validity interval")
        return self


class RiskAssessment(Model):
    asset_id: str
    score: float | None
    priority: Priority
    reasons: list[str]
    data_quality: list[str]


class Alert(Model):
    id: str
    dedupe_key: str
    asset_id: str
    kind: Literal["weather", "anomaly"]
    event_id: str | None = None
    version: int = 1
    priority: Priority
    status: Literal["open", "acknowledged", "closed"] = "open"
    updated_at: datetime
    details: dict


class TelemetryPoint(Model):
    timestamp: datetime
    asset_id: str
    running: bool
    speed_pct: float = Field(ge=0, le=100)
    current_a: float = Field(ge=0, le=200)
    flow_m3h: float = Field(ge=0, le=500)
    motor_temp_c: float = Field(ge=-30, le=150)

    @field_validator("timestamp")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value


class FeatureWindow(Model):
    asset_id: str
    window_end: datetime
    values: list[float]


class AnomalyResult(Model):
    asset_id: str
    window_end: datetime
    score: float
    threshold: float
    exceeds_threshold: bool
    model_version: str
    input_fingerprint: str
    feature_errors: dict[str, float]


class Evidence(Model):
    id: str
    document: str
    section: str
    version: str
    text: str
    hazard: str
    asset_type: str
    score: float = 0


class ProposedAction(Model):
    action_code: str
    rationale: str
    source_ids: list[str] = Field(min_length=1)


class GroundedAnswer(Model):
    summary: str
    source_ids: list[str]
    missing_information: list[str]
    insufficient_evidence: bool
    actions: list[ProposedAction]


class ActionPlan(Model):
    id: str
    alert_id: str
    alert_version: int
    state: Literal["draft", "approved", "rejected"] = "draft"
    answer: GroundedAnswer
    evidence: list[Evidence]
    context: dict
    generation_mode: str
    created_at: datetime
    approved_task_ids: list[str] = Field(default_factory=list)


class Task(Model):
    id: str
    plan_id: str | None
    alert_id: str | None
    asset_id: str
    action_code: str
    description: str
    assignee: str
    approved_by: str
    due_at: datetime
    status: Literal["pending", "in_progress", "completed"] = "pending"
    outcome: str | None = None
    updated_at: datetime


class AuditEntry(Model):
    id: str
    action: str
    entity_id: str
    actor: str
    at: datetime
    details: dict
