from datetime import datetime, timezone
from uuid import uuid4

from app.domain.errors import Conflict, InvalidEvidence, NotFound
from app.domain.features import FeatureBuilder, consecutive_exceedances
from app.domain.models import Alert, AnomalyResult, AuditEntry, Priority, TelemetryPoint
from app.domain.ports import AlertStore, AnomalyDetector, AssetReader, ObservationStore, WorkStore

PERSISTENCE_WINDOWS = 3


class ConditionWorkflow:
    def __init__(
        self,
        assets: AssetReader,
        observations: ObservationStore,
        alerts: AlertStore,
        work: WorkStore,
        detector: AnomalyDetector,
        features: FeatureBuilder,
    ):
        self.assets = assets
        self.observations = observations
        self.alerts = alerts
        self.work = work
        self.detector = detector
        self.features = features

    def evaluate(self, points: list[TelemetryPoint], actor: str):
        """Evaluate telemetry windows, reuse prior results and update persistent alerts."""
        try:
            windows = self.features.windows(points)
        except ValueError as exc:
            raise InvalidEvidence(str(exc)) from exc

        asset = self.assets.asset(windows[0].asset_id)
        if asset is None or asset.asset_type != "pump":
            raise NotFound("this model requires a registered pump of the demo equipment family")

        results = []
        updated_alerts_by_id = {}

        for window in windows:
            result = self.detector.evaluate(window)
            previous_result = self._replayed_result(result)
            if previous_result is not None:
                results.append(previous_result)
                continue

            history = self.observations.observations(asset.id)
            if history and window.window_end <= history[-1].window_end:
                raise Conflict("out-of-order telemetry must be reviewed before replay")

            self.observations.save_observation(result)
            results.append(result)

            streak = consecutive_exceedances(
                history + [result], result.window_end, result.model_version
            )
            active_alert = self._find_active_anomaly_alert(asset.id)
            if streak < PERSISTENCE_WINDOWS and active_alert is None:
                continue

            updated_alert = self._update_anomaly_alert(active_alert, result, streak)
            self.alerts.save_alert(updated_alert)
            # later windows replace the same alert while keeping its position in the response
            updated_alerts_by_id[updated_alert.id] = updated_alert

        alert_results = list(updated_alerts_by_id.values())
        self.work.add_audit(
            AuditEntry(
                id=str(uuid4()),
                action="telemetry_evaluated",
                entity_id=asset.id,
                actor=actor,
                at=datetime.now(timezone.utc),
                details={"windows": len(results), "alerts": [a.id for a in alert_results]},
            )
        )
        return {"observations": results, "alerts": alert_results, "synthetic": True}

    def _replayed_result(self, result: AnomalyResult) -> AnomalyResult | None:
        """Reuse an identical window reject changed inputs for an evaluated window."""

        previous_result = self.observations.observation(
            result.asset_id, result.window_end, result.model_version
        )
        if previous_result is None:
            return None
        if previous_result.input_fingerprint != result.input_fingerprint:
            raise Conflict("conflicting telemetry for an already evaluated window")
        return previous_result

    def _find_active_anomaly_alert(self, asset_id: str) -> Alert | None:
        for alert in self.alerts.alerts(asset_id):
            if alert.kind == "anomaly" and alert.status != "closed":
                return alert
        return None

    def _update_anomaly_alert(
        self, active_alert: Alert | None, result: AnomalyResult, streak: int
    ) -> Alert:
        if active_alert is None:
            dedupe_key = (
                f"anomaly:{result.asset_id}:{result.model_version}:{result.window_end.isoformat()}"
            )
            active_alert = Alert(
                id=str(uuid4()),
                dedupe_key=dedupe_key,
                asset_id=result.asset_id,
                kind="anomaly",
                priority=Priority.HIGH,
                updated_at=datetime.now(timezone.utc),
                details={},
            )
        else:
            active_alert.version += 1

        persistent_anomaly = streak >= PERSISTENCE_WINDOWS
        if persistent_anomaly:
            reason = "persistent unusual operating pattern"
        else:
            reason = "recent score below persistence rule; engineer review still required"

        # recovery updates evidence; an operator still decides when to close the alert
        active_alert.updated_at = datetime.now(timezone.utc)
        active_alert.details = {
            "score": result.score,
            "threshold": result.threshold,
            "window_end": result.window_end.isoformat(),
            "model_version": result.model_version,
            "consecutive_exceedances": streak,
            "feature_errors": result.feature_errors,
            "reasons": [reason],
            "normalizing": not persistent_anomaly,
            "interpretation": "not a diagnosis, failure probability, or future failure forecast",
        }
        return active_alert
