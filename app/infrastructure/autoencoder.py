import hashlib
from pathlib import Path

import joblib
import numpy as np

from app.domain.errors import DependencyUnavailable
from app.domain.features import FEATURE_NAMES
from app.domain.models import AnomalyResult, FeatureWindow


class DenseAutoencoderDetector:
    def __init__(self, artifact_path: Path):
        self.path = artifact_path
        self._bundle = None

    def bundle(self):
        if self._bundle is None:
            if not self.path.exists():
                raise DependencyUnavailable(
                    "autoencoder artifact missing; run python -m scripts.train_autoencoder"
                )
            self._bundle = joblib.load(self.path)
            if self._bundle["features"] != FEATURE_NAMES:
                raise DependencyUnavailable("model feature schema does not match the application")
        return self._bundle

    def evaluate(self, window: FeatureWindow) -> AnomalyResult:
        bundle = self.bundle()
        feature_values = np.asarray([window.values], dtype=float)
        scaled_features = bundle["scaler"].transform(feature_values)
        reconstructed_features = bundle["model"].predict(scaled_features)
        reconstruction_errors = np.square(scaled_features - reconstructed_features)[0]
        score = float(reconstruction_errors.mean())
        return AnomalyResult(
            asset_id=window.asset_id,
            window_end=window.window_end,
            score=score,
            threshold=bundle["threshold"],
            exceeds_threshold=score > bundle["threshold"],
            model_version=bundle["version"],
            input_fingerprint=hashlib.sha256(window.model_dump_json().encode()).hexdigest(),
            feature_errors={
                name: float(error) for name, error in zip(FEATURE_NAMES, reconstruction_errors)
            },
        )

    def info(self):
        bundle = self.bundle()
        return {
            "version": bundle["version"],
            "features": bundle["features"],
            "threshold": bundle["threshold"],
            "metadata": bundle["metadata"],
            "metrics": bundle["metrics"],
            "prediction_horizon": None,
            "interpretation": "recent-condition anomaly detection; not a failure probability or diagnosis",
        }
