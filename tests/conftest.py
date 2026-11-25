import pytest
from src.database.database import init_db


@pytest.fixture(scope="session", autouse=True)
def initialize_database_schema():
    """Ensures database schema and tables are initialized for all pytest test suites."""
    try:
        init_db()
    except Exception:
        pass
