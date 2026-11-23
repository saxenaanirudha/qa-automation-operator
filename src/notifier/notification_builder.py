"""
Notification Builder Module.

Builds a platform-independent notification payload dictionary combining key metrics
from all QA analyzers.

Supports:
    - Quality Gate Status & Release Recommendation
    - Severity level mapping (PASS -> INFO, WARNING -> WARNING, FAIL -> CRITICAL)
    - Executive Pass/Fail summary
    - Top N Risk Modules (default 3)
    - Newly Failing Tests summary (limited to max N, e.g. 5)
    - Flaky Tests summary (limited to max N, e.g. 3)
    - Report URL generation if REPORT_BASE_URL is set, falling back to local file path
"""

import os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

from config import get_notification_config

load_dotenv()


# Severity mapping based on Quality Gate status
SEVERITY_MAP = {
    "PASS": "INFO",
    "WARNING": "WARNING",
    "FAIL": "CRITICAL",
}


def build_notification_payload(
    build_number: int,
    summary: Optional[Dict[str, Any]] = None,
    comparison: Optional[Dict[str, Any]] = None,
    trend_analysis: Optional[Dict[str, Any]] = None,
    risk_analysis: Optional[Dict[str, Any]] = None,
    quality_gate: Optional[Dict[str, Any]] = None,
    flaky_analysis: Optional[Dict[str, Any]] = None,
    report_path: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Constructs a platform-independent notification payload dictionary.

    Args:
        build_number: Build number.
        summary: Build summary dictionary.
        comparison: Build comparison dictionary.
        trend_analysis: Multi-build trend analysis dictionary.
        risk_analysis: Module risk analysis dictionary.
        quality_gate: Quality gate evaluation dictionary.
        flaky_analysis: Flaky test detection dictionary.
        report_path: Path to the generated HTML report.
        config: Optional notification configuration override.

    Returns:
        Structured notification payload dictionary.
    """
    cfg = config or get_notification_config()
    max_risk_modules = int(cfg.get("max_risk_modules", 3))
    max_new_failures = int(cfg.get("max_new_failures", 5))
    max_flaky_tests = int(cfg.get("max_flaky_tests", 3))

    # 1. Quality Gate & Severity
    qg_status = quality_gate.get("status", "UNKNOWN") if quality_gate else "UNKNOWN"
    qg_rec = (
        quality_gate.get("release_recommendation", "UNKNOWN")
        if quality_gate
        else "UNKNOWN"
    )
    severity = SEVERITY_MAP.get(qg_status, "INFO")

    # 2. Executive Summary
    pass_rate = summary.get("pass_rate", 0.0) if summary else 0.0
    passed = summary.get("passed", 0) if summary else 0
    failed = summary.get("failed", 0) if summary else 0
    skipped = summary.get("skipped", 0) if summary else 0

    # 3. Comparison & Trend
    comp_status = (
        comparison.get("overall_status", "N/A") if comparison else "N/A"
    )
    trend_status = (
        trend_analysis.get("overall_trend", "N/A") if trend_analysis else "N/A"
    )

    # 4. Top Risk Modules
    top_risk_modules: List[Dict[str, Any]] = []
    if risk_analysis and risk_analysis.get("ranked_modules"):
        ranked = risk_analysis["ranked_modules"][:max_risk_modules]
        for mod in ranked:
            data = risk_analysis["modules"].get(mod, {})
            top_risk_modules.append(
                {
                    "module": mod,
                    "score": data.get("score", 0),
                    "level": data.get("level", "LOW"),
                }
            )

    # 5. Newly Failing Tests
    new_failing_raw = (
        comparison.get("newly_failing_tests", []) if comparison else []
    )
    total_newly_failing = len(new_failing_raw)
    newly_failing_tests = new_failing_raw[:max_new_failures]
    newly_failing_overflow = max(0, total_newly_failing - max_new_failures)

    # 6. Flaky Tests
    flaky_raw = (
        flaky_analysis.get("ranked_flaky_tests", []) if flaky_analysis else []
    )
    total_flaky = len(flaky_raw)
    total_pos_flaky = (
        len(flaky_analysis.get("possibly_flaky_tests", []))
        if flaky_analysis
        else 0
    )

    top_flaky_tests: List[Dict[str, Any]] = []
    if flaky_analysis and flaky_raw:
        for t in flaky_raw[:max_flaky_tests]:
            data = flaky_analysis.get("tests", {}).get(t, {})
            top_flaky_tests.append(
                {
                    "test_name": t,
                    "score": data.get("flaky_score", 0),
                    "module": data.get("module", ""),
                }
            )

    # 7. HTML Report URL or Path
    report_link = "N/A"
    if report_path:
        base_url = os.getenv("REPORT_BASE_URL", "").strip()
        if base_url:
            filename = os.path.basename(report_path)
            report_link = f"{base_url.rstrip('/')}/{filename}"
        else:
            # Normalize path slashes for readable output
            report_link = str(report_path).replace("\\", "/")

    return {
        "build": build_number,
        "severity": severity,
        "quality_gate": {
            "status": qg_status,
            "recommendation": qg_rec,
        },
        "summary": {
            "pass_rate": pass_rate,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
        "comparison": comp_status,
        "trend": trend_status,
        "top_risk_modules": top_risk_modules,
        "newly_failing_tests": newly_failing_tests,
        "total_newly_failing": total_newly_failing,
        "newly_failing_overflow": newly_failing_overflow,
        "flaky_tests": top_flaky_tests,
        "total_flaky": total_flaky,
        "total_possibly_flaky": total_pos_flaky,
        "report": report_link,
    }
