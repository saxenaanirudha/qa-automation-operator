import os
import tempfile
import pytest
from src.parser.csv_parser import parse_csv
from src.parser.junit_parser import parse_junit_xml


def test_csv_and_junit_parser_equivalence():
    """
    Step 17 Parser Equivalence Test:
    Verifies that equivalent test result representations in CSV and JUnit XML format
    produce functionally identical normalized schemas (test_name, module, status, duration, error, build).
    """
    # 1. Create CSV file for Build 999
    csv_content = (
        "test_name,module,status,duration,error,build\n"
        "tests.auth.TestAuth.test_login,Auth,PASS,1.5,,999\n"
        "tests.payment.TestPayment.test_payment_card,Payment,FAIL,2.3,TimeoutError,999\n"
    )

    # 2. Create equivalent JUnit XML file for Build 999
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <testsuites>
        <properties>
            <property name="build" value="999"/>
        </properties>
        <testsuite name="Auth">
            <testcase classname="tests.auth.TestAuth" name="test_login" time="1.5"/>
        </testsuite>
        <testsuite name="Payment">
            <testcase classname="tests.payment.TestPayment" name="test_payment_card" time="2.3">
                <failure message="TimeoutError" type="TimeoutError">Connection timed out</failure>
            </testcase>
        </testsuite>
    </testsuites>"""

    with tempfile.TemporaryDirectory() as temp_dir:
        csv_path = os.path.join(temp_dir, "results.csv")
        xml_path = os.path.join(temp_dir, "results.xml")

        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(csv_content)

        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(xml_content)

        # Parse both formats
        csv_res = parse_csv(csv_path)
        xml_res = parse_junit_xml(xml_path)

        # Compare top-level summary metrics
        assert csv_res["build"] == xml_res["build"] == 999
        assert csv_res["total"] == xml_res["total"] == 2
        assert csv_res["passed"] == xml_res["passed"] == 1
        assert csv_res["failed"] == xml_res["failed"] == 1
        assert csv_res["pass_rate"] == xml_res["pass_rate"] == 50.0

        # Compare normalized DataFrame columns
        csv_df = csv_res["data"].sort_values(by="test_name").reset_index(drop=True)
        xml_df = xml_res["data"].sort_values(by="test_name").reset_index(drop=True)

        for col in ["test_name", "module", "status", "duration", "build"]:
            assert list(csv_df[col]) == list(xml_df[col])

        # Verify error extraction mapping
        assert csv_df.loc[csv_df["status"] == "FAIL", "error"].values[0] == "TimeoutError"
        assert "TimeoutError" in str(xml_df.loc[xml_df["status"] == "FAIL", "error"].values[0])
