import pytest
import pandas as pd
from src.analyzer.failure_analyzer import analyze_failures

def test_missing_required_columns():
    df = pd.DataFrame({'test_name': ['t1'], 'status': ['FAIL']})
    with pytest.raises(ValueError, match="Missing required columns for failure analysis:"):
        analyze_failures(df)

def test_no_failed_tests():
    df = pd.DataFrame({
        'test_name': ['t1', 't2'],
        'module': ['ModA', 'ModB'],
        'status': ['PASS', 'SKIP'],
        'error': [None, None]
    })
    result = analyze_failures(df)
    assert result['total_failures'] == 0
    assert result['most_failed_module'] is None
    assert result['most_common_error'] is None
    assert result['failures_by_module'] == {}
    assert result['error_distribution'] == {}
    assert result['failed_tests'] == []

def test_single_failed_test():
    df = pd.DataFrame({
        'test_name': ['t1'],
        'module': ['ModA'],
        'status': ['FAIL'],
        'error': ['Some Error']
    })
    result = analyze_failures(df)
    assert result['total_failures'] == 1
    assert result['most_failed_module'] == 'ModA'
    assert result['most_common_error'] == 'Some Error'
    assert result['failures_by_module'] == {'ModA': 1}
    assert result['error_distribution'] == {'Some Error': 1}
    assert result['failed_tests'] == ['t1']

def test_multiple_modules_with_failures():
    df = pd.DataFrame({
        'test_name': ['t1', 't2', 't3'],
        'module': ['ModA', 'ModA', 'ModB'],
        'status': ['FAIL', 'FAIL', 'FAIL'],
        'error': ['Err1', 'Err2', 'Err1']
    })
    result = analyze_failures(df)
    assert result['total_failures'] == 3
    assert result['failures_by_module'] == {'ModA': 2, 'ModB': 1}
    assert result['error_distribution'] == {'Err1': 2, 'Err2': 1}
    assert result['failed_tests'] == ['t1', 't2', 't3']
    assert result['most_failed_module'] == 'ModA'
    assert result['most_common_error'] == 'Err1'

def test_tie_breaking():
    df = pd.DataFrame({
        'test_name': ['t1', 't2', 't3', 't4'],
        'module': ['ZZZ', 'ZZZ', 'AAA', 'AAA'],
        'status': ['FAIL', 'FAIL', 'FAIL', 'FAIL'],
        'error': ['Error Z', 'Error A', 'Error Z', 'Error A']
    })
    result = analyze_failures(df)
    # Both modules have 2, 'AAA' should come before 'ZZZ'
    assert list(result['failures_by_module'].keys()) == ['AAA', 'ZZZ']
    assert result['most_failed_module'] == 'AAA'
    # Both errors have 2, 'Error A' should come before 'Error Z'
    assert list(result['error_distribution'].keys()) == ['Error A', 'Error Z']
    assert result['most_common_error'] == 'Error A'

def test_missing_error_values():
    df = pd.DataFrame({
        'test_name': ['t1', 't2', 't3'],
        'module': ['ModA', 'ModB', 'ModC'],
        'status': ['FAIL', 'FAIL', 'FAIL'],
        'error': [None, '', '   ']
    })
    result = analyze_failures(df)
    assert result['total_failures'] == 3
    assert result['error_distribution'] == {'Unknown Error': 3}
    assert result['most_common_error'] == 'Unknown Error'


def test_tied_most_common_errors():
    """Verify tied most common error categories are detected and formatted deterministically."""
    df = pd.DataFrame({
        'test_name': ['t1', 't2', 't3', 't4'],
        'module': ['ModA', 'ModA', 'ModB', 'ModB'],
        'status': ['FAIL', 'FAIL', 'FAIL', 'FAIL'],
        'error': ['TimeoutException', 'Payment API Error', 'TimeoutException', 'Payment API Error']
    })
    result = analyze_failures(df)
    assert result['total_failures'] == 4
    assert result['is_error_tie'] is True
    # Alphabetical order for tied categories with equal count (2 each)
    assert result['most_common_errors'] == ['Payment API Error', 'TimeoutException']
    assert result['most_common_error'] == 'Payment API Error'
    assert result['most_common_error_display'] == 'Payment API Error, TimeoutException (Tie)'


def test_single_winner_most_common_error():
    """Verify single dominant error category has is_error_tie=False and matches display."""
    df = pd.DataFrame({
        'test_name': ['t1', 't2', 't3'],
        'module': ['ModA', 'ModA', 'ModB'],
        'status': ['FAIL', 'FAIL', 'FAIL'],
        'error': ['NetworkError', 'NetworkError', 'TimeoutError']
    })
    result = analyze_failures(df)
    assert result['is_error_tie'] is False
    assert result['most_common_errors'] == ['NetworkError']
    assert result['most_common_error'] == 'NetworkError'
    assert result['most_common_error_display'] == 'NetworkError'
