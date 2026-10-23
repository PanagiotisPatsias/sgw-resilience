# Assumptions and Limitations

This prototype demonstrates flood readiness and pump condition review using synthetic data. Both workflows require human approval before proposed actions become response tasks.

## Assumptions

- **Linked asset records:** SGW can provide asset locations, maintenance records and existing field tasks linked through shared asset IDs or an agreed mapping.
- **Weather warnings:** A provider can supply warning areas, severity, validity times and updates. The provider and access details are not specified in the case.
- **Pump telemetry:** Suitable measurements are available, and engineers can identify normal operation for model training. Telemetry access is an additional assumption, not confirmed by the case.
- **Operating procedures:** SGW can provide current, approved procedures. The documents and permitted action types need review by the relevant teams.

## Prototype choices

- **Weather priority:** The formula, exposure values, priority thresholds and 24-hour asset-data freshness rule are illustrative choices requiring agreement with SGW. Missing exposure is flagged for review rather than treated as low risk.
- **Pump monitoring:** The demo uses one-minute measurements, 15-minute windows, evaluation every five minutes and three consecutive threshold exceedances before creating a new alert. These settings require engineering validation.

## Limitations

- **Synthetic data:** Assets, warnings, maintenance, tasks, telemetry and procedures are simulated. Results do not establish performance on SGW data.
- **Simplified geography:** Warning areas use rectangular boundaries. The prototype does not model flood depth or actual asset damage.
- **Model validation:** The autoencoder is trained and tested on separate runs from the same simulator. The UI provides telemetry for P-02 only. An anomaly indicates unusual behaviour, not a diagnosis, failure probability or failure forecast.
- **AI accuracy:** Citation and action-code checks constrain generated recommendations but do not guarantee factual correctness. People must review the facts, sources and actions.
- **Manual operation:** Source loading and refresh are manual. Live source connections and synchronization with field tools are not implemented. The application does not control equipment or dispatch crews.
- **User access:** A shared API token protects backend requests. Reviewer names are manually entered; enterprise identity and role-based permissions are not implemented.

The prototype does not establish avoided outages, financial return or production reliability. These require evaluation with real data and users.
