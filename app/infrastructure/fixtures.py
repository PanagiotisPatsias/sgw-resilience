import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.domain.models import Asset, MaintenanceFact, Task, WeatherEvent

DATA = Path(__file__).resolve().parents[2] / "data"


def seed_repository(repo, now=None):
    if repo.assets():
        return
    now = now or datetime.now(timezone.utc)
    for row in json.loads((DATA / "gis/assets.json").read_text()):
        age = row.pop("updated_hours_ago")
        repo.save_asset(Asset(**row, updated_at=now - timedelta(hours=age)))
    for row in json.loads((DATA / "maintenance/records.json").read_text()):
        repo.save_maintenance(MaintenanceFact(**row, updated_at=now - timedelta(hours=2)))
    for row in json.loads((DATA / "field_operations/tasks.json").read_text()):
        repo.save_task(Task(**row, due_at=now + timedelta(hours=6), updated_at=now))


def weather_fixture(name: str, previous=None, now=None):
    now = now or datetime.now(timezone.utc)
    source_path = DATA / f"weather/{name}.json"
    warning_data = json.loads(source_path.read_text())
    if previous and previous.revision >= warning_data["revision"]:
        return previous
    return WeatherEvent(
        **warning_data, issued_at=now, valid_from=now, valid_until=now + timedelta(hours=24)
    )
