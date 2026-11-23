"""
CSV Test Log Parser Module.

Parses CSV files containing test execution logs and converts them into the
project's normalized internal data structure.
"""

import os
from typing import Any, Dict
import pandas as pd

from src.parser.parser_utils import calculate_summary, VALID_STATUSES

REQUIRED_COLUMNS = {"test_name", "module", "status", "duration", "error", "build"}


def parse_csv(file_path: str) -> Dict[str, Any]:
    """
    Parses a CSV file containing test results and returns a summary.

    Args:
        file_path: Path to the CSV file.

    Returns:
        Dictionary containing parsed data, counts, and rates.

    Raises:
        FileNotFoundError: If the CSV file does not exist.
        ValueError: If required columns are missing or invalid statuses are found.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Test result file not found: {file_path}")

    try:
        df = pd.read_csv(file_path)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=list(REQUIRED_COLUMNS))

    if df.empty and list(df.columns) == []:
        df = pd.DataFrame(columns=list(REQUIRED_COLUMNS))

    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_columns))}")

    if df.empty:
        return calculate_summary(df, build_number=None)

    df["status"] = df["status"].astype(str).str.strip().str.upper()

    invalid_statuses = set(df["status"]) - VALID_STATUSES
    if invalid_statuses:
        raise ValueError(f"Invalid test status found: {', '.join(invalid_statuses)}")

    return calculate_summary(df)
