---
id: SOP-DATA
version: "1.0"
status: active
hazard: all
asset_type: all
---
# Illustrative data quality controls

## Missing and stale information
Missing geographic exposure or stale asset information must be visible to the operator. Do not interpret missing information as low risk. Use confirm_missing_data and identify the missing field, source and last update. The 24-hour asset freshness limit in this demo is an assumption requiring client validation.

## Telemetry integrity
Reject windows with missing, duplicated or irregular timestamps. Stopped operation and rapid speed transitions are outside the model's stable-running baseline. A data quality issue must not be converted into a healthy equipment score. Review sensor validity before treating an anomaly as an equipment issue.
