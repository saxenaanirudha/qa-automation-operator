import pytest
from sqlalchemy.exc import OperationalError
from src.database.database import init_db, is_sqlite_database, DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
def initialize_database_schema():
    """
    Ensures database schema and tables are initialized for all pytest test suites.

    Only tolerates connection failure when an external PostgreSQL instance is unreachable,
    allowing test_postgres_integration.py to mark integration tests as skipped.
    Genuine SQLite defects and unexpected schema errors will raise immediately.
    """
    try:
        init_db()
    except OperationalError as exc:
        if not is_sqlite_database(DATABASE_URL):
            return
        raise exc
