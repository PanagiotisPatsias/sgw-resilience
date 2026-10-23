import numpy as np

from app.domain.features import FeatureBuilder
from app.infrastructure.simulation import pump_run


def test_feature_window_is_past_only_and_finite():
    points = pump_run(11)
    builder = FeatureBuilder()
    original = builder.build(points[:15])
    points[-1].motor_temp_c = 140
    assert builder.build(points[:15]) == original
    assert len(original.values) == 7 and np.isfinite(original.values).all()
