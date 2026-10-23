# SGW Resilience

A local technical prototype for the AECOM AI Solution Engineer case assignment. It connects weather, asset, maintenance and field-work information.

The prototype demonstrates two workflows:

- **Weather readiness:** match a flood warning to assets, calculate review priorities, retrieve procedures, draft actions, approve work and record the outcome.
- **Pump condition:** evaluate telemetry with a trained autoencoder, flag persistent unusual behaviour and use the same review and approval process.

Weather priorities use explicit rules. AI is used for procedure retrieval, action and briefing drafts, and pump anomaly detection. All operational inputs and procedures are synthetic. The application does not control equipment or dispatch crews.

## Quick start

You need Docker with Compose. The first build downloads packages and retrieval models, which can take several minutes. No GPU is required. The saved autoencoder is included; training is not needed to start the demo.

### 1. Create your configuration

From the repository root, on first setup:

```bash
cp .env.example .env
```

If `.env` already exists, edit it instead of overwriting it. For real GPT generation, set:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4.1-mini
```

The key needs access to the selected model and available API quota. Set `DEMO_API_TOKEN` to your chosen local API token; Compose supplies it to both the UI and backend. Keep credentials in `.env`, which is excluded from Git, and leave `OPENAI_API_KEY` empty in `.env.example`.

### 2. Start the application

```bash
docker compose up --build
```

| Service | Address |
|---|---|
| Dashboard | <http://localhost:8502> |
| API documentation | <http://localhost:8002/docs> |
| API health | <http://localhost:8002/health> |

Wait for the API health check to pass before opening the dashboard. The dashboard calls the API inside the Docker network. Published ports are restricted to the local machine.

Protected API endpoints require the `x-api-key` header with the same value as `DEMO_API_TOKEN`. The dashboard sends this automatically; supply it manually when using the API documentation.

After changing `.env`, recreate the affected containers to load the new values. Recreate both services to apply a changed API token consistently:

```bash
docker compose up -d --force-recreate api dashboard
```

Environment-only changes do not require an image rebuild. Source-code or dependency changes do.

### Without an OpenAI key

Weather assessment, anomaly detection, procedure retrieval and existing-task updates work without a key. GPT drafting and briefings require one. Set `LLM_PROVIDER=extractive_preview` for an explicit evidence-preview mode with no proposed actions. The application does not silently replace GPT output with a fake answer.

## Try the demo

### Workflow 1: flood readiness

1. Select **Load initial flood warning** in the sidebar.
2. In **Situation**, inspect the affected assets and select **P-02** in **Asset context**. Review its maintenance record and existing access task.
3. In **Decision & approval**, explicitly select the **P-02 weather alert**. Select **Retrieve source evidence** to inspect relevant procedures, then **Draft grounded action plan**.
4. Review the summary, sources and proposed actions. Select an action, team and deadline, confirm review, and select **Approve selected actions**. Drafting alone creates no tasks.
5. In **Response work**, select the approved task. Save `in_progress`, then `completed` with a written outcome. Repeat for any other approved tasks before closing the alert.
6. Under **Update alert status**, select the weather alert, choose `closed`, enter a reason and select **Record disposition**. Incomplete linked tasks prevent closure.

Existing active work may be reused instead of duplicated. Closing an alert records a review decision; it does not remove weather exposure or complete unrelated work.

### Workflow 2: pump condition

1. In **Equipment condition**, choose `normal`, select **Load telemetry sample**, then **Evaluate condition**.
2. Repeat with `anomaly`. Inspect the signal charts, reconstruction error, threshold and feature contributions. A new alert requires three consecutive threshold exceedances.
3. In **Decision & approval**, explicitly select the **P-02 anomaly alert** and draft a plan. Review its equipment procedures and approve supported actions.
4. Complete the resulting work and record the alert decision through the same response process.

Telemetry is demonstrated for P-02 only. An unusual pattern is not a fault diagnosis or failure forecast. Avoid changing the supporting alerts between drafting and approval; changed information requires a fresh draft.

In **Leadership & evidence**, review alerts, work and snapshot time. **Generate grounded briefing** requests a written summary. **Decision audit trail** shows recorded decisions and updates.

### Optional examples

- **Load expanded warning:** enlarges the affected area and includes P-04; P-01 stays outside. To test stale-plan rejection, create a draft, load the expanded warning, then attempt to approve that draft.
- **P-07 weather:** missing exposure and old asset information are flagged for review, with no numeric priority index.
- **S-13 weather:** substation guidance shows that retrieval filters procedures by asset type.

## Reset and stop

To restart the scenario, open **Reset demo**, tick the confirmation and select **Reset to initial state**. This clears current demo progress and restores the original assets, maintenance and seeded task. Credentials, model artifacts and the retrieval index are retained.

To stop the containers while preserving database and index volumes:

```bash
docker compose down
```

Restarting does not reset existing records. Use the UI reset after changing source fixtures if you want the database to reflect them.

## Data and technical documentation

| Location | Contents |
|---|---|
| `data/gis/` | Five fictional assets: four pumps and one substation. |
| `data/weather/` | Two revisions of one flood warning: initially three affected assets, then four. |
| `data/maintenance/` | One open maintenance record per asset. |
| `data/field_operations/` | One existing access-confirmation task for P-02. |
| `data/telemetry/` | Normal and anomaly CSV examples. The UI generates samples using `pump_run()` rather than reading these files. |
| `data/playbooks/` | Eight fictional, versioned procedures used for retrieval. |
| `artifacts/` | Saved autoencoder bundle, model card, feature sample and evaluation reports. |

Application code is in `app/`; the Streamlit interface is in `ui/`. `scripts/` contains training, model preparation, evaluation and API startup tools. PostgreSQL stores operational state; Chroma stores the playbook search index. Raw telemetry is evaluated in memory, while window results are saved.

- [High-level architecture](docs/high-level-architecture.md) and [diagram](docs/high-level-architecture.svg).
- [Assumptions and limitations](docs/assumptions-and-limitations.md).
- [Pump anomaly detection: data, training and evaluation](docs/autoencoder.md).

Citations and allowed-action checks constrain GPT recommendations but do not guarantee factual accuracy. Human review remains required.

## Tests

The suite contains 20 focused cases covering core workflows, generation checks, UI behaviour, feature windows and optional real retrieval. Default tests use mocked OpenAI responses and temporary SQLite; no key or running application is needed.

For tests only, use Python 3.12 and install the test dependencies:

```bash
python -m pip install '.[ui,dev]'
python -m pytest -q
ruff check app scripts tests ui
ruff format --check app scripts tests ui
```

The real retrieval test is skipped unless `RUN_RAG_TESTS=1` and its model dependencies are available. CI also runs the workflow suite against a disposable PostgreSQL database. If setting `TEST_DATABASE_URL` yourself, use a dedicated test database: its tables are dropped by the fixture.

To rerun the bundled retrieval evaluation using the running API container:

```bash
docker compose exec api python -m scripts.evaluate_rag
```

This prints the report and writes `artifacts/rag_evaluation.json` inside that container. Retrieval cases are defined in `data/rag_evaluation.json`. These checks assess source retrieval, not the factual correctness of GPT answers.

## Other deliverables

- [Product Requirements Document](docs/SGW_Resilience_PRD.pdf).
- [Executive Management Briefing](<docs/Executive Management Briefing.pdf>).

The 5–10 minute demonstration video is a separate deliverable and is not included in this repository.
