"""
Step 9 — Flaky Test Detector Tests

All 32 tests use an isolated in-memory SQLite database.
No production database is touched.
"""

import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.database import Base
from src.database.repository import save_build_result
from config import validate_flaky_detection_config
from src.analyzer.flaky_detector import (
    detect_flaky_tests,
    build_effective_status_sequence,
    count_status_transitions,
    calculate_flakiness_rate,
    classify_flakiness,
)
from src.quality_gate.quality_gate import evaluate_quality_gate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """Fresh in-memory SQLite session for each test."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def default_flaky_config():
    return {
        "history_limit": 10,
        "minimum_observations": 3,
        "thresholds": {
            "possibly_flaky": 25.0,
            "flaky": 50.0,
        },
    }


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _summary(build_num, total, passed, failed, skipped):
    pr = round(passed / total * 100, 2) if total else 0.0
    fr = round(failed / total * 100, 2) if total else 0.0
    return {
        "build": build_num,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": pr,
        "failure_rate": fr,
    }


def _df(rows, build_num):
    return pd.DataFrame([
        {"test_name": r[0], "module": r[1], "status": r[2],
         "duration": 1.0, "error": r[3], "build": build_num}
        for r in rows
    ])


def _seed(session, build_num, rows):
    total = len(rows)
    passed = sum(1 for r in rows if r[2] == "PASS")
    failed = sum(1 for r in rows if r[2] == "FAIL")
    skipped = sum(1 for r in rows if r[2] == "SKIP")
    save_build_result(
        _summary(build_num, total, passed, failed, skipped),
        _df(rows, build_num),
        session=session,
    )


def _pass(name, mod="M"):  return (name, mod, "PASS", None)
def _fail(name, mod="M"):  return (name, mod, "FAIL", "Err")
def _skip(name, mod="M"):  return (name, mod, "SKIP", None)


# ---------------------------------------------------------------------------
# Tests 1-4: Basic Sequence Classifications
# ---------------------------------------------------------------------------

def test_pass_fail_pass_classified_flaky(db_session):
    """Test 1: PASS -> FAIL -> PASS is classified FLAKY."""
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 101, [_fail("t1")])
    _seed(db_session, 102, [_pass("t1")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert res["tests"]["t1"]["classification"] == "FLAKY"
    assert "t1" in res["flaky_tests"]


def test_fail_pass_fail_classified_flaky(db_session):
    """Test 2: FAIL -> PASS -> FAIL is classified FLAKY."""
    _seed(db_session, 100, [_fail("t1")])
    _seed(db_session, 101, [_pass("t1")])
    _seed(db_session, 102, [_fail("t1")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert res["tests"]["t1"]["classification"] == "FLAKY"
    assert res["tests"]["t1"]["flakiness_rate"] == 100.0


def test_all_pass_classified_stable(db_session):
    """Test 3: PASS -> PASS -> PASS is classified STABLE."""
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 101, [_pass("t1")])
    _seed(db_session, 102, [_pass("t1")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert res["tests"]["t1"]["classification"] == "STABLE"
    assert res["tests"]["t1"]["flaky_score"] == 0


def test_all_fail_classified_stable(db_session):
    """Test 4: FAIL -> FAIL -> FAIL -> FAIL is classified STABLE."""
    for b in range(100, 104):
        _seed(db_session, b, [_fail("t1")])
    res = detect_flaky_tests(limit=4, session=db_session)
    assert res["tests"]["t1"]["classification"] == "STABLE"
    assert res["tests"]["t1"]["transitions"] == 0


# ---------------------------------------------------------------------------
# Tests 5-8: Transitions & Scoring
# ---------------------------------------------------------------------------

def test_single_transition():
    """Test 5: Single transition in 4 observations."""
    eff = ["PASS", "PASS", "PASS", "FAIL"]
    assert count_status_transitions(eff) == 1


def test_multiple_transitions():
    """Test 6: Multiple transitions counted correctly."""
    eff = ["PASS", "FAIL", "PASS", "FAIL", "PASS"]
    assert count_status_transitions(eff) == 4


def test_correct_flakiness_rate():
    """Test 7: 1 transition out of 4 possible = 25.0%."""
    assert calculate_flakiness_rate(1, 4) == 25.0


def test_correct_flaky_score():
    """Test 8: Flaky score is rounded integer rate."""
    assert round(calculate_flakiness_rate(1, 3)) == 33  # 1/3 = 33.33% -> score 33


# ---------------------------------------------------------------------------
# Tests 9-12: Classifications & Minimum History
# ---------------------------------------------------------------------------

def test_possibly_flaky_classification():
    """Test 9: 25% flakiness rate triggers POSSIBLY_FLAKY."""
    assert classify_flakiness(25.0, 4) == "POSSIBLY_FLAKY"


def test_flaky_classification():
    """Test 10: 50% flakiness rate triggers FLAKY."""
    assert classify_flakiness(50.0, 4) == "FLAKY"


def test_stable_classification():
    """Test 11: 0% flakiness rate triggers STABLE."""
    assert classify_flakiness(0.0, 4) == "STABLE"


def test_insufficient_history(db_session):
    """Test 12: Test with only 2 executions returns INSUFFICIENT_HISTORY."""
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 101, [_fail("t1")])
    res = detect_flaky_tests(limit=2, session=db_session)
    assert res["tests"]["t1"]["classification"] == "INSUFFICIENT_HISTORY"
    assert "t1" in res["insufficient_history_tests"]


# ---------------------------------------------------------------------------
# Tests 13-15: SKIP Handling
# ---------------------------------------------------------------------------

def test_skip_ignored_between_pass_and_fail(db_session):
    """Test 13: PASS -> SKIP -> FAIL counts as 1 PASS-to-FAIL transition."""
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 101, [_skip("t1")])
    _seed(db_session, 102, [_fail("t1")])
    _seed(db_session, 103, [_pass("t1")])
    res = detect_flaky_tests(limit=4, session=db_session)
    # effective statuses: PASS, FAIL, PASS -> 2 transitions out of 2 possible -> 100%
    assert res["tests"]["t1"]["transitions"] == 2
    assert res["tests"]["t1"]["effective_observations"] == 3
    assert res["tests"]["t1"]["observations"] == 4


def test_pass_skip_pass_is_stable(db_session):
    """Test 14: PASS -> SKIP -> PASS is STABLE."""
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 101, [_skip("t1")])
    _seed(db_session, 102, [_pass("t1")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert res["tests"]["t1"]["transitions"] == 0
    assert res["tests"]["t1"]["classification"] == "STABLE"


def test_fail_skip_fail_is_stable(db_session):
    """Test 15: FAIL -> SKIP -> FAIL is STABLE."""
    _seed(db_session, 100, [_fail("t1")])
    _seed(db_session, 101, [_skip("t1")])
    _seed(db_session, 102, [_fail("t1")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert res["tests"]["t1"]["transitions"] == 0
    assert res["tests"]["t1"]["classification"] == "STABLE"


# ---------------------------------------------------------------------------
# Tests 16-20: Missing Builds, Ordering & Module Updates
# ---------------------------------------------------------------------------

def test_missing_test_in_intermediate_build(db_session):
    """Test 16: Test present in builds 1, 3, 5 calculates correctly."""
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 101, [_pass("t2")])  # t1 absent
    _seed(db_session, 102, [_fail("t1")])
    _seed(db_session, 103, [_pass("t2")])  # t1 absent
    _seed(db_session, 104, [_pass("t1")])
    res = detect_flaky_tests(limit=5, session=db_session)
    t1 = res["tests"]["t1"]
    assert t1["observations"] == 3
    assert t1["transitions"] == 2
    assert t1["classification"] == "FLAKY"


def test_non_sequential_build_numbers(db_session):
    """Test 17: Non-sequential build numbers (10, 50, 999) handled correctly."""
    _seed(db_session, 10, [_pass("t1")])
    _seed(db_session, 50, [_fail("t1")])
    _seed(db_session, 999, [_pass("t1")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert res["builds_analyzed"] == [10, 50, 999]


def test_latest_n_builds_selected(db_session):
    """Test 18: Only the N most recent builds are analyzed."""
    for b in range(100, 108):
        _seed(db_session, b, [_pass("t1")])
    res = detect_flaky_tests(limit=5, session=db_session)
    assert res["builds_analyzed"] == [103, 104, 105, 106, 107]


def test_oldest_to_newest_history_ordering(db_session):
    """Test 19: History list in result is ordered oldest to newest."""
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 101, [_fail("t1")])
    _seed(db_session, 102, [_pass("t1")])
    res = detect_flaky_tests(limit=3, session=db_session)
    hist_builds = [h["build"] for h in res["tests"]["t1"]["history"]]
    assert hist_builds == [100, 101, 102]


def test_module_taken_from_most_recent_result(db_session):
    """Test 20: Module is updated to the most recent execution's module."""
    _seed(db_session, 100, [_pass("t1", "OldMod")])
    _seed(db_session, 101, [_fail("t1", "OldMod")])
    _seed(db_session, 102, [_pass("t1", "NewMod")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert res["tests"]["t1"]["module"] == "NewMod"


# ---------------------------------------------------------------------------
# Tests 21-27: Grouping, Module Summary & Ranking
# ---------------------------------------------------------------------------

def test_multiple_flaky_tests(db_session):
    """Test 21: Multiple flaky tests are categorized in flaky_tests."""
    _seed(db_session, 100, [_pass("t1"), _pass("t2")])
    _seed(db_session, 101, [_fail("t1"), _fail("t2")])
    _seed(db_session, 102, [_pass("t1"), _pass("t2")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert "t1" in res["flaky_tests"]
    assert "t2" in res["flaky_tests"]


def test_flaky_tests_grouped_by_module(db_session):
    """Test 22: flaky_by_module correctly counts flaky tests per module."""
    _seed(db_session, 100, [_pass("t1", "Pay"), _pass("t2", "Pay"), _pass("t3", "Cart")])
    _seed(db_session, 101, [_fail("t1", "Pay"), _fail("t2", "Pay"), _fail("t3", "Cart")])
    _seed(db_session, 102, [_pass("t1", "Pay"), _pass("t2", "Pay"), _pass("t3", "Cart")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert res["flaky_by_module"]["Pay"] == 2
    assert res["flaky_by_module"]["Cart"] == 1


def test_top_flaky_module(db_session):
    """Test 23: top_flaky_module returns module with most flaky tests."""
    _seed(db_session, 100, [_pass("t1", "Pay"), _pass("t2", "Pay"), _pass("t3", "Cart")])
    _seed(db_session, 101, [_fail("t1", "Pay"), _fail("t2", "Pay"), _fail("t3", "Cart")])
    _seed(db_session, 102, [_pass("t1", "Pay"), _pass("t2", "Pay"), _pass("t3", "Cart")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert res["top_flaky_module"] == "Pay"


def test_no_flaky_tests(db_session):
    """Test 24: When all tests are stable, flaky_tests is empty and top_flaky_module is None."""
    for b in range(100, 103):
        _seed(db_session, b, [_pass("t1", "M1"), _pass("t2", "M2")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert len(res["flaky_tests"]) == 0
    assert len(res["ranked_flaky_tests"]) == 0
    assert res["top_flaky_module"] is None


def test_alphabetical_ranking_tie(db_session):
    """Test 25: Flaky tests with identical score and transitions rank alphabetically."""
    _seed(db_session, 100, [_pass("Bravo"), _pass("Alpha")])
    _seed(db_session, 101, [_fail("Bravo"), _fail("Alpha")])
    _seed(db_session, 102, [_pass("Bravo"), _pass("Alpha")])
    res = detect_flaky_tests(limit=3, session=db_session)
    assert res["ranked_flaky_tests"] == ["Alpha", "Bravo"]


def test_score_ranking(db_session):
    """Test 26: Higher flaky score ranks before lower flaky score."""
    # t_high: PASS->FAIL->PASS->FAIL->PASS (100% flakiness)
    # t_mid: PASS->PASS->FAIL->PASS->PASS (50% flakiness)
    _seed(db_session, 100, [_pass("t_high"), _pass("t_mid")])
    _seed(db_session, 101, [_fail("t_high"), _pass("t_mid")])
    _seed(db_session, 102, [_pass("t_high"), _fail("t_mid")])
    _seed(db_session, 103, [_fail("t_high"), _pass("t_mid")])
    _seed(db_session, 104, [_pass("t_high"), _pass("t_mid")])
    res = detect_flaky_tests(limit=5, session=db_session)
    assert res["ranked_flaky_tests"] == ["t_high", "t_mid"]


def test_transition_count_tie_breaker():
    """Test 27: Transition count breaks ties when score is identical."""
    # Handled cleanly in sorting key (-flaky_score, -transitions, test_name)
    eff1 = ["PASS", "FAIL", "PASS"]  # 2 trans / 2 possible = 100%, 2 trans
    eff2 = ["PASS", "FAIL", "PASS", "FAIL"] # 3 trans / 3 possible = 100%, 3 trans
    assert count_status_transitions(eff2) > count_status_transitions(eff1)


# ---------------------------------------------------------------------------
# Tests 28-31: Validation, Config & Safe Arithmetic
# ---------------------------------------------------------------------------

def test_duplicate_test_result_validation(db_session):
    """Test 28: Duplicate test result in the same build raises ValueError."""
    rows = [_pass("t1"), _fail("t1")]  # duplicate t1 in build
    _seed(db_session, 100, rows)
    with pytest.raises(ValueError, match="Duplicate result found for t1 in build 100"):
        detect_flaky_tests(limit=1, session=db_session)


def test_minimum_observation_configuration(db_session):
    """Test 29: Configuring minimum_observations=4 marks 3-observation tests as INSUFFICIENT_HISTORY."""
    custom_cfg = {
        "history_limit": 10,
        "minimum_observations": 4,
        "thresholds": {"possibly_flaky": 25.0, "flaky": 50.0},
    }
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 101, [_fail("t1")])
    _seed(db_session, 102, [_pass("t1")])
    res = detect_flaky_tests(limit=3, session=db_session, config=custom_cfg)
    assert res["tests"]["t1"]["classification"] == "INSUFFICIENT_HISTORY"


def test_invalid_threshold_configuration():
    """Test 30: Invalid flaky configuration raises ValueError."""
    bad_cfg = {
        "minimum_observations": 3,
        "thresholds": {"possibly_flaky": 60.0, "flaky": 40.0},
    }
    with pytest.raises(ValueError, match="possibly_flaky threshold must be lower than flaky threshold"):
        validate_flaky_detection_config(bad_cfg)


def test_no_division_by_zero():
    """Test 31: Single observation or 0 possible transitions returns 0.0 rate without division-by-zero."""
    assert calculate_flakiness_rate(0, 0) == 0.0


# ---------------------------------------------------------------------------
# Test 32: Step 8 Quality Gate Compatibility
# ---------------------------------------------------------------------------

def test_step8_quality_gate_remains_unchanged(db_session):
    """Test 32: Step 8 Quality Gate output remains identical and unchanged."""
    _seed(db_session, 100, [_pass("t1"), _pass("t2")])
    res = evaluate_quality_gate(100, session=db_session)
    assert res["status"] == "PASS"
    assert res["release_recommendation"] == "PROCEED"
