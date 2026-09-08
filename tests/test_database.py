import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.database import Base
from src.database.models import Build, TestResult
from src.database.repository import (
    save_build_result,
    get_build_by_number,
    get_all_builds,
    DuplicateBuildError
)

@pytest.fixture
def db_session():
    # Set up in-memory sqlite engine
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

def test_database_tables_initialize(db_session):
    # Verify tables metadata exists
    assert "builds" in Base.metadata.tables
    assert "test_results" in Base.metadata.tables

def test_build_summary_and_test_rows_save_correctly(db_session):
    summary = {
        "build": 101,
        "total": 2,
        "passed": 1,
        "failed": 1,
        "skipped": 0,
        "pass_rate": 50.0,
        "failure_rate": 50.0
    }
    df = pd.DataFrame([
        {"test_name": "test_pass", "module": "Auth", "status": "PASS", "duration": 1.2, "error": None, "build": 101},
        {"test_name": "test_fail", "module": "Auth", "status": "FAIL", "duration": 0.8, "error": "AssertionError", "build": 101}
    ])

    build = save_build_result(summary, df, session=db_session)
    
    # 1. Build summary saves correctly
    assert build.id is not None
    assert build.build_number == 101
    assert build.total_tests == 2
    assert build.passed == 1
    assert build.failed == 1
    assert build.skipped == 0
    assert build.pass_rate == 50.0
    assert build.failure_rate == 50.0

    # 2. All individual test rows save correctly and linked to the correct build
    assert len(build.test_results) == 2
    assert build.test_results[0].test_name == "test_pass"
    assert build.test_results[0].status == "PASS"
    assert build.test_results[0].build_id == build.id
    
    assert build.test_results[1].test_name == "test_fail"
    assert build.test_results[1].status == "FAIL"
    assert build.test_results[1].error == "AssertionError"
    assert build.test_results[1].build_id == build.id

def test_get_build_by_number(db_session):
    summary = {
        "build": 102,
        "total": 1,
        "passed": 1,
        "failed": 0,
        "skipped": 0,
        "pass_rate": 100.0,
        "failure_rate": 0.0
    }
    df = pd.DataFrame([
        {"test_name": "test_pass", "module": "Auth", "status": "PASS", "duration": 1.2, "error": "", "build": 102}
    ])

    save_build_result(summary, df, session=db_session)
    
    retrieved = get_build_by_number(102, session=db_session)
    assert retrieved is not None
    assert retrieved.build_number == 102

    non_existent = get_build_by_number(999, session=db_session)
    assert non_existent is None

def test_get_all_builds_and_ordering(db_session):
    summary_1 = {
        "build": 101, "total": 1, "passed": 1, "failed": 0, "skipped": 0, "pass_rate": 100.0, "failure_rate": 0.0
    }
    summary_2 = {
        "build": 102, "total": 1, "passed": 1, "failed": 0, "skipped": 0, "pass_rate": 100.0, "failure_rate": 0.0
    }
    df = pd.DataFrame([
        {"test_name": "test_pass", "module": "Auth", "status": "PASS", "duration": 1.2, "error": None, "build": 101}
    ])

    save_build_result(summary_1, df, session=db_session)
    save_build_result(summary_2, df, session=db_session)

    all_builds = get_all_builds(session=db_session)
    assert len(all_builds) == 2
    # Ordering should be newest (highest build_number) to oldest
    assert all_builds[0].build_number == 102
    assert all_builds[1].build_number == 101

def test_duplicate_build_rejected(db_session):
    summary = {
        "build": 103, "total": 1, "passed": 1, "failed": 0, "skipped": 0, "pass_rate": 100.0, "failure_rate": 0.0
    }
    df = pd.DataFrame([
        {"test_name": "test_pass", "module": "Auth", "status": "PASS", "duration": 1.2, "error": None, "build": 103}
    ])

    save_build_result(summary, df, session=db_session)

    with pytest.raises(DuplicateBuildError, match="Build 103 already exists in database."):
        save_build_result(summary, df, session=db_session)

def test_empty_error_value_stored_as_none(db_session):
    summary = {
        "build": 104, "total": 2, "passed": 2, "failed": 0, "skipped": 0, "pass_rate": 100.0, "failure_rate": 0.0
    }
    df = pd.DataFrame([
        {"test_name": "test_pass_nan", "module": "Auth", "status": "PASS", "duration": 1.2, "error": float('nan'), "build": 104},
        {"test_name": "test_pass_empty", "module": "Auth", "status": "PASS", "duration": 1.2, "error": "   ", "build": 104}
    ])

    build = save_build_result(summary, df, session=db_session)
    assert build.test_results[0].error is None
    assert build.test_results[1].error is None

def test_transaction_rollback_works(db_session):
    summary = {
        "build": 105, "total": 2, "passed": 1, "failed": 1, "skipped": 0, "pass_rate": 50.0, "failure_rate": 50.0
    }
    # One invalid row that will cause db insert error (e.g. missing test_name)
    df = pd.DataFrame([
        {"test_name": "test_pass", "module": "Auth", "status": "PASS", "duration": 1.2, "error": None, "build": 105},
        {"test_name": None, "module": "Auth", "status": "FAIL", "duration": 0.8, "error": "Err", "build": 105}
    ])

    with pytest.raises(Exception):
        save_build_result(summary, df, session=db_session)

    # Ensure build was not saved (rollback worked)
    build = get_build_by_number(105, session=db_session)
    assert build is None
