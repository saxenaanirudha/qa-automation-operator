# QA Automation Operator

A production-grade QA test operations and test analytics platform designed to ingest automated test execution results (CSV and JUnit XML), identify failures, detect flaky tests, apply configurable Quality Gates, calculate module risk scores, and generate comprehensive interactive visual dashboards. Exposes both a resilient CLI interface and a high-performance FastAPI REST API service supporting both SQLite and PostgreSQL storage.

---

## Key Features

- **Multi-Format Ingestion:** Ingests both standard CSV test results and standard JUnit XML (single suite, multi-suite, and nested suites) with automatic schema normalization.
- **Security Hardening (Barn Door Protocol):**
  - Constant-time `X-API-Key` authentication via `secrets.compare_digest`.
  - Fail-closed production startup gate refusing to start if `API_KEY` is unconfigured.
  - In-memory sliding-window rate limiting per client IP.
  - Strict proxy header validation: `X-Forwarded-For` is ignored unless explicitly enabled from trusted proxies.
  - XML external entity expansion (XXE / Billion Laughs) rejection.
  - Streaming file upload size validation (enforced in 64 KB chunks up to 10 MB).
  - Path traversal defense via server-generated UUID temporary files.
- **Deep Test Analytics:**
  - **Failure Diagnostics:** Root cause pattern grouping, error classification, and component failure clustering.
  - **Build Comparison:** Automated regression tracking against the previous build (new failures, recovered tests, persistent issues).
  - **Historical Trend Engine:** Multi-build pass/fail trajectory and module stability trends.
  - **Flaky Test Detector:** Transition tracking (`PASS ↔ FAIL`) across historical runs to identify non-deterministic tests.
  - **Risk Scoring:** Algorithmic module risk assessment (0–100 score) categorizing components into `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` risk.
- **Automated Quality Gates:** Enforces automated release readiness decisions (`PASS / PROCEED`, `WARNING / REVIEW`, `FAIL / BLOCK`) based on configurable failure rate, risk score, and regression thresholds.
- **Dual Execution Interfaces:**
  - **CLI (`main.py`):** Standalone zero-dependency command-line runner for local terminal use and CI/CD pipelines.
  - **FastAPI Service (`src.api.app`):** Async REST API with OpenAPI/Swagger documentation, background reporting, and webhook dispatching.
- **Dual Database Architecture:** Zero-configuration local SQLite for rapid testing and production-ready PostgreSQL with SQLAlchemy connection pooling and duplicate submission conflict handling.
- **Interactive Visual Reporting:** Generates standalone, self-contained HTML reports with embedded CSS, base64 Matplotlib trend charts, and modal failure details.
- **Notification Engine:** Dispatches formatted quality summaries and gate decisions to Slack and Microsoft Teams webhooks.

---

## Architecture

```text
       Automation Framework / CI (GitHub Actions, Jenkins, Pytest)
                                 │
                                 ▼
                     CSV / JUnit XML Test Results
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       CLI Interface (main.py)       FastAPI REST Service (port 8000)
                 │                               │
                 │                 ┌─────────────┴─────────────┐
                 │                 ▼                           ▼
                 │         Security Middleware         API Route Handlers
                 │         - Constant-Time API Key     - /health, /builds
                 │         - Sliding Rate Limiter      - /analyze, /analysis
                 │         - Trusted Proxy Filter      - /report, /notify
                 │                 │                           │
                 └─────────────────┼───────────────────────────┘
                                   ▼
                    Core Analytics & Pipeline Engine
         ┌───────────────────────────────────────────────────┐
         │ - Result Parsers (CSV & JUnit XML with XXE Guard) │
         │ - Failure Analysis & Stack Trace Normalizer       │
         │ - Historical Trend & Regression Engine            │
         │ - Module Risk Scoring Engine                      │
         │ - Flaky Test Transition Detector                  │
         │ - Quality Gate Policy Evaluator                   │
         └─────────────────────────┬─────────────────────────┘
                                   ▼
                      Data Persistence Layer
                     (SQLAlchemy 2.0 ORM Engine)
                 ┌─────────────────┴─────────────────┐
                 ▼                                   ▼
        SQLite Database                     PostgreSQL Database
      (sqlite:///qa_results.db)           (postgresql+psycopg2://)
         [Dev & Local Pytest]               [Production & Docker]
                                   │
                 ┌─────────────────┴─────────────────┐
                 ▼                                   ▼
       HTML Dashboard Generator             Notification Dispatcher
      (Standalone Self-Contained)           (Slack & MS Teams Webhooks)
```

---

## Technology Stack & Requirements

- **Runtime:** Python 3.12+ (tested on Python 3.12.10)
- **Web Framework:** FastAPI 0.165+, Starlette 1.10+, Uvicorn 0.54+
- **Data Analysis & Charts:** Pandas 3.1+, Matplotlib 3.11+
- **Database ORM:** SQLAlchemy 2.1+, psycopg2-binary 2.9+
- **Templating:** Jinja2 3.1+
- **HTTP Client:** HTTPX 0.28+, Requests 2.34+
- **Configuration:** PyYAML 6.0+, Python-Dotenv 1.2+
- **Testing:** Pytest 9.2+, Pytest-Cov 7.1+

---

## Installation & Setup

### 1. Clone & Set Up Virtual Environment

```bash
# Clone the repository
git clone <repository-url>
cd qa-automation-operator

# Create and activate Python virtual environment
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate

# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and adjust settings as required:

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | Set to `production` to enforce fail-closed API key security. |
| `API_KEY` | *(empty)* | Secret key for `X-API-Key` authentication. Required in production. |
| `REQUIRE_API_KEY` | `false` | When `true`, enforces `X-API-Key` even in `development` mode. |
| `RATE_LIMIT_ENABLED` | `true` | Enables or disables sliding-window rate limiting. |
| `RATE_LIMIT_REQUESTS`| `60` | Maximum requests allowed per rate limit window. |
| `RATE_LIMIT_WINDOW`  | `60` | Duration of rate limiting window in seconds. |
| `TRUST_PROXIES`      | `false`| When `true`, parses client IP from `X-Forwarded-For`. |
| `TRUSTED_PROXIES`    | `127.0.0.1,::1,testclient` | Comma-separated list of peer IPs permitted to forward client headers. |
| `DATABASE_URL`       | `sqlite:///qa_results.db` | SQLAlchemy connection URL (SQLite or PostgreSQL). |
| `SLACK_WEBHOOK_URL`  | *(empty)* | Optional Incoming Webhook URL for Slack alerts. |
| `TEAMS_WEBHOOK_URL`  | *(empty)* | Optional Incoming Webhook URL for Teams alerts. |
| `REPORT_BASE_URL`    | *(empty)* | Optional base URL prepended to report links in webhooks. |

---

## Usage Guide

### Command-Line Interface (CLI)

The CLI runner `main.py` is fully self-contained and operates directly without starting the web server:

```bash
# Analyze a test run from CSV
python main.py --input sample_data/test_results.csv

# Analyze a test run from JUnit XML
python main.py --input sample_data/junit_results.xml --format junit

# Enforce Quality Gate (exits with code 1 if Quality Gate fails)
python main.py --input sample_data/test_results.csv --enforce-quality-gate

# Generate an HTML report
python main.py --input sample_data/test_results.csv --report

# Dispatch notifications on completion
python main.py --input sample_data/test_results.csv --notify --slack --teams
```

### PowerShell Helper Script (Windows)

```powershell
# Run CLI demo analysis
.\start-project.ps1 -Mode cli

# Start the FastAPI server locally
.\start-project.ps1 -Mode api

# Start Docker Compose services
.\start-project.ps1 -Mode docker
```

### Running the FastAPI REST API

Start the local development server:

```bash
uvicorn src.api.app:app --host 127.0.0.1 --port 8000 --reload
```

Interactive OpenAPI Swagger documentation is immediately accessible at:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

---

## API Endpoints Reference

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `GET` | `/health` | No | Liveness probe returning application status and version. |
| `GET` | `/health/db` | No | Verifies database connectivity and query execution. |
| `GET` | `/builds` | Optional* | Lists stored build history (`?limit=20`). |
| `GET` | `/builds/{build}` | Optional* | Retrieves summary metrics for a specific build. |
| `GET` | `/builds/{build}/tests` | Optional* | Retrieves individual test results (`?status=FAIL&module=Payment`). |
| `GET` | `/builds/{build}/failures` | Optional* | Returns detailed failure pattern breakdown. |
| `GET` | `/builds/{build}/comparison` | Optional* | Compares specified build against preceding build. |
| `GET` | `/builds/{build}/risk` | Optional* | Calculates module risk scores and risk ranking. |
| `GET` | `/builds/{build}/quality-gate`| Optional* | Evaluates Quality Gate status and triggered rules. |
| `POST`| `/builds/{build}/report` | **Yes** (`X-API-Key`) | Triggers server-side HTML dashboard report generation. |
| `POST`| `/builds/{build}/notify` | **Yes** (`X-API-Key`) | Dispatches formatted alert payload to configured webhooks. |
| `GET` | `/analysis/trends` | Optional* | Multi-build quality trajectory and failure trend analysis. |
| `GET` | `/analysis/flaky-tests` | Optional* | Detects non-deterministic tests across historical builds. |
| `POST`| `/analyze` | **Yes** (`X-API-Key`) | Multipart upload for `.csv` or `.xml` test results. |

*\*Note: When `REQUIRE_API_KEY=true` or in production mode, all sensitive endpoints enforce authentication.*

### Making Authenticated Requests

```bash
# Upload and analyze a test execution result file
curl -X POST "http://localhost:8000/analyze" \
  -H "X-API-Key: your-secret-api-key" \
  -F "file=@sample_data/test_results.csv" \
  -F "format=csv"

# Trigger Slack/Teams notification for build 245
curl -X POST "http://localhost:8000/builds/245/notify" \
  -H "X-API-Key: your-secret-api-key" \
  -H "Content-Type: application/json" \
  -d '{"slack": true, "teams": false}'
```

---

## Database Configuration

### SQLite (Default for Local Development & Testing)
Zero-configuration SQLite database stored locally:
```bash
DATABASE_URL=sqlite:///qa_results.db
```
SQLAlchemy SQLite connection includes `timeout=30` to handle brief file locks during concurrent reads.

### PostgreSQL (Production & Containerized Deployment)
```bash
DATABASE_URL=postgresql+psycopg2://qa_user:<REPLACE_WITH_STRONG_PASSWORD>@postgres:5432/qa_operator
```
The application manages table initialization via SQLAlchemy ORM metadata (`init_db()`), connection pooling, and explicit rollback on concurrent duplicate key conflicts (`DuplicateBuildError`).

---

## Docker Compose & Container Security

To run the application inside Docker containers:

```bash
# Launch API and PostgreSQL services
docker compose up -d --build

# View container logs
docker compose logs -f api

# Tear down containers and preserve database volume
docker compose down
```

### Production Security Hardening Recommendations

When deploying `docker-compose.yml` to production environments:
1. **Change Default Credentials:** Set `POSTGRES_PASSWORD` and `POSTGRES_USER` via environment variables or Docker secrets. Never run with weak or unconfigured credentials.
2. **Restrict PostgreSQL Port Binding:** Modify `docker-compose.yml` to bind `127.0.0.1:5432:5432` or omit host port exposure entirely, allowing access only within the internal Docker bridge network (`qa_api` -> `qa_postgres`).
3. **Configure API Keys:** Inject `ENVIRONMENT=production` and `API_KEY=<strong-random-key>` into container environment variables.
4. **Set Resource Constraints:** Specify CPU and memory limits (`deploy.resources.limits`) to prevent denial-of-service via resource exhaustion.

---

## Verification & Testing

The project maintains a rigorous, multi-layered test suite enforced under the Barn Door Protocol.

### Running Pytest

```bash
# Run the full test suite with verbose output
pytest -v

# Run with test coverage measurement
pytest --cov=src --cov-report=term
```

### Current Verification Status

- **Unit & Regression Tests:** **281 PASSED**, 0 failed, 0 errors.
- **Code Coverage:** **92%** across 1,838 statements.
- **Security Tests:**
  - `tests/test_api_security.py` verifies constant-time comparison, missing/invalid keys, fail-closed production startup, sliding-window rate limiting, and trusted proxy header filtering.
  - `tests/test_barn_door_remediation.py` verifies streaming upload size capping, path traversal protection, concurrent duplicate submission rollback, thread-safe Matplotlib generation, and XML entity expansion denial.
- **PostgreSQL Integration Tests:**
  - Located in `tests/test_postgres_integration.py`.
  - **Status: 4 SKIPPED / BLOCKED.** Live container integration tests require an active Docker engine and PostgreSQL container. On host environments without a running Docker daemon, these tests safely detect absence and skip without falsifying results.

---

## License

This project is licensed under the terms of the **MIT License**. See the [LICENSE](LICENSE) file for details.
