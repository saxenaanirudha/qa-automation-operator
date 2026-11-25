"""
Live Gemini API Verification Script for QA Automation Operator.

Executes exactly two live requests (Scenario A: Successful Build, Scenario B: Synthetic Failed Build)
within free-tier limits, validates genuine Gemini responses, and renders authentic HTML dashboards
with zero repeated API calls.
"""

import os
import sys
import json
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

from src.services.ai_service import (
    generate_ai_insights,
    is_ai_enabled,
    get_gemini_api_key,
    get_gemini_model,
    get_gemini_timeout_seconds,
)
from src.reporter.html_reporter import generate_html_report
from src.database.database import init_db
from src.database.repository import save_build_result


def main():
    print("=" * 60)
    print("  QA Automation Operator — Live Gemini API Verification")
    print("=" * 60)

    # 1. Check configuration
    enabled = is_ai_enabled()
    key = get_gemini_api_key()
    model = get_gemini_model()
    timeout = get_gemini_timeout_seconds()

    print(f"\n[1] Configuration Check:")
    print(f"  - AI_ENABLED: {enabled}")
    print(f"  - GEMINI_MODEL: {model}")
    print(f"  - GEMINI_TIMEOUT_SECONDS: {timeout:.1f}s")
    print(f"  - GEMINI_API_KEY: {'[CONFIGURED]' if key else '[NOT FOUND / EMPTY]'}")

    if not enabled:
        print("\n[ERROR] AI_ENABLED is false. Set AI_ENABLED=true in your environment or .env file.")
        sys.exit(1)

    if not key:
        print("\n[ERROR] GEMINI_API_KEY is not configured. Set GEMINI_API_KEY in your environment or .env file.")
        sys.exit(1)

    init_db()
    os.makedirs("reports", exist_ok=True)
    os.makedirs("reports/screenshots/genai", exist_ok=True)

    # =========================================================================
    # Scenario A: Successful Build (Zero Failures)
    # =========================================================================
    print("\n[2] Executing Scenario A: Successful Build (Zero Failures)...")
    build_a = int(time.time_ns() % 10000000) + 11000
    df_a = pd.DataFrame([
        {"test_name": f"test_auth_module_{i}", "module": "Auth", "status": "PASS", "duration": 0.15, "error": None}
        for i in range(1, 6)
    ] + [
        {"test_name": f"test_checkout_flow_{i}", "module": "Checkout", "status": "PASS", "duration": 0.22, "error": None}
        for i in range(1, 6)
    ])
    summary_a = {
        "build": build_a,
        "total": 10,
        "passed": 10,
        "failed": 0,
        "skipped": 0,
        "pass_rate": 100.0,
        "failure_rate": 0.0,
        "data": df_a,
    }
    save_build_result(summary_a, df_a)

    print("  -> Dispatching Live Request #1 to Gemini API...")
    insights_a = generate_ai_insights(summary_a)

    if not insights_a:
        print("  [!] Scenario A failed. Stopping immediately without executing Scenario B.")
        sys.exit(1)

    print("  [OK] Received Genuine Gemini Response for Scenario A:")
    print(f"       Model: {insights_a.get('model')}")
    print(f"       Summary: {insights_a.get('summary')[:100]}...")
    print(f"       Probable Root Causes count: {len(insights_a.get('probable_root_causes', []))} (Expected: 0)")
    assert len(insights_a.get("probable_root_causes", [])) == 0, "Invariant violation: Zero failures must produce zero root causes!"
    print(f"       Recommended Scenarios: {len(insights_a.get('recommended_test_scenarios', []))}")

    report_a_path = generate_html_report(
        build_number=build_a,
        output_path="reports/qa_report_ai_success.html",
        summary=summary_a,
        ai_insights=insights_a,
    )
    print(f"  [OK] Generated Dashboard: {report_a_path}")

    # =========================================================================
    # Scenario B: Synthetic Failed Build
    # =========================================================================
    print("\n[3] Executing Scenario B: Synthetic Failed Build...")
    build_b = int(time.time_ns() % 10000000) + 12000
    df_b = pd.DataFrame([
        {"test_name": f"test_auth_module_{i}", "module": "Auth", "status": "PASS", "duration": 0.12, "error": None}
        for i in range(1, 6)
    ] + [
        {"test_name": "test_order_checkout_flow", "module": "Checkout", "status": "FAIL", "duration": 5.01,
         "error": "HTTP 504 Gateway Timeout while contacting payment authorization microservice after 3 retries"},
        {"test_name": "test_database_connection_retry", "module": "Database", "status": "FAIL", "duration": 3.10,
         "error": "psycopg2.OperationalError: could not connect to server: Connection refused on port 5432"},
        {"test_name": "test_notification_dispatcher", "module": "Notifier", "status": "PASS", "duration": 0.35, "error": None},
    ])
    summary_b = {
        "build": build_b,
        "total": 8,
        "passed": 6,
        "failed": 2,
        "skipped": 0,
        "pass_rate": 75.0,
        "failure_rate": 25.0,
        "data": df_b,
    }
    save_build_result(summary_b, df_b)

    failure_analysis_b = {
        "total_failures": 2,
        "failures_by_module": {"Checkout": 1, "Database": 1},
        "failed_tests": [
            {"test_name": "test_order_checkout_flow", "module": "Checkout",
             "error": "HTTP 504 Gateway Timeout while contacting payment authorization microservice after 3 retries"},
            {"test_name": "test_database_connection_retry", "module": "Database",
             "error": "psycopg2.OperationalError: could not connect to server: Connection refused on port 5432"},
        ]
    }
    risk_b = {
        "module_risks": [
            {"module": "Checkout", "level": "HIGH"},
            {"module": "Database", "level": "MEDIUM"},
        ]
    }

    print("  -> Dispatching Live Request #2 to Gemini API...")
    insights_b = generate_ai_insights(
        summary=summary_b,
        failure_analysis=failure_analysis_b,
        risk_analysis=risk_b,
    )

    if not insights_b:
        print("  [!] Scenario B failed.")
        sys.exit(1)

    print("  [OK] Received Genuine Gemini Response for Scenario B:")
    print(f"       Model: {insights_b.get('model')}")
    print(f"       Summary: {insights_b.get('summary')[:100]}...")
    print(f"       Probable Root Causes count: {len(insights_b.get('probable_root_causes', []))}")
    for rc in insights_b.get("probable_root_causes", []):
        print(f"         * Test: {rc.get('test_name')} | Cause: {rc.get('probable_cause')[:60]}...")
    print(f"       Recommended Scenarios: {len(insights_b.get('recommended_test_scenarios', []))}")

    report_b_path = generate_html_report(
        build_number=build_b,
        output_path="reports/qa_report_ai_failure.html",
        summary=summary_b,
        failure_analysis=failure_analysis_b,
        ai_insights=insights_b,
    )
    print(f"  [OK] Generated Dashboard: {report_b_path}")

    # =========================================================================
    # Persist live responses for screenshots and audit
    # =========================================================================
    live_records = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "model_used": model,
        "timeout_seconds": timeout,
        "total_live_requests": 2,
        "scenario_a_success": insights_a,
        "scenario_b_failure": insights_b,
    }
    with open("reports/live_ai_responses.json", "w", encoding="utf-8") as f:
        json.dump(live_records, f, indent=2)

    print("\n" + "=" * 60)
    print("  [SUCCESS] All 2 Live Gemini Verifications Completed!")
    print("  Live responses saved to: reports/live_ai_responses.json")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
