"""
Step 6 — Multi-Build Trend Analyzer Tests

All 27 tests use an isolated in-memory SQLite database.
No production database is touched.
"""
import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.database import Base
from src.database.repository import save_build_result
from src.analyzer.trend_analyzer import (
    analyze_trends,
    classify_trend,
    NotEnoughBuildsError,
    MINIMUM_BUILDS,
    PASS_RATE_TOLERANCE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """Fresh in-memory SQLite session for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _summary(build_num, total, passed, failed, skipped):
    pr = round(passed / total * 100, 2) if total else 0.0
    fr = round(failed / total * 100, 2) if total else 0.0
    return {"build": build_num, "total": total, "passed": passed,
            "failed": failed, "skipped": skipped, "pass_rate": pr, "failure_rate": fr}


def _df(rows, build_num):
    return pd.DataFrame([
        {"test_name": r[0], "module": r[1], "status": r[2],
         "duration": 1.0, "error": r[3], "build": build_num}
        for r in rows
    ])


def _seed(session, build_num, rows):
    total   = len(rows)
    passed  = sum(1 for r in rows if r[2] == "PASS")
    failed  = sum(1 for r in rows if r[2] == "FAIL")
    skipped = sum(1 for r in rows if r[2] == "SKIP")
    save_build_result(_summary(build_num, total, passed, failed, skipped),
                      _df(rows, build_num), session=session)


# Shorthand row builders
def _pass(name, mod="M"):  return (name, mod, "PASS", None)
def _fail(name, mod="M"):  return (name, mod, "FAIL", "Err")
def _skip(name, mod="M"):  return (name, mod, "SKIP", None)


# ---------------------------------------------------------------------------
# Tests 1-4: Pass Rate Trend (classify_trend pure-function tests)
# ---------------------------------------------------------------------------

def test_classify_trend_increasing_pass_rate():
    """Test 1: Increasing pass rate → IMPROVING."""
    assert classify_trend([88.0, 90.0, 91.0, 93.0, 95.0],
                          higher_is_better=True) == "IMPROVING"


def test_classify_trend_decreasing_pass_rate():
    """Test 2: Decreasing pass rate → WORSENING."""
    assert classify_trend([95.0, 94.0, 92.0, 90.0, 87.0],
                          higher_is_better=True) == "WORSENING"


def test_classify_trend_stable_pass_rate():
    """Test 3: Pass rate changes within tolerance → STABLE."""
    # All deltas ≤ 0.5
    assert classify_trend([92.0, 92.3, 92.0, 92.4, 92.1],
                          higher_is_better=True, tolerance=0.5) == "STABLE"


def test_classify_trend_mixed_pass_rate():
    """Test 4: Pass rate oscillating without clear direction → MIXED."""
    assert classify_trend([90.0, 95.0, 89.0, 94.0, 91.0],
                          higher_is_better=True) == "MIXED"


# ---------------------------------------------------------------------------
# Tests 5-8: Failure Count Trend (classify_trend with higher_is_better=False)
# ---------------------------------------------------------------------------

def test_classify_trend_decreasing_failures():
    """Test 5: Decreasing failure count → IMPROVING (lower = better)."""
    assert classify_trend([15.0, 12.0, 10.0, 7.0, 5.0],
                          higher_is_better=False, tolerance=0) == "IMPROVING"


def test_classify_trend_increasing_failures():
    """Test 6: Increasing failure count → WORSENING."""
    assert classify_trend([4.0, 6.0, 7.0, 10.0, 14.0],
                          higher_is_better=False, tolerance=0) == "WORSENING"


def test_classify_trend_stable_failures():
    """Test 7: Unchanged failure count → STABLE."""
    assert classify_trend([5.0, 5.0, 5.0, 5.0, 5.0],
                          higher_is_better=False, tolerance=0) == "STABLE"


def test_classify_trend_mixed_failures():
    """Test 8: Failure count up and down → MIXED."""
    assert classify_trend([4.0, 7.0, 3.0, 8.0, 5.0],
                          higher_is_better=False, tolerance=0) == "MIXED"


# ---------------------------------------------------------------------------
# Tests 9-12: Overall Trend (database-driven)
# ---------------------------------------------------------------------------

def test_overall_improving(db_session):
    """Test 9: Both pass rate and failures improving → overall IMPROVING."""
    _seed(db_session, 100, [_pass("t1"), _pass("t2"), _fail("t3"), _fail("t4")])  # 50%, 2f
    _seed(db_session, 101, [_pass("t1"), _pass("t2"), _pass("t3"), _fail("t4")])  # 75%, 1f
    _seed(db_session, 102, [_pass("t1"), _pass("t2"), _pass("t3"), _pass("t4")])  # 100%, 0f
    r = analyze_trends(limit=3, session=db_session)
    assert r["pass_rate_trend"] == "IMPROVING"
    assert r["failure_trend"] == "IMPROVING"
    assert r["overall_trend"] == "IMPROVING"


def test_overall_worsening(db_session):
    """Test 10: Both pass rate and failures worsening → overall WORSENING."""
    _seed(db_session, 100, [_pass("t1"), _pass("t2"), _pass("t3"), _pass("t4")])  # 100%, 0f
    _seed(db_session, 101, [_pass("t1"), _pass("t2"), _pass("t3"), _fail("t4")])  # 75%, 1f
    _seed(db_session, 102, [_pass("t1"), _pass("t2"), _fail("t3"), _fail("t4")])  # 50%, 2f
    r = analyze_trends(limit=3, session=db_session)
    assert r["pass_rate_trend"] == "WORSENING"
    assert r["failure_trend"] == "WORSENING"
    assert r["overall_trend"] == "WORSENING"


def test_overall_stable(db_session):
    """Test 11: Both pass rate and failures stable → overall STABLE."""
    rows = [_pass("t1"), _pass("t2"), _fail("t3")]  # 66.67%, 1f
    _seed(db_session, 100, rows)
    _seed(db_session, 101, rows)
    _seed(db_session, 102, rows)
    r = analyze_trends(limit=3, session=db_session)
    assert r["overall_trend"] == "STABLE"


def test_overall_mixed(db_session):
    """Test 12: Pass rate improves but failures also change inconsistently → MIXED."""
    # pass_rate: 50 → 75 → 100 (IMPROVING)
    # failures:  2  → 1  → 0  (IMPROVING) — both improving should give IMPROVING
    # Let's engineer a MIXED: pass rate up, failures also up
    # pass_rate: 50% → 75% (IMPROVING) but failures: 0 → 1 → 2 (WORSENING)
    _seed(db_session, 100, [_pass("t1"), _pass("t2"), _fail("t3"), _fail("t4")])       # 50%, 0f
    _seed(db_session, 101, [_pass("t1"), _pass("t2"), _pass("t3"), _fail("t4"), _fail("t5")])  # 60%, 2f
    _seed(db_session, 102, [_pass("t1"), _pass("t2"), _pass("t3"), _pass("t4"), _fail("t5"), _fail("t6"), _fail("t7")])  # 57%,3f
    r = analyze_trends(limit=3, session=db_session)
    # Different trends → MIXED
    assert r["overall_trend"] == "MIXED"


# ---------------------------------------------------------------------------
# Tests 13-15: Module Trends
# ---------------------------------------------------------------------------

def test_module_improving(db_session):
    """Test 13: Module failure count decreasing → IMPROVING."""
    _seed(db_session, 100, [_fail("t1", "Pay"), _fail("t2", "Pay"), _fail("t3", "Pay")])
    _seed(db_session, 101, [_fail("t1", "Pay"), _fail("t2", "Pay"), _pass("t3", "Pay")])
    _seed(db_session, 102, [_fail("t1", "Pay"), _pass("t2", "Pay"), _pass("t3", "Pay")])
    r = analyze_trends(limit=3, session=db_session)
    assert r["module_trends"]["Pay"]["trend"] == "IMPROVING"
    assert "Pay" in r["improving_modules"]


def test_module_worsening(db_session):
    """Test 14: Module failure count increasing → WORSENING."""
    _seed(db_session, 100, [_pass("t1", "Pay"), _pass("t2", "Pay"), _pass("t3", "Pay")])
    _seed(db_session, 101, [_fail("t1", "Pay"), _pass("t2", "Pay"), _pass("t3", "Pay")])
    _seed(db_session, 102, [_fail("t1", "Pay"), _fail("t2", "Pay"), _pass("t3", "Pay")])
    r = analyze_trends(limit=3, session=db_session)
    assert r["module_trends"]["Pay"]["trend"] == "WORSENING"
    assert "Pay" in r["worsening_modules"]


def test_module_stable(db_session):
    """Test 15: Module failure count unchanged → STABLE."""
    rows = [_fail("t1", "Pay"), _pass("t2", "Pay"), _pass("t3", "Pay")]
    _seed(db_session, 100, rows)
    _seed(db_session, 101, rows)
    _seed(db_session, 102, rows)
    r = analyze_trends(limit=3, session=db_session)
    assert r["module_trends"]["Pay"]["trend"] == "STABLE"
    assert "Pay" in r["stable_modules"]


# ---------------------------------------------------------------------------
# Test 16: Module absent from some builds → uses 0
# ---------------------------------------------------------------------------

def test_module_missing_from_some_builds_uses_zero(db_session):
    """Test 16: Module with 0 failures in some builds should not be dropped."""
    _seed(db_session, 100, [_pass("t1", "Auth"), _pass("t2", "Auth")])       # Search absent → 0
    _seed(db_session, 101, [_pass("t1", "Auth"), _fail("t2", "Search")])     # Search = 1
    _seed(db_session, 102, [_pass("t1", "Auth"), _fail("t3", "Search"), _fail("t4", "Search")])  # Search = 2
    r = analyze_trends(limit=3, session=db_session)
    assert "Search" in r["module_trends"]
    values = r["module_trends"]["Search"]["values"]
    assert values[0] == 0  # absent in first build


# ---------------------------------------------------------------------------
# Test 17: Module first appearing in later build → earlier values are 0
# ---------------------------------------------------------------------------

def test_module_first_appears_in_later_build(db_session):
    """Test 17: New module should have 0s for earlier builds."""
    _seed(db_session, 100, [_pass("t1", "Auth")])
    _seed(db_session, 101, [_pass("t1", "Auth")])
    _seed(db_session, 102, [_pass("t1", "Auth"), _fail("t2", "NewMod")])
    r = analyze_trends(limit=3, session=db_session)
    assert "NewMod" in r["module_trends"]
    values = r["module_trends"]["NewMod"]["values"]
    assert values == [0, 0, 1]


# ---------------------------------------------------------------------------
# Test 18: Latest N builds selected correctly
# ---------------------------------------------------------------------------

def test_latest_n_builds_selected(db_session):
    """Test 18: Only the N most recent builds are used."""
    for i in range(240, 248):  # 8 builds total
        _seed(db_session, i, [_pass(f"t{i}")])
    r = analyze_trends(limit=5, session=db_session)
    assert r["builds_analyzed"] == [243, 244, 245, 246, 247]


# ---------------------------------------------------------------------------
# Test 19: Build order is oldest to newest
# ---------------------------------------------------------------------------

def test_build_order_oldest_to_newest(db_session):
    """Test 19: Builds in result are ordered oldest → newest."""
    _seed(db_session, 303, [_pass("t1")])
    _seed(db_session, 301, [_pass("t1")])
    _seed(db_session, 302, [_pass("t1")])
    r = analyze_trends(limit=3, session=db_session)
    assert r["builds_analyzed"] == [301, 302, 303]


# ---------------------------------------------------------------------------
# Test 20: Non-sequential build numbers
# ---------------------------------------------------------------------------

def test_non_sequential_build_numbers(db_session):
    """Test 20: Non-sequential build numbers still produce correct order."""
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 250, [_pass("t1")])
    _seed(db_session, 999, [_pass("t1")])
    r = analyze_trends(limit=3, session=db_session)
    assert r["builds_analyzed"] == [100, 250, 999]


# ---------------------------------------------------------------------------
# Test 21: Fewer than 3 builds → NotEnoughBuildsError
# ---------------------------------------------------------------------------

def test_fewer_than_minimum_builds_raises_error(db_session):
    """Test 21: Fewer than 3 builds raises NotEnoughBuildsError."""
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 101, [_pass("t1")])
    with pytest.raises(NotEnoughBuildsError, match="Minimum required builds: 3"):
        analyze_trends(limit=5, session=db_session)


# ---------------------------------------------------------------------------
# Test 22: Exactly 3 builds succeeds
# ---------------------------------------------------------------------------

def test_exactly_minimum_builds_succeeds(db_session):
    """Test 22: Exactly 3 builds should not raise an error."""
    _seed(db_session, 100, [_pass("t1"), _fail("t2")])
    _seed(db_session, 101, [_pass("t1"), _fail("t2")])
    _seed(db_session, 102, [_pass("t1"), _fail("t2")])
    r = analyze_trends(limit=3, session=db_session)
    assert len(r["builds_analyzed"]) == 3


# ---------------------------------------------------------------------------
# Test 23: More builds than limit — only limit used
# ---------------------------------------------------------------------------

def test_more_builds_than_limit_uses_only_limit(db_session):
    """Test 23: When more builds exist than limit, only the latest N are used."""
    for i in range(200, 210):  # 10 builds
        _seed(db_session, i, [_pass(f"t{i}")])
    r = analyze_trends(limit=3, session=db_session)
    assert len(r["builds_analyzed"]) == 3
    assert r["builds_analyzed"] == [207, 208, 209]


# ---------------------------------------------------------------------------
# Test 24: Deterministic alphabetical module ordering
# ---------------------------------------------------------------------------

def test_alphabetical_module_ordering(db_session):
    """Test 24: Module trend keys are alphabetically sorted."""
    _seed(db_session, 100, [_fail("t1", "Zeta"), _fail("t2", "Alpha"), _fail("t3", "Mu")])
    _seed(db_session, 101, [_fail("t1", "Zeta"), _fail("t2", "Alpha"), _fail("t3", "Mu")])
    _seed(db_session, 102, [_fail("t1", "Zeta"), _fail("t2", "Alpha"), _fail("t3", "Mu")])
    r = analyze_trends(limit=3, session=db_session)
    keys = list(r["module_trends"].keys())
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# Test 25: Pass-rate tolerance handles near-zero changes as STABLE
# ---------------------------------------------------------------------------

def test_pass_rate_tolerance_treats_tiny_changes_as_stable(db_session):
    """Test 25: Pass-rate changes within ±0.5 are classified as STABLE."""
    # All changes are within 0.3, well within tolerance
    values = [92.0, 92.3, 92.1, 92.4, 92.2]
    assert classify_trend(values, higher_is_better=True,
                          tolerance=PASS_RATE_TOLERANCE) == "STABLE"


# ---------------------------------------------------------------------------
# Test 26: No failures in one build
# ---------------------------------------------------------------------------

def test_no_failures_in_one_build(db_session):
    """Test 26: A build with zero failures should not break analysis."""
    _seed(db_session, 100, [_fail("t1"), _fail("t2")])
    _seed(db_session, 101, [_pass("t1"), _pass("t2")])   # 0 failures
    _seed(db_session, 102, [_pass("t1"), _fail("t2")])   # 1 failure
    r = analyze_trends(limit=3, session=db_session)
    assert r["failure_history"][1] == 0  # second build has zero failures


# ---------------------------------------------------------------------------
# Test 27: No failures across all builds
# ---------------------------------------------------------------------------

def test_no_failures_in_multiple_builds(db_session):
    """Test 27: All builds with zero failures → STABLE failure trend."""
    for i in range(100, 103):
        _seed(db_session, i, [_pass("t1"), _pass("t2"), _pass("t3")])
    r = analyze_trends(limit=3, session=db_session)
    assert all(f == 0 for f in r["failure_history"])
    assert r["failure_trend"] == "STABLE"
