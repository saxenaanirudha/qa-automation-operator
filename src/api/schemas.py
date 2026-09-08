from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str
    database: Optional[str] = None


class BuildSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    build_number: int
    total_tests: int
    passed: int
    failed: int
    skipped: int
    pass_rate: float
    failure_rate: float
    created_at: Optional[str] = None


class TestResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    build_id: int
    test_name: str
    module: str
    status: str
    duration: float
    error: Optional[str] = None


class QualityGateResponse(BaseModel):
    build: int
    status: str
    release_recommendation: str
    triggered_rules: List[Dict[str, Any]] = []
    checks: Dict[str, Any] = {}


class NotificationRequest(BaseModel):
    slack: bool = True
    teams: bool = True


class NotificationResponse(BaseModel):
    build: int
    slack: Dict[str, Any]
    teams: Dict[str, Any]


class AnalyzeSummary(BaseModel):
    total: int
    passed: int
    failed: int
    skipped: int
    pass_rate: float
    failure_rate: float


class RiskModuleSummary(BaseModel):
    module: str
    score: int
    level: str


class AnalyzeResponse(BaseModel):
    build: int
    summary: AnalyzeSummary
    quality_gate: Dict[str, Any]
    top_risk_modules: List[RiskModuleSummary] = []
    flaky_tests: int = 0
    report_path: Optional[str] = None
