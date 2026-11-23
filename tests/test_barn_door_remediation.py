import io
import time
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
import pandas as pd

from src.api.app import app
from src.database.database import get_session
from src.database.models import Build, TestResult
from src.database.repository import save_build_result, DuplicateBuildError
from src.reporter.chart_generator import generate_pass_rate_chart

client = TestClient(app)


# ---------------------------------------------------------------------------
# 1. Path Traversal & Server-Generated Temp Filename Test
# ---------------------------------------------------------------------------
def test_path_traversal_file_upload_uses_safe_server_name(monkeypatch):
    """
    TDD Test: Uploads with path traversal sequences ('../../malicious.csv')
    must not use user-controlled filenames in os.path.join.
    The server must store temporary uploads using server-generated filenames.
    """
    captured_paths = []
    original_analyze_and_store = None

    import src.api.routes.analyze as analyze_module
    original_analyze_and_store = analyze_module.analyze_and_store_results

    def mock_analyze(file_path, **kwargs):
        captured_paths.append(file_path)
        # Verify the saved file name does NOT contain path traversal and is server-generated
        filename = os.path.basename(file_path)
        assert "../" not in file_path
        assert "..\\" not in file_path
        assert not filename.startswith("evil")
        return {
            "build": 9991,
            "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0, "pass_rate": 100.0, "failure_rate": 0.0},
            "quality_gate": {"status": "PASS", "release_recommendation": "PROCEED", "triggered_rules": []},
            "risk_analysis": {"ranked_modules": []},
            "flaky_analysis": {"flaky_tests": []},
        }

    monkeypatch.setattr(analyze_module, "analyze_and_store_results", mock_analyze)

    file_content = b"test_name,module,status,duration,error,build\ntest1,Auth,PASS,1.0,,9991\n"
    response = client.post(
        "/analyze",
        files={"file": ("../../evil.csv", io.BytesIO(file_content), "text/csv")},
        data={"format": "csv"},
    )
    assert response.status_code == 200
    assert len(captured_paths) == 1
    # Check that the filename used was not user-controlled
    assert "evil.csv" not in captured_paths[0]


# ---------------------------------------------------------------------------
# 2. Streaming Size Limit Rejection Test
# ---------------------------------------------------------------------------
def test_upload_streaming_size_limit_rejection():
    """
    TDD Test: Uploads exceeding the maximum allowed size must be rejected with HTTP 400
    without reading arbitrary gigabytes into memory.
    """
    from src.api.routes.analyze import MAX_FILE_SIZE_BYTES
    oversized_data = b"x" * (MAX_FILE_SIZE_BYTES + 1024)
    response = client.post(
        "/analyze",
        files={"file": ("large_results.csv", io.BytesIO(oversized_data), "text/csv")},
        data={"format": "csv"},
    )
    assert response.status_code == 400
    assert "File size exceeds maximum limit" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 3. Notification Flags Honored Test
# ---------------------------------------------------------------------------
def test_dispatch_notifications_respects_request_flags(monkeypatch):
    """
    TDD Test: POST /builds/{build}/notify must honor the 'slack' and 'teams'
    flags supplied in NotificationRequest.
    """
    build_num = int(time.time_ns() % 1000000) + 20000
    csv_content = f"test_name,module,status,duration,error,build\nt1,A,PASS,0.1,,{build_num}\n"
    upload_res = client.post(
        "/analyze",
        files={"file": (f"test_{build_num}.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
        data={"format": "csv"},
    )
    assert upload_res.status_code == 200

    dispatched_args = {}

    def mock_send(notification, slack_enabled=None, teams_enabled=None, config=None):
        dispatched_args["slack_enabled"] = slack_enabled
        dispatched_args["teams_enabled"] = teams_enabled
        return {"slack": {"sent": False, "enabled": slack_enabled}, "teams": {"sent": False, "enabled": teams_enabled}}

    import src.api.routes.builds as builds_module
    monkeypatch.setattr(builds_module, "send_qa_notifications", mock_send)

    # Send with slack=False, teams=True
    resp = client.post(f"/builds/{build_num}/notify", json={"slack": False, "teams": True})
    assert resp.status_code == 200
    assert dispatched_args.get("slack_enabled") is False
    assert dispatched_args.get("teams_enabled") is True

    # Send with slack=True, teams=False
    resp2 = client.post(f"/builds/{build_num}/notify", json={"slack": True, "teams": False})
    assert resp2.status_code == 200
    assert dispatched_args.get("slack_enabled") is True
    assert dispatched_args.get("teams_enabled") is False


# ---------------------------------------------------------------------------
# 4. Database Concurrency & IntegrityError -> DuplicateBuildError Test
# ---------------------------------------------------------------------------
def test_save_build_result_catches_integrity_error_as_duplicate():
    """
    TDD Test: When concurrent workers insert the same build number simultaneously,
    SQLAlchemy's IntegrityError must be caught, rolled back, and raised as
    DuplicateBuildError so the API layer can reliably return HTTP 409 Conflict.
    """
    session = get_session()
    build_num = int(time.time_ns() % 1000000) + 30000
    summary = {
        "build": build_num,
        "total": 1,
        "passed": 1,
        "failed": 0,
        "skipped": 0,
        "pass_rate": 100.0,
        "failure_rate": 0.0,
    }
    df = pd.DataFrame([{"test_name": "t1", "module": "M", "status": "PASS", "duration": 1.0, "error": None}])

    # First insert succeeds
    build = save_build_result(summary, df, session=session)
    assert build.build_number == build_num

    # Second insert with same session or simulated concurrent commit must raise DuplicateBuildError
    with pytest.raises(DuplicateBuildError):
        save_build_result(summary, df, session=session)
    session.close()


def test_concurrent_duplicate_upload_returns_409():
    """
    TDD Test: Concurrent uploads of identical build numbers must produce HTTP 409 Conflict,
    never unhandled HTTP 500 Internal Server Error.
    """
    build_num = int(time.time_ns() % 1000000) + 40000
    csv_content = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.5,,{build_num}\n"

    results = []

    def upload():
        c = TestClient(app)
        res = c.post(
            "/analyze",
            files={"file": ("results.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
            data={"format": "csv"},
        )
        results.append(res.status_code)

    threads = [threading.Thread(target=upload) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # One must succeed (200), and all duplicates must return 409 Conflict (NEVER 500)
    assert 200 in results
    for code in results:
        assert code in (200, 409)


# ---------------------------------------------------------------------------
# 5. Concurrency Safety in Matplotlib Chart Generation
# ---------------------------------------------------------------------------
def test_concurrent_chart_generation_thread_safety(tmp_path):
    """
    TDD Test: Concurrent calls to chart generation across multiple threads
    must execute cleanly without figure collisions or exceptions.
    """
    errors = []

    def generate_chart(idx):
        try:
            out_file = str(tmp_path / f"chart_{idx}.png")
            generate_pass_rate_chart([90.0, 95.0, 98.0], [101, 102, 103], out_file)
            assert os.path.exists(out_file)
        except Exception as e:
            errors.append(e)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(generate_chart, i) for i in range(16)]
        for f in futures:
            f.result()

    assert len(errors) == 0


# ---------------------------------------------------------------------------
# 6. Negative & Security Tests: XML Entity Expansion & Malformed Files
# ---------------------------------------------------------------------------
def test_xxe_entity_expansion_rejected(tmp_path):
    """
    Security Test: XML with <!ENTITY declarations (XXE / Billion Laughs)
    must be safely rejected without processing entity expansion.
    """
    from src.parser.junit_parser import parse_junit_xml

    xml_bomb = """<?xml version="1.0"?>
    <!DOCTYPE lolz [
      <!ENTITY lol "lol">
      <!ELEMENT lolz (#PCDATA)>
      <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
    ]>
    <testsuites>
      <testsuite name="bomb">
        <testcase classname="tests.TestBomb" name="&lol1;" time="0.1"/>
      </testsuite>
    </testsuites>"""
    bomb_file = tmp_path / "bomb.xml"
    bomb_file.write_text(xml_bomb, encoding="utf-8")

    with pytest.raises(ValueError, match="Security violation: XML entity declarations"):
        parse_junit_xml(str(bomb_file), build_number=888)


def test_negative_invalid_status_rejected_in_csv(tmp_path):
    """
    Negative Test: CSV with invalid status value must raise ValueError.
    """
    from src.parser.csv_parser import parse_csv
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("test_name,module,status,duration,error,build\nt1,M,CORRUPT,1.0,,100\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid test status found"):
        parse_csv(str(bad_csv))


def test_cli_execution_remains_functional():
    """
    Regression Test: CLI functions (determine_exit_code, parse_input_file)
    remain completely intact and backward-compatible.
    """
    from main import determine_exit_code, parse_input_file
    assert determine_exit_code("PASS", enforce=True) == 0
    assert determine_exit_code("FAIL", enforce=True) == 1
    assert determine_exit_code("FAIL", enforce=False) == 0

