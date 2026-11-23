from typing import Generator
from sqlalchemy.orm import Session
from src.database.database import get_db


def get_db_session() -> Generator[Session, None, None]:
    """Dependency for providing a SQLAlchemy database session to FastAPI route handlers."""
    yield from get_db()
