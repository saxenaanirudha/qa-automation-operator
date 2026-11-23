from tests import test_chart_generator
import argparse
import os
import sys
from typing import Any, Dict, Optional

from config import load_config
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




def _print_build_comparison(build_number: int) -> Optional[Dict[str, Any]]:
    """Runs compare_with_previous_build and prints formatted results to stdout."""
    print("Build Comparison")
    print("----------------")
    try:
        report = compare_with_previous_build(build_number)
    except NoPreviousBuildError:
        print("No previous build available.")
        return None
    except BuildNotFoundError as exc:
        print(str(exc))
        return None

    prev = report["previous_build"]
    curr = report["current_build"]
    status = report["overall_status"]
    summary = report["summary"]

    print(f"Previous Build: {prev}")
    print(f"Current Build:  {curr}")
    print()
    print(f"Overall Status: {status}")
    print()

    pr = summary["pass_rate"]
    sign = "+" if pr["difference"] >= 0 else ""
    print("Pass Rate:")
    print(f"  {pr['previous']}% -> {pr['current']}%")
    print(f"  Change: {sign}{pr['difference']}%")
    print()

    fa = summary["failed"]
    sign = "+" if fa["difference"] >= 0 else ""
    print("Failures:")
    print(f"  {fa['previous']} -> {fa['current']}")
    print(f"  Change: {sign}{fa['difference']}")

    print()

    newly_failing = report["newly_failing_tests"]
    print("Newly Failing Tests:")
    if newly_failing:
        for t in newly_failing:
            print(f"  - {t}")
    else:
        print("  None")
    print()

    recovered = report["recovered_tests"]
    print("Recovered Tests:")
    if recovered:
        for t in recovered:
            print(f"  - {t}")
    else:
        print("  None")
    print()

    persistent = report["persistent_failures"]
    print("Persistent Failures:")
    if persistent:
        for t in persistent:
            print(f"  - {t}")
    else:
        print("  None")
    print()

    if report["tests_added"]:
        print("Tests Added (not in previous build):")
        for t in report["tests_added"]:
            print(f"  - {t}")
        print()

    if report["tests_removed"]:
        print("Tests Removed (not in previous build):")
        for t in report["tests_removed"]:
            print(f"  - {t}")
        print()

    return report


def _print_trend_analysis() -> Optional[Dict[str, Any]]:
    """Runs analyze_trends and prints formatted results to stdout."""
    print("Trend Analysis")
    print("--------------")
    try:
        report = analyze_trends()
    except NotEnoughBuildsError as exc:
        print(str(exc))
        return None

    builds_str = " -> ".join(str(b) for b in report["builds_analyzed"])
    print(f"Builds Analyzed:")
    print(f"  {builds_str}")
    print()

    pr_history = " -> ".join(str(v) for v in report["pass_rate_history"])
    print("Pass Rate:")
    print(f"  {pr_history}")
    print(f"Pass Rate Trend: {report['pass_rate_trend']}")
    print()

    fail_history = " -> ".join(str(v) for v in report["failure_history"])

    print("Failures:")
    print(f"  {fail_history}")
    print(f"Failure Trend: {report['failure_trend']}")
    print()

    print(f"Overall QA Trend: {report['overall_trend']}")
    print()

    worsening = report["worsening_modules"]
    print("Worsening Modules:")
    if worsening:
        for m in worsening:
            print(f"  - {m}")
    else:
        print("  None")
    print()

    improving = report["improving_modules"]
    print("Improving Modules:")
    if improving:
        for m in improving:
            print(f"  - {m}")
    else:
        print("  None")
    print()

    return report


def _print_risk_analysis(build_number: int) -> Optional[Dict[str, Any]]:
    """Runs analyze_risk and prints a formatted risk report to stdout."""
    print("Risk Analysis")
    print("-------------")
    try:
        report = analyze_risk(build_number)
    except BuildNotFoundError as exc:
        print(str(exc))
        return None

    ranked = report["ranked_modules"]
    if not ranked:
        print("No modules to analyze.")
        return report

    for rank, module in enumerate(ranked, start=1):
        data = report["modules"][module]
        factors = data["factors"]
        print(f"{rank}. {module}")
        print(f"   Risk Score: {data['score']}/100")
        print(f"   Level: {data['level']}")
        print(f"   Current Failures: {factors['current_failures']['value']}")
        print(f"   Trend: {factors['trend']['value']}")
        print(f"   Persistent Failures: {factors['persistent_failures']['value']}")
        print(f"   Failure Share: {factors['failure_share']['value']}%")
        print()

    # Highlight the single highest-risk module
    print(f"Highest Risk Module:")
    print(f"  {ranked[0]}")
    print()

    return report


def _print_quality_gate(build_number: int) -> Optional[Dict[str, Any]]:
    """Runs evaluate_quality_gate and prints formatted results to stdout."""
    print("Quality Gate")
    print("------------")
    try:
        report = evaluate_quality_gate(build_number)
    except BuildNotFoundError as exc:
        print(str(exc))
        return None

    print(f"Status: {report['status']}\n")
    print("Triggered Rules:\n")

    triggered = report["triggered_rules"]
    if triggered:
        for rule in triggered:
            print(f"[{rule['severity']}] {rule['rule']}")
            print(f"{rule['message']}\n")
    else:
        print("  None\n")

    print("Release Recommendation:")
    print(f"{report['release_recommendation']}\n")

    return report


def _print_flaky_test_analysis(limit: int = 10) -> Dict[str, Any]:
    """Runs detect_flaky_tests and prints formatted results to stdout."""
    print("Flaky Test Analysis")
    print("-------------------")
    report = detect_flaky_tests(limit=limit)

    builds_str = " -> ".join(str(b) for b in report["builds_analyzed"])
    print("Builds Analyzed:")
    print(f"  {builds_str}\n")

    flaky_count = len(report["flaky_tests"])
    possibly_flaky_count = len(report["possibly_flaky_tests"])

    print(f"Flaky Tests: {flaky_count}")
    print(f"Possibly Flaky Tests: {possibly_flaky_count}\n")

    if report["ranked_flaky_tests"]:
        print("Top Flaky Tests:\n")
        for rank, test_name in enumerate(report["ranked_flaky_tests"], start=1):
            data = report["tests"][test_name]
            hist_str = " -> ".join(h["status"] for h in data["history"])

            print(f"{rank}. {test_name}")
            print(f"   Module: {data['module']}")
            print(f"   Flaky Score: {data['flaky_score']}/100")
            print(f"   Transitions: {data['transitions']}")
            print(f"   History: {hist_str}\n")

    if report["possibly_flaky_tests"]:
        print("Possibly Flaky:")
        for t in report["possibly_flaky_tests"]:
            print(f"  - {t}")
        print()

    if report["top_flaky_module"]:
        print("Top Flaky Module:")
        print(f"  {report['top_flaky_module']}\n")
    elif not report["ranked_flaky_tests"] and not report["possibly_flaky_tests"]:
        print("No flaky tests detected.\n")

    return report


def _print_html_report(
    build_number: int,
    summary: Dict[str, Any],
    failure_analysis: Dict[str, Any],
    comparison: Optional[Dict[str, Any]],
    trend_analysis: Optional[Dict[str, Any]],
    risk_analysis: Optional[Dict[str, Any]],
    quality_gate: Optional[Dict[str, Any]],
    flaky_analysis: Dict[str, Any],
) -> Optional[str]:
    """Generates the HTML QA Report and prints status to stdout."""
    print("HTML Report")
    print("-----------")
    try:
        report_path = generate_html_report(
            build_number=build_number,
            summary=summary,
            failure_analysis=failure_analysis,
            comparison=comparison,
            trend_analysis=trend_analysis,
            risk_analysis=risk_analysis,
            quality_gate=quality_gate,
            flaky_analysis=flaky_analysis,
        )
        rel_path = os.path.relpath(report_path)
        print("Report generated successfully.\n")
        print(f"{rel_path}\n")
        return rel_path
    except Exception as exc:
        print(f"Error generating HTML report: {exc}\n")
        return None


def _print_notifications(
    build_number: int,
    summary: Dict[str, Any],
    comparison: Optional[Dict[str, Any]],
    trend_analysis: Optional[Dict[str, Any]],
    risk_analysis: Optional[Dict[str, Any]],
    quality_gate: Optional[Dict[str, Any]],
    flaky_analysis: Dict[str, Any],
    report_path: Optional[str],
) -> None:
    """Dispatches notifications and prints status to stdout without raising errors."""
    print("Notifications")
    print("-------------")
    try:
        payload = build_notification_payload(
            build_number=build_number,
            summary=summary,
            comparison=comparison,
            trend_analysis=trend_analysis,
            risk_analysis=risk_analysis,
            quality_gate=quality_gate,
            flaky_analysis=flaky_analysis,
            report_path=report_path,
        )
        res = send_qa_notifications(payload)
        print(f"Slack: {res['slack']['message']}")
        print(f"Teams: {res['teams']['message']}\n")
    except Exception as exc:
        print(f"Error sending notifications: {exc}\n")


def determine_exit_code(gate_status: str, enforce: bool) -> int:
    """Determines process exit code based on Quality Gate status and enforcement flag."""
    if gate_status == "FAIL" and enforce:
        return 1
    return 0


def write_github_step_summary(
    result: Dict[str, Any],
    qg_report: Optional[Dict[str, Any]],
    risk_report: Optional[Dict[str, Any]],
    flaky_report: Optional[Dict[str, Any]],
) -> None:
    """Writes a concise Markdown summary to GITHUB_STEP_SUMMARY when running in GitHub Actions."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return

    try:
        gate_status = qg_report.get("status", "UNKNOWN") if qg_report else "UNKNOWN"
        rec = qg_report.get("release_recommendation", "UNKNOWN") if qg_report else "UNKNOWN"
        pass_rate = result.get("pass_rate", 0.0)
        failed_count = result.get("failed", 0)

        high_risk_cnt = 0
        if risk_report and "high_risk_modules" in risk_report:
            high_risk_cnt = len(risk_report["high_risk_modules"])

        flaky_cnt = 0
        if flaky_report and "flaky_tests" in flaky_report:
            flaky_cnt = len(flaky_report["flaky_tests"])

        md = f"""# QA Automation Operator

- **Build:** `{result.get('build')}`
- **Quality Gate:** `{gate_status}`
- **Release Recommendation:** `{rec}`

| Metric | Value |
| :--- | :--- |
| **Pass Rate** | `{pass_rate}%` |
| **Failed Tests** | `{failed_count}` |
| **High Risk Modules** | `{high_risk_cnt}` |
| **Flaky Tests** | `{flaky_cnt}` |

*HTML QA report and charts have been uploaded as workflow artifacts.*
"""
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(md)
    except Exception as exc:
        print(f"Warning: Failed to write GITHUB_STEP_SUMMARY: {exc}")


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


def main():
    parser = argparse.ArgumentParser(
        description="QA Automation Operator - Analyze test execution results, quality trends, and risk metrics."
    )
    parser.add_argument(
        "--file",
        "-f",
        "--input",
        "-i",
        dest="input_file",
        default=os.path.join("sample_data", "test_results_247.csv"),
        help="Path to CSV or JUnit XML test results file.",
    )
    parser.add_argument(
        "--format",
        "-fmt",
        choices=["auto", "csv", "junit"],
        default="auto",
        help="Test result file format (auto, csv, junit). Default: auto.",
    )
    parser.add_argument(
        "--build",
        "-b",
        type=int,
        default=None,
        help="Optional build number override.",
    )
    parser.add_argument(
        "--enforce-quality-gate",
        "-e",
        action="store_true",
        help="Enforce Quality Gate failure exit code (returns exit code 1 on FAIL).",
    )

    args = parser.parse_args()

    # Load configuration default fallback for enforcement
    cfg = load_config()
    ci_enforce_config = cfg.get("ci", {}).get("enforce_quality_gate", False)

    enforce_gate = args.enforce_quality_gate or ci_enforce_config

    try:
        result = parse_input_file(args.input_file, build_number=args.build, format_hint=args.format)
        print("QA Automation Operator\n")
        print(f"Build: {result['build']}\n")
        print(f"Total Tests: {result['total']}")
        print(f"Passed: {result['passed']}")
        print(f"Failed: {result['failed']}")
        print(f"Skipped: {result['skipped']}\n")
        print(f"Pass Rate: {result['pass_rate']}%")
        print(f"Failure Rate: {result['failure_rate']}%\n")

        failure_analysis = analyze_failures(result["data"])

        print("Failure Analysis")
        print("----------------\n")
        print(f"Total Failures: {failure_analysis['total_failures']}\n")

        print("Failures by Module:")
        if failure_analysis['failures_by_module']:
            for module, count in failure_analysis['failures_by_module'].items():
                print(f"  {module}: {count}")
        else:
            print("  None")
        print()

        print("Error Distribution:")
        if failure_analysis['error_distribution']:
            for error, count in failure_analysis['error_distribution'].items():
                print(f"  {error}: {count}")
        else:
            print("  None")
        print()

        print(f"Most Failed Module: {failure_analysis['most_failed_module']}")
        print(f"Most Common Error: {failure_analysis['most_common_error']}\n")

        print("Failed Tests:")
        if failure_analysis['failed_tests']:
            for test in failure_analysis['failed_tests']:
                print(f"  - {test}")
        else:
            print("  None")
        print()

        # Database initialization and saving
        init_db()
        print("Database")
        print("--------")
        try:
            save_build_result(result, result["data"])
            print(f"Build {result['build']} saved successfully.")
        except DuplicateBuildError:
            print(f"Build {result['build']} is already stored.")
        print()

        # Build Comparison
        comp_report = _print_build_comparison(result["build"])

        # Trend Analysis
        trend_report = _print_trend_analysis()

        # Risk Analysis
        risk_report = _print_risk_analysis(result["build"])

        # Quality Gate
        qg_report = _print_quality_gate(result["build"])

        # Flaky Test Detector
        flaky_report = _print_flaky_test_analysis()

        # HTML Report
        report_path = _print_html_report(
            build_number=result["build"],
            summary=result,
            failure_analysis=failure_analysis,
            comparison=comp_report,
            trend_analysis=trend_report,
            risk_analysis=risk_report,
            quality_gate=qg_report,
            flaky_analysis=flaky_report,
        )

        # Notifications
        _print_notifications(
            build_number=result["build"],
            summary=result,
            comparison=comp_report,
            trend_analysis=trend_report,
            risk_analysis=risk_report,
            quality_gate=qg_report,
            flaky_analysis=flaky_report,
            report_path=report_path,
        )

        # CI / Quality Gate Summary output & Exit Code logic
        gate_status = qg_report.get("status", "PASS") if qg_report else "PASS"
        exit_code = determine_exit_code(gate_status, enforce_gate)

        print("CI / Quality Gate")
        print("-----------------")
        print(f"Quality Gate: {gate_status}")
        if qg_report:
            print(f"Release Recommendation: {qg_report.get('release_recommendation', 'N/A')}")
        print(f"Enforcement: {'ENABLED' if enforce_gate else 'DISABLED'}")
        print(f"Process Result: {'FAILED' if exit_code != 0 else 'ANALYSIS COMPLETED'}\n")

        write_github_step_summary(result, qg_report, risk_report, flaky_report)

        if exit_code != 0:
            sys.exit(exit_code)

    except SystemExit:
        raise
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
