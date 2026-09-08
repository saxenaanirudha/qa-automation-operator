import os
import pytest
from unittest.mock import patch, MagicMock

from main import determine_exit_code, parse_input_file, write_github_step_summary
from config import load_config



def test_determine_exit_code_pass_enforced():
    assert determine_exit_code("PASS", enforce=True) == 0


def test_determine_exit_code_warning_enforced():
    assert determine_exit_code("WARNING", enforce=True) == 0


def test_determine_exit_code_fail_enforced():
    assert determine_exit_code("FAIL", enforce=True) == 1


def test_determine_exit_code_fail_advisory():
    assert determine_exit_code("FAIL", enforce=False) == 0


def test_parse_input_file_csv_hint(tmp_path):
    csv_content = "test_name,module,status,duration,error,build\ntest_a,Auth,PASS,1.0,,301\n"
    csv_file = tmp_path / "results.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    res = parse_input_file(str(csv_file), format_hint="csv")
    assert res["build"] == 301
    assert res["total"] == 1
    assert res["passed"] == 1


def test_parse_input_file_junit_hint(tmp_path):
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <testsuites>
        <properties>
            <property name="build" value="302"/>
        </properties>
        <testsuite name="Payment">
            <testcase classname="tests.payment.TestCard" name="test_card" time="1.0"/>
        </testsuite>
    </testsuites>"""
    xml_file = tmp_path / "results.xml"
    xml_file.write_text(xml_content, encoding="utf-8")

    res = parse_input_file(str(xml_file), format_hint="junit")
    assert res["build"] == 302
    assert res["total"] == 1
    assert res["passed"] == 1


def test_parse_input_file_auto_detection_xml(tmp_path):
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <testsuite name="Auth">
        <testcase classname="tests.auth.TestLogin" name="test_login" time="0.5"/>
    </testsuite>"""
    xml_file = tmp_path / "results.custom"
    xml_file.write_text(xml_content, encoding="utf-8")

    res = parse_input_file(str(xml_file), build_number=303, format_hint="auto")
    assert res["build"] == 303
    assert res["total"] == 1


def test_parse_input_file_missing_file_raises_error():
    with pytest.raises(FileNotFoundError, match="Input file not found"):
        parse_input_file("non_existent_file.csv")


def test_config_ci_block():
    cfg = load_config()
    assert "ci" in cfg
    assert "enforce_quality_gate" in cfg["ci"]
    assert cfg["ci"]["enforce_quality_gate"] is False



def test_write_github_step_summary(tmp_path, monkeypatch):
    summary_file = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    result = {"build": 501, "pass_rate": 85.0, "failed": 2}
    qg_report = {"status": "WARNING", "release_recommendation": "REVIEW"}
    risk_report = {"high_risk_modules": ["Payment"]}
    flaky_report = {"flaky_tests": ["test_checkout"]}

    write_github_step_summary(result, qg_report, risk_report, flaky_report)

    content = summary_file.read_text(encoding="utf-8")
    assert "QA Automation Operator" in content
    assert "501" in content
    assert "WARNING" in content
    assert "REVIEW" in content
