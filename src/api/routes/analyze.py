import os
import shutil
import tempfile
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from src.api.dependencies import get_db_session
from src.api.schemas import AnalyzeResponse, AnalyzeSummary, RiskModuleSummary
from src.api.security import verify_api_key, check_rate_limit
from src.services.qa_service import analyze_and_store_results
from src.database.repository import DuplicateBuildError

router = APIRouter(tags=["Analyze"])

# Maximum allowed file size for API upload (10 MB)
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    dependencies=[Depends(verify_api_key), Depends(check_rate_limit)],
)
def analyze_uploaded_file(
    file: UploadFile = File(...),
    build_number: Optional[int] = Form(None),
    format: Optional[str] = Form("auto"),
    session: Session = Depends(get_db_session),
) -> AnalyzeResponse:
    """
    Multipart file upload endpoint for analyzing CSV or JUnit XML test results.

    Saves uploaded file to a temporary location, processes analysis pipeline,
    stores build into database, evaluates Quality Gate, and returns summary metrics.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required for analysis upload.",
        )

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".csv", ".xml"] and format.lower() not in ["csv", "junit", "auto"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Please upload a .csv or .xml test results file.",
        )

    # Save to safe temporary file using server-generated filename
    safe_filename = f"upload_{uuid.uuid4().hex}{ext if ext in ['.csv', '.xml'] else ''}"
    temp_dir = tempfile.mkdtemp(prefix="qa_upload_")
    temp_path = os.path.join(temp_dir, safe_filename)

    try:
        total_size = 0
        chunk_size = 64 * 1024
        with open(temp_path, "wb") as f:
            while True:
                chunk = file.file.read(chunk_size)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > MAX_FILE_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"File size exceeds maximum limit of {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB.",
                    )
                f.write(chunk)

        res = analyze_and_store_results(
            file_path=temp_path,
            build_number=build_number,
            format_hint=format,
            generate_report=True,
            send_notifications=False,
            session=session,
        )

        b_num = res["build"]
        s = res["summary"]
        qg = res["quality_gate"]

        risk_modules = []
        if res.get("risk_analysis") and "ranked_modules" in res["risk_analysis"]:
            for r in res["risk_analysis"]["ranked_modules"][:3]:
                m_info = res["risk_analysis"]["modules"][r]
                risk_modules.append(
                    RiskModuleSummary(
                        module=r,
                        score=m_info["score"],
                        level=m_info["level"],
                    )
                )

        flaky_count = 0
        if res.get("flaky_analysis") and "flaky_tests" in res["flaky_analysis"]:
            flaky_count = len(res["flaky_analysis"]["flaky_tests"])

        return AnalyzeResponse(
            build=b_num,
            summary=AnalyzeSummary(
                total=s["total"],
                passed=s["passed"],
                failed=s["failed"],
                skipped=s["skipped"],
                pass_rate=s["pass_rate"],
                failure_rate=s["failure_rate"],
            ),
            quality_gate={
                "status": qg["status"],
                "release_recommendation": qg["release_recommendation"],
                "triggered_rules": qg.get("triggered_rules", []),
            },
            top_risk_modules=risk_modules,
            flaky_tests=flaky_count,
            report_path=res.get("report_path"),
        )

    except DuplicateBuildError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Build already exists in database.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing test analysis: {exc}",
        )
    finally:
        # Clean up temp file & directory
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        if os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
