from datetime import datetime, timezone
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TestRun(Base):
    __tablename__ = "test_runs"
    __test__ = False
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|passed|findings|failed|inconclusive
    demo_mode: Mapped[str] = mapped_column(String(20), default="unknown")  # observed metadata only
    total_tests: Mapped[int] = mapped_column(Integer, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, default=0)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    inconclusive_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(String(300), nullable=True)  # generic text only
    results: Mapped[list["TestResult"]] = relationship(back_populates="run", order_by="TestResult.id")


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_case_key: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(20))
    endpoint: Mapped[str] = mapped_column(String(200))
    requesting_tenant_id: Mapped[str] = mapped_column(String(60))
    resource_owner_tenant_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expected_behavior: Mapped[str] = mapped_column(Text)
    actual_behavior: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[dict] = mapped_column(JSON)
    first_detected_run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TestResult(Base):
    __tablename__ = "test_results"
    __test__ = False
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"), index=True)
    test_case_key: Mapped[str] = mapped_column(String(60))
    test_name: Mapped[str] = mapped_column(String(200))
    requesting_tenant_id: Mapped[str] = mapped_column(String(60))
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    endpoint: Mapped[str] = mapped_column(String(200))
    expected_outcome: Mapped[str] = mapped_column(Text)
    actual_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_outcome: Mapped[str] = mapped_column(Text)
    result_status: Mapped[str] = mapped_column(String(20))  # passed|finding|failed|inconclusive
    finding_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id"), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    evidence_json: Mapped[dict] = mapped_column(JSON)
    run: Mapped[TestRun] = relationship(back_populates="results")


class RegressionTest(Base):
    __tablename__ = "regression_tests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    source_finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"))
    test_definition_json: Mapped[dict] = mapped_column(JSON)
    expected_policy: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_result_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Retention policy: deleting a regression test is a SOFT delete. Its retest history is kept.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    runs: Mapped[list["RegressionRun"]] = relationship(back_populates="test", order_by="RegressionRun.id.desc()")


class RegressionRun(Base):
    """Each retest is its own row, so history is never rewritten."""
    __tablename__ = "regression_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    regression_test_id: Mapped[int] = mapped_column(ForeignKey("regression_tests.id"), index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    demo_mode: Mapped[str] = mapped_column(String(20), default="unknown")
    result_status: Mapped[str] = mapped_column(String(20))
    actual_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_outcome: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    evidence_json: Mapped[dict] = mapped_column(JSON)
    test: Mapped[RegressionTest] = relationship(back_populates="runs")


class FindingOccurrence(Base):
    """Append-only log of every detection of a finding (suite run or regression retest).

    Finding.evidence_json / created_at / first_detected_run_id are the ORIGINAL detection and never change.
    """
    __tablename__ = "finding_occurrences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # "suite" | "regression"
    run_id: Mapped[int | None] = mapped_column(ForeignKey("test_runs.id"), nullable=True)
    result_id: Mapped[int | None] = mapped_column(ForeignKey("test_results.id"), nullable=True)
    regression_run_id: Mapped[int | None] = mapped_column(ForeignKey("regression_runs.id"), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    demo_mode: Mapped[str] = mapped_column(String(20), default="unknown")
    evidence_json: Mapped[dict] = mapped_column(JSON)
