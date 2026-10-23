from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://sgw:sgw_local_password@localhost:5432/sgw"
    demo_api_token: str = "local-demo-token-change-before-deploy"
    llm_provider: Literal["openai", "extractive_preview"] = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    chroma_path: Path = ROOT / "runtime/chroma"
    docs_path: Path = ROOT / "data/playbooks"
    artifacts_path: Path = ROOT / "artifacts"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    rerank_min_score: float = 0
    auto_seed: bool = True
