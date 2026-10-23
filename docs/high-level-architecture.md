# High-Level Architecture

The prototype uses a Streamlit interface and one FastAPI backend, with separate modules for weather, pump condition and decision workflows.

[View the architecture diagram](high-level-architecture.svg)

## Main components

| Component | Role |
|---|---|
| **Streamlit** | Displays asset information, telemetry, recommendations, response work and leadership updates. |
| **FastAPI** | Validates requests and runs the workflows, approval checks and task updates. |
| **PostgreSQL** | Stores assets, maintenance, weather events, alerts, model results, plans, tasks and audit history. |
| **Local retrieval** | Searches versioned playbooks using keyword search, Chroma embeddings and a reranker. |
| **Local autoencoder** | Evaluates pump features using a saved model, scaler and threshold. |
| **OpenAI API** | Drafts recommendations and briefings using operational facts and retrieved procedures. |

## Workflow

- **Weather readiness:** A simulated warning is matched to asset locations. Explicit rules calculate review priorities and create or update weather alerts.
- **Pump condition:** Synthetic telemetry is converted into features and evaluated by the autoencoder. Persistent deviations create an anomaly alert. Raw measurements are processed in memory; window results are stored.
- **Shared response:** The operator selects an alert, reviews retrieved procedures and requests a draft. Approved actions create response tasks or reuse existing work.
- **Leadership:** The overview reads the current database state. An optional AI briefing summarizes a recorded snapshot.

## Key design choices

- **One backend application:** Workflow modules separate responsibilities while keeping setup and testing simple.
- **Separate UI and API containers:** The interface can be updated independently of the backend and its model dependencies.
- **Saved state and transactions:** Successful changes are committed together; failed requests roll back database changes.
- **Explicit approval:** Generating a draft does not create tasks. Approval checks that the supporting alert information has not changed.
- **Local analysis, external generation:** Retrieval and anomaly detection run locally. GPT generation requires an OpenAI API key.
- **Separate training:** The autoencoder is trained before use. User requests load and use the saved model.

For data assumptions and prototype boundaries, see [Assumptions and Limitations](assumptions-and-limitations.md).
