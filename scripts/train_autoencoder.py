import argparse
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from app.domain.features import FEATURE_NAMES, FeatureBuilder
from app.infrastructure.simulation import pump_run


def make_split(seeds, start_day, anomalous=False):
    builder, rows, groups = FeatureBuilder(), [], []
    for i, seed in enumerate(seeds):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=start_day + i)
        for window in builder.windows(pump_run(seed, start=start, anomalous=anomalous)):
            rows.append(window.values)
            groups.append(
                {
                    "run": seed,
                    "window_end": window.window_end.isoformat(),
                    "anomaly_present": anomalous
                    and window.window_end >= start + timedelta(minutes=60),
                }
            )
    return np.asarray(rows), groups


def train(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    train_x, _ = make_split(range(100, 180), 0)
    valid_x, _ = make_split(range(200, 212), 100)
    calibration_x, _ = make_split(range(300, 324), 130)
    normal_test, normal_groups = make_split(range(400, 424), 170)
    abnormal_test, abnormal_groups = make_split(range(500, 512), 210, anomalous=True)
    # fit preprocessing on training only; raw runs never cross split boundaries
    scaler = StandardScaler().fit(train_x)
    x, valid = scaler.transform(train_x), scaler.transform(valid_x)
    model = MLPRegressor(
        hidden_layer_sizes=(6, 3, 6),
        activation="tanh",
        solver="adam",
        learning_rate_init=0.003,
        alpha=0.005,
        batch_size=64,
        random_state=42,
    )
    best, best_loss, patience = None, float("inf"), 0
    for epoch in range(250):
        model.partial_fit(x, x)
        loss = float(np.mean((valid - model.predict(valid)) ** 2))
        if loss < best_loss - 1e-5:
            best, best_loss, patience = deepcopy(model), loss, 0
        else:
            patience += 1
        if patience >= 25:
            break
    model = best

    def errors(values):
        z = scaler.transform(values)
        return np.mean((z - model.predict(z)) ** 2, axis=1)

    calibration_errors = errors(calibration_x)
    threshold = float(np.quantile(calibration_errors, 0.99))
    normal_errors, abnormal_errors = errors(normal_test), errors(abnormal_test)

    def episode_hits(scores, groups):
        hits, streaks = {}, {}
        for score, group in zip(scores, groups):
            run = group["run"]
            streaks[run] = streaks.get(run, 0) + 1 if score > threshold else 0
            hits[run] = hits.get(run, False) or streaks[run] >= 3
        return hits

    normal_hits = episode_hits(normal_errors, normal_groups)
    anomaly_hits = episode_hits(abnormal_errors, abnormal_groups)
    metrics = {
        "normal_test_window_exceedance_rate": float(np.mean(normal_errors > threshold)),
        "normal_test_runs_with_persistent_alert": sum(normal_hits.values()),
        "normal_test_runs": len(normal_hits),
        "injected_test_runs_detected": sum(anomaly_hits.values()),
        "injected_test_runs": len(anomaly_hits),
        "warning": "synthetic demonstration metrics; no operational accuracy or failure lead time established",
    }
    bundle = {
        "model": model,
        "scaler": scaler,
        "features": FEATURE_NAMES,
        "threshold": threshold,
        "version": "pump-ae-synthetic-v1",
        "metadata": {
            "architecture": [7, 6, 3, 6, 7],
            "epochs": epoch + 1,
            "lookback_minutes": 15,
            "evaluation_interval_minutes": 5,
            "persistence_windows": 3,
            "threshold_quantile": 0.99,
            "normal_reference_training": True,
            "failure_labels_used": False,
            "split": "disjoint chronological runs; separate normal validation and calibration",
            "train_windows": len(train_x),
            "calibration_windows": len(calibration_x),
        },
        "metrics": metrics,
    }
    joblib.dump(bundle, output / "autoencoder.joblib")
    (output / "model_card.json").write_text(
        json.dumps({k: v for k, v in bundle.items() if k not in ("model", "scaler")}, indent=2)
    )
    sample = pd.DataFrame(train_x[:30], columns=FEATURE_NAMES)
    sample.to_csv(output / "training_features_sample.csv", index=False)
    evaluation = pd.DataFrame(normal_groups + abnormal_groups)
    evaluation["score"] = np.concatenate([normal_errors, abnormal_errors])
    evaluation["threshold"] = threshold
    evaluation.to_csv(output / "evaluation_windows.csv", index=False)
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    print(json.dumps(train(args.output), indent=2))
