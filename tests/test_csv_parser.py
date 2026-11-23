import os
import pytest
import pandas as pd
from src.parser.csv_parser import parse_csv

def test_valid_csv(tmp_path):
    csv_content = """test_name,module,status,duration,error,build
test_1,ModA,PASS,1.0,,100
test_2,ModA,FAIL,2.0,Err,100
test_3,ModB,SKIP,0.0,,100"""
    file_path = tmp_path / "valid.csv"
    file_path.write_text(csv_content)
    
    result = parse_csv(str(file_path))
    
    assert result["total"] == 3
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert result["skipped"] == 1
    assert result["pass_rate"] == 33.33
    assert result["failure_rate"] == 33.33
    assert result["build"] == 100
    assert isinstance(result["data"], pd.DataFrame)

def test_file_not_found():
    with pytest.raises(FileNotFoundError, match="Test result file not found:"):
        parse_csv("non_existent_file.csv")

def test_missing_required_columns(tmp_path):
    csv_content = """test_name,status,duration\ntest_1,PASS,1.0"""
    file_path = tmp_path / "missing.csv"
    file_path.write_text(csv_content)
    
    with pytest.raises(ValueError, match="Missing required columns:"):
        parse_csv(str(file_path))

def test_invalid_status(tmp_path):
    csv_content = """test_name,module,status,duration,error,build
test_1,ModA,PASS,1.0,,100
test_2,ModA,ERROR,2.0,Err,100"""
    file_path = tmp_path / "invalid.csv"
    file_path.write_text(csv_content)
    
    with pytest.raises(ValueError, match="Invalid test status found: ERROR"):
        parse_csv(str(file_path))

def test_status_normalization(tmp_path):
    csv_content = """test_name,module,status,duration,error,build
test_1,ModA, pass ,1.0,,100
test_2,ModA,fAil,2.0,Err,100
test_3,ModA, SKIP,0.0,,100"""
    file_path = tmp_path / "mixed_case.csv"
    file_path.write_text(csv_content)
    
    result = parse_csv(str(file_path))
    assert result["passed"] == 1
    assert result["failed"] == 1
    assert result["skipped"] == 1

def test_empty_csv(tmp_path):
    csv_content = """test_name,module,status,duration,error,build\n"""
    file_path = tmp_path / "empty.csv"
    file_path.write_text(csv_content)
    
    result = parse_csv(str(file_path))
    
    assert result["total"] == 0
    assert result["passed"] == 0
    assert result["failed"] == 0
    assert result["skipped"] == 0
    assert result["pass_rate"] == 0.0
    assert result["failure_rate"] == 0.0
