import os

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.container import Container
from app.domain.models import GroundedAnswer, ProposedAction
from app.main import create_app


class FakeRetriever:
    def retrieve(self, question, hazard, asset_type):
        from app.infrastructure.retrieval import load_playbooks

        eligible = [
            e
            for e in load_playbooks(ROOT / "data/playbooks")
            if e.hazard in (hazard, "all") and e.asset_type in (asset_type, "all")
        ]
        return sorted(eligible, key=lambda e: (e.hazard != hazard, e.asset_type != asset_type))[:4]


class FakeGenerator:
    mode = "test_fake_not_a_real_llm"

    def generate(self, question, context, evidence):
        briefing = "snapshot" in question or "leadership" in question.lower()
        code = (
            "review_telemetry"
            if context.get("alert", {}).get("kind") == "anomaly"
            else "verify_flood_defences"
        )
        source = evidence[0] if briefing else next(e for e in evidence if code in e.text)
        return GroundedAnswer(
            summary="Review the supplied evidence.",
            source_ids=[source.id],
            missing_information=[],
            insufficient_evidence=False,
            actions=[]
            if briefing
            else [
                ProposedAction(
                    action_code=code,
                    rationale="An inspection is pending.",
                    source_ids=[source.id],
                )
            ],
        )


@pytest.fixture
def configured(tmp_path):
    url = os.getenv("TEST_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    settings = Settings(
        database_url=url,
        demo_api_token="test-token",
        auto_seed=True,
        artifacts_path=ROOT / "artifacts",
        chroma_path=tmp_path / "chroma",
    )
    container = Container(settings, retriever=FakeRetriever(), generator=FakeGenerator())
    if os.getenv("TEST_DATABASE_URL"):
        from app.infrastructure.database import metadata

        metadata.drop_all(container.database.engine)
    with TestClient(create_app(settings, container)) as client:
        yield client, container


@pytest.fixture
def client(configured):
    client, _ = configured
    client.headers.update({"x-api-key": "test-token"})
    return client
