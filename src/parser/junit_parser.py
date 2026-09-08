"""
JUnit XML Parser Module.

Parses JUnit XML test execution files (single suite, multiple suites, nested suites)
and converts them into the project's normalized internal data structure.

Features:
    - Standard XML parsing using xml.etree.ElementTree
    - Automatic testcase status mapping: PASS, FAIL, SKIP
    - Module extraction from classname or parent testsuite name
    - Duration parsing with safe numeric fallback (0.0)
    - Error message extraction & truncation
    - Build number resolution from function arguments or XML properties
    - Normalization compatibility with CSV parser output
"""

import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
import pandas as pd

from config import get_parser_config
from src.parser.parser_utils import calculate_summary, truncate_error


# ---------------------------------------------------------------------------
# Module Name Extraction Helper
# ---------------------------------------------------------------------------

def extract_module_name(testcase: ET.Element, suite_name: Optional[str] = None) -> str:
    """
    Extracts a normalized module name from a JUnit testcase or testsuite.

    Precedence:
        1. Explicit testcase `classname` attribute (e.g. tests.payment.TestPayment -> Payment)
        2. Parent testsuite `name` attribute
        3. "Unknown"

    Args:
        testcase: XML Element representing <testcase>.
        suite_name: Optional parent suite name string.

    Returns:
        Non-empty normalized module string.
    """
    classname = testcase.get("classname", "").strip()

    if classname:
        parts = [p for p in classname.split(".") if p]
        if parts:
            last_part = parts[-1]
            # Strip common 'Test' or 'Tests' prefixes
            if last_part.startswith("Test") and len(last_part) > 4:
                return last_part[4:]
            if last_part.startswith("Tests") and len(last_part) > 5:
                return last_part[5:]
            if len(parts) >= 2 and parts[-2].lower() != "tests":
                # Use subpackage name (e.g. tests.payment.TestPayment -> payment -> Payment)
                return parts[-2].capitalize()
            return last_part.capitalize()

    if suite_name and suite_name.strip():
        clean_suite = suite_name.strip()
        if clean_suite.startswith("Test") and len(clean_suite) > 4:
            return clean_suite[4:]
        return clean_suite.capitalize()

    return "Unknown"


# ---------------------------------------------------------------------------
# Error Message Extraction Helper
# ---------------------------------------------------------------------------

def extract_error_info(testcase: ET.Element, max_len: int = 500) -> Optional[str]:
    """
    Extracts a concise error or skip message from a failed/skipped testcase.

    Args:
        testcase: XML Element for <testcase>.
        max_len: Maximum length for error truncation.

    Returns:
        Truncated error message string or None.
    """
    # Check failure or error tags
    fail_elem = testcase.find("failure")
    if fail_elem is None:
        fail_elem = testcase.find("error")

    if fail_elem is not None:
        msg = fail_elem.get("message")
        if not msg or not msg.strip():
            msg = fail_elem.get("type")
        if not msg or not msg.strip():
            msg = fail_elem.text
        if not msg or not msg.strip():
            msg = "Unknown Error"
        return truncate_error(msg, max_length=max_len)

    # Check skipped tag
    skip_elem = testcase.find("skipped")
    if skip_elem is not None:
        msg = skip_elem.get("message")
        if not msg or not msg.strip():
            msg = skip_elem.text
        if not msg or not msg.strip():
            msg = "Test skipped"
        return truncate_error(msg, max_length=max_len)

    return None


# ---------------------------------------------------------------------------
# Build Number XML Property Extraction
# ---------------------------------------------------------------------------

def extract_build_number_from_properties(root: ET.Element) -> Optional[int]:
    """
    Searches XML <property> tags for build number properties.

    Args:
        root: Root XML element.

    Returns:
        Build number integer or None.
    """
    cfg = get_parser_config()
    prop_names = cfg.get("junit", {}).get(
        "build_properties", ["build", "build_number", "BUILD_NUMBER"]
    )

    for prop in root.findall(".//property"):
        name = prop.get("name", "").strip()
        val = prop.get("value", "").strip()
        if name in prop_names and val:
            try:
                return int(val)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Parent Suite Discovery Helper
# ---------------------------------------------------------------------------

def _find_parent_suite_name(root: ET.Element, testcase: ET.Element) -> Optional[str]:
    """Finds the nearest parent <testsuite> name attribute for a given <testcase>."""
    # Walk tree using parent mapping
    parent_map = {c: p for p in root.iter() for c in p}
    curr = testcase
    while curr in parent_map:
        curr = parent_map[curr]
        if curr.tag == "testsuite" and curr.get("name"):
            return curr.get("name")
    return None


# ---------------------------------------------------------------------------
# Core JUnit XML Parser
# ---------------------------------------------------------------------------

def parse_junit_xml(
    file_path: str,
    build_number: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Parses a JUnit XML test execution file into a normalized summary dictionary.

    Args:
        file_path: Path to the JUnit XML file.
        build_number: Optional build number override.

    Returns:
        Summary dict containing data DataFrame, build number, counts, and rates.

    Raises:
        FileNotFoundError: If the XML file does not exist.
        ValueError: If XML is invalid, missing testcases, missing names, or missing build number.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"JUnit XML file not found: {file_path}")

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except ET.ParseError:
        raise ValueError("Invalid JUnit XML: unable to parse document.")
    except Exception as exc:
        raise ValueError(f"Invalid JUnit XML: {exc}")

    # Resolve build number
    resolved_build = build_number
    if resolved_build is None:
        resolved_build = extract_build_number_from_properties(root)

    if resolved_build is None:
        raise ValueError("Build number is required for JUnit XML input.")

    # Discover all <testcase> elements recursively
    testcases = root.findall(".//testcase")
    if not testcases:
        raise ValueError("No testcase elements found in JUnit XML.")

    cfg = get_parser_config()
    max_err_len = int(cfg.get("max_error_length", 500))

    rows: List[Dict[str, Any]] = []

    for tc in testcases:
        raw_name = tc.get("name")
        if not raw_name or not raw_name.strip():
            raise ValueError("JUnit testcase is missing required name attribute.")
        raw_name = raw_name.strip()

        classname = tc.get("classname", "").strip()
        if classname and not raw_name.startswith(classname):
            name = f"{classname}.{raw_name}"
        else:
            name = raw_name

        suite_name = _find_parent_suite_name(root, tc)

        module = extract_module_name(tc, suite_name)

        # Status mapping
        if tc.find("failure") is not None or tc.find("error") is not None:
            status = "FAIL"
        elif tc.find("skipped") is not None:
            status = "SKIP"
        else:
            status = "PASS"

        # Duration mapping
        time_str = tc.get("time")
        try:
            duration = float(time_str) if time_str is not None else 0.0
        except ValueError:
            duration = 0.0

        # Error extraction
        error_msg = extract_error_info(tc, max_len=max_err_len)

        rows.append(
            {
                "test_name": name,
                "module": module,
                "status": status,
                "duration": duration,
                "error": error_msg,
                "build": resolved_build,
            }
        )

    df = pd.DataFrame(rows)
    return calculate_summary(df, build_number=resolved_build)
