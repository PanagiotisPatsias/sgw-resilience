import re
from datetime import datetime, timedelta

from app.domain.models import (
    Asset,
    Evidence,
    MaintenanceFact,
    Priority,
    RiskAssessment,
    WeatherEvent,
)

ACTION_CATALOG = {
    "verify_flood_defences": "Verify flood defences with an authorized site team",
    "review_standby_capacity": "Review standby capacity with the operations supervisor",
    "verify_access": "Confirm site access through the field operations team",
    "review_telemetry": "Review telemetry and sensor validity with an engineer",
    "inspect_equipment": "Arrange an authorized equipment inspection",
    "confirm_missing_data": "Confirm missing or stale asset information",
}


def supported_action_catalog(evidence: list[Evidence]) -> dict[str, str]:
    """Demo procedures explicitly name the action codes they support."""
    return {
        code: description
        for code, description in ACTION_CATALOG.items()
        if any(re.search(rf"\b{re.escape(code)}\b", source.text) for source in evidence)
    }


class RiskPolicy:
    def assess(
        self, asset: Asset, event: WeatherEvent, maintenance: list[MaintenanceFact]
    ) -> RiskAssessment | None:
        west, south, east, north = event.bbox
        inside_warning_area = west <= asset.longitude <= east and south <= asset.latitude <= north
        if asset.region != event.region or not inside_warning_area:
            return None
        quality = []
        if event.issued_at - asset.updated_at > timedelta(hours=24):
            quality.append("asset information is older than 24 hours")
        exposure = asset.hazard_exposure.get(event.hazard)
        if exposure is None:
            return RiskAssessment(
                asset_id=asset.id,
                score=None,
                priority=Priority.HIGH,
                reasons=["exposure is unknown; engineering review required"],
                data_quality=quality + ["missing exposure mapping"],
            )
        open_items = [m for m in maintenance if m.state == "open"]
        has_urgent_maintenance = any(
            item.priority in (Priority.HIGH, Priority.CRITICAL) for item in open_items
        )
        severity_weight = {"low": 0.3, "medium": 0.55, "high": 0.8, "critical": 1.0}[event.severity]
        maintenance_factor = 0.2 if has_urgent_maintenance else 0.0
        backup_factor = 0.0 if asset.backup_available else 0.1
        risk_factor = 1 + maintenance_factor + backup_factor
        score = round(
            min(100, 100 * severity_weight * exposure * asset.criticality / 5 * risk_factor), 1
        )
        reasons = [
            f"{event.severity} {event.hazard} warning; exposure index {exposure:.2f}",
            f"business criticality {asset.criticality}/5",
            f"{len(open_items)} open maintenance item(s)",
        ]
        if not asset.backup_available:
            reasons.append("no standby capacity recorded")
        return RiskAssessment(
            asset_id=asset.id,
            score=score,
            priority=priority_for(score),
            reasons=reasons,
            data_quality=quality,
        )


def priority_for(score: float) -> Priority:
    if score >= 70:
        return Priority.CRITICAL
    if score >= 45:
        return Priority.HIGH
    if score >= 20:
        return Priority.MEDIUM
    return Priority.LOW


def is_current(event: WeatherEvent, now: datetime) -> bool:
    return event.issued_at <= now < event.valid_until
