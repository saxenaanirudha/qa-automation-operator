"""
Flaky Test Detector Module.

Analyzes historical test execution data across recent builds to identify flaky tests.
A test is defined as flaky if its execution status switches between PASS and FAIL
repeatedly over time.

Rules:
    - Minimum history required (default 3 observations); otherwise INSUFFICIENT_HISTORY.
    - SKIP statuses are preserved in history but ignored when counting PASS/FAIL switches.
    - Persistent failures (e.g. FAIL -> FAIL -> FAIL) have 0 transitions and are classified STABLE.
    - Flakiness Rate = (transitions / possible_transitions) * 100.
    - Flaky Score = round(flakiness_rate).
    - Thresholds:
        * 0% – 24.99%: STABLE
        * 25% – 49.99%: POSSIBLY_FLAKY
        * 50% – 100%: FLAKY
"""

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from config import get_flaky_detection_config
from src.database.models import TestResult
from src.database.repository import (
    get_test_results_for_latest_builds,
)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def build_effective_status_sequence(history: List[Dict[str, Any]]) -> List[str]:
    """
    Filters a test's build history to return only PASS and FAIL statuses,
    ignoring SKIP.

    Args:
        history: List of history dicts, e.g. [{"build": 242, "status": "PASS"}, ...].

    Returns:
        List of status strings containing only "PASS" and "FAIL".
    """
    return [h["status"] for h in history if h["status"] in ("PASS", "FAIL")]


def count_status_transitions(statuses: List[str]) -> int:
    """
    Counts status transitions between consecutive PASS/FAIL entries.

    Args:
        statuses: Sequence of PASS/FAIL status strings.

    Returns:
        Number of status switches.
    """
    if len(statuses) < 2:
        return 0

    transitions = 0
    for i in range(1, len(statuses)):
        if statuses[i] != statuses[i - 1]:
            transitions += 1

    return transitions


def calculate_flakiness_rate(transitions: int, possible_transitions: int) -> float:
    """
    Calculates the flakiness percentage based on actual vs possible transitions.

    Args:
        transitions: Number of PASS/FAIL switches.
        possible_transitions: Maximum possible switches (effective_observations - 1).

    Returns:
        Rounded flakiness rate percentage (0.0 to 100.0).
    """
    if possible_transitions <= 0:
        return 0.0

    rate = (transitions / possible_transitions) * 100.0
    return round(rate, 2)


def classify_flakiness(
    rate: float,
    observation_count: int,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Classifies a test as STABLE, POSSIBLY_FLAKY, FLAKY, or INSUFFICIENT_HISTORY.

    Args:
        rate: Flakiness rate percentage (0.0 - 100.0).
        observation_count: Total observation count for the test.
        config: Optional flaky detection configuration.

    Returns:
        Classification string: "STABLE", "POSSIBLY_FLAKY", "FLAKY", or "INSUFFICIENT_HISTORY".
    """
    cfg = config or get_flaky_detection_config()
    min_obs = int(cfg.get("minimum_observations", 3))
    thresholds = cfg.get("thresholds", {})
    pos_flaky = float(thresholds.get("possibly_flaky", 25.0))
    flaky = float(thresholds.get("flaky", 50.0))

    if observation_count < min_obs:
        return "INSUFFICIENT_HISTORY"

    if rate >= flaky:
        return "FLAKY"
    if rate >= pos_flaky:
        return "POSSIBLY_FLAKY"
    return "STABLE"


# ---------------------------------------------------------------------------
# Core Flaky Test Detector
# ---------------------------------------------------------------------------

def detect_flaky_tests(
    limit: int = 10,
    session: Optional[Session] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Analyzes historical test results across recent builds and identifies flaky tests.

    Args:
        limit: Number of latest builds to analyze (default 10).
        session: Optional SQLAlchemy session.
        config: Optional flaky detection configuration.

    Returns:
        Structured dict containing build history, test classifications,
        module summaries, and ranked flaky tests.

    Raises:
        ValueError: If duplicate test results exist within the same build.
    """
    flaky_cfg = config or get_flaky_detection_config()
    effective_limit = limit or flaky_cfg.get("history_limit", 10)

    # 1. Retrieve test results for the latest builds (ordered oldest -> newest)
    build_results_map = get_test_results_for_latest_builds(
        limit=effective_limit, session=session
    )

    builds_analyzed = list(build_results_map.keys())

    # 2. Group results by test_name, validating uniqueness per build
    test_histories: Dict[str, List[Dict[str, Any]]] = {}
    test_modules: Dict[str, str] = {}  # test_name -> most recent module name

    for build_num, results in build_results_map.items():
        seen_tests: set = set()
        for tr in results:
            if tr.test_name in seen_tests:
                raise ValueError(
                    f"Duplicate result found for {tr.test_name} in build {build_num}."
                )
            seen_tests.add(tr.test_name)

            if tr.test_name not in test_histories:
                test_histories[tr.test_name] = []
            test_histories[tr.test_name].append(
                {"build": build_num, "status": tr.status}
            )
            # Update module to the most recent build's module
            test_modules[tr.test_name] = tr.module

    # 3. Analyze each test
    tests_summary: Dict[str, Dict[str, Any]] = {}
    flaky_tests: List[str] = []
    possibly_flaky_tests: List[str] = []
    stable_tests: List[str] = []
    insufficient_history_tests: List[str] = []

    for test_name, history in test_histories.items():
        obs_count = len(history)
        eff_statuses = build_effective_status_sequence(history)
        eff_obs_count = len(eff_statuses)

        transitions = count_status_transitions(eff_statuses)
        possible_transitions = max(0, eff_obs_count - 1)

        rate = calculate_flakiness_rate(transitions, possible_transitions)
        score = int(round(rate))

        # Minimum history applies if total observations < min_obs or eff_obs_count < 2
        classification = classify_flakiness(rate, obs_count, config=flaky_cfg)
        if eff_obs_count < 2 and classification != "INSUFFICIENT_HISTORY":
            classification = "INSUFFICIENT_HISTORY"

        test_data = {
            "module": test_modules[test_name],
            "observations": obs_count,
            "effective_observations": eff_obs_count,
            "transitions": transitions,
            "flakiness_rate": rate,
            "flaky_score": score,
            "classification": classification,
            "history": history,
        }
        tests_summary[test_name] = test_data

        if classification == "FLAKY":
            flaky_tests.append(test_name)
        elif classification == "POSSIBLY_FLAKY":
            possibly_flaky_tests.append(test_name)
        elif classification == "STABLE":
            stable_tests.append(test_name)
        else:
            insufficient_history_tests.append(test_name)

    # 4. Rank FLAKY tests: highest flaky_score -> highest transitions -> alphabetical
    flaky_objects = [(t, tests_summary[t]) for t in flaky_tests]
    flaky_objects.sort(
        key=lambda x: (-x[1]["flaky_score"], -x[1]["transitions"], x[0])
    )
    ranked_flaky_tests = [t for t, _ in flaky_objects]

    # Sort categories alphabetically
    flaky_tests.sort()
    possibly_flaky_tests.sort()
    stable_tests.sort()
    insufficient_history_tests.sort()

    # 5. Summarize flaky tests by module
    module_flaky_counts: Dict[str, int] = {}
    for test_name in ranked_flaky_tests:
        mod = test_modules[test_name]
        module_flaky_counts[mod] = module_flaky_counts.get(mod, 0) + 1

    # Sort module counts by highest count, then alphabetical module name
    sorted_modules = sorted(
        module_flaky_counts.items(), key=lambda x: (-x[1], x[0])
    )
    flaky_by_module = dict(sorted_modules)

    top_flaky_module = sorted_modules[0][0] if sorted_modules else None

    return {
        "builds_analyzed": builds_analyzed,
        "flaky_tests": flaky_tests,
        "possibly_flaky_tests": possibly_flaky_tests,
        "stable_tests": stable_tests,
        "insufficient_history_tests": insufficient_history_tests,
        "tests": tests_summary,
        "flaky_by_module": flaky_by_module,
        "top_flaky_module": top_flaky_module,
        "ranked_flaky_tests": ranked_flaky_tests,
    }
