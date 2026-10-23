from datetime import datetime, timedelta, timezone

import numpy as np

from app.domain.models import TelemetryPoint


def pump_run(
    seed: int, asset_id="P-02", minutes=120, anomalous=False, start: datetime | None = None
) -> list[TelemetryPoint]:
    rng = np.random.default_rng(seed)
    start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    speed = rng.uniform(50, 90)
    ambient = rng.uniform(16, 28)
    phase = rng.uniform(0, 6.28)
    points = []
    for i in range(minutes):
        operating_speed = speed + 0.12 * np.sin(i / 15 + phase)
        current = 0.48 * operating_speed + rng.normal(0, 0.18)
        flow = 1.25 * operating_speed + 0.06 * current + rng.normal(0, 0.45)
        temp = (
            27
            + 0.38 * current
            + 0.18 * ambient
            + 0.12 * np.sin(i / 18 + phase)
            + rng.normal(0, 0.08)
        )
        if anomalous:
            progression = min(35, max(0, i - 55))
            current += 0.10 * progression
            flow -= 0.65 * progression
            temp += 0.30 * progression
        points.append(
            TelemetryPoint(
                timestamp=start + timedelta(minutes=i),
                asset_id=asset_id,
                running=True,
                speed_pct=float(operating_speed),
                current_a=float(current),
                flow_m3h=float(flow),
                motor_temp_c=float(temp),
            )
        )
    return points
