import os
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from src.parser.csv_parser import parse_csv
from src.parser.junit_parser import parse_junit_xml
from src.analyzer.failure_analyzer import analyze_failures
from src.analyzer.build_comparison import compare_with_previous_build, NoPreviousBuildError
from src.analyzer.trend_analyzer import analyze_trends, NotEnoughBuildsError
from src.analyzer.risk_analyzer import analyze_risk
from src.quality_gate.quality_gate import evaluate_quality_gate
from src.analyzer.flaky_detector import detect_flaky_tests
from src.reporter.html_reporter import generate_html_report
from src.notifier.notification_builder import build_notification_payload
from src.notifier.notifier_service import send_qa_notifications
from src.database.database import init_db
from src.database.repository import save_build_result, DuplicateBuildError, BuildNotFoundError


def parse_input_file(
    file_path: str, build_number: Optional[int] = None, format_hint: str = "auto"
) -> Dict[str, Any]:
    """Auto-detects or parses file based on format_hint (.xml vs .csv) and calls parser."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Input file not found: {file_path}")

    fmt = format_hint.lower()
    if fmt == "junit" or (fmt == "auto" and file_path.endswith(".xml")):
        return parse_junit_xml(file_path, build_number=build_number)
    elif fmt == "csv" or (fmt == "auto" and file_path.endswith(".csv")):
        return parse_csv(file_path)
    else:
        # Fallback inspection by content
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline().strip()
        if first_line.startswith("<?xml") or first_line.startswith("<"):
            return parse_junit_xml(file_path, build_number=build_number)
        return parse_csv(file_path)


def analyze_and_store_results(
    file_path: str,
    build_number: Optional[int] = None,
    format_hint: str = "auto",
    generate_report: bool = True,
    send_notifications: bool = False,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Core QA pipeline function shared by CLI and API.

    Parses test results, analyzes failures, saves to database, runs build comparison,
    analyzes multi-build trends, computes module risk, evaluates quality gate,
    detects flaky tests, and optionally generates HTML reports and dispatches notifications.
    """
    # 1. Parse Input File
    summary = parse_input_file(file_path, build_number=build_number, format_hint=format_hint)
    b_num = summary["build"]

    # 2. Failure Analysis
    failure_analysis = analyze_failures(summary["data"])

    # 3. Database Persistence
    init_db()
    save_build_result(summary, summary["data"], session=session)

    # 4. Build Comparison
    comparison = None
    try:
        comparison = compare_with_previous_build(b_num, session=session)
    except (NoPreviousBuildError, BuildNotFoundError):
        comparison = None

    # 5. Trend Analysis
    trend_analysis = None
    try:
        trend_analysis = analyze_trends(session=session)
    except NotEnoughBuildsError:
        trend_analysis = None

    # 6. Risk Analysis
    risk_analysis = None
    try:
        risk_analysis = analyze_risk(b_num, session=session)
    except Exception:
        risk_analysis = None

    # 7. Quality Gate Evaluation
    quality_gate = evaluate_quality_gate(
        current_build_number=b_num,
        session=session,
    )

    # 8. Flaky Test Detection
    flaky_analysis = detect_flaky_tests(session=session)

    # 9. HTML Report Generation (Optional)
    report_path = None
    if generate_report:
        try:
            report_path = generate_html_report(
                build_number=b_num,
                summary=summary,
                failure_analysis=failure_analysis,
                comparison=comparison,
                trend_analysis=trend_analysis,
                risk_analysis=risk_analysis,
                quality_gate=quality_gate,
                flaky_analysis=flaky_analysis,
            )
        except Exception as exc:
            print(f"Warning: Failed to generate HTML report: {exc}")

    # 10. Notifications (Optional)
    notification_result = None
    if send_notifications:
        try:
            payload = build_notification_payload(
                build_number=b_num,
                summary=summary,
                comparison=comparison,
                trend_analysis=trend_analysis,
                risk_analysis=risk_analysis,
                quality_gate=quality_gate,
                flaky_analysis=flaky_analysis,
                report_path=report_path,
            )
            notification_result = send_qa_notifications(payload)
        except Exception as exc:
            print(f"Warning: Failed to send notifications: {exc}")

    return {
        "build": b_num,
        "summary": summary,
        "failure_analysis": failure_analysis,
        "comparison": comparison,
        "trend_analysis": trend_analysis,
        "risk_analysis": risk_analysis,
        "quality_gate": quality_gate,
        "flaky_analysis": flaky_analysis,
        "report_path": report_path,
        "notification_result": notification_result,
    }
