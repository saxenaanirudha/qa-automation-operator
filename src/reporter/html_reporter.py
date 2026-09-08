"""
HTML Reporter Module — Server-Side QA Dashboard Generation.

Combines data from all QA analyzers into a single, self-contained, responsive
HTML report template rendered with Jinja2.

Features:
    - Quality Gate & Release Recommendation Header
    - Executive Summary Cards
    - QA Attention Required section
    - Quality Gate detailed checks and triggered rules
    - Failure Analysis details
    - Build Comparison diffs
    - Multi-build Trend Analysis with Matplotlib line charts
    - Module Risk Scores with Matplotlib bar chart
    - Flaky Test Analysis table
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from src.database.repository import (
    get_build_by_number,
    get_test_results_for_build,
    BuildNotFoundError,
)
from src.analyzer.failure_analyzer import analyze_failures
from src.analyzer.build_comparison import (
    compare_with_previous_build,
    NoPreviousBuildError,
)
from src.analyzer.trend_analyzer import (
    analyze_trends,
    NotEnoughBuildsError,
)
from src.analyzer.risk_analyzer import analyze_risk
from src.quality_gate.quality_gate import evaluate_quality_gate
from src.analyzer.flaky_detector import detect_flaky_tests
from src.reporter.chart_generator import (
    generate_pass_rate_chart,
    generate_failure_trend_chart,
    generate_module_failure_chart,
    generate_risk_chart,
)


# ---------------------------------------------------------------------------
# Template Setup
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
_JINJA_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


# ---------------------------------------------------------------------------
# Attention Section Helper
# ---------------------------------------------------------------------------

def _generate_attention_items(
    quality_gate: Optional[Dict[str, Any]],
    risk_analysis: Optional[Dict[str, Any]],
    comparison: Optional[Dict[str, Any]],
    trend_analysis: Optional[Dict[str, Any]],
    flaky_analysis: Optional[Dict[str, Any]],
) -> List[str]:
    """Generates a deterministic list of high-priority QA attention points."""
    items: List[str] = []

    if quality_gate and quality_gate.get("status") != "PASS":
        status = quality_gate["status"]
        rec = quality_gate.get("release_recommendation", "")
        items.append(f"Quality Gate status is {status} ({rec} release recommended).")

    if risk_analysis and risk_analysis.get("high_risk_modules"):
        high_mods = ", ".join(risk_analysis["high_risk_modules"])
        items.append(f"HIGH risk detected in module(s): {high_mods}.")

    if comparison and comparison.get("newly_failing_tests"):
        count = len(comparison["newly_failing_tests"])
        items.append(f"{count} newly failing test(s) detected compared to previous build.")

    if trend_analysis and trend_analysis.get("overall_trend") == "WORSENING":
        items.append("Overall QA quality trend is WORSENING across recent builds.")

    if flaky_analysis and flaky_analysis.get("flaky_tests"):
        count = len(flaky_analysis["flaky_tests"])
        items.append(f"{count} flaky test(s) identified across execution history.")

    return items


# ---------------------------------------------------------------------------
# Core Report Generator
# ---------------------------------------------------------------------------

def generate_html_report(
    build_number: int,
    output_path: Optional[str] = None,
    summary: Optional[Dict[str, Any]] = None,
    failure_analysis: Optional[Dict[str, Any]] = None,
    comparison: Optional[Dict[str, Any]] = None,
    trend_analysis: Optional[Dict[str, Any]] = None,
    risk_analysis: Optional[Dict[str, Any]] = None,
    quality_gate: Optional[Dict[str, Any]] = None,
    flaky_analysis: Optional[Dict[str, Any]] = None,
    session: Optional[Session] = None,
) -> str:
    """
    Generates an HTML QA Report / Dashboard for the specified build.

    Args:
        build_number: The build number to generate the report for.
        output_path: Optional output file path (defaults to ``reports/qa_report_build_<build_number>.html``).
        summary: Optional pre-calculated build summary dict.
        failure_analysis: Optional pre-calculated failure analysis dict.
        comparison: Optional pre-calculated build comparison dict.
        trend_analysis: Optional pre-calculated trend analysis dict.
        risk_analysis: Optional pre-calculated risk analysis dict.
        quality_gate: Optional pre-calculated quality gate dict.
        flaky_analysis: Optional pre-calculated flaky test detection dict.
        session: Optional SQLAlchemy session.

    Returns:
        Absolute filepath string of the generated HTML report.

    Raises:
        BuildNotFoundError: If the build does not exist.
    """
    # 1. Determine target filepaths
    if output_path is None:
        target_path = Path("reports") / f"qa_report_build_{build_number}.html"
    else:
        target_path = Path(output_path)

    target_path = target_path.resolve()
    reports_dir = target_path.parent
    assets_dir = reports_dir / "assets"

    reports_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    # 2. Gather missing analyzer results
    if summary is None:
        build_obj = get_build_by_number(build_number, session=session)
        if build_obj is None:
            raise BuildNotFoundError(f"Build {build_number} not found in database.")
        summary = {
            "build": build_number,
            "total": build_obj.total_tests,
            "passed": build_obj.passed,
            "failed": build_obj.failed,
            "skipped": build_obj.skipped,
            "pass_rate": build_obj.pass_rate,
            "failure_rate": build_obj.failure_rate,
        }

    if failure_analysis is None:
        test_results = get_test_results_for_build(build_number, session=session)
        import pandas as pd
        rows = [
            {
                "test_name": tr.test_name,
                "module": tr.module,
                "status": tr.status,
                "duration": tr.duration,
                "error": tr.error,
            }
            for tr in test_results
        ]
        df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["test_name", "module", "status", "error"])
        failure_analysis = analyze_failures(df)

    if comparison is None:
        try:
            comparison = compare_with_previous_build(build_number, session=session)
        except (NoPreviousBuildError, BuildNotFoundError):
            comparison = None

    if trend_analysis is None:
        try:
            trend_analysis = analyze_trends(session=session)
        except NotEnoughBuildsError:
            trend_analysis = None

    if risk_analysis is None:
        risk_analysis = analyze_risk(build_number, session=session)

    if quality_gate is None:
        quality_gate = evaluate_quality_gate(build_number, session=session)

    if flaky_analysis is None:
        flaky_analysis = detect_flaky_tests(session=session)

    # 3. Generate Charts & asset paths
    charts: Dict[str, Optional[str]] = {
        "pass_rate_trend": None,
        "failure_trend": None,
        "module_failures": None,
        "risk_scores": None,
    }

    if trend_analysis:
        pr_chart_path = assets_dir / f"pass_rate_trend_{build_number}.png"
        pr_chart = generate_pass_rate_chart(
            trend_analysis["pass_rate_history"],
            trend_analysis["builds_analyzed"],
            str(pr_chart_path),
        )
        if pr_chart:
            charts["pass_rate_trend"] = f"assets/{pr_chart_path.name}"

        fail_chart_path = assets_dir / f"failure_trend_{build_number}.png"
        fail_chart = generate_failure_trend_chart(
            trend_analysis["failure_history"],
            trend_analysis["builds_analyzed"],
            str(fail_chart_path),
        )
        if fail_chart:
            charts["failure_trend"] = f"assets/{fail_chart_path.name}"

    if failure_analysis and failure_analysis.get("failures_by_module"):
        mod_chart_path = assets_dir / f"module_failures_{build_number}.png"
        mod_chart = generate_module_failure_chart(
            failure_analysis["failures_by_module"], str(mod_chart_path)
        )
        if mod_chart:
            charts["module_failures"] = f"assets/{mod_chart_path.name}"

    if risk_analysis and risk_analysis.get("modules"):
        risk_chart_path = assets_dir / f"risk_scores_{build_number}.png"
        risk_chart = generate_risk_chart(
            risk_analysis["modules"], str(risk_chart_path)
        )
        if risk_chart:
            charts["risk_scores"] = f"assets/{risk_chart_path.name}"

    # 4. Extract detailed failed test records for rich failure view
    import pandas as pd
    failed_test_details: List[Dict[str, Any]] = []
    if summary and isinstance(summary.get("data"), pd.DataFrame):
        df_data = summary["data"]
        if not df_data.empty and "status" in df_data.columns:
            failed_df = df_data[df_data["status"] == "FAIL"]
            for _, row in failed_df.iterrows():
                err_val = row.get("error", "Unknown Error")
                if pd.isna(err_val) or str(err_val).strip() == "":
                    err_val = "Unknown Error"
                failed_test_details.append({
                    "test_name": str(row.get("test_name", "")),
                    "module": str(row.get("module", "")),
                    "error": str(err_val),
                    "duration": row.get("duration", None),
                })

    if not failed_test_details:
        try:
            test_results = get_test_results_for_build(build_number, session=session)
            for tr in test_results:
                if tr.status == "FAIL":
                    failed_test_details.append({
                        "test_name": tr.test_name,
                        "module": tr.module,
                        "error": tr.error or "Unknown Error",
                        "duration": tr.duration,
                    })
        except Exception:
            pass

    # 5. Generate QA Attention Items
    attention_items = _generate_attention_items(
        quality_gate, risk_analysis, comparison, trend_analysis, flaky_analysis
    )

    # 6. Render Jinja2 template
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    template = _JINJA_ENV.get_template("qa_report.html")

    html_content = template.render(
        build_number=build_number,
        generated_at=generated_at,
        summary=summary,
        failure_analysis=failure_analysis,
        failed_test_details=failed_test_details,
        comparison=comparison,
        trend_analysis=trend_analysis,
        risk_analysis=risk_analysis,
        quality_gate=quality_gate,
        flaky_analysis=flaky_analysis,
        attention_items=attention_items,
        charts=charts,
    )

    # 7. Write HTML file
    with open(target_path, "w", encoding="utf-8") as fh:
        fh.write(html_content)

    return str(target_path)
