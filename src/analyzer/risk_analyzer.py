"""
Risk Analyzer — Rule-Based Module Risk Scoring.

Calculates a deterministic, explainable 0–100 risk score for every module in
the current build based on four weighted factors:

    A. Current Failure Count      (max 40 pts)
    B. Historical Failure Trend   (max 25 pts)
    C. Persistent Failures        (max 20 pts)
    D. Failure Share              (max 15 pts)

All thresholds and weights are loaded from ``config/config.yaml`` so they can
be tuned without changing code.

No machine learning or prediction is used — the score is fully rule-based.
"""

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from config import get_risk_config
from src.database.models import Build, TestResult
from src.database.repository import (
    get_build_by_number,
    get_previous_build,
    get_test_results_for_build,
    get_latest_builds,
    BuildNotFoundError,
)
from src.analyzer.trend_analyzer import (
    analyze_trends,
    NotEnoughBuildsError,
)
from src.analyzer.build_comparison import compare_builds, NoPreviousBuildError


# ---------------------------------------------------------------------------
# Configuration helpers (read once per call via get_risk_config())
# ---------------------------------------------------------------------------

def _risk_cfg() -> Dict[str, Any]:
    """Shorthand for loading the ``risk`` configuration section."""
    return get_risk_config()


# ---------------------------------------------------------------------------
# Factor scoring functions — each is independently testable
# ---------------------------------------------------------------------------

def score_current_failures(count: int) -> int:
    """
    Factor A — scores the raw failure count for a single module.

    Uses ``current_failure_brackets`` from config.  Anything above the last
    bracket gets the maximum weight.

    Args:
        count: Number of failures in the current build for this module.

    Returns:
        Integer score (0 to weight_max).
    """
    cfg = _risk_cfg()
    weight_max: int = cfg["weights"]["current_failures"]
    brackets: List[List[int]] = cfg["current_failure_brackets"]

    for max_count, score in brackets:
        if count <= max_count:
            return score
    return weight_max


def score_trend(trend: str) -> int:
    """
    Factor B — scores the historical failure trend for a module.

    Args:
        trend: One of IMPROVING, STABLE, MIXED, WORSENING, UNKNOWN.

    Returns:
        Integer score (0 to weight_max).
    """
    cfg = _risk_cfg()
    trend_map: Dict[str, int] = cfg["trend_scores"]
    return trend_map.get(trend, 0)


def score_persistent_failures(count: int) -> int:
    """
    Factor C — scores the number of persistent (repeated) failures.

    Args:
        count: Number of tests that failed in *both* the previous and current build
               for this module.

    Returns:
        Integer score (0 to weight_max).
    """
    cfg = _risk_cfg()
    weight_max: int = cfg["weights"]["persistent_failures"]
    brackets: List[List[int]] = cfg["persistent_failure_brackets"]

    for max_count, score in brackets:
        if count <= max_count:
            return score
    return weight_max


def score_failure_share(percent: float) -> int:
    """
    Factor D — scores the proportion of total build failures that belong to
    this module.

    Args:
        percent: Module failure share as a percentage (0.0–100.0).

    Returns:
        Integer score (0 to weight_max).
    """
    cfg = _risk_cfg()
    weight_max: int = cfg["weights"]["failure_share"]
    brackets: List[List[int]] = cfg["failure_share_brackets"]

    for max_pct, score in brackets:
        if percent <= max_pct:
            return score
    return weight_max


# ---------------------------------------------------------------------------
# Risk level classification
# ---------------------------------------------------------------------------

def classify_risk_level(score: int) -> str:
    """
    Maps a numeric risk score to LOW / MEDIUM / HIGH.

    Thresholds are read from ``config.yaml``.

    Args:
        score: Integer risk score (expected 0–100).

    Returns:
        One of: ``"LOW"``, ``"MEDIUM"``, ``"HIGH"``.
    """
    cfg = _risk_cfg()
    low_max: int = cfg["levels"]["low_max"]
    medium_max: int = cfg["levels"]["medium_max"]

    if score <= low_max:
        return "LOW"
    if score <= medium_max:
        return "MEDIUM"
    return "HIGH"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _module_failure_counts(
    test_results: List[TestResult],
) -> Dict[str, int]:
    """Returns ``{module_name: failure_count}`` for the given test results."""
    counts: Dict[str, int] = {}
    for tr in test_results:
        if tr.status == "FAIL":
            counts[tr.module] = counts.get(tr.module, 0) + 1
    return counts


def _all_modules_in_results(test_results: List[TestResult]) -> set:
    """Returns the set of all module names present in test results."""
    return {tr.module for tr in test_results}


def _persistent_failures_by_module(
    prev_results: List[TestResult],
    curr_results: List[TestResult],
) -> Dict[str, int]:
    """
    Counts per-module persistent failures (tests that FAILed in both builds).

    Reuses the same logic as ``build_comparison._test_set_analysis`` but
    attributes each persistent failure to its module.
    """
    prev_fail_map: Dict[str, str] = {}  # test_name → module
    for tr in prev_results:
        if tr.status == "FAIL":
            prev_fail_map[tr.test_name] = tr.module

    curr_fail_map: Dict[str, str] = {}
    for tr in curr_results:
        if tr.status == "FAIL":
            curr_fail_map[tr.test_name] = tr.module

    counts: Dict[str, int] = {}
    for test_name in prev_fail_map:
        if test_name in curr_fail_map:
            # Attribute to the *current* module (same test, current build's module)
            module = curr_fail_map[test_name]
            counts[module] = counts.get(module, 0) + 1

    return counts


def _get_module_trends(
    current_build_number: int,
    trend_limit: int,
    session: Optional[Session],
) -> Dict[str, str]:
    """
    Returns ``{module_name: trend_string}`` using the existing trend analyzer.

    If there are not enough builds for trend analysis, returns ``UNKNOWN`` for
    every requested module.
    """
    try:
        report = analyze_trends(limit=trend_limit, session=session)
        return {
            module: info["trend"]
            for module, info in report.get("module_trends", {}).items()
        }
    except NotEnoughBuildsError:
        return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_risk(
    current_build_number: int,
    trend_limit: int = 5,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Analyzes risk for every module visible in the current build (and any
    module with recent historical failures).

    Args:
        current_build_number: The build to score.
        trend_limit: How many recent builds the trend analyzer should consider.
        session: Optional SQLAlchemy session (useful for testing).

    Returns:
        A structured dict with keys: ``build``, ``modules``,
        ``ranked_modules``, ``high_risk_modules``, ``medium_risk_modules``,
        ``low_risk_modules``.

    Raises:
        BuildNotFoundError: If the requested build does not exist.
    """
    # ---- Fetch current build data ----------------------------------------
    curr_build = get_build_by_number(current_build_number, session=session)
    if curr_build is None:
        raise BuildNotFoundError(
            f"Build {current_build_number} not found in database."
        )

    curr_results: List[TestResult] = get_test_results_for_build(
        current_build_number, session=session
    )

    # ---- Current failure counts ------------------------------------------
    curr_failure_counts = _module_failure_counts(curr_results)
    total_failures: int = sum(curr_failure_counts.values())

    # ---- All modules in current build ------------------------------------
    current_modules: set = _all_modules_in_results(curr_results)

    # ---- Previous-build persistent failures ------------------------------
    prev_build: Optional[Build] = get_previous_build(
        current_build_number, session=session
    )
    if prev_build is not None:
        prev_results = get_test_results_for_build(
            prev_build.build_number, session=session
        )
        persistent_by_module = _persistent_failures_by_module(
            prev_results, curr_results
        )
    else:
        prev_results = []
        persistent_by_module = {}

    # ---- Module trends from trend analyzer -------------------------------
    module_trends = _get_module_trends(
        current_build_number, trend_limit, session
    )

    # ---- Determine which modules to score --------------------------------
    # Current modules + modules that have trend data (historical failures)
    modules_to_score: set = current_modules | set(module_trends.keys())

    # ---- Score each module -----------------------------------------------
    modules_report: Dict[str, Dict[str, Any]] = {}

    for module in modules_to_score:
        # Factor A — Current Failures
        fail_count = curr_failure_counts.get(module, 0)
        factor_a_score = score_current_failures(fail_count)

        # Factor B — Trend
        trend_value = module_trends.get(module, "UNKNOWN")
        factor_b_score = score_trend(trend_value)

        # Factor C — Persistent Failures
        persistent_count = persistent_by_module.get(module, 0)
        factor_c_score = score_persistent_failures(persistent_count)

        # Factor D — Failure Share
        if total_failures > 0:
            share_pct = round(fail_count / total_failures * 100, 2)
        else:
            share_pct = 0.0
        factor_d_score = score_failure_share(share_pct)

        # Final score — sum, clamped to [0, 100]
        raw_score = factor_a_score + factor_b_score + factor_c_score + factor_d_score
        final_score = max(0, min(100, raw_score))

        modules_report[module] = {
            "score": final_score,
            "level": classify_risk_level(final_score),
            "factors": {
                "current_failures": {
                    "value": fail_count,
                    "score": factor_a_score,
                },
                "trend": {
                    "value": trend_value,
                    "score": factor_b_score,
                },
                "persistent_failures": {
                    "value": persistent_count,
                    "score": factor_c_score,
                },
                "failure_share": {
                    "value": share_pct,
                    "score": factor_d_score,
                },
            },
        }

    # ---- Ranking ---------------------------------------------------------
    # Sort by score descending, then alphabetically for ties
    ranked: List[Tuple[str, int]] = sorted(
        ((m, d["score"]) for m, d in modules_report.items()),
        key=lambda x: (-x[1], x[0]),
    )

    ranked_modules = [m for m, _ in ranked]
    high_risk_modules = [m for m, d in modules_report.items() if d["level"] == "HIGH"]
    medium_risk_modules = [m for m, d in modules_report.items() if d["level"] == "MEDIUM"]
    low_risk_modules = [m for m, d in modules_report.items() if d["level"] == "LOW"]

    # Keep the categorised lists deterministic (alphabetical within category)
    high_risk_modules.sort()
    medium_risk_modules.sort()
    low_risk_modules.sort()

    return {
        "build": current_build_number,
        "modules": modules_report,
        "ranked_modules": ranked_modules,
        "high_risk_modules": high_risk_modules,
        "medium_risk_modules": medium_risk_modules,
        "low_risk_modules": low_risk_modules,
    }
