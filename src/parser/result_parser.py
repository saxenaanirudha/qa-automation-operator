"""
Result Parser Dispatcher Module.

Provides a unified input entrypoint `parse_test_results()` that automatically
detects or explicitly accepts file format (.csv, .xml/junit) and routes execution
to the appropriate parser.
"""

import os
from typing import Any, Dict, Optional

from src.parser.csv_parser import parse_csv
from src.parser.junit_parser import parse_junit_xml

JUNIT_ALIASES = {"junit", "xml", "junit_xml"}


def parse_test_results(
    file_path: str,
    build_number: Optional[int] = None,
    input_format: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parses a test result file (CSV or JUnit XML) into a normalized summary dictionary.

    Args:
        file_path: Path to the test result file.
        build_number: Optional build number override (required for JUnit XML if missing in XML).
        input_format: Optional explicit format override ('csv', 'junit', 'xml', 'junit_xml').

    Returns:
        Summary dict containing normalized data DataFrame, counts, rates, and build number.

    Raises:
        FileNotFoundError: If file_path does not exist.
        ValueError: If format is unsupported or file contents are invalid.
    """
    if input_format:
        fmt = str(input_format).strip().lower()
        if fmt == "csv":
            return parse_csv(file_path)
        if fmt in JUNIT_ALIASES:
            return parse_junit_xml(file_path, build_number=build_number)
        raise ValueError(f"Unsupported format: {input_format}")

    # Automatic format detection based on file extension
    _, ext = os.path.splitext(file_path)
    ext_clean = ext.strip().lower()

    if ext_clean == ".csv":
        return parse_csv(file_path)
    if ext_clean == ".xml":
        return parse_junit_xml(file_path, build_number=build_number)

    raise ValueError(f"Unsupported test result format: {ext}")
