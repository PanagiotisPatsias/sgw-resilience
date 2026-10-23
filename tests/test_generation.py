import json

import httpx
import pytest

from app.domain.errors import InvalidEvidence
from app.domain.models import GroundedAnswer
from app.infrastructure.generation import OpenAIGenerator


def completed_response(text):
    return {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
    }


def test_openai_schema_restricts_citations_to_retrieved_policy_ids():
    from app.config import ROOT
    from app.infrastructure.retrieval import load_playbooks

    evidence = load_playbooks(ROOT / "data/playbooks")[:2]
    source_ids = [e.id for e in evidence]

    def handler(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["store"] is False
        assert payload["text"]["format"]["strict"] is True
        assert json.loads(payload["input"])["allowed_source_ids"] == source_ids
        schema = payload["text"]["format"]["schema"]
        assert list(json.loads(payload["input"])["allowed_actions"]) == ["confirm_missing_data"]
        assert schema["$defs"]["ProposedAction"]["properties"]["action_code"]["enum"] == [
            "confirm_missing_data"
        ]
        assert schema["properties"]["source_ids"]["items"]["enum"] == source_ids
        assert schema["properties"]["source_ids"]["minItems"] == 1
        action_sources = schema["$defs"]["ProposedAction"]["properties"]["source_ids"]
        assert action_sources["items"]["enum"] == source_ids
        answer = GroundedAnswer(
            summary="Review",
            source_ids=source_ids,
            missing_information=[],
            insufficient_evidence=False,
            actions=[],
        )
        return httpx.Response(200, json=completed_response(answer.model_dump_json()))

    generator = OpenAIGenerator("test-key", "test-model", httpx.MockTransport(handler))
    assert generator.generate("question", {}, evidence).source_ids == source_ids


def test_invalid_openai_output_is_rejected():
    body = completed_response("not json")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with pytest.raises(InvalidEvidence):
        OpenAIGenerator("test-key", "test-model", transport).generate("question", {}, [])


def test_failed_generation_does_not_save_plans_or_tasks(configured):
    client, container = configured
    client.headers.update({"x-api-key": "test-token"})
    client.post("/demo/weather/initial")
    alert = client.get("/alerts").json()[0]
    before_plans = client.get("/plans").json()
    before_tasks = client.get("/tasks").json()
    transport = httpx.MockTransport(lambda request: httpx.Response(429, json={"error": {}}))
    container.generator = OpenAIGenerator("test-key", "test-model", transport)
    result = client.post(
        "/plans",
        json={"alert_id": alert["id"], "question": "What should we inspect?", "actor": "reviewer"},
    )
    assert result.status_code == 503
    assert client.get("/plans").json() == before_plans
    assert client.get("/tasks").json() == before_tasks
