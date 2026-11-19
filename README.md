# InsightFlow

**AI-powered data intelligence and analytics platform.** Upload a CSV, validate and profile it, clean a copy without touching the original, explore interactive charts, detect statistical anomalies with Isolation Forest, and ask grounded natural-language questions about your data.

InsightFlow is a complete, locally runnable application: a FastAPI + PostgreSQL backend, a pandas/scikit-learn analytics engine, a provider-agnostic LLM integration, and a polished Streamlit dashboard that consumes only the REST API.

---

## Table of contents

1. [Why this project](#why-this-project)
2. [Features](#features)
3. [Architecture](#architecture)
4. [Technology stack](#technology-stack)
5. [Folder structure](#folder-structure)
6. [Quick start](#quick-start)
7. [Configuration](#configuration)
8. [Database setup and migrations](#database-setup-and-migrations)
9. [Running the application](#running-the-application)
10. [Tests](#tests)
11. [API reference](#api-reference)
12. [Sample data](#sample-data)
13. [How the AI assistant is grounded](#how-the-ai-assistant-is-grounded)
14. [Engineering decisions](#engineering-decisions)
15. [Screenshots](#screenshots)
16. [Limitations and future improvements](#limitations-and-future-improvements)

---

## Why this project

Most “analytics dashboards” stop at static charts. InsightFlow demonstrates a full data product:

- **Trustworthy numbers** — every statistic, chart and assistant figure is computed from the uploaded data with pandas. Nothing is hardcoded.
- **Safe AI** — the LLM receives compact calculated facts and summaries, never the full dataset. It never executes generated SQL or Python.
- **Auditable cleaning** — cleaning always starts from the original upload, writes a separate copy, and records every operation.
- **Real persistence** — datasets, cleaning history, analyses, anomaly runs and conversations live in PostgreSQL (or SQLite for local development) with migrations.
- **Testable architecture** — thin routes, a service layer, repositories, typed schemas, and 84 hermetic tests that require no paid API.

The result is a small, inspectable analytics product rather than a prototype.

---

## Features

### Data ingestion
- CSV upload through the UI or REST API with extension, size, encoding and content validation.
- Safe filenames and storage confined to `storage/` (no path traversal).
- Detection of column types, missing values, duplicates, high-cardinality fields and date columns.
- Ingestion quality snapshot and paginated row preview.
- SHA-256 checksum for upload integrity.

### Data cleaning
- Missing-value strategies: drop rows, mean, median, mode, constant or zero — globally or per column.
- Duplicate removal, explicit type conversions, column-name normalization, column dropping.
- IQR-based outlier removal or clipping.
- Every run records operations and affected-record counts.
- Before/after previews and a cleaning summary.
- **Original uploads are immutable**; the cleaned copy is a new file.

### Exploratory analytics
- Numeric statistics: mean, median, standard deviation, min/max, quartiles, IQR, skewness, outlier counts, histograms.
- Categorical distributions, unique counts and frequency tables.
- Pearson correlation matrix with strength labels.
- Automatic time-series detection and aggregation.
- Automated dataset summary and concrete quality observations.
- Plotly charts for histograms, box plots, category bars, heatmaps and trends.

### Machine learning anomaly detection
- Isolation Forest with configurable contamination, tree count, random seed and feature list.
- Median imputation plus `StandardScaler`; rows with all features missing are excluded and reported.
- Anomaly scores, rankings, original record values and download of results as CSV.
- Reproducible runs, persisted history and honest disclaimers (no accuracy claims without labels).

### AI assistant
- Deterministic pandas question engine handles aggregations, group rankings, counts, correlations, trends, summaries and IQR outlier scans.
- LLM interprets the calculated facts; numbers always come from pandas.
- Configurable OpenAI-compatible provider, timeouts, rate-limit and authentication handling.
- Graceful calculations-only fallback when no provider is configured or the provider fails.
- Conversation history persisted per dataset, with a new-conversation action.
- Every assistant response shows the calculated facts and their methods.

### REST API and dashboard
- 23 documented REST endpoints with Pydantic schemas, consistent error envelopes and Swagger UI.
- Streamlit dashboard with seven pages, all backed by live API data.
- Overview metrics, dataset explorer, cleaning workspace, analytics, anomaly detection, assistant and reports.
- JSON reports and CSV exports for data, quality and anomalies.
- Docker Compose deployment with PostgreSQL, health checks and Alembic migrations.

---

## Architecture

```mermaid
flowchart TB
    subgraph UI["Streamlit frontend"]
        A[Overview] --- B[Datasets]
        B --- C[Cleaning]
        C --- D[Analytics]
        D --- E[Anomalies]
        E --- F[Assistant]
        F --- G[Reports]
    end

    subgraph API["FastAPI backend"]
        R[Routers]
        P[Pydantic schemas]
        S[Service layer]
        REPO[Repositories]
        R --> P --> S --> REPO
    end

    subgraph DATA["Data & ML"]
        PD[pandas / NumPy]
        SK[scikit-learn Isolation Forest]
        FS[(Controlled file storage)]
    end

    subgraph AI["LLM provider"]
        LLM[OpenAI-compatible API]
    end

    UI -->|REST / JSON| R
    S --> PD
    S --> SK
    S --> FS
    S -->|facts only| LLM
    REPO --> DB[(PostgreSQL / SQLite)]
```

The frontend never imports backend models, services or database sessions. It talks to the backend exclusively through `frontend/services/api_client.py`.

### Layered request flow

```mermaid
sequenceDiagram
    participant U as Streamlit UI
    participant R as FastAPI route
    participant S as Service
    participant DB as Database
    participant FS as Storage

    U->>R: POST /api/v1/datasets/{id}/clean
    R->>R: Validate request with Pydantic
    R->>S: CleaningService.clean(dataset, config)
    S->>FS: Read original CSV (never modified)
    S->>S: Apply transformations to a copy
    S->>FS: Write cleaned copy
    S->>DB: Record operations + update dataset
    S-->>R: CleaningSummary
    R-->>U: 200 JSON
```

More detail: [docs/architecture.md](docs/architecture.md).

---

## Technology stack

| Layer | Technology |
|---|---|
| API | Python 3.11, FastAPI, Pydantic v2, Uvicorn |
| Persistence | SQLAlchemy 2.0, Alembic, PostgreSQL 16, SQLite for local development/tests |
| Data processing | pandas, NumPy |
| Machine learning | scikit-learn (Isolation Forest, StandardScaler) |
| AI | Any OpenAI-compatible chat completions API via HTTPX |
| Frontend | Streamlit, Plotly |
| Testing | Pytest, HTTPX/TestClient, mocked LLM transport |
| Deployment | Docker, Docker Compose |
| Quality | Ruff, type hints, docstrings, structured logging |

No message queues, Kubernetes, microservices or authentication libraries are introduced for this single-user MVP.

---

## Folder structure

```text
insightflow/
├── backend/
│   ├── app/
│   │   ├── main.py                  # App factory, middleware, routers, health
│   │   ├── core/                    # Settings, logging, exception handling
│   │   ├── api/
│   │   │   ├── deps.py              # Dependency injection
│   │   │   └── routes/              # datasets, cleaning, analytics, anomalies, chat, reports, overview
│   │   ├── models/                  # SQLAlchemy models
│   │   ├── schemas/                 # Pydantic request/response models
│   │   ├── services/                # Business logic (ingestion, cleaning, analytics, ML, LLM, reports)
│   │   ├── repositories/            # Database access
│   │   ├── db/                      # Engine, session, declarative base
│   │   └── utils/                   # Validation, serialization
│   ├── migrations/                  # Alembic environment and revisions
│   ├── tests/                       # 84 tests
│   ├── alembic.ini
│   ├── entrypoint.sh
│   ├── Dockerfile
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── app.py                       # Shell, sidebar, navigation
│   ├── pages/                       # overview, datasets, cleaning, analytics, anomalies, assistant, reports
│   ├── components/                  # Design system and Plotly builders
│   ├── services/api_client.py       # Typed HTTP client
│   ├── .streamlit/config.toml
│   ├── Dockerfile
│   └── requirements.txt
├── sample_data/                     # Generated sales and marketing datasets
├── scripts/generate_sample_data.py  # Reproducible generator (seed 42)
├── storage/                         # Uploads and processed files (gitignored)
├── docs/
│   ├── architecture.md
│   ├── api.md
│   └── screenshots/
├── docker-compose.yml
├── .env.example
├── pyproject.toml                   # Ruff configuration
└── README.md
```

---

## Quick start

### Option A — Docker Compose (PostgreSQL, recommended)

```bash
cp .env.example .env
# Edit .env if you want to enable the AI assistant.
docker compose up --build
```

- Frontend: <http://localhost:8501>
- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

The backend container waits for PostgreSQL, applies Alembic migrations via `entrypoint.sh`, then starts Uvicorn. Uploaded files persist in a named volume.

### Option B — Local Python with SQLite

```bash
python3.11 -m venv .venv
source .venv/bin/activate

pip install -r backend/requirements-dev.txt
pip install -r frontend/requirements.txt

cp .env.example .env
# For a zero-setup local database, set:
# DATABASE_URL=sqlite:///storage/insightflow.db
```

Start the backend:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

SQLite schema creation is automatic at startup. For PostgreSQL, run migrations instead (see below).

Start the frontend in a second terminal:

```bash
cd frontend
API_BASE_URL=http://localhost:8000 streamlit run app.py --server.port 8501
```

> The frontend port is independent of the backend port. If you use different ports, set `API_BASE_URL` accordingly.

### Local Python with PostgreSQL

```bash
docker compose up -d db

export DATABASE_URL="postgresql+psycopg://insightflow:insightflow@localhost:5432/insightflow"
cd backend
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

---

## Configuration

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///storage/insightflow.db` | SQLAlchemy URL. Use `postgresql+psycopg://...` for PostgreSQL. |
| `ENVIRONMENT` | `development` | Environment label. |
| `DEBUG` | `false` | Debug flag (stack traces are still never returned by handlers). |
| `LOG_LEVEL` | `INFO` | Python logging level. |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins. |
| `MAX_UPLOAD_SIZE_MB` | `25` | Upload size limit. |
| `MAX_DATASET_ROWS` | `500000` | Row limit enforced during ingestion. |
| `STORAGE_DIR` | `storage` | Root for uploads and processed files. |
| `UPLOAD_DIR` | `storage/uploads` | Original upload directory. |
| `PROCESSED_DIR` | `storage/processed` | Cleaned copies. |
| `LLM_API_KEY` | — | Provider key. If absent, assistant runs calculations-only. |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL. |
| `LLM_MODEL` | `gpt-4o-mini` | Model name. |
| `LLM_TIMEOUT_SECONDS` | `30` | External request timeout. |
| `LLM_MAX_TOKENS` | `800` | Completion token cap. |
| `LLM_TEMPERATURE` | `0.2` | Interpretation temperature. |
| `ANOMALY_CONTAMINATION` | `0.05` | Default anomaly prior. |
| `ANOMALY_RANDOM_STATE` | `42` | Reproducible model seed. |
| `API_BASE_URL` | `http://localhost:8000` | Frontend → backend URL. |
| `PUBLIC_API_BASE_URL` | same as API_BASE_URL | Browser-facing URL used for download links (important in Docker). |

Supported LLM providers are anything exposing an OpenAI-compatible `/chat/completions` endpoint (OpenAI, Azure-compatible gateways, local servers, etc.).

---

## Database setup and migrations

Alembic configuration lives in `backend/alembic.ini`; the URL is read from application settings.

```bash
cd backend
alembic upgrade head          # apply migrations
alembic revision --autogenerate -m "describe change"
alembic downgrade -1          # roll back one revision
```

### Schema

```mermaid
erDiagram
    DATASETS ||--o{ CLEANING_OPERATIONS : records
    DATASETS ||--o{ ANALYSIS_RESULTS : caches
    DATASETS ||--o{ ANOMALY_RESULTS : scores
    DATASETS ||--o{ CHAT_SESSIONS : has
    CHAT_SESSIONS ||--o{ CHAT_MESSAGES : contains

    DATASETS {
        string id PK
        string filename
        string original_filename
        int file_size
        int row_count
        int column_count
        string checksum
        datetime upload_timestamp
        string processing_status
        string storage_path
        string cleaned_path
        int cleaned_row_count
        json column_metadata
    }
    CLEANING_OPERATIONS {
        int id PK
        string dataset_id FK
        string operation_type
        json operation_details
        int records_affected
        datetime created_at
    }
    ANALYSIS_RESULTS {
        int id PK
        string dataset_id FK
        string analysis_type
        json result_json
        datetime created_at
    }
    ANOMALY_RESULTS {
        int id PK
        string dataset_id FK
        float contamination
        int total_records
        int anomalies_detected
        json result_json
        datetime created_at
    }
    CHAT_SESSIONS {
        string id PK
        string dataset_id FK
        string title
        datetime created_at
        datetime updated_at
    }
    CHAT_MESSAGES {
        int id PK
        string session_id FK
        string role
        text content
        json message_metadata
        datetime created_at
    }
```

- JSON columns use JSONB on PostgreSQL and portable JSON on SQLite.
- Foreign keys cascade on dataset deletion.
- Indexes cover dataset lookups, analysis type, anomaly time ordering and chat sessions.
- Raw CSV bytes are never stored in the database; only metadata and controlled paths.

---

## Running the application

### Backend

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- Health: `/health`

### Frontend

```bash
cd frontend
API_BASE_URL=http://localhost:8000 streamlit run app.py
```

### Generate sample data

```bash
python scripts/generate_sample_data.py
```

This deterministically recreates `sample_data/sales.csv` (759 rows, missing values, 9 duplicates, deliberate outliers) and `sample_data/marketing_campaigns.csv` (420 rows, multiple channels, missing spend/clicks). The Datasets page can load these from the UI.

---

## Tests

```bash
cd backend
pytest -q
# or with coverage
pytest --cov=app --cov-report=term-missing
```

The suite runs against a temporary SQLite database and temporary storage directory. It never calls a paid LLM:

- Ingestion: valid/invalid/empty/oversized files, duplicate columns, path traversal, encoding, previews.
- Cleaning: missing strategies, duplicate removal, type conversion, outlier handling, normalization, original-file preservation.
- Analytics: exact mean/median/quartiles, missing percentages, categorical distributions, correlation, time series, cache invalidation.
- Anomalies: planted outliers, insufficient features, too few rows, exclusions, reproducibility, persistence.
- API: status codes, error envelopes, uploads, previews, cleaning, profiling, anomalies, chat, reports, downloads, deletion cascades, overview metrics.
- LLM/assistant: missing credentials, timeouts, rate limits, auth failures, mocked completions, prompt grounding and deterministic fallback.
- Question engine: group rankings, aggregation aliases, counts, correlations, trends, summaries, unanswerable questions.

Current status: **84 passing tests**, Ruff clean.

---

## API reference

Base path: `/api/v1`. Full request/response schemas are available at `/docs`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service/database health |
| GET | `/api/v1/overview` | Dashboard metrics and recent activity |
| POST | `/api/v1/datasets/upload` | Upload and validate a CSV (multipart) |
| GET | `/api/v1/datasets` | List datasets (pagination) |
| GET | `/api/v1/datasets/{id}` | Dataset metadata and columns |
| DELETE | `/api/v1/datasets/{id}` | Delete dataset and all related records/files |
| GET | `/api/v1/datasets/{id}/preview` | Paginated JSON preview |
| POST | `/api/v1/datasets/{id}/clean` | Run a cleaning recipe on a copy |
| GET | `/api/v1/datasets/{id}/cleaning-history` | Recorded cleaning operations |
| GET | `/api/v1/datasets/{id}/profile` | Full profile, correlations and chart data |
| GET | `/api/v1/datasets/{id}/statistics` | Descriptive statistics |
| POST | `/api/v1/datasets/{id}/anomalies` | Train Isolation Forest and store results |
| GET | `/api/v1/datasets/{id}/anomalies` | Latest anomaly run |
| GET | `/api/v1/datasets/{id}/anomalies/history` | Anomaly run history |
| GET | `/api/v1/datasets/{id}/anomalies/{run_id}` | Specific anomaly run |
| POST | `/api/v1/datasets/{id}/chat` | Ask a grounded question |
| GET | `/api/v1/datasets/{id}/chat/history` | Conversation messages |
| GET | `/api/v1/datasets/{id}/chat/sessions` | List conversations |
| POST | `/api/v1/datasets/{id}/chat/sessions` | Start a new conversation |
| GET | `/api/v1/datasets/{id}/report` | Consolidated JSON report |
| GET | `/api/v1/datasets/{id}/report/dataset.csv` | Active dataset CSV |
| GET | `/api/v1/datasets/{id}/report/quality.csv` | Column quality CSV |
| GET | `/api/v1/datasets/{id}/report/anomalies.csv` | Anomaly records CSV |

Errors use one envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Unknown request columns: nope.",
    "details": {"missing_columns": ["nope"]},
    "request_id": "7d3f…"
  }
}
```

Every response includes `X-Request-ID`. Stack traces are logged server-side and never returned.

Examples and details: [docs/api.md](docs/api.md).

---

## Sample data

| File | Rows | Intentional characteristics |
|---|---|---|
| `sample_data/sales.csv` | 759 (750 unique) | 9 exact duplicates, missing region/customer/price values, bulk-order and price-spike outliers, 18 months of dates, 5 categories, 5 regions |
| `sample_data/marketing_campaigns.csv` | 420 | 5 channels with different CTR/CVR profiles, missing spend/clicks, overspending and zero-conversion campaigns |

Both are generated with NumPy seed 42 by `scripts/generate_sample_data.py`.

---

## How the AI assistant is grounded

1. The backend loads the active dataset and computes (or reuses cached) statistics.
2. `QuestionEngine` detects the intent and calculates deterministic pandas results:
   - scalar aggregates and aliases (`sales` → `revenue` when that is the closest column),
   - grouped rankings with explicit aggregation and sort direction,
   - counts and distinct counts,
   - Pearson correlations,
   - time-series aggregation,
   - IQR outlier scans,
   - dataset summaries.
3. Only compact metadata, profile highlights and those calculated facts are included in the LLM prompt. The full dataset is never sent.
4. The LLM is instructed to use only supplied figures, separate interpretation from facts, avoid causation claims, and avoid generating code/SQL.
5. The response always begins with the deterministic sentence. AI interpretation is appended and labelled.
6. Missing credentials, timeouts, 429s, authentication failures and malformed provider responses fall back to `calculations_only` with a clear note.

This design means an incorrect LLM narrative cannot change the calculated figures returned to the user.

---

## Engineering decisions

- **Service + repository layers** keep route handlers small, make services unit-testable, and avoid circular imports through dependency injection.
- **Cleaning starts from the original every time.** Recipes are reproducible and repeated runs cannot compound transformations. The active version is the cleaned copy when present.
- **Profiles are cached** in `analysis_results`, keyed by dataset path, file mtime and a cache version. Cleaning a dataset invalidates stale results automatically.
- **JSON storage for analytical payloads** keeps the schema small while allowing chart-ready outputs. Query-critical fields (IDs, types, timestamps, counts) are real columns with indexes.
- **Deterministic-first AI** is a correctness feature, not a fallback hack: numbers are never delegated to a language model.
- **Upload validation happens before persistence**, uses an in-memory parse, sanitizes filenames and confines writes to the storage root.
- **SQLite is a first-class local/testing option**, but PostgreSQL is the deployment target; migrations render JSONB correctly and the Compose entrypoint applies them.
- **No authentication is implemented.** The app is explicitly a single-user local MVP. Adding auth later means adding middleware/identity to dependencies without changing service code.
- **Anomaly record payloads are capped at 2,000 records** per run to bound JSON size; the response reports truncation. This is documented rather than hidden.

---

## Screenshots

Real screenshots captured from the running application:

| Overview | Analytics |
|---|---|
| ![Overview dashboard](docs/screenshots/overview.png) | ![Analytics page](docs/screenshots/analytics.png) |

| Anomaly detection | AI assistant |
|---|---|
| ![Anomaly detection](docs/screenshots/anomalies.png) | ![AI assistant](docs/screenshots/assistant.png) |

| Dataset explorer | Cleaning workspace |
|---|---|
| ![Dataset explorer](docs/screenshots/datasets.png) | ![Cleaning workspace](docs/screenshots/cleaning.png) |

> The UI shown is generated from live API responses. No dashboard metric is hardcoded.
> Regenerate these images with `python scripts/capture_screenshots.py` (requires `playwright` and a running app).

---

## Limitations and future improvements

Current scope (intentional for the MVP):

- Single-user, no authentication/authorization.
- Local filesystem storage, not object storage.
- CSV only; no Excel/Parquet connectors.
- Synchronous LLM calls (run in FastAPI’s threadpool) with a hard timeout.
- Anomaly history stores up to 2,000 flagged records per run.
- No background job queue; large profiling requests are handled inline with caching.

Natural next steps:

1. Authentication and per-user dataset ownership (JWT/OIDC) plus row-level authorization.
2. Background workers (Celery/RQ) for very large profiles and anomaly runs.
3. Object storage with signed URLs and virus scanning.
4. Additional connectors (Excel, Parquet, warehouse tables) and scheduled ingestion.
5. Anomaly model comparison, explainability (SHAP) and labeled evaluation when ground truth exists.
6. Conversation memory with provider-side tools that call the same deterministic engine.
7. CI pipeline running Ruff, Pytest and Docker image builds; observability via OpenTelemetry.

---

## License

Educational / portfolio project. Add a license before commercial distribution.
