# Pump Anomaly Detection

## Purpose

The model flags pump operating patterns that differ from its normal reference. It supports engineering review; it does not diagnose faults, estimate failure probabilities or predict when a pump will fail.

## Data and features

The `pump_run()` function in `app/infrastructure/simulation.py` generates synthetic one-minute measurements of speed, current, water flow and motor temperature. Training and the demo use the same simulator with different seeds. The sample CSVs in `data/telemetry/` are examples; the training script and demo endpoint do not read them.

Each evaluation uses the latest 15 consecutive samples from one pump. Evaluations are five minutes apart and use no future measurements. The seven features are:

1. Mean speed.
2. Mean current.
3. Current standard deviation.
4. Mean flow.
5. Flow standard deviation.
6. Mean motor temperature.
7. Motor temperature slope per minute.

Asset IDs and timestamps identify the window; they are not numerical model features. Incomplete windows, duplicate timestamps, mixed assets, stopped pumps and rapid speed changes are rejected. The current UI provides telemetry for P-02 only.

## Training

Run `python -m scripts.train_autoencoder` to generate the datasets and train the model. Each run contains 120 one-minute measurements. Separate runs and seeds are used for each dataset:

| Dataset | Runs | Use |
|---|---:|---|
| Normal training | 80 | Learn normal operating patterns |
| Normal validation | 12 | Select the model checkpoint with the lowest validation error |
| Normal calibration | 24 | Set the anomaly threshold |
| Normal test | 24 | Evaluate on separate normal runs |
| Injected-anomaly test | 12 | Evaluate runs containing synthetic deviations |

The autoencoder uses scikit-learn's `MLPRegressor` with a `7 → 6 → 3 → 6 → 7` architecture. It learns to reconstruct its input: the same standardized features are used as input and target. Only normal data is used to train it.

`StandardScaler` is fitted on the training set only and reused for all later data. The model, scaler, feature order, threshold, version and metrics are saved together in `artifacts/autoencoder.joblib`. The backend loads this bundle for inference; clicking Evaluate does not retrain the model.

Full training measurements are generated in memory rather than saved as a dataset. `artifacts/training_features_sample.csv` contains the first 30 training feature windows. `artifacts/evaluation_windows.csv` records test-window scores and thresholds.

## Scoring and alerts

The score is the mean squared difference between the standardized input features and their reconstruction. The threshold is the 99th percentile of errors on the separate normal calibration set; it is not selected using the final anomaly test results.

A new alert requires three consecutive evaluations above the threshold, five minutes apart. A normal result or a missing evaluation breaks the streak. An existing alert remains open for human review when the score returns below the threshold.

Per-feature errors show contributions to the reconstruction error, not the cause of a fault. Because evaluation windows overlap, the 99th-percentile threshold does not guarantee a 1% operational false-alert rate.

## Evaluation and limits

The saved evaluation in `artifacts/model_card.json` reports:

| Measure | Synthetic result |
|---|---:|
| Injected-anomaly runs that produced a persistent alert | 12 of 12 |
| Normal test runs that produced a persistent alert | 0 of 24 |

These results describe the simulator, not expected performance on real pumps. Training and testing share the simulator's assumptions. Real use requires representative telemetry, an engineer-reviewed normal reference, and evaluation of missed anomalies and false alerts under different operating conditions.

See [Assumptions and Limitations](assumptions-and-limitations.md) for the wider prototype boundaries.
