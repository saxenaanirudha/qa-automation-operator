# qa-automation-operator

A production-level QA operations platform designed to analyze automated test results, identify failures, detect flaky tests, apply Quality Gates, and generate comprehensive reports. Exposes both a CLI interface and a production-ready FastAPI REST API service with PostgreSQL persistent storage.

## Problem Statement
Managing automated test execution results at scale is challenging. Test reports are scattered, identifying flaky tests manually is tedious, and failing tests often lack immediate visibility to the right teams.

This project solves this by automatically parsing test results, analyzing trends, identifying failure patterns by components, enforcing quality gates, calculating risk scores, detecting flaky tests, and notifying stakeholders via Slack/Teams.

---

## Production Architecture (Step 14)

```text
  Automation Framework / CI (GitHub Actions, Jenkins, Pytest)
                                ↓
                        CSV / JUnit XML
                                ↓
                    QA Automation Operator
               ┌────────────────┴────────────────┐
               │                                 │
           CLI (main.py)               FastAPI REST API (port 8000)
               │                                 │
               └────────────────┬────────────────┘
                                ↓
                  Pipeline & Analytics Engine
             (Parser, Failure, Trend, Risk, Gate, Flaky)
                                ↓
           SQLAlchemy ORM + Connection Management Layer
                 (Isolate SQLite vs PostgreSQL URLs)
               ┌────────────────┴────────────────┐
               │                                 │
    SQLite (sqlite:///qa_results.db)   PostgreSQL (postgresql+psycopg2://)
         (Local Dev & Pytest)              (Docker Compose & Prod)
                                ↓
                 HTML Dashboard & Notification Service
```

---

## Current Development Status
**Step 14 - PostgreSQL + FastAPI Production Upgrade**

The application is upgraded from a local CLI tool into a production-style QA service. It provides:
- **FastAPI REST API:** Full HTTP endpoints for builds, tests, failure analysis, build comparisons, risk analysis, Quality Gates, flaky test detection, HTML report generation, and Slack/Teams notification triggers.
- **PostgreSQL Support:** Shared persistent build history across runs via `DATABASE_URL`.
- **SQLite Compatibility:** Unchanged zero-config local SQLite support for dev/testing.
- **Docker Compose:** Containerized API and PostgreSQL setup with volume persistence and health checks.
- **CLI Compatibility:** Unchanged `main.py` CLI compatibility for local & CI workflows.

---

## REST API Endpoints & Interactive Documentation

When running the FastAPI server or Docker Compose, interactive Swagger documentation is available at:
`http://localhost:8000/docs` (or ReDoc at `http://localhost:8000/redoc`).

### Key Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Liveness health check |
| `GET` | `/health/db` | Database connectivity health check |
| `GET` | `/builds` | List stored builds (`?limit=20`) |
| `GET` | `/builds/{build}` | Get summary metrics for a build |
| `GET` | `/builds/{build}/tests` | Get test results (`?status=FAIL&module=Payment`) |
| `GET` | `/builds/{build}/failures` | Get failure analysis breakdown |
| `GET` | `/builds/{build}/comparison` | Compare build against previous build |
| `GET` | `/builds/{build}/risk` | Calculate module risk scores |
| `GET` | `/builds/{build}/quality-gate` | Evaluate Quality Gate rules |
| `POST` | `/builds/{build}/report` | Trigger server-side HTML report generation |
| `POST` | `/builds/{build}/notify` | Trigger Slack/Teams webhook notifications |
| `GET` | `/analysis/trends` | Historical quality trend analysis |
| `GET` | `/analysis/flaky-tests` | Detect flaky tests across builds |
| `POST` | `/analyze` | Multipart CSV/XML test result file upload and execution pipeline |

---

## Docker Compose Setup (FastAPI + PostgreSQL)

Launch the API backend and PostgreSQL database with named volume data persistence:

```bash
docker compose up --build -d
```

Check logs and health status:
```bash
docker compose logs -f api
```

Upload a CSV test result file to the API:
```bash
curl -X POST "http://localhost:8000/analyze" \
  -F "file=@sample_data/test_results_247.csv" \
  -F "format=csv"
```

Stop services:
```bash
docker compose down
```

---

## Database Strategy: SQLite vs PostgreSQL

The system uses SQLAlchemy ORM to isolate database connection details from business logic via `DATABASE_URL`:

- **SQLite (Local Dev & Testing):** `DATABASE_URL=sqlite:///qa_results.db`
- **PostgreSQL (Production & Docker Compose):** `DATABASE_URL=postgresql+psycopg2://qa_user:change_me@postgres:5432/qa_operator`

---

## GitHub Actions CI/CD Integration

The workflow (`.github/workflows/qa-pipeline.yml`) executes on every `push` and `pull_request`:
1. **Pytest Run:** Runs unit test suite (`pytest -v --junitxml=reports/pytest-results.xml`).
2. **QA Automation Operator:** Runs CLI enforcement against generated JUnit XML (`python main.py --input reports/pytest-results.xml --enforce-quality-gate`).
3. **Artifact Upload & Step Summary:** Uploads reports and writes Markdown summaries.

---

## Local Setup & Test Suite Execution

1. **Clone repository & activate virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate # Windows: venv\Scripts\activate
   ```
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Run unit & API test suite:**
   ```bash
   pytest -v
   ```
4. **Run FastAPI development server locally:**
   ```bash
   uvicorn src.api.app:app --reload
   ```

---

## QA Dashboard (Dashboard V2)

The platform generates a self-contained, responsive **Dashboard V2** designed for daily QA monitoring, release readiness decisions, CI/CD reporting, and technical demonstrations.

### What the Dashboard Shows

1. **Header & Status Badges:** Current build identifier, generation timestamp, overall QA trend (`IMPROVING`, `WORSENING`, `STABLE`, `MIXED`), and release recommendation.
2. **Top KPI Cards:** Total tests, passed, failed, skipped, pass rate percentage (with progress visualization), Quality Gate status, and Release decision.
3. **Quality Gate Hero & Evaluated Policies:** Prominent release recommendation banner, list of triggered policy rules with severity, detailed check breakdown table, and high-priority QA attention action items.
4. **Build Comparison:** Comparison against previous build showing pass rate delta, failure delta, direction indicators (↑ Better, ↓ Worse, → Same), newly failing tests, recovered tests, and persistent failures.
5. **Build Quality Trend:** Multi-build pass rate and failure trajectory with high-resolution Matplotlib trend visualizations and improving/worsening module tracking.
6. **Risky Modules Analysis:** Ranked module risk scoring (0-100 scale), "#1 Highest Risk Module" spotlight card, visual risk level meters (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), and failure share breakdown.
7. **Flaky Test Detector:** Multi-build transition analysis tracking non-deterministic tests, flakiness score, and color-coded status history pills (`FAIL → PASS → FAIL`).
8. **Failure Analysis & Diagnostics:** Aggregate failure breakdown by module, error distribution, and a dedicated **Failed Test Details** section with wrapped error stack traces.

### How Quality Gate & Release Recommendations Work

| Quality Gate Status | Release Recommendation | Meaning & Action |
|---|---|---|
| **`PASS`** | **`PROCEED`** | All quality criteria satisfied; build is healthy and approved for release. |
| **`WARNING`** | **`REVIEW`** | Non-blocking thresholds exceeded (e.g. moderate flakiness or minor regressions); QA / Release lead review recommended. |
| **`FAIL`** | **`BLOCK`** | Critical quality thresholds breached (e.g. low pass rate, excessive failures, multiple high-risk modules); automated release blocked. |

### How to Generate the Dashboard

- **Via CLI:**
  ```bash
  python main.py --input sample_data/test_results.csv
  ```
- **Via PowerShell helper script:**
  ```powershell
  .\start-project.ps1 -Mode cli
  ```
- **Via REST API:**
  ```bash
  curl -X POST "http://localhost:8000/builds/245/report"
  ```

### Report Storage Location

Generated HTML reports are self-contained and stored locally under:
```text
reports/qa_report_build_<BUILD>.html
reports/assets/
```

---

## Portfolio Production Disclaimer

> [!NOTE]
> This application is designed as a modular portfolio-style QA engineering service. It does not enforce user authentication (OAuth/JWT), TLS termination, or rate limiting out of the box, which should be configured at an ingress controller / API gateway layer in multi-tenant enterprise deployments.

