from datetime import datetime, timedelta

import numpy as np

from app.domain.models import AnomalyResult, FeatureWindow, TelemetryPoint

FEATURE_NAMES = [
    "speed_mean",
    "current_mean",
    "current_std",
    "flow_mean",
    "flow_std",
    "temperature_mean",
    "temperature_slope",
]
WINDOW_MINUTES = 15
STEP_MINUTES = 5


class FeatureBuilder:
    def build(self, points: list[TelemetryPoint]) -> FeatureWindow:
        if len(points) != WINDOW_MINUTES:
            raise ValueError("a window requires 15 one-minute observations")

        points = sorted(points, key=lambda p: p.timestamp)

        asset_ids = {point.asset_id for point in points}
        if len(asset_ids) != 1:
            raise ValueError("a window must contain one asset")

        gaps = [
            (following.timestamp - current.timestamp).total_seconds()
            for current, following in zip(points, points[1:])
        ]

        if any(gap != 60 for gap in gaps):
            raise ValueError("missing, duplicate, or irregular telemetry timestamps")

        if not all(p.running for p in points):
            raise ValueError("stopped or transitional operation is outside this model's scope")
        speed = np.array([p.speed_pct for p in points])

        if np.std(speed) > 2:
            raise ValueError("variable-speed transitions require a separate operating baseline")

        current = np.array([p.current_a for p in points])
        flow = np.array([p.flow_m3h for p in points])
        temperature = np.array([point.motor_temp_c for point in points])
        temperature_slope = np.polyfit(np.arange(len(temperature)), temperature, 1)[0]

        values = [
            speed.mean(),
            current.mean(),
            current.std(),
            flow.mean(),
            flow.std(),
            temperature.mean(),
            temperature_slope,
        ]

        if not np.isfinite(values).all():
            raise ValueError("non-finite feature value")
        return FeatureWindow(
            asset_id=points[0].asset_id,
            window_end=points[-1].timestamp,
            values=[float(v) for v in values],
        )

    def windows(self, points: list[TelemetryPoint]) -> list[FeatureWindow]:
        """Build past-only windows ending on the five-minute clock grid."""
        ordered_points = sorted(points, key=lambda point: point.timestamp)
        if not ordered_points:
            return []

        asset_ids = {point.asset_id for point in ordered_points}
        if len(asset_ids) != 1:
            raise ValueError("submit a single asset per telemetry batch")
        windows = []

        for end_index in range(WINDOW_MINUTES, len(ordered_points) + 1):
            last_point = ordered_points[end_index - 1]
            if last_point.timestamp.minute % STEP_MINUTES != 0:
                continue

            start_index = end_index - WINDOW_MINUTES
            window_points = ordered_points[start_index:end_index]
            windows.append(self.build(window_points))

        if not windows:
            raise ValueError("no complete evaluation window on the five-minute grid")
        return windows


def consecutive_exceedances(results: list[AnomalyResult], at: datetime, version: str) -> int:
    """Count backwards until a normal result or a missing evaluation breaks the streak."""
    results_by_time = {}
    for result in results:
        if result.model_version == version:
            results_by_time[result.window_end] = result

    count = 0
    current_time = at
    while current_time in results_by_time:
        if not results_by_time[current_time].exceeds_threshold:
            break
        count += 1
        current_time -= timedelta(minutes=STEP_MINUTES)
    return count
