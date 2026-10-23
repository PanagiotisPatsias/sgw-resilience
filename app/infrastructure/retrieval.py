import hashlib
import re
from pathlib import Path
from threading import Lock

import numpy as np
import yaml
from rank_bm25 import BM25Okapi

from app.domain.errors import DependencyUnavailable
from app.domain.models import Evidence


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def load_playbooks(directory: Path) -> list[Evidence]:
    chunks = []
    for path in sorted(directory.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        if not content.startswith("---\n"):
            continue
        _, header, body = content.split("---", 2)
        meta = yaml.safe_load(header)
        if meta.get("status") != "active":
            continue
        parts = re.split(r"^## (.+)$", body, flags=re.MULTILINE)
        for i in range(1, len(parts), 2):
            heading, paragraph = parts[i].strip(), parts[i + 1].strip()
            slug = "-".join(tokenize(heading))
            chunks.append(
                Evidence(
                    id=f"{meta['id']}:{slug}",
                    document=path.name,
                    section=heading,
                    version=str(meta["version"]),
                    text=paragraph,
                    hazard=meta["hazard"],
                    asset_type=meta["asset_type"],
                )
            )
    if not chunks:
        raise DependencyUnavailable("no active playbook sections found")
    return chunks


def reciprocal_rank_fusion(rankings: list[list[str]], k=60) -> list[str]:
    scores = {}
    for ranking in rankings:
        for rank, identifier in enumerate(ranking, 1):
            scores[identifier] = scores.get(identifier, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda identifier: (-scores[identifier], identifier))


class HybridRetriever:
    def __init__(
        self, docs: Path, index: Path, embedding_model: str, reranker_model: str, min_score=0.0
    ):
        self.chunks = load_playbooks(docs)
        self.index, self.embedding_model, self.reranker_model = (
            index,
            embedding_model,
            reranker_model,
        )
        self.min_score = min_score
        self._lock, self._ready = Lock(), False

    def prepare(self):
        with self._lock:
            if self._ready:
                return
            try:
                import chromadb
                from sentence_transformers import CrossEncoder, SentenceTransformer

                self.encoder = SentenceTransformer(self.embedding_model, device="cpu")
                self.reranker = CrossEncoder(self.reranker_model, device="cpu")
                self.client = chromadb.PersistentClient(path=str(self.index))
                fingerprint = hashlib.sha256(
                    (
                        self.embedding_model
                        + "\n"
                        + "\n".join(c.model_dump_json() for c in self.chunks)
                    ).encode()
                ).hexdigest()[:16]
                self.collection = self.client.get_or_create_collection("playbooks-" + fingerprint)
                if self.collection.count() != len(self.chunks):
                    texts = [c.section + "\n" + c.text for c in self.chunks]
                    embeddings = self.encoder.encode(texts, normalize_embeddings=True).tolist()
                    self.collection.upsert(
                        ids=[c.id for c in self.chunks],
                        documents=texts,
                        embeddings=embeddings,
                        metadatas=[
                            {"hazard": c.hazard, "asset_type": c.asset_type} for c in self.chunks
                        ],
                    )
                self._ready = True
            except Exception as exc:
                raise DependencyUnavailable(
                    "hybrid retrieval models or index are unavailable; run the prepare command and check the server logs"
                ) from exc

    def retrieve(self, query: str, hazard: str, asset_type: str) -> list[Evidence]:
        self.prepare()
        eligible = [
            c
            for c in self.chunks
            if c.hazard in (hazard, "all") and c.asset_type in (asset_type, "all")
        ]
        if not eligible:
            return []
        texts = [c.section + " " + c.text for c in eligible]
        lexical_scores = BM25Okapi([tokenize(t) for t in texts]).get_scores(tokenize(query))
        lexical = [eligible[i].id for i in np.argsort(-lexical_scores)[:8] if lexical_scores[i] > 0]
        query_embedding = self.encoder.encode([query], normalize_embeddings=True).tolist()
        dense = self.collection.query(
            query_embeddings=query_embedding,
            n_results=min(8, len(eligible)),
            where={
                "$and": [
                    {"hazard": {"$in": [hazard, "all"]}},
                    {"asset_type": {"$in": [asset_type, "all"]}},
                ]
            },
        )["ids"][0]
        fused = reciprocal_rank_fusion([lexical, dense])[:10]
        lookup = {c.id: c for c in eligible}
        candidates = [lookup[i] for i in fused if i in lookup]
        if not candidates:
            return []
        scores = np.asarray(
            self.reranker.predict([(query, c.section + " " + c.text) for c in candidates])
        ).reshape(-1)
        results = [
            c.model_copy(update={"score": float(score)})
            for c, score in zip(candidates, scores)
            if score >= self.min_score
        ]
        return sorted(results, key=lambda c: c.score, reverse=True)[:4]
