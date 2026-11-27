import pandas as pd
from typing import Dict, Any

REQUIRED_COLUMNS = {'test_name', 'module', 'status', 'error'}

def analyze_failures(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyzes failed tests from the parsed test DataFrame.

    Args:
        df: Pandas DataFrame containing parsed test results.

    Returns:
        Dictionary containing failure metrics and distributions.

    Raises:
        ValueError: If required columns for analysis are missing.
    """
    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns for failure analysis: {', '.join(sorted(missing_columns))}")

    default_result = {
        "total_failures": 0,
        "failures_by_module": {},
        "error_distribution": {},
        "failed_tests": [],
        "most_failed_module": None,
        "most_common_error": None
    }

    if df.empty:
        return default_result

    # Filter for failed tests
    failed_df = df[df['status'] == 'FAIL'].copy()

    if failed_df.empty:
        return default_result

    # Handle missing/empty error values
    failed_df['error'] = failed_df['error'].fillna('Unknown Error')
    failed_df.loc[failed_df['error'].astype(str).str.strip() == '', 'error'] = 'Unknown Error'

    # Calculate failures by module with tie-breaking
    module_counts = failed_df.groupby('module').size().reset_index(name='count')
    module_counts = module_counts.sort_values(by=['count', 'module'], ascending=[False, True])
    failures_by_module = dict(zip(module_counts['module'], module_counts['count']))
    most_failed_module = module_counts.iloc[0]['module'] if not module_counts.empty else None

    # Calculate error distribution with deterministic tie-breaking (count desc, error asc)
    error_counts = failed_df.groupby('error').size().reset_index(name='count')
    error_counts = error_counts.sort_values(by=['count', 'error'], ascending=[False, True])
    error_distribution = dict(zip(error_counts['error'], error_counts['count']))

    # Identify tied most common errors
    max_error_count = int(error_counts['count'].max()) if not error_counts.empty else 0
    top_errors = error_counts[error_counts['count'] == max_error_count]['error'].tolist() if max_error_count > 0 else []
    is_error_tie = len(top_errors) > 1
    most_common_error = top_errors[0] if top_errors else None
    most_common_error_display = f"{', '.join(top_errors)} (Tie)" if is_error_tie else most_common_error

    # Failed tests list
    failed_tests = failed_df['test_name'].tolist()

    return {
        "total_failures": len(failed_df),
        "failures_by_module": failures_by_module,
        "error_distribution": error_distribution,
        "failed_tests": failed_tests,
        "most_failed_module": most_failed_module,
        "most_common_error": most_common_error,
        "most_common_errors": top_errors,
        "is_error_tie": is_error_tie,
        "most_common_error_display": most_common_error_display,
    }
