"""
Build Comparison Analyzer.

Compares two stored builds and reports whether QA quality improved, worsened,
or stayed the same. All database access is delegated to repository functions.
"""

from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from src.database.models import Build, TestResult
from src.database.repository import (
    get_build_by_number,
    get_test_results_for_build,
    get_previous_build,
    BuildNotFoundError,
)


class NoPreviousBuildError(Exception):
    """Raised when no earlier build exists to compare against."""
    pass


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _validate_unique_test_names(test_results: List[TestResult], build_number: int) -> None:
    """
    Raises ValueError if any test_name appears more than once within the build.

    Args:
        test_results: List of TestResult rows for the build.
        build_number: Build number (used in the error message).
    """
    seen: set = set()
    for tr in test_results:
        if tr.test_name in seen:
            raise ValueError(
                f"Duplicate test_name found in build {build_number}: {tr.test_name}"
            )
        seen.add(tr.test_name)


def _metric_diff(previous: float, current: float, *, round_to: int = 2) -> Dict[str, float]:
    """Returns a dict with previous, current, and rounded difference."""
    return {
        "previous": previous,
        "current": current,
        "difference": round(current - previous, round_to),
    }


def _build_summary_diff(prev_build: Build, curr_build: Build) -> Dict[str, Any]:
    """
    Computes build-level metric differences.

    Returns:
        Dict with keys: total_tests, passed, failed, skipped, pass_rate, failure_rate.
    """
    return {
        "total_tests": _metric_diff(prev_build.total_tests, curr_build.total_tests, round_to=0),
        "passed":      _metric_diff(prev_build.passed,      curr_build.passed,      round_to=0),
        "failed":      _metric_diff(prev_build.failed,      curr_build.failed,      round_to=0),
        "skipped":     _metric_diff(prev_build.skipped,     curr_build.skipped,     round_to=0),
        "pass_rate":   _metric_diff(prev_build.pass_rate,   curr_build.pass_rate,   round_to=2),
        "failure_rate":_metric_diff(prev_build.failure_rate,curr_build.failure_rate,round_to=2),
    }


def _determine_overall_status(summary: Dict[str, Any]) -> str:
    """
    Determines overall build status from the summary diff.

    Rules:
        BETTER  — pass rate improved AND failure count decreased
        WORSE   — pass rate decreased AND failure count increased
        SAME    — pass rate and failure count both unchanged
        MIXED   — any other combination

    Returns:
        One of: "BETTER", "WORSE", "SAME", "MIXED"
    """
    pass_rate_diff = summary["pass_rate"]["difference"]
    failed_diff    = summary["failed"]["difference"]

    pass_rate_up   = pass_rate_diff > 0
    pass_rate_down = pass_rate_diff < 0
    pass_rate_flat = pass_rate_diff == 0

    failures_down  = failed_diff < 0
    failures_up    = failed_diff > 0
    failures_flat  = failed_diff == 0

    if pass_rate_up and failures_down:
        return "BETTER"
    if pass_rate_down and failures_up:
        return "WORSE"
    if pass_rate_flat and failures_flat:
        return "SAME"
    return "MIXED"


def _module_comparison(
    prev_results: List[TestResult],
    curr_results: List[TestResult],
) -> Dict[str, Any]:
    """
    Compares failure counts per module between two builds.

    Modules present in only one build use 0 for the missing side.
    Result is sorted alphabetically by module name.

    Returns:
        Alphabetically-sorted dict mapping module name → comparison sub-dict.
    """
    def failure_counts(results: List[TestResult]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for tr in results:
            if tr.status == "FAIL":
                counts[tr.module] = counts.get(tr.module, 0) + 1
        return counts

    prev_counts = failure_counts(prev_results)
    curr_counts = failure_counts(curr_results)

    all_modules = sorted(set(prev_counts) | set(curr_counts))

    result: Dict[str, Any] = {}
    for module in all_modules:
        prev_val = prev_counts.get(module, 0)
        curr_val = curr_counts.get(module, 0)
        diff = curr_val - prev_val

        if diff < 0:
            trend = "BETTER"
        elif diff > 0:
            trend = "WORSE"
        else:
            trend = "SAME"

        result[module] = {
            "previous":   prev_val,
            "current":    curr_val,
            "difference": diff,
            "trend":      trend,
        }

    return result


def _test_set_analysis(
    prev_results: List[TestResult],
    curr_results: List[TestResult],
) -> Dict[str, List[str]]:
    """
    Identifies newly failing, recovered, persistent failures, added, and removed tests.

    A test is identified solely by test_name.

    Returns:
        Dict with keys: newly_failing_tests, recovered_tests, persistent_failures,
                        tests_added, tests_removed — all sorted alphabetically.
    """
    # Build lookup maps  {test_name: status}
    prev_map: Dict[str, str] = {tr.test_name: tr.status for tr in prev_results}
    curr_map: Dict[str, str] = {tr.test_name: tr.status for tr in curr_results}

    prev_names = set(prev_map)
    curr_names = set(curr_map)

    # Tests added / removed (exist in one build but not the other)
    tests_added   = sorted(curr_names - prev_names)
    tests_removed = sorted(prev_names - curr_names)

    # Tests present in BOTH builds
    common_names = prev_names & curr_names

    newly_failing:    List[str] = []
    recovered:        List[str] = []
    persistent_fail:  List[str] = []

    for name in common_names:
        prev_status = prev_map[name]
        curr_status = curr_map[name]

        was_failing = prev_status == "FAIL"
        is_failing  = curr_status == "FAIL"
        is_passing_or_skip = curr_status in ("PASS", "SKIP")

        if not was_failing and is_failing:
            newly_failing.append(name)
        elif was_failing and is_passing_or_skip:
            recovered.append(name)
        elif was_failing and is_failing:
            persistent_fail.append(name)

    return {
        "newly_failing_tests": sorted(newly_failing),
        "recovered_tests":     sorted(recovered),
        "persistent_failures": sorted(persistent_fail),
        "tests_added":         tests_added,
        "tests_removed":       tests_removed,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare_builds(
    previous_build_number: int,
    current_build_number: int,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Compares two stored builds and returns a structured comparison report.

    Args:
        previous_build_number: Build number of the earlier build.
        current_build_number:  Build number of the later build.
        session: Optional SQLAlchemy session (useful for testing with in-memory DBs).

    Returns:
        Comparison dict with keys: previous_build, current_build, overall_status,
        summary, module_comparison, newly_failing_tests, recovered_tests,
        persistent_failures, tests_added, tests_removed.

    Raises:
        BuildNotFoundError: If either build does not exist in the database.
        ValueError: If duplicate test names are found within either build.
    """
    # Fetch builds — BuildNotFoundError bubbles up cleanly if missing
    prev_build = get_build_by_number(previous_build_number, session=session)
    if prev_build is None:
        raise BuildNotFoundError(
            f"Build {previous_build_number} not found in database."
        )

    curr_build = get_build_by_number(current_build_number, session=session)
    if curr_build is None:
        raise BuildNotFoundError(
            f"Build {current_build_number} not found in database."
        )

    # Fetch test results
    prev_results = get_test_results_for_build(previous_build_number, session=session)
    curr_results = get_test_results_for_build(current_build_number, session=session)

    # Validate uniqueness within each build
    _validate_unique_test_names(prev_results, previous_build_number)
    _validate_unique_test_names(curr_results, current_build_number)

    # Compute comparison components
    summary    = _build_summary_diff(prev_build, curr_build)
    status     = _determine_overall_status(summary)
    modules    = _module_comparison(prev_results, curr_results)
    test_sets  = _test_set_analysis(prev_results, curr_results)

    # Evaluate population identity comparability using canonical (module, test_name)
    prev_identities = {(tr.module, tr.test_name) for tr in prev_results}
    curr_identities = {(tr.module, tr.test_name) for tr in curr_results}
    common_identities = prev_identities & curr_identities

    if not prev_identities or not curr_identities:
        population_status = "UNKNOWN"
        is_comparable = False
        comparability_note = "Cannot establish population equivalence because test results are unavailable for one or both builds."
    elif prev_identities == curr_identities:
        population_status = "IDENTICAL"
        is_comparable = True
        comparability_note = None
    else:
        population_status = "DIFFERENT"
        is_comparable = False
        added_cnt = len(test_sets["tests_added"])
        removed_cnt = len(test_sets["tests_removed"])
        comparability_note = (
            f"Test populations differ (Build {previous_build_number}: {len(prev_identities)} tests vs "
            f"Build {current_build_number}: {len(curr_identities)} tests; {added_cnt} added, {removed_cnt} removed; "
            f"{len(common_identities)} common). Aggregate pass-rate difference reflects test suite population changes "
            f"rather than a like-for-like regression comparison."
        )

    return {
        "previous_build": previous_build_number,
        "current_build":  current_build_number,
        "overall_status": status,
        "summary":        summary,
        "module_comparison": modules,
        "population_status": population_status,
        "is_comparable": is_comparable,
        "comparability_note": comparability_note,
        **test_sets,
    }


def compare_with_previous_build(
    current_build_number: int,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Automatically finds the nearest preceding build and compares it with the current one.

    Does NOT subtract 1 from the build number — uses the actual stored build history.

    Args:
        current_build_number: The build number to compare against its predecessor.
        session: Optional SQLAlchemy session.

    Returns:
        Same structure as compare_builds().

    Raises:
        BuildNotFoundError: If the current build does not exist.
        NoPreviousBuildError: If no earlier build exists in the database.
    """
    # Confirm the current build exists
    curr_build = get_build_by_number(current_build_number, session=session)
    if curr_build is None:
        raise BuildNotFoundError(
            f"Build {current_build_number} not found in database."
        )

    prev_build = get_previous_build(current_build_number, session=session)
    if prev_build is None:
        raise NoPreviousBuildError(
            f"No previous build available for build {current_build_number}."
        )

    return compare_builds(prev_build.build_number, current_build_number, session=session)
