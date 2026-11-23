from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.api.dependencies import get_db_session
from src.api.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Basic service liveness health check."""
    return HealthResponse(status="ok")


@router.get("/health/db", response_model=HealthResponse)
def get_health_db(session: Session = Depends(get_db_session)) -> HealthResponse:
    """Database connectivity health check."""
    try:
        session.execute(text("SELECT 1"))
        return HealthResponse(status="ok", database="connected")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection failed: {exc}",
        )
