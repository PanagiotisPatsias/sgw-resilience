import json
import time
from pathlib import Path

from app.config import ROOT, Settings
from app.container import Container

if __name__ == "__main__":
    retriever = Container(Settings()).retriever
    retriever.prepare()
    cases = json.loads((ROOT / "data/rag_evaluation.json").read_text())
    results = []
    for case in cases:
        start = time.monotonic()
        hits = retriever.retrieve(case["question"], case["hazard"], case["asset_type"])
        passed = (
            any(h.id.startswith(case["expected_document"] + ":") for h in hits)
            if case["answerable"]
            else not hits
        )
        results.append(
            {
                **case,
                "passed": passed,
                "retrieved": [h.id for h in hits],
                "latency_ms": round(1000 * (time.monotonic() - start), 1),
            }
        )
    report = {
        "cases_passed": sum(r["passed"] for r in results),
        "total": len(results),
        "note": "retrieval smoke evaluation, not proof of semantic answer grounding",
        "results": results,
    }
    Path("artifacts/rag_evaluation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
