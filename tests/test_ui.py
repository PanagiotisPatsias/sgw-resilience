import importlib
import json
from datetime import datetime, timedelta

import pytest

from app.config import ROOT

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def workspace(client, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "ui"))
    api_client = importlib.import_module("client")

    def request(self, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.is_error:
            raise RuntimeError(f"{response.status_code}: {response.json()['detail']}")
        return response.json()

    monkeypatch.setattr(api_client.ApiClient, "request", request)
    return AppTest.from_file(str(ROOT / "ui/dashboard.py")).run(timeout=30)


def widget(elements, label):
    return next(element for element in elements if element.label == label)


def test_weather_selection_survives_new_anomaly_and_warning_revision(client, monkeypatch):
    asset_id = "S-13"
    client.post("/demo/weather/initial")
    weather = next(a for a in client.get("/alerts").json() if a["asset_id"] == asset_id)
    app = workspace(client, monkeypatch)
    app.session_state["demo_reset_complete"] = True
    app.run(timeout=30)
    widget(app.button, "Load telemetry sample").click().run(timeout=30)
    assert len(app.session_state["telemetry"]) == 120
    assert not app.exception and not app.error
    assert widget(app.selectbox, "Alert").value is None
    widget(app.selectbox, "Alert").select(weather["id"]).run(timeout=30)
    widget(app.radio, "Synthetic telemetry scenario").set_value("anomaly").run(timeout=30)
    widget(app.button, "Load telemetry sample").click().run(timeout=30)
    widget(app.button, "Evaluate condition").click().run(timeout=30)
    assert widget(app.selectbox, "Alert").value == weather["id"]
    widget(app.button, "Draft grounded action plan").click().run(timeout=30)
    assert not app.exception and not app.error
    plans = client.get("/plans").json()
    assert len(plans) == 1
    assert plans[0]["alert_id"] == weather["id"]
    assert plans[0]["context"]["alert"]["kind"] == "weather"
    assert plans[0]["context"]["asset"]["id"] == asset_id

    client.post("/demo/weather/update")
    widget(app.button, "Retrieve source evidence").click().run(timeout=30)
    assert widget(app.selectbox, "Alert").value == weather["id"]
    assert not app.exception and not app.error

    anomaly = next(a for a in client.get("/alerts").json() if a["kind"] == "anomaly")
    widget(app.selectbox, "Alert").select(anomaly["id"]).run(timeout=30)
    widget(app.button, "Draft grounded action plan").click().run(timeout=30)
    assert not app.exception and not app.error
    assert widget(app.selectbox, "Alert").value == anomaly["id"]
    assert {p["alert_id"] for p in client.get("/plans").json()} == {weather["id"], anomaly["id"]}


def test_approval_task_completion_and_disposition_keep_the_selected_records(client, monkeypatch):
    client.post("/demo/weather/initial")
    weather = next(a for a in client.get("/alerts").json() if a["asset_id"] == "P-02")
    app = workspace(client, monkeypatch)
    widget(app.selectbox, "Alert").select(weather["id"]).run(timeout=30)
    widget(app.button, "Draft grounded action plan").click().run(timeout=30)
    widget(app.multiselect, "Actions to approve").set_value(["verify_flood_defences"])
    widget(app.checkbox, "I reviewed the facts, sources and existing work").check()
    widget(app.button, "Approve selected actions").click().run(timeout=30)
    assert not app.exception and not app.error
    task = next(t for t in client.get("/tasks").json() if t["plan_id"] is not None)
    assert widget(app.button, "Save task update").disabled
    widget(app.selectbox, "Task").select(task["id"]).run(timeout=30)
    widget(app.selectbox, "New status").set_value("in_progress")
    widget(app.button, "Save task update").click().run(timeout=30)
    assert widget(app.selectbox, "Task").value == task["id"]
    widget(app.selectbox, "New status").set_value("completed")
    widget(app.text_area, "Inspection outcome / update").set_value(
        "Inspection reviewed by engineer"
    )
    widget(app.button, "Save task update").click().run(timeout=30)
    assert widget(app.selectbox, "Task").value == task["id"]
    assert (
        next(t for t in client.get("/tasks").json() if t["id"] == task["id"])["status"]
        == "completed"
    )
    widget(app.selectbox, "Reviewed alert").select(weather["id"]).run(timeout=30)
    widget(app.selectbox, "Disposition").set_value("closed")
    widget(app.text_area, "Reason / engineer review").set_value(
        "Response work reviewed and completed"
    )
    widget(app.button, "Record disposition").click().run(timeout=30)
    assert not app.exception and not app.error
    assert (
        next(a for a in client.get("/alerts").json() if a["id"] == weather["id"])["status"]
        == "closed"
    )
    assert widget(app.selectbox, "Alert").value is None


def test_warning_map_expands_and_keeps_closed_assets_exposed(client, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "ui"))
    presentation = importlib.import_module("presentation")
    client.post("/demo/weather/initial")
    assets = client.get("/assets").json()

    def map_layers(now=None):
        deck = presentation.weather_map(
            assets, client.get("/events").json(), client.get("/alerts").json(), now=now
        )
        return {layer["id"]: layer for layer in json.loads(deck.to_json())["layers"]}

    initial = map_layers()
    points = {p["asset_id"]: p for p in initial["assets"]["data"]}
    assert points["P-02"]["warning"] == "Inside current warning"
    assert points["P-04"]["warning"] == points["P-01"]["warning"] == "Outside current warning"
    initial_polygon = initial["warning-area"]["data"][0]["polygon"]

    client.post("/demo/weather/update")
    expanded = map_layers()
    expanded_polygon = expanded["warning-area"]["data"][0]["polygon"]
    assert min(p[0] for p in expanded_polygon) < min(p[0] for p in initial_polygon)
    assert max(p[0] for p in expanded_polygon) > max(p[0] for p in initial_polygon)
    assert min(p[1] for p in expanded_polygon) < min(p[1] for p in initial_polygon)
    assert max(p[1] for p in expanded_polygon) > max(p[1] for p in initial_polygon)
    points = {p["asset_id"]: p for p in expanded["assets"]["data"]}
    assert points["P-04"]["warning"] == "Inside current warning"
    assert points["P-01"]["warning"] == "Outside current warning"

    alert = next(a for a in client.get("/alerts").json() if a["asset_id"] == "P-02")
    client.patch(
        f"/alerts/{alert['id']}",
        json={"status": "closed", "reason": "response work reviewed", "actor": "engineer"},
    )
    closed = {p["asset_id"]: p for p in map_layers()["assets"]["data"]}["P-02"]
    assert closed["status"] == "Closed"
    assert closed["warning"] == "Inside current warning"
    assert closed["color"] == points["P-02"]["color"]

    event = client.get("/events").json()[0]
    expired = map_layers(
        datetime.fromisoformat(event["valid_until"].replace("Z", "+00:00")) + timedelta(seconds=1)
    )
    assert not expired["warning-area"]["data"]
    assert all(p["warning"] == "No current warning" for p in expired["assets"]["data"])
