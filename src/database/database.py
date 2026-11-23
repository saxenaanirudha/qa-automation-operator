import os
from typing import Generator
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///qa_results.db")


def is_sqlite_database(url: str) -> bool:
    """Checks if the given database URL points to a SQLite database."""
    return url.lower().startswith("sqlite")


# Engine creation with pool pre-ping and database-specific connection arguments
engine_kwargs = {"pool_pre_ping": True}

if is_sqlite_database(DATABASE_URL):
    engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}

engine = create_engine(DATABASE_URL, **engine_kwargs)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative base for models
Base = declarative_base()


def init_db() -> None:
    """Initializes the database by creating all tables if they do not exist."""
    Base.metadata.create_all(bind=engine)


def get_session():
    """Returns a new session instance."""
    return SessionLocal()


def get_db() -> Generator:
    """FastAPI database session dependency yielding a session and closing on cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
