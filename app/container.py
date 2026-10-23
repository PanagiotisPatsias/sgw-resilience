from dataclasses import dataclass

from app.application.condition import ConditionWorkflow
from app.application.decision import DecisionWorkflow
from app.application.weather import WeatherWorkflow
from app.config import Settings
from app.domain.features import FeatureBuilder
from app.domain.policies import RiskPolicy
from app.domain.ports import AnomalyDetector, AnswerGenerator, Retriever
from app.infrastructure.autoencoder import DenseAutoencoderDetector
from app.infrastructure.database import Database, SqlRepository
from app.infrastructure.generation import ExtractivePreviewGenerator, OpenAIGenerator
from app.infrastructure.retrieval import HybridRetriever


@dataclass
class Services:
    weather: WeatherWorkflow
    condition: ConditionWorkflow
    decision: DecisionWorkflow


class Container:
    """Assemble adapters and workflows; workflow repositories share one transaction."""

    def __init__(
        self,
        settings: Settings,
        retriever: Retriever | None = None,
        generator: AnswerGenerator | None = None,
        detector: AnomalyDetector | None = None,
    ):
        self.settings = settings
        self.database = Database(settings.database_url)
        self.retriever = retriever or HybridRetriever(
            docs=settings.docs_path,
            index=settings.chroma_path,
            embedding_model=settings.embedding_model,
            reranker_model=settings.reranker_model,
            min_score=settings.rerank_min_score,
        )
        self.generator = generator or (
            OpenAIGenerator(key=settings.openai_api_key, model=settings.openai_model)
            if settings.llm_provider == "openai"
            else ExtractivePreviewGenerator()
        )
        self.detector = detector or DenseAutoencoderDetector(
            settings.artifacts_path / "autoencoder.joblib"
        )

    def services(self, repository: SqlRepository) -> Services:
        # one repository implements several ports within the current transaction
        return Services(
            weather=WeatherWorkflow(
                assets=repository,
                events=repository,
                alerts=repository,
                audit=repository,
                policy=RiskPolicy(),
            ),
            condition=ConditionWorkflow(
                assets=repository,
                observations=repository,
                alerts=repository,
                work=repository,
                detector=self.detector,
                features=FeatureBuilder(),
            ),
            decision=DecisionWorkflow(
                assets=repository,
                alerts=repository,
                events=repository,
                work=repository,
                retriever=self.retriever,
                generator=self.generator,
            ),
        )
