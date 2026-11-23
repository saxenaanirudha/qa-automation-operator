"""
Quality Gate Module — Decision Engine for QA Build Evaluation.

Evaluates the current build against configurable quality rules to determine
whether the build passes quality criteria, requires review (WARNING), or must be
blocked (FAIL).

Rules evaluated:
    - Pass Rate
    - Failure Count
    - High-Risk Module Count
    - Overall Trend
    - Build Comparison Status
    - Newly Failing Test Count

Outputs:
    - Overall Status: PASS | WARNING | FAIL
    - Release Recommendation: PROCEED | REVIEW | BLOCK
    - Detailed checks breakdown
    - Triggered rules with severity and explanatory messages
"""

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from config import get_quality_gate_config
from src.database.repository import (
    get_build_by_number,
    BuildNotFoundError,
)
from src.analyzer.build_comparison import (
    compare_with_previous_build,
    NoPreviousBuildError,
)
from src.analyzer.trend_analyzer import (
    analyze_trends,
    NotEnoughBuildsError,
)
from src.analyzer.risk_analyzer import analyze_risk


# ---------------------------------------------------------------------------
# Release Recommendation Mapping
# ---------------------------------------------------------------------------

RELEASE_RECOMMENDATIONS = {
    "PASS": "PROCEED",
    "WARNING": "REVIEW",
    "FAIL": "BLOCK",
}


# ---------------------------------------------------------------------------
# Individual Rule Evaluators
# ---------------------------------------------------------------------------

def evaluate_pass_rate(
    pass_rate: float, config: Optional[Dict[str, Any]] = None
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Evaluates pass rate against warning and fail thresholds.

    Rules:
        - pass_rate < fail_below → FAIL
        - fail_below <= pass_rate < warning_below → WARNING
        - pass_rate >= warning_below → PASS

    Returns:
        Tuple of (status, triggered_rule_dict_or_None)
    """
    cfg = (config or get_quality_gate_config())["pass_rate"]
    fail_below = float(cfg["fail_below"])
    warning_below = float(cfg["warning_below"])

    if pass_rate < fail_below:
        status = "FAIL"
        msg = f"Pass rate {pass_rate}% is below fail threshold {fail_below}%."
    elif pass_rate < warning_below:
        status = "WARNING"
        msg = f"Pass rate {pass_rate}% is below warning threshold {warning_below}%."
    else:
        return "PASS", None

    return status, {
        "rule": "PASS_RATE",
        "severity": status,
        "message": msg,
    }


def evaluate_failure_count(
    count: int, config: Optional[Dict[str, Any]] = None
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Evaluates failed test count against warning and fail thresholds.

    Rules:
        - count >= fail_at → FAIL
        - warning_at <= count < fail_at → WARNING
        - count < warning_at → PASS

    Returns:
        Tuple of (status, triggered_rule_dict_or_None)
    """
    cfg = (config or get_quality_gate_config())["failure_count"]
    fail_at = int(cfg["fail_at"])
    warning_at = int(cfg["warning_at"])

    if count >= fail_at:
        status = "FAIL"
        msg = f"Failed test count {count} reached fail threshold {fail_at}."
    elif count >= warning_at:
        status = "WARNING"
        msg = f"Failed test count {count} reached warning threshold {warning_at}."
    else:
        return "PASS", None

    return status, {
        "rule": "FAILURE_COUNT",
        "severity": status,
        "message": msg,
    }


def evaluate_high_risk_modules(
    count: int, config: Optional[Dict[str, Any]] = None
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Evaluates high-risk module count against warning and fail thresholds.

    Rules:
        - count >= fail_at → FAIL
        - warning_at <= count < fail_at → WARNING
        - count < warning_at → PASS

    Returns:
        Tuple of (status, triggered_rule_dict_or_None)
    """
    cfg = (config or get_quality_gate_config())["high_risk_modules"]
    fail_at = int(cfg["fail_at"])
    warning_at = int(cfg["warning_at"])

    if count >= fail_at:
        status = "FAIL"
        module_str = "module" if count == 1 else "modules"
        msg = f"{count} high-risk {module_str} reached fail threshold {fail_at}."
    elif count >= warning_at:
        status = "WARNING"
        module_str = "module" if count == 1 else "modules"
        msg = f"{count} high-risk {module_str} reached warning threshold {warning_at}."
    else:
        return "PASS", None

    return status, {
        "rule": "HIGH_RISK_MODULES",
        "severity": status,
        "message": msg,
    }


def evaluate_new_failures(
    count: int, config: Optional[Dict[str, Any]] = None
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Evaluates newly failing test count against warning and fail thresholds.

    Rules:
        - count >= fail_at → FAIL
        - warning_at <= count < fail_at → WARNING
        - count < warning_at → PASS

    Returns:
        Tuple of (status, triggered_rule_dict_or_None)
    """
    cfg = (config or get_quality_gate_config())["newly_failing_tests"]
    fail_at = int(cfg["fail_at"])
    warning_at = int(cfg["warning_at"])

    if count >= fail_at:
        status = "FAIL"
        msg = f"Newly failing test count {count} reached fail threshold {fail_at}."
    elif count >= warning_at:
        status = "WARNING"
        msg = f"Newly failing test count {count} reached warning threshold {warning_at}."
    else:
        return "PASS", None

    return status, {
        "rule": "NEWLY_FAILING_TESTS",
        "severity": status,
        "message": msg,
    }


def evaluate_trend(
    overall_trend: str, config: Optional[Dict[str, Any]] = None
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Evaluates overall QA trend.

    Rules:
        - overall_trend in warning_on list → WARNING
        - else → PASS

    Returns:
        Tuple of (status, triggered_rule_dict_or_None)
    """
    cfg = (config or get_quality_gate_config())["overall_trend"]
    warning_on = cfg.get("warning_on", [])

    if overall_trend in warning_on:
        status = "WARNING"
        msg = f"Overall QA trend is {overall_trend}."
        return status, {
            "rule": "OVERALL_TREND",
            "severity": status,
            "message": msg,
        }

    return "PASS", None


def evaluate_build_comparison(
    status_str: str, config: Optional[Dict[str, Any]] = None
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Evaluates build comparison status.

    Rules:
        - status_str in warning_on list → WARNING
        - else → PASS

    Returns:
        Tuple of (status, triggered_rule_dict_or_None)
    """
    cfg = (config or get_quality_gate_config())["build_comparison"]
    warning_on = cfg.get("warning_on", [])

    if status_str in warning_on:
        status = "WARNING"
        msg = f"Build comparison status is {status_str}."
        return status, {
            "rule": "BUILD_COMPARISON",
            "severity": status,
            "message": msg,
        }

    return "PASS", None


# ---------------------------------------------------------------------------
# Core Quality Gate Evaluator
# ---------------------------------------------------------------------------

def evaluate_quality_gate(
    current_build_number: int,
    session: Optional[Session] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates the Quality Gate for the specified build number.

    Args:
        current_build_number: The build number to evaluate.
        session: Optional SQLAlchemy session.
        config: Optional Quality Gate configuration dictionary.

    Returns:
        Dict containing build, status, release_recommendation, checks, and triggered_rules.

    Raises:
        BuildNotFoundError: If the current build does not exist.
        ValueError: If configuration thresholds are invalid.
    """
    # 1. Load build summary
    curr_build = get_build_by_number(current_build_number, session=session)
    if curr_build is None:
        raise BuildNotFoundError(
            f"Build {current_build_number} not found in database."
        )

    qg_config = config or get_quality_gate_config()

    # 2. Gather metric inputs from analyzers
    pass_rate = curr_build.pass_rate
    failure_count = curr_build.failed

    # High risk modules from Risk Analyzer
    risk_report = analyze_risk(current_build_number, session=session)
    high_risk_count = len(risk_report.get("high_risk_modules", []))

    # Overall trend from Trend Analyzer (handles insufficient builds gracefully)
    try:
        trend_report = analyze_trends(session=session)
        overall_trend_val = trend_report.get("overall_trend", "UNKNOWN")
    except NotEnoughBuildsError:
        overall_trend_val = "UNKNOWN"

    # Build comparison & newly failing tests (handles missing previous build gracefully)
    try:
        comp_report = compare_with_previous_build(
            current_build_number, session=session
        )
        build_comp_val = comp_report.get("overall_status", "UNKNOWN")
        newly_failing_count = len(comp_report.get("newly_failing_tests", []))
    except (NoPreviousBuildError, BuildNotFoundError):
        build_comp_val = "UNKNOWN"
        newly_failing_count = 0

    # 3. Evaluate each rule
    pr_status, pr_trig = evaluate_pass_rate(pass_rate, config=qg_config)
    fc_status, fc_trig = evaluate_failure_count(failure_count, config=qg_config)
    hr_status, hr_trig = evaluate_high_risk_modules(high_risk_count, config=qg_config)
    nft_status, nft_trig = evaluate_new_failures(newly_failing_count, config=qg_config)
    trend_status, trend_trig = evaluate_trend(overall_trend_val, config=qg_config)
    comp_status, comp_trig = evaluate_build_comparison(build_comp_val, config=qg_config)

    # 4. Assemble checks
    checks = {
        "pass_rate": {
            "value": pass_rate,
            "status": pr_status,
        },
        "failure_count": {
            "value": failure_count,
            "status": fc_status,
        },
        "high_risk_modules": {
            "value": high_risk_count,
            "status": hr_status,
        },
        "newly_failing_tests": {
            "value": newly_failing_count,
            "status": nft_status,
        },
        "overall_trend": {
            "value": overall_trend_val,
            "status": trend_status,
        },
        "build_comparison": {
            "value": build_comp_val,
            "status": comp_status,
        },
    }

    # 5. Collect triggered rules
    triggered_rules: List[Dict[str, Any]] = []
    for trig in [pr_trig, fc_trig, hr_trig, nft_trig, trend_trig, comp_trig]:
        if trig is not None:
            triggered_rules.append(trig)

    # 6. Determine overall Quality Gate status (FAIL > WARNING > PASS)
    all_statuses = [
        pr_status,
        fc_status,
        hr_status,
        nft_status,
        trend_status,
        comp_status,
    ]
    if "FAIL" in all_statuses:
        overall_status = "FAIL"
    elif "WARNING" in all_statuses:
        overall_status = "WARNING"
    else:
        overall_status = "PASS"

    release_recommendation = RELEASE_RECOMMENDATIONS[overall_status]

    return {
        "build": current_build_number,
        "status": overall_status,
        "release_recommendation": release_recommendation,
        "checks": checks,
        "triggered_rules": triggered_rules,
    }
