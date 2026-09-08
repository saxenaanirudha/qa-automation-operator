import os
import tempfile
import pytest
from src.parser.result_parser import parse_test_results


def test_parse_test_results_csv_explicit():
    csv_content = "test_name,module,status,duration,error,build\ntest_a,M1,PASS,1.0,,10\n"
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        f.write(csv_content)
        temp_path = f.name

    try:
        res = parse_test_results(temp_path, input_format="csv")
        assert res["build"] == 10
        assert res["total"] == 1
    finally:
        os.remove(temp_path)


def test_parse_test_results_xml_explicit():
    xml_content = '<testsuite name="M1"><testcase classname="C" name="T" time="1.0"/></testsuite>'
    with tempfile.NamedTemporaryFile(suffix=".xml", mode="w", delete=False) as f:
        f.write(xml_content)
        temp_path = f.name

    try:
        res = parse_test_results(temp_path, build_number=20, input_format="junit")
        assert res["build"] == 20
        assert res["total"] == 1
    finally:
        os.remove(temp_path)


def test_parse_test_results_auto_detect():
    csv_content = "test_name,module,status,duration,error,build\ntest_a,M1,PASS,1.0,,30\n"
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
        f.write(csv_content)
        temp_path = f.name

    try:
        res = parse_test_results(temp_path)
        assert res["build"] == 30
    finally:
        os.remove(temp_path)


def test_parse_test_results_invalid_format_raises_error():
    with pytest.raises(ValueError, match="Unsupported format"):
        parse_test_results("dummy.txt", input_format="invalid_fmt")
