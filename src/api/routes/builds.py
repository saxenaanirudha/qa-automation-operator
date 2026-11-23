import os
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session
from src.api.security import verify_api_key, check_rate_limit
from src.api.schemas import (
    BuildSummaryResponse,
    TestResultResponse,
    QualityGateResponse,
    NotificationRequest,
    NotificationResponse,
)
from src.database.repository import (
    get_all_builds,
    get_build_by_number,
    get_test_results_for_build,
    get_latest_builds,
    BuildNotFoundError,
)
from src.analyzer.failure_analyzer import analyze_failures
from src.analyzer.build_comparison import compare_with_previous_build, NoPreviousBuildError
from src.analyzer.risk_analyzer import analyze_risk
from src.quality_gate.quality_gate import evaluate_quality_gate
from src.analyzer.trend_analyzer import analyze_trends, NotEnoughBuildsError
from src.analyzer.flaky_detector import detect_flaky_tests
from src.reporter.html_reporter import generate_html_report
from src.notifier.notification_builder import build_notification_payload
from src.notifier.notifier_service import send_qa_notifications

router = APIRouter(prefix="/builds", tags=["Builds"])


@router.get("", response_model=List[BuildSummaryResponse])
def list_builds(
    limit: int = Query(20, ge=1, le=100, description="Maximum number of recent builds to return"),
    session: Session = Depends(get_db_session),
) -> List[BuildSummaryResponse]:
    """Retrieves stored build summaries ordered from newest to oldest."""
    recent_builds = get_latest_builds(limit, session=session)
    results = []
    for b in recent_builds:
        results.append(
            BuildSummaryResponse(
                build_number=b.build_number,
                total_tests=b.total_tests,
                passed=b.passed,
                failed=b.failed,
                skipped=b.skipped,
                pass_rate=b.pass_rate,
                failure_rate=b.failure_rate,
                created_at=str(b.created_at) if b.created_at else None,
            )
        )
    return results


@router.get("/{build_number}", response_model=BuildSummaryResponse)
def get_build(
    build_number: int, session: Session = Depends(get_db_session)
) -> BuildSummaryResponse:
    """Retrieves the build summary for a single build number."""
    build = get_build_by_number(build_number, session=session)
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build {build_number} not found in database.",
        )
    return BuildSummaryResponse(
        build_number=build.build_number,
        total_tests=build.total_tests,
        passed=build.passed,
        failed=build.failed,
        skipped=build.skipped,
        pass_rate=build.pass_rate,
        failure_rate=build.failure_rate,
        created_at=str(build.created_at) if build.created_at else None,
    )


@router.get("/{build_number}/tests", response_model=List[TestResultResponse])
def get_build_tests(
    build_number: int,
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by test status (PASS, FAIL, SKIP)"),
    module_filter: Optional[str] = Query(None, alias="module", description="Filter by module name"),
    session: Session = Depends(get_db_session),
) -> List[TestResultResponse]:
    """Retrieves test result details for a specific build with optional status/module filtering."""
    try:
        results = get_test_results_for_build(build_number, session=session)
    except BuildNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build {build_number} not found in database.",
        )

    filtered = results
    if status_filter:
        filtered = [r for r in filtered if r.status.upper() == status_filter.upper()]
    if module_filter:
        filtered = [r for r in filtered if r.module.lower() == module_filter.lower()]

    output = []
    for r in filtered:
        output.append(
            TestResultResponse(
                id=r.id,
                build_id=r.build_id,
                test_name=r.test_name,
                module=r.module,
                status=r.status,
                duration=r.duration,
                error=r.error,
            )
        )
    return output


@router.get("/{build_number}/failures")
def get_build_failures(
    build_number: int, session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """Runs failure analysis on a specific build."""
    try:
        test_results = get_test_results_for_build(build_number, session=session)
    except BuildNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build {build_number} not found in database.",
        )

    rows = []
    for r in test_results:
        rows.append(
            {
                "test_name": r.test_name,
                "module": r.module,
                "status": r.status,
                "duration": r.duration,
                "error": r.error,
                "build": build_number,
            }
        )
    import pandas as pd

    df = pd.DataFrame(rows)
    analysis = analyze_failures(df)
    return {"build": build_number, **analysis}


@router.get("/{build_number}/comparison")
def get_build_comparison(
    build_number: int, session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """Compares the specified build against the preceding stored build."""
    build = get_build_by_number(build_number, session=session)
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build {build_number} not found in database.",
        )

    try:
        return compare_with_previous_build(build_number, session=session)
    except NoPreviousBuildError:
        return {
            "build": build_number,
            "comparison_available": False,
            "reason": "No previous build available.",
        }


@router.get("/{build_number}/risk")
def get_build_risk(
    build_number: int, session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """Calculates rule-based module risk scores for the specified build."""
    build = get_build_by_number(build_number, session=session)
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build {build_number} not found in database.",
        )

    try:
        return analyze_risk(build_number, session=session)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error evaluating risk analysis: {exc}",
        )


@router.get("/{build_number}/quality-gate")
def get_build_quality_gate(
    build_number: int, session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """Evaluates Quality Gate status for a build (returns HTTP 200 regardless of PASS/WARNING/FAIL status)."""
    build = get_build_by_number(build_number, session=session)
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build {build_number} not found in database.",
        )

    summary = {
        "build": build.build_number,
        "total": build.total_tests,
        "passed": build.passed,
        "failed": build.failed,
        "skipped": build.skipped,
        "pass_rate": build.pass_rate,
        "failure_rate": build.failure_rate,
    }

    test_results = get_test_results_for_build(build_number, session=session)
    import pandas as pd

    df = pd.DataFrame([{"test_name": r.test_name, "module": r.module, "status": r.status, "duration": r.duration, "error": r.error, "build": build_number} for r in test_results])
    failure_analysis = analyze_failures(df)

    comparison = None
    try:
        comparison = compare_with_previous_build(build_number, session=session)
    except Exception:
        comparison = None

    trend = None
    try:
        trend = analyze_trends(session=session)
    except Exception:
        trend = None

    risk = None
    try:
        risk = analyze_risk(build_number, session=session)
    except Exception:
        risk = None

    qg = evaluate_quality_gate(build_number, session=session)
    return qg


@router.post(
    "/{build_number}/report",
    dependencies=[Depends(verify_api_key), Depends(check_rate_limit)],
)
def generate_build_report(
    build_number: int, session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """Triggers server-side HTML report generation for a specified build."""
    build = get_build_by_number(build_number, session=session)
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build {build_number} not found in database.",
        )

    summary = {
        "build": build.build_number,
        "total": build.total_tests,
        "passed": build.passed,
        "failed": build.failed,
        "skipped": build.skipped,
        "pass_rate": build.pass_rate,
        "failure_rate": build.failure_rate,
    }

    test_results = get_test_results_for_build(build_number, session=session)
    import pandas as pd

    df = pd.DataFrame([{"test_name": r.test_name, "module": r.module, "status": r.status, "duration": r.duration, "error": r.error, "build": build_number} for r in test_results])
    failure_analysis = analyze_failures(df)
    comparison = compare_with_previous_build(build_number, session=session) if build_number else None
    trend = analyze_trends(session=session) if len(get_all_builds(session=session)) >= 3 else None
    risk = analyze_risk(build_number, session=session)
    quality_gate = evaluate_quality_gate(build_number, session=session)
    flaky = detect_flaky_tests(session=session)

    report_path = generate_html_report(
        build_number=build_number,
        summary=summary,
        failure_analysis=failure_analysis,
        comparison=comparison,
        trend_analysis=trend,
        risk_analysis=risk,
        quality_gate=quality_gate,
        flaky_analysis=flaky,
    )

    rel_path = os.path.relpath(report_path)
    return {
        "build": build_number,
        "status": "generated",
        "report_path": rel_path,
    }


@router.post(
    "/{build_number}/notify",
    response_model=NotificationResponse,
    dependencies=[Depends(verify_api_key), Depends(check_rate_limit)],
)
def dispatch_build_notifications(
    build_number: int,
    req: NotificationRequest,
    session: Session = Depends(get_db_session),
) -> NotificationResponse:
    """Dispatches build summary notifications to configured webhooks."""
    build = get_build_by_number(build_number, session=session)
    if not build:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build {build_number} not found in database.",
        )

    summary = {
        "build": build.build_number,
        "total": build.total_tests,
        "passed": build.passed,
        "failed": build.failed,
        "skipped": build.skipped,
        "pass_rate": build.pass_rate,
        "failure_rate": build.failure_rate,
    }

    test_results = get_test_results_for_build(build_number, session=session)
    import pandas as pd

    df = pd.DataFrame([{"test_name": r.test_name, "module": r.module, "status": r.status, "duration": r.duration, "error": r.error, "build": build_number} for r in test_results])
    failure_analysis = analyze_failures(df)
    comparison = None
    try:
        comparison = compare_with_previous_build(build_number, session=session)
    except Exception:
        comparison = None

    trend = None
    try:
        trend = analyze_trends(session=session)
    except Exception:
        trend = None

    risk = None
    try:
        risk = analyze_risk(build_number, session=session)
    except Exception:
        risk = None

    qg = evaluate_quality_gate(build_number, session=session)
    flaky = detect_flaky_tests(session=session)

    payload = build_notification_payload(
        build_number=build_number,
        summary=summary,
        comparison=comparison,
        trend_analysis=trend,
        risk_analysis=risk,
        quality_gate=qg,
        flaky_analysis=flaky,
        report_path=f"reports/qa_report_build_{build_number}.html",
    )

    res = send_qa_notifications(
        payload,
        slack_enabled=req.slack,
        teams_enabled=req.teams,
    )
    return NotificationResponse(
        build=build_number,
        slack=res.get("slack", {}),
        teams=res.get("teams", {}),
    )
