from typing import Any, Dict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session
from src.analyzer.trend_analyzer import analyze_trends, NotEnoughBuildsError
from src.analyzer.flaky_detector import detect_flaky_tests

router = APIRouter(prefix="/analysis", tags=["Analysis"])


@router.get("/trends")
def get_historical_trends(
    limit: int = Query(5, ge=3, le=100, description="Number of recent builds to include in trend analysis"),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieves multi-build historical quality trend analysis."""
    try:
        return analyze_trends(limit=limit, session=session)
    except NotEnoughBuildsError as exc:
        return {
            "status": "insufficient_data",
            "reason": str(exc),
        }


@router.get("/flaky-tests")
def get_flaky_test_analysis(
    limit: int = Query(10, ge=1, le=100, description="Maximum number of top flaky tests to return"),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieves flaky test detector analysis and intermittent failure statistics."""
    return detect_flaky_tests(limit=limit, session=session)
