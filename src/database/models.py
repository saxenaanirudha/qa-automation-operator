from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.database.database import Base


class Build(Base):
    __tablename__ = "builds"

    id = Column(Integer, primary_key=True, index=True)
    build_number = Column(Integer, unique=True, nullable=False, index=True)
    total_tests = Column(Integer, nullable=False)
    passed = Column(Integer, nullable=False)
    failed = Column(Integer, nullable=False)
    skipped = Column(Integer, nullable=False)
    pass_rate = Column(Float, nullable=False)
    failure_rate = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship to test results
    test_results = relationship("TestResult", back_populates="build", cascade="all, delete-orphan")


class TestResult(Base):
    __tablename__ = "test_results"
    __test__ = False

    id = Column(Integer, primary_key=True, index=True)
    build_id = Column(Integer, ForeignKey("builds.id", ondelete="CASCADE"), nullable=False, index=True)
    test_name = Column(String, nullable=False, index=True)
    module = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, index=True)
    duration = Column(Float, nullable=False)
    error = Column(String, nullable=True)

    # Relationship to build
    build = relationship("Build", back_populates="test_results")
