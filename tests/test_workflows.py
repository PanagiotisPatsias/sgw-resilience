from datetime import datetime, timedelta, timezone


def weather_alert(client):
    response = client.post("/demo/weather/initial")
    assert response.status_code == 200, response.text
    return next(a for a in response.json()["alerts"] if a["asset_id"] == "P-02")


def draft(client, alert):
    response = client.post(
        "/plans",
        json={
            "alert_id": alert["id"],
            "question": "Review flood preparedness",
            "actor": "operator",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def approval(action_code="verify_flood_defences"):
    return {
        "action_codes": [action_code],
        "assignee": "Team A",
        "actor": "reviewer",
        "due_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
    }


def test_demo_reset_restores_fixtures_and_allows_a_fresh_run(configured):
    client, container = configured
    client.headers.update({"x-api-key": "test-token"})
    original_assets = client.get("/assets").json()
    original_task = client.get("/tasks").json()[0]
    original_maintenance = client.get("/assets/P-02/context").json()["maintenance"]
    plan = draft(client, weather_alert(client))
    assert client.post(f"/plans/{plan['id']}/approve", json=approval()).status_code == 200
    assert client.post("/demo/weather/update").status_code == 200
    points = client.get("/demo/telemetry/anomaly").json()["points"]
    assert (
        client.post("/telemetry/evaluate", json={"points": points, "actor": "engineer"}).status_code
        == 200
    )
    with container.database.transaction() as repo:
        asset = repo.asset("P-02")
        asset.name = "Changed during the demo"
        repo.save_asset(asset)
        fact = repo.maintenance("P-02")[0]
        fact.state = "completed"
        repo.save_maintenance(fact)

    response = client.post("/demo/reset", json={"confirm": True})
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "reset", "assets": len(original_assets), "tasks": 1}
    for path in ("/events", "/alerts", "/plans", "/audit", "/telemetry/P-02/observations"):
        assert client.get(path).json() == [], path
    restored_assets = client.get("/assets").json()
    assert [{k: v for k, v in a.items() if k != "updated_at"} for a in restored_assets] == [
        {k: v for k, v in a.items() if k != "updated_at"} for a in original_assets
    ]
    context = client.get("/assets/P-02/context").json()
    assert [{k: v for k, v in m.items() if k != "updated_at"} for m in context["maintenance"]] == [
        {k: v for k, v in m.items() if k != "updated_at"} for m in original_maintenance
    ]
    restored_tasks = client.get("/tasks").json()
    assert len(restored_tasks) == 1
    assert restored_tasks[0]["id"] == original_task["id"]
    assert restored_tasks[0]["status"] == "pending"
    assert restored_tasks[0]["plan_id"] is None
    assert datetime.fromisoformat(restored_tasks[0]["due_at"]) > datetime.now(timezone.utc)
    assert weather_alert(client)["version"] == 1
    assert client.get("/events").json()[0]["revision"] == 1
    assert client.post("/demo/reset", json={"confirm": True}).status_code == 200
    assert len(client.get("/tasks").json()) == 1


def test_demo_reset_requires_authentication_and_confirmation(configured):
    client, _ = configured
    assert client.get("/health").status_code == 200
    assert client.get("/assets").status_code == 401
    assert client.post("/demo/reset", json={"confirm": True}).status_code == 401
    client.headers.update({"x-api-key": "test-token"})
    weather_alert(client)
    before = client.get("/alerts").json()
    for body in ({}, {"confirm": False}):
        assert client.post("/demo/reset", json=body).status_code == 422
        assert client.get("/alerts").json() == before


def test_weather_workflow_handles_replay_approval_and_completion(client):
    alert = weather_alert(client)
    alerts_before_replay = client.get("/alerts").json()
    assert client.post("/demo/weather/initial").json()["idempotent"]
    assert client.get("/alerts").json() == alerts_before_replay

    plan = draft(client, alert)
    assert len(client.get("/tasks").json()) == 1
    response = client.post(f"/plans/{plan['id']}/approve", json=approval())
    assert response.status_code == 200, response.text
    task = response.json()["tasks"][0]
    assert task["approved_by"] == "reviewer"
    tasks_before_replay = client.get("/tasks").json()
    approval_replay = client.post(f"/plans/{plan['id']}/approve", json=approval()).json()
    assert approval_replay["idempotent"]
    assert approval_replay["tasks"][0]["id"] == task["id"]
    assert client.get("/tasks").json() == tasks_before_replay
    assert (
        client.patch(
            f"/tasks/{task['id']}",
            json={"status": "completed", "outcome": "done", "actor": "operator"},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/tasks/{task['id']}", json={"status": "in_progress", "actor": "operator"}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/tasks/{task['id']}", json={"status": "completed", "actor": "operator"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/tasks/{task['id']}",
            json={"status": "completed", "outcome": "inspection verified", "actor": "operator"},
        ).status_code
        == 200
    )
    audit = client.get("/audit").json()
    assert {"plan_approved", "task_completed"} <= {r["action"] for r in audit}


def test_new_warning_invalidates_old_draft(client):
    plan = draft(client, weather_alert(client))
    assert client.post("/demo/weather/update").status_code == 200
    assert client.post(f"/plans/{plan['id']}/approve", json=approval()).status_code == 409
    alerts = client.get("/alerts").json()
    assert len({a["dedupe_key"] for a in alerts}) == len(alerts)


def test_fake_citations_are_rejected(configured):
    from app.domain.models import GroundedAnswer, ProposedAction

    client, container = configured
    client.headers.update({"x-api-key": "test-token"})

    class InvalidGenerator:
        mode = "test"

        def generate(self, question, context, evidence):
            return GroundedAnswer(
                summary="unsupported",
                source_ids=["invented"],
                missing_information=[],
                insufficient_evidence=False,
                actions=[
                    ProposedAction(
                        action_code="verify_access", rationale="check", source_ids=["invented"]
                    )
                ],
            )

    container.generator = InvalidGenerator()
    alert = weather_alert(client)
    assert (
        client.post(
            "/plans", json={"alert_id": alert["id"], "question": "Review", "actor": "op"}
        ).status_code
        == 422
    )
    assert client.get("/plans").json() == []


def test_known_action_with_an_unrelated_valid_citation_is_rejected(configured):
    from app.domain.models import GroundedAnswer, ProposedAction

    client, container = configured
    client.headers.update({"x-api-key": "test-token"})
    alert = weather_alert(client)
    before_tasks = client.get("/tasks").json()

    class UnsupportedActionGenerator:
        mode = "test"

        def generate(self, question, context, evidence):
            return GroundedAnswer(
                summary="Review",
                source_ids=[evidence[0].id],
                missing_information=[],
                insufficient_evidence=False,
                actions=[
                    ProposedAction(
                        action_code="inspect_equipment",
                        rationale="Inspect equipment",
                        source_ids=[evidence[0].id],
                    )
                ],
            )

    container.generator = UnsupportedActionGenerator()
    response = client.post(
        "/plans",
        json={"alert_id": alert["id"], "question": "Review flood readiness", "actor": "operator"},
    )
    assert response.status_code == 422
    assert "not supported by its cited procedure" in response.json()["detail"]
    assert client.get("/plans").json() == []
    assert client.get("/tasks").json() == before_tasks


def test_anomaly_workflow_and_replay(client):
    points = client.get("/demo/telemetry/anomaly").json()["points"]
    result = client.post("/telemetry/evaluate", json={"points": points, "actor": "engineer"})
    assert result.status_code == 200, result.text
    assert len(result.json()["alerts"]) == 1
    observations = result.json()["observations"]
    assert not observations[0]["exceeds_threshold"]
    assert observations[-1]["exceeds_threshold"]
    assert observations[-1]["score"] > observations[0]["score"]
    assert client.get("/model/card").json()["prediction_horizon"] is None
    count = len(client.get("/telemetry/P-02/observations").json())
    again = client.post("/telemetry/evaluate", json={"points": points, "actor": "engineer"})
    assert again.status_code == 200
    assert len(client.get("/telemetry/P-02/observations").json()) == count
    assert len([a for a in client.get("/alerts").json() if a["kind"] == "anomaly"]) == 1

    points[0]["current_a"] += 10
    conflicting = client.post("/telemetry/evaluate", json={"points": points, "actor": "engineer"})
    assert conflicting.status_code == 409
    assert len(client.get("/telemetry/P-02/observations").json()) == count


def test_normal_and_invalid_telemetry(client):
    points = client.get("/demo/telemetry/normal").json()["points"]
    result = client.post("/telemetry/evaluate", json={"points": points, "actor": "engineer"})
    assert result.status_code == 200
    assert not result.json()["alerts"]
    points.pop(20)
    assert (
        client.post("/telemetry/evaluate", json={"points": points, "actor": "engineer"}).status_code
        == 422
    )


def test_uncertain_exposure_is_not_low_risk(client):
    client.post("/demo/weather/update")
    alert = next(a for a in client.get("/alerts").json() if a["asset_id"] == "P-07")
    assert alert["details"]["score"] is None
    assert alert["priority"] == "high"
    assert "missing exposure mapping" in alert["details"]["data_quality"]


def test_management_has_snapshot_and_briefing(client):
    weather_alert(client)
    overview = client.get("/overview").json()
    assert overview["as_of"] and overview["active_alerts"] and overview["tasks"]
    response = client.post("/briefing")
    assert response.status_code == 200, response.text
    assert response.json()["snapshot"]["as_of"]


def test_reused_work_keeps_assignment_and_must_finish_before_alert_closure(
    client, configured, monkeypatch
):
    _, container = configured
    generate = container.generator.generate

    def shared_data_review(question, context, evidence):
        answer = generate(question, context, evidence)
        answer.actions[0].action_code = "confirm_missing_data"
        answer.actions[0].source_ids = [
            next(source.id for source in evidence if "confirm_missing_data" in source.text)
        ]
        return answer

    monkeypatch.setattr(container.generator, "generate", shared_data_review)
    weather = weather_alert(client)
    weather_plan = draft(client, weather)
    original_task = client.post(
        f"/plans/{weather_plan['id']}/approve", json=approval("confirm_missing_data")
    ).json()["tasks"][0]

    # A second plan for the same alert must also reuse the active task.
    second_weather_plan = draft(client, weather)
    second_approval = client.post(
        f"/plans/{second_weather_plan['id']}/approve", json=approval("confirm_missing_data")
    )
    assert second_approval.status_code == 200, second_approval.text
    assert second_approval.json()["tasks"][0]["id"] == original_task["id"]
    assert len(client.get("/tasks").json()) == 2

    points = client.get("/demo/telemetry/anomaly").json()["points"]
    condition = client.post("/telemetry/evaluate", json={"points": points, "actor": "engineer"})
    assert condition.status_code == 200, condition.text
    anomaly = condition.json()["alerts"][0]
    anomaly_plan = draft(client, anomaly)
    changed_assignment = approval("confirm_missing_data")
    changed_assignment["assignee"] = "Team B"
    changed_assignment["due_at"] = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    response = client.post(f"/plans/{anomaly_plan['id']}/approve", json=changed_assignment)
    assert response.status_code == 200, response.text
    reused_task = response.json()["tasks"][0]
    assert reused_task["id"] == original_task["id"]
    assert reused_task["assignee"] == original_task["assignee"]
    assert reused_task["due_at"] == original_task["due_at"]

    disposition = {"status": "closed", "reason": "review complete", "actor": "engineer"}
    assert client.patch(f"/alerts/{anomaly['id']}", json=disposition).status_code == 409
    assert (
        client.patch(
            f"/tasks/{reused_task['id']}", json={"status": "in_progress", "actor": "engineer"}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/tasks/{reused_task['id']}",
            json={"status": "completed", "outcome": "inspection recorded", "actor": "engineer"},
        ).status_code
        == 200
    )
    assert client.patch(f"/alerts/{anomaly['id']}", json=disposition).status_code == 200
    weather_after = next(
        alert for alert in client.get("/alerts").json() if alert["id"] == weather["id"]
    )
    assert weather_after["status"] == "open"


def test_condition_recovery_updates_one_alert_and_preserves_human_review(client):
    from app.infrastructure.simulation import pump_run

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    anomaly_points = pump_run(888, start=start, anomalous=True)
    response = client.post(
        "/telemetry/evaluate",
        json={
            "points": [point.model_dump(mode="json") for point in anomaly_points],
            "actor": "engineer",
        },
    )
    assert response.status_code == 200, response.text
    original_alert = response.json()["alerts"][0]
    assert original_alert["details"]["consecutive_exceedances"] >= 3

    normal_points = pump_run(888, start=start + timedelta(hours=2))
    response = client.post(
        "/telemetry/evaluate",
        json={
            "points": [point.model_dump(mode="json") for point in normal_points],
            "actor": "engineer",
        },
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["alerts"]) == 1
    updated_alert = response.json()["alerts"][0]
    assert updated_alert["id"] == original_alert["id"]
    assert updated_alert["version"] > original_alert["version"]
    assert updated_alert["status"] == "open"
    assert updated_alert["details"]["normalizing"] is True
    assert updated_alert["details"]["consecutive_exceedances"] == 0
    assert updated_alert["details"]["score"] == response.json()["observations"][-1]["score"]
