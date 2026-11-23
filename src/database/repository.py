import pandas as pd
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from src.database.database import get_session
from src.database.models import Build, TestResult

class DuplicateBuildError(Exception):
    """Exception raised when trying to save a build that already exists."""
    pass

class BuildNotFoundError(Exception):
    """Exception raised when a requested build does not exist in the database."""
    pass

def save_build_result(summary: Dict[str, Any], df: pd.DataFrame, session: Optional[Session] = None) -> Build:
    """
    Saves a build summary and its test results to the database.
    
    Args:
        summary: Dictionary with build summary metrics.
        df: Pandas DataFrame with test result rows.
        session: Optional SQLAlchemy session. If not provided, a new one will be created and closed.
        
    Returns:
        The created Build model instance.
        
    Raises:
        DuplicateBuildError: If the build number already exists in the database.
        Exception: Re-raises any database/other exception after rollback.
    """
    build_num = summary.get("build")
    if build_num is None:
        raise ValueError("Build summary must contain a build number.")
    
    own_session = False
    if session is None:
        session = get_session()
        own_session = True

    try:
        # Check for duplicate build
        existing_build = session.query(Build).filter(Build.build_number == build_num).first()
        if existing_build:
            raise DuplicateBuildError(f"Build {build_num} already exists in database.")

        # Create Build record
        build = Build(
            build_number=build_num,
            total_tests=summary["total"],
            passed=summary["passed"],
            failed=summary["failed"],
            skipped=summary["skipped"],
            pass_rate=summary["pass_rate"],
            failure_rate=summary["failure_rate"]
        )
        session.add(build)
        # Flush to get the build ID
        session.flush()

        # Create TestResult records
        test_results = []
        for _, row in df.iterrows():
            error_val = row.get("error")
            # Convert empty string/spaces/NaN to None
            if pd.isna(error_val) or (isinstance(error_val, str) and not error_val.strip()):
                error_val = None
            else:
                error_val = str(error_val)

            test_result = TestResult(
                build_id=build.id,
                test_name=row["test_name"],
                module=row["module"],
                status=row["status"],
                duration=float(row["duration"]),
                error=error_val
            )
            test_results.append(test_result)
        
        session.add_all(test_results)
        session.commit()
        # Refresh to load attributes
        session.refresh(build)
        return build
    except IntegrityError as e:
        session.rollback()
        raise DuplicateBuildError(f"Build {build_num} already exists in database.") from e
    except Exception as e:
        session.rollback()
        raise e
    finally:
        if own_session:
            session.close()

def get_build_by_number(build_number: int, session: Optional[Session] = None) -> Optional[Build]:
    """
    Retrieves a Build record by its build number.
    
    Args:
        build_number: The build number to search.
        session: Optional SQLAlchemy session.
    """
    own_session = False
    if session is None:
        session = get_session()
        own_session = True

    try:
        return session.query(Build).filter(Build.build_number == build_number).first()
    finally:
        if own_session:
            session.close()

def get_all_builds(session: Optional[Session] = None) -> List[Build]:
    """
    Retrieves all Build records ordered from newest to oldest (by build_number desc).
    
    Args:
        session: Optional SQLAlchemy session.
    """
    own_session = False
    if session is None:
        session = get_session()
        own_session = True

    try:
        return session.query(Build).order_by(Build.build_number.desc()).all()
    finally:
        if own_session:
            session.close()

def get_test_results_for_build(build_number: int, session: Optional[Session] = None) -> List[TestResult]:
    """
    Retrieves all TestResult rows for a given build number.

    Args:
        build_number: The build number to fetch test results for.
        session: Optional SQLAlchemy session.

    Returns:
        List of TestResult instances (empty list if build has no results).

    Raises:
        BuildNotFoundError: If the build does not exist in the database.
    """
    own_session = False
    if session is None:
        session = get_session()
        own_session = True

    try:
        build = session.query(Build).filter(Build.build_number == build_number).first()
        if build is None:
            raise BuildNotFoundError(f"Build {build_number} not found in database.")
        return list(build.test_results)
    finally:
        if own_session:
            session.close()

def get_previous_build(current_build_number: int, session: Optional[Session] = None) -> Optional[Build]:
    """
    Finds the most recent stored build with a build_number strictly less than current_build_number.

    Does NOT assume sequential build numbers — queries the actual stored history.

    Args:
        current_build_number: The reference build number.
        session: Optional SQLAlchemy session.

    Returns:
        The preceding Build instance, or None if no earlier build exists.
    """
    own_session = False
    if session is None:
        session = get_session()
        own_session = True

    try:
        return (
            session.query(Build)
            .filter(Build.build_number < current_build_number)
            .order_by(Build.build_number.desc())
            .first()
        )
    finally:
        if own_session:
            session.close()

def get_latest_builds(limit: int, session: Optional[Session] = None) -> List[Build]:
    """
    Returns the most recent ``limit`` builds ordered from newest to oldest.

    The caller is responsible for reversing the list if oldest-to-newest
    order is required (e.g. for trend analysis).

    Args:
        limit: Maximum number of builds to return.
        session: Optional SQLAlchemy session.

    Returns:
        List of Build instances, newest first.
    """
    own_session = False
    if session is None:
        session = get_session()
        own_session = True

    try:
        return (
            session.query(Build)
            .order_by(Build.build_number.desc())
            .limit(limit)
            .all()
        )
    finally:
        if own_session:
            session.close()


def get_test_results_for_latest_builds(
    limit: int, session: Optional[Session] = None
) -> Dict[int, List[TestResult]]:
    """
    Retrieves test results for the latest ``limit`` builds.

    Args:
        limit: Maximum number of recent builds to fetch.
        session: Optional SQLAlchemy session.

    Returns:
        Dict mapping build_number → list of TestResult rows.
    """
    recent_builds = get_latest_builds(limit, session=session)
    builds = list(reversed(recent_builds))

    result: Dict[int, List[TestResult]] = {}
    for build in builds:
        result[build.build_number] = get_test_results_for_build(
            build.build_number, session=session
        )
    return result

