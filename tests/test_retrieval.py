import os

import pytest

from app.config import ROOT, Settings
from app.infrastructure.retrieval import HybridRetriever


@pytest.mark.rag
@pytest.mark.skipif(
    not os.getenv("RUN_RAG_TESTS"), reason="requires downloaded embedding and reranking models"
)
def test_real_hybrid_retrieval(tmp_path):
    settings = Settings()
    retriever = HybridRetriever(
        ROOT / "data/playbooks",
        tmp_path / "chroma",
        settings.embedding_model,
        settings.reranker_model,
        min_score=settings.rerank_min_score,
    )
    hits = retriever.retrieve(
        "How do we handle persistent pump telemetry anomalies?", "equipment", "pump"
    )
    assert any(c.id.startswith("SOP-CONDITION:") for c in hits)
    assert not retriever.retrieve("What is the recipe for chocolate cake?", "equipment", "pump")
