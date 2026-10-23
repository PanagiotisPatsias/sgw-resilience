---
id: SOP-CONDITION
version: "1.0"
status: active
hazard: equipment
asset_type: pump
---
# Illustrative pump condition monitoring

## Persistent telemetry anomaly
When an anomaly persists across three consecutive evaluation windows, request engineering review using review_telemetry. Examine current, flow, motor temperature and operating speed together. Compare the time series with maintenance and operating context. Reconstruction error indicates departure from a learned normal reference, not a diagnosis, failure probability or remaining useful life.

## Inspection proposal
If the responsible engineer confirms the unusual behavior needs investigation, propose inspect_equipment for an authorized team. Review existing open inspections and field reports first. The platform must not automatically stop, start or modify a pump. An operator approves the task, owner and due time.

## Returning to baseline
When reconstruction error returns below the threshold, mark the observation as normalizing. Do not automatically close an incident. Record the engineer's disposition and the actual inspection outcome. These reviewed outcomes may support future model evaluation but are not automatically failure labels.
