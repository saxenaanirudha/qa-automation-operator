"""
Isolated PostgreSQL Integration Test Suite.

Tests database connectivity, schema creation, persistence, rollback,
and concurrent write safety when a PostgreSQL instance is available.
When PostgreSQL is unreachable or Docker is unavailable, tests are
gracefully marked as BLOCKED / SKIPPED rather than claiming false completion.
"""

import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.database.database import Base
from src.database.models import Build, TestResult
from src.database.repository import (
    save_build_result,
    get_build_by_number,
    DuplicateBuildError,
)

POSTGRES_TEST_URL = os.getenv(
    "POSTGRES_TEST_URL",
    "postgresql+psycopg2://qa_user:change_me@localhost:5432/qa_operator_test",
)


def is_postgres_available() -> bool:
    """Probes PostgreSQL database connectivity with a low timeout."""
    try:
        engine = create_engine(POSTGRES_TEST_URL, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# Skip entire module if PostgreSQL is not available
pytestmark = pytest.mark.skipif(
    not is_postgres_available(),
    reason="PostgreSQL integration BLOCKED: PostgreSQL service unreachable / Docker not available on host.",
)


@pytest.fixture(scope="module")
def pg_session_factory():
    """Module-level session factory connected to disposable test database."""
    engine = create_engine(POSTGRES_TEST_URL, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    yield session_factory
    # Teardown: clean up disposable tables
    Base.metadata.drop_all(bind=engine)


def test_postgres_connectivity_and_schema_init(pg_session_factory):
    """Verifies direct connectivity and schema creation on PostgreSQL."""
    session = pg_session_factory()
    try:
        result = session.execute(text("SELECT 1")).scalar()
        assert result == 1
    finally:
        session.close()


def test_postgres_build_persistence(pg_session_factory):
    """Verifies persisting build metrics and test records to PostgreSQL."""
    session = pg_session_factory()
    try:
        build_num = int(time.time_ns() % 10000000) + 80000
        summary = {
            "build": build_num,
            "total": 2,
            "passed": 1,
            "failed": 1,
            "skipped": 0,
            "pass_rate": 50.0,
            "failure_rate": 50.0,
        }
        df = pd.DataFrame([
            {"test_name": "test_auth", "module": "Auth", "status": "PASS", "duration": 0.4, "error": None},
            {"test_name": "test_pay", "module": "Payment", "status": "FAIL", "duration": 1.2, "error": "Timeout"},
        ])
        build = save_build_result(summary, df, session=session)
        assert build.build_number == build_num

        retrieved = get_build_by_number(build_num, session=session)
        assert retrieved is not None
        assert retrieved.total_tests == 2
        assert retrieved.failed == 1
    finally:
        session.close()


def test_postgres_duplicate_submission_rollback(pg_session_factory):
    """Verifies PostgreSQL unique constraint enforcement and transaction rollback on duplicate build."""
    session = pg_session_factory()
    try:
        build_num = int(time.time_ns() % 10000000) + 81000
        summary = {
            "build": build_num,
            "total": 1,
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "pass_rate": 100.0,
            "failure_rate": 0.0,
        }
        df = pd.DataFrame([
            {"test_name": "test_x", "module": "Core", "status": "PASS", "duration": 0.1, "error": None}
        ])
        save_build_result(summary, df, session=session)

        # Duplicate submission must raise DuplicateBuildError
        with pytest.raises(DuplicateBuildError):
            save_build_result(summary, df, session=session)
    finally:
        session.close()


def test_postgres_concurrent_writes(pg_session_factory):
    """Verifies transaction safety during concurrent writes to PostgreSQL."""
    build_num = int(time.time_ns() % 10000000) + 82000
    summary = {
        "build": build_num,
        "total": 1,
        "passed": 1,
        "failed": 0,
        "skipped": 0,
        "pass_rate": 100.0,
        "failure_rate": 0.0,
    }
    df = pd.DataFrame([
        {"test_name": "test_c", "module": "Core", "status": "PASS", "duration": 0.2, "error": None}
    ])

    results = []
    errors = []

    def worker():
        session = pg_session_factory()
        try:
            b = save_build_result(summary, df, session=session)
            results.append(b.build_number)
        except DuplicateBuildError:
            results.append("duplicate")
        except Exception as exc:
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert build_num in results
    assert results.count(build_num) == 1
    assert results.count("duplicate") == 3
