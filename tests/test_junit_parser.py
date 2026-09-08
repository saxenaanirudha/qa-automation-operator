import os
import pytest
import xml.etree.ElementTree as ET

from src.parser.junit_parser import (
    parse_junit_xml,
    extract_module_name,
    extract_error_info,
    extract_build_number_from_properties,
)


def test_parse_junit_xml_valid(tmp_path):
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <testsuites>
        <properties>
            <property name="build" value="101"/>
        </properties>
        <testsuite name="Payment">
            <testcase classname="tests.payment.TestCard" name="test_card_payment" time="1.2">
                <failure message="Card declined">Failure stack trace</failure>
            </testcase>
            <testcase classname="tests.payment.TestUPI" name="test_upi_payment" time="0.8"/>
            <testcase classname="tests.payment.TestWallet" name="test_wallet_payment" time="0.5">
                <skipped message="Feature flag off"/>
            </testcase>
        </testsuite>
    </testsuites>
    """
    file_path = tmp_path / "results.xml"
    file_path.write_text(xml_content, encoding="utf-8")

    result = parse_junit_xml(str(file_path))

    assert result["build"] == 101
    assert result["total"] == 3
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert result["skipped"] == 1
    assert round(result["pass_rate"], 2) == 33.33
    assert round(result["failure_rate"], 2) == 33.33

    df = result["data"]
    assert len(df) == 3
    assert "test_name" in df.columns
    assert "module" in df.columns
    assert "status" in df.columns
    assert "duration" in df.columns
    assert "error" in df.columns
    assert "build" in df.columns


def test_parse_junit_xml_build_number_override(tmp_path):
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <testsuite name="Auth">
        <testcase classname="tests.auth.TestLogin" name="test_login" time="1.0"/>
    </testsuite>
    """
    file_path = tmp_path / "results.xml"
    file_path.write_text(xml_content, encoding="utf-8")

    result = parse_junit_xml(str(file_path), build_number=200)
    assert result["build"] == 200
    assert result["total"] == 1
    assert result["passed"] == 1


def test_parse_junit_xml_missing_build_raises_error(tmp_path):
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <testsuite name="Auth">
        <testcase classname="tests.auth.TestLogin" name="test_login" time="1.0"/>
    </testsuite>
    """
    file_path = tmp_path / "results.xml"
    file_path.write_text(xml_content, encoding="utf-8")

    with pytest.raises(ValueError, match="Build number is required"):
        parse_junit_xml(str(file_path))


def test_parse_junit_xml_missing_file():
    with pytest.raises(FileNotFoundError, match="JUnit XML file not found"):
        parse_junit_xml("non_existent_file.xml", build_number=100)


def test_parse_junit_xml_invalid_xml(tmp_path):
    file_path = tmp_path / "invalid.xml"
    file_path.write_text("Not valid XML <tag>", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JUnit XML"):
        parse_junit_xml(str(file_path), build_number=100)


def test_parse_junit_xml_no_testcases(tmp_path):
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
    <testsuites></testsuites>
    """
    file_path = tmp_path / "empty.xml"
    file_path.write_text(xml_content, encoding="utf-8")

    with pytest.raises(ValueError, match="No testcase elements found"):
        parse_junit_xml(str(file_path), build_number=100)


def test_extract_module_name():
    tc1 = ET.Element("testcase", attrib={"classname": "tests.payment.TestCardPayment"})
    assert extract_module_name(tc1) == "CardPayment"

    tc2 = ET.Element("testcase", attrib={"classname": "Checkout"})
    assert extract_module_name(tc2) == "Checkout"

    tc3 = ET.Element("testcase", attrib={})
    assert extract_module_name(tc3, suite_name="TestPayment") == "Payment"

    tc4 = ET.Element("testcase", attrib={})
    assert extract_module_name(tc4) == "Unknown"


def test_extract_error_info():
    tc_fail = ET.Element("testcase")
    fail = ET.SubElement(tc_fail, "failure", attrib={"message": "NullPointer Exception"})
    assert extract_error_info(tc_fail) == "NullPointer Exception"

    tc_err = ET.Element("testcase")
    err = ET.SubElement(tc_err, "error", attrib={"type": "ConnectionRefused"})
    assert extract_error_info(tc_err) == "ConnectionRefused"

    tc_skip = ET.Element("testcase")
    skip = ET.SubElement(tc_skip, "skipped", attrib={"message": "Skipped test"})
    assert extract_error_info(tc_skip) == "Skipped test"

    tc_pass = ET.Element("testcase")
    assert extract_error_info(tc_pass) is None


def test_extract_build_number_from_properties():
    xml_content = """<testsuites>
        <properties>
            <property name="BUILD_NUMBER" value="305"/>
        </properties>
    </testsuites>"""
    root = ET.fromstring(xml_content)
    assert extract_build_number_from_properties(root) == 305

    xml_no_build = "<testsuites></testsuites>"
    root_no_build = ET.fromstring(xml_no_build)
    assert extract_build_number_from_properties(root_no_build) is None
