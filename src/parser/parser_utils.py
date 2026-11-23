"""
Shared Parser Utilities.

Common helpers used across CSV and JUnit XML parsers for summary metrics calculation,
error message truncation, and status normalization.
"""

from typing import Any, Dict, Optional
import pandas as pd

VALID_STATUSES = {"PASS", "FAIL", "SKIP"}


def truncate_error(error_msg: Optional[str], max_length: int = 500) -> Optional[str]:
    """
    Safely truncates long error messages / stack traces to max_length.

    Args:
        error_msg: Error message string.
        max_length: Maximum allowed characters (default 500).

    Returns:
        Truncated error string or None.
    """
    if not error_msg or not isinstance(error_msg, str):
        return None

    cleaned = error_msg.strip()
    if not cleaned:
        return None

    if len(cleaned) > max_length:
        return cleaned[: max_length - 3] + "..."
    return cleaned


def normalize_status(status: Any) -> str:
    """
    Normalizes status string to PASS, FAIL, or SKIP.

    Args:
        status: Raw status input.

    Returns:
        Normalized status string.

    Raises:
        ValueError: If status is not a valid status.
    """
    if not status:
        raise ValueError("Invalid test status found: Empty status")

    norm = str(status).strip().upper()
    if norm not in VALID_STATUSES:
        raise ValueError(f"Invalid test status found: {norm}")
    return norm


def calculate_summary(df: pd.DataFrame, build_number: Optional[int] = None) -> Dict[str, Any]:
    """
    Calculates summary metrics dictionary from a normalized test results DataFrame.

    Args:
        df: Pandas DataFrame with columns [test_name, module, status, duration, error, build].
        build_number: Build number override.

    Returns:
        Summary dict containing data DataFrame, build number, counts, and rates.
    """
    total = len(df)
    if total == 0:
        return {
            "data": df,
            "build": build_number,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "pass_rate": 0.0,
            "failure_rate": 0.0,
        }

    passed = int((df["status"] == "PASS").sum())
    failed = int((df["status"] == "FAIL").sum())
    skipped = int((df["status"] == "SKIP").sum())

    pass_rate = round((passed / total) * 100, 2) if total > 0 else 0.0
    failure_rate = round((failed / total) * 100, 2) if total > 0 else 0.0

    if build_number is None and "build" in df.columns:
        build_val = df["build"].dropna().unique()
        build_number = int(build_val[0]) if len(build_val) > 0 else None

    return {
        "data": df,
        "build": build_number,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": pass_rate,
        "failure_rate": failure_rate,
    }
