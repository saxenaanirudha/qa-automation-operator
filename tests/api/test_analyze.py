import io
import time
import pytest
from fastapi.testclient import TestClient
from src.api.app import app

client = TestClient(app)


def test_analyze_csv_upload():
    build_num = int(time.time_ns() % 1000000) + 10000
    csv_content = (
        f"test_name,module,status,duration,error,build\n"
        f"test_auth,Auth,PASS,1.2,,{build_num}\n"
        f"test_pay,Payment,FAIL,2.1,Timeout,{build_num}\n"
    )
    files = {"file": ("test_results.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    response = client.post("/analyze", files=files, data={"format": "csv"})

    assert response.status_code == 200
    data = response.json()
    assert data["build"] == build_num
    assert data["summary"]["total"] == 2
    assert data["summary"]["passed"] == 1
    assert data["summary"]["failed"] == 1
    assert "quality_gate" in data


def test_analyze_junit_xml_upload():
    build_num = int(time.time_ns() % 1000000) + 20000
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
    <testsuites>
        <properties>
            <property name="build" value="{build_num}"/>
        </properties>
        <testsuite name="Payment">
            <testcase classname="tests.payment.TestCard" name="test_card_payment" time="1.0"/>
            <testcase classname="tests.payment.TestUPI" name="test_upi_payment" time="0.5"/>
        </testsuite>
    </testsuites>"""
    files = {"file": ("results.xml", io.BytesIO(xml_content.encode("utf-8")), "application/xml")}
    response = client.post("/analyze", files=files, data={"format": "junit"})

    assert response.status_code == 200
    data = response.json()
    assert data["build"] == build_num
    assert data["summary"]["total"] == 2
    assert data["summary"]["passed"] == 2


def test_analyze_duplicate_build_conflict():
    build_num = int(time.time_ns() % 1000000) + 30000
    csv_content = (
        f"test_name,module,status,duration,error,build\n"
        f"test_auth,Auth,PASS,1.2,,{build_num}\n"
    )
    files1 = {"file": ("test_results.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    res1 = client.post("/analyze", files=files1, data={"format": "csv"})
    assert res1.status_code == 200

    files2 = {"file": ("test_results.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    res2 = client.post("/analyze", files=files2, data={"format": "csv"})
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"]


def test_analyze_unsupported_file_format():
    files = {"file": ("script.py", io.BytesIO(b"print('hello')"), "text/plain")}
    response = client.post("/analyze", files=files, data={"format": "txt"})

    assert response.status_code == 400
    assert "Unsupported file format" in response.json()["detail"]
