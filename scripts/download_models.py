import os

from sentence_transformers import CrossEncoder, SentenceTransformer

if __name__ == "__main__":
    SentenceTransformer(
        os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"), device="cpu"
    )
    CrossEncoder(os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L6-v2"), device="cpu")
    print("Embedding and reranking weights are cached.")
