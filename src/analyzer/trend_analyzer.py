"""
Multi-Build Trend Analyzer.

Analyzes the most recent N historical builds to determine whether QA quality
is IMPROVING, WORSENING, STABLE, or MIXED.

All database access is delegated to repository functions.
No machine learning or regression is used — logic is deterministic and
based on simple sign-counting of consecutive differences.
"""

from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from src.database.models import Build, TestResult
from src.database.repository import get_latest_builds, get_test_results_for_build


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MINIMUM_BUILDS: int = 3
DEFAULT_LIMIT: int = 5

# Pass-rate changes within ±PASS_RATE_TOLERANCE are treated as "no change".
PASS_RATE_TOLERANCE: float = 0.5

# Failure counts are integers; a difference of 0 is strictly stable.
FAILURE_COUNT_TOLERANCE: int = 0


class NotEnoughBuildsError(Exception):
    """Raised when there are fewer than MINIMUM_BUILDS stored builds."""
    pass


# ---------------------------------------------------------------------------
# Core trend classification helper
# ---------------------------------------------------------------------------

def classify_trend(
    values: List[float],
    higher_is_better: bool = True,
    tolerance: float = 0.5,
) -> str:
    """
    Classifies a sequence of metric values as IMPROVING, WORSENING, STABLE, or MIXED.

    The sequence must be ordered oldest → newest.

    Rules (applied to consecutive differences):
        * A difference within ±tolerance is counted as STABLE.
        * A positive difference is IMPROVING when higher_is_better=True,
          else WORSENING.
        * A negative difference is WORSENING when higher_is_better=True,
          else IMPROVING.

    Classification thresholds:
        * STABLE   — all changes within tolerance
        * IMPROVING — all meaningful changes are in the improving direction
        * WORSENING — all meaningful changes are in the worsening direction
        * MIXED    — anything else

    Args:
        values: Metric values ordered oldest → newest.  Must have ≥ 2 entries.
        higher_is_better: True for pass rate; False for failure counts.
        tolerance: Changes within this magnitude are treated as stable/flat.

    Returns:
        One of: "IMPROVING", "WORSENING", "STABLE", "MIXED"
    """
    if len(values) < 2:
        return "STABLE"

    improving_count = 0
    worsening_count = 0
    stable_count    = 0

    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]

        if abs(delta) <= tolerance:
            stable_count += 1
        elif delta > 0:
            if higher_is_better:
                improving_count += 1
            else:
                worsening_count += 1
        else:  # delta < 0
            if higher_is_better:
                worsening_count += 1
            else:
                improving_count += 1

    total = improving_count + worsening_count + stable_count

    # Purely stable (all changes within tolerance)
    if stable_count == total:
        return "STABLE"

    meaningful = improving_count + worsening_count

    # All meaningful movements in the same direction
    if meaningful > 0:
        if improving_count == total:
            return "IMPROVING"
        if worsening_count == total:
            return "WORSENING"
        # All meaningful moves one-way, but some stable steps mixed in
        if worsening_count == 0 and improving_count > 0:
            return "IMPROVING"
        if improving_count == 0 and worsening_count > 0:
            return "WORSENING"

    return "MIXED"


# ---------------------------------------------------------------------------
# Module failure helpers
# ---------------------------------------------------------------------------

def _collect_module_failure_counts(
    builds: List[Build],
    build_results_map: Dict[int, List[TestResult]],
) -> Dict[str, List[int]]:
    """
    Builds a {module_name: [failure_count_per_build]} mapping.

    Builds are in chronological order (oldest → newest).
    Modules absent from a build are recorded as 0.

    Args:
        builds: Chronologically ordered list of Build instances.
        build_results_map: Dict mapping build_number → list of TestResult rows.

    Returns:
        Dict mapping module name → list of failure counts, one per build.
    """
    # First pass: collect all known module names
    all_modules: set = set()
    for build in builds:
        for tr in build_results_map.get(build.build_number, []):
            all_modules.add(tr.module)

    # Second pass: fill in counts per build, using 0 for absent modules
    module_counts: Dict[str, List[int]] = {m: [] for m in all_modules}

    for build in builds:
        results = build_results_map.get(build.build_number, [])
        # Count failures per module for this build
        counts_this_build: Dict[str, int] = {}
        for tr in results:
            if tr.status == "FAIL":
                counts_this_build[tr.module] = counts_this_build.get(tr.module, 0) + 1

        for module in all_modules:
            module_counts[module].append(counts_this_build.get(module, 0))

    return module_counts


def _determine_overall_trend(pass_rate_trend: str, failure_trend: str) -> str:
    """
    Combines pass-rate and failure-count trends into a single overall trend.

    Rules:
        IMPROVING — both IMPROVING
        WORSENING — both WORSENING
        STABLE    — both STABLE
        MIXED     — anything else

    Args:
        pass_rate_trend: Trend string for pass rate.
        failure_trend:   Trend string for failure count.

    Returns:
        One of: "IMPROVING", "WORSENING", "STABLE", "MIXED"
    """
    if pass_rate_trend == failure_trend == "IMPROVING":
        return "IMPROVING"
    if pass_rate_trend == failure_trend == "WORSENING":
        return "WORSENING"
    if pass_rate_trend == failure_trend == "STABLE":
        return "STABLE"
    return "MIXED"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_trends(
    limit: int = DEFAULT_LIMIT,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Analyzes the latest ``limit`` builds and returns a structured trend report.

    Builds are sorted oldest → newest before analysis.

    Args:
        limit: Number of most-recent builds to include. Defaults to 5.
        session: Optional SQLAlchemy session (useful for testing).

    Returns:
        Dict with keys: builds_analyzed, pass_rate_history, failure_history,
        pass_rate_trend, failure_trend, overall_trend, module_trends,
        improving_modules, worsening_modules, stable_modules.

    Raises:
        NotEnoughBuildsError: If fewer than MINIMUM_BUILDS builds are stored.
    """
    # Fetch latest N builds (newest-first from DB)
    recent_builds: List[Build] = get_latest_builds(limit, session=session)

    if len(recent_builds) < MINIMUM_BUILDS:
        raise NotEnoughBuildsError(
            f"Not enough build history for trend analysis. "
            f"Minimum required builds: {MINIMUM_BUILDS}. "
            f"Currently stored: {len(recent_builds)}."
        )

    # Reverse to chronological order: oldest → newest
    builds: List[Build] = list(reversed(recent_builds))

    # Fetch test results for every build
    build_results_map: Dict[int, List[TestResult]] = {}
    for build in builds:
        build_results_map[build.build_number] = get_test_results_for_build(
            build.build_number, session=session
        )

    # --- Metric histories ------------------------------------------------
    builds_analyzed: List[int]   = [b.build_number for b in builds]
    pass_rate_history: List[float] = [round(b.pass_rate, 2) for b in builds]
    failure_history: List[int]   = [b.failed for b in builds]

    # --- Trends ----------------------------------------------------------
    pass_rate_trend: str = classify_trend(
        pass_rate_history,
        higher_is_better=True,
        tolerance=PASS_RATE_TOLERANCE,
    )
    failure_trend: str = classify_trend(
        [float(f) for f in failure_history],
        higher_is_better=False,
        tolerance=float(FAILURE_COUNT_TOLERANCE),
    )
    overall_trend: str = _determine_overall_trend(pass_rate_trend, failure_trend)

    # --- Module-level trends ---------------------------------------------
    module_counts = _collect_module_failure_counts(builds, build_results_map)

    module_trends: Dict[str, Any] = {}
    improving_modules: List[str] = []
    worsening_modules: List[str] = []
    stable_modules: List[str]    = []

    for module in sorted(module_counts.keys()):
        values = module_counts[module]
        trend  = classify_trend(
            [float(v) for v in values],
            higher_is_better=False,
            tolerance=float(FAILURE_COUNT_TOLERANCE),
        )
        module_trends[module] = {"values": values, "trend": trend}
        if trend == "IMPROVING":
            improving_modules.append(module)
        elif trend == "WORSENING":
            worsening_modules.append(module)
        else:
            stable_modules.append(module)

    # Alphabetical order within each category (already guaranteed by sorted() above,
    # but explicit for clarity)
    improving_modules.sort()
    worsening_modules.sort()
    stable_modules.sort()

    return {
        "builds_analyzed":  builds_analyzed,
        "pass_rate_history": pass_rate_history,
        "failure_history":  failure_history,
        "pass_rate_trend":  pass_rate_trend,
        "failure_trend":    failure_trend,
        "overall_trend":    overall_trend,
        "module_trends":    module_trends,
        "improving_modules": improving_modules,
        "worsening_modules": worsening_modules,
        "stable_modules":   stable_modules,
    }
