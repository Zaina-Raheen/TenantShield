"""Small, idempotent, non-destructive schema migrations (additive columns/tables + backfill).

No data is ever dropped. Safe to run on every startup, on fresh and on pre-existing databases.
"""
import logging

from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

from .db import Base

log = logging.getLogger("tenantshield")
SCHEMA_VERSION = 2  # 1 = original schema, 2 = occurrences + soft delete + run error_summary


def _add_column(conn, table: str, column: str, ddl: str) -> None:
    if column not in {c["name"] for c in inspect(conn).get_columns(table)}:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _backfill_occurrences(engine: Engine) -> None:
    from .models import Finding, FindingOccurrence, RegressionRun, RegressionTest, TestResult, TestRun, utcnow

    with Session(engine) as db:
        for res in db.query(TestResult).filter(TestResult.finding_id.isnot(None), TestResult.result_status == "finding"):
            if db.query(FindingOccurrence.id).filter_by(result_id=res.id).first():
                continue
            run = db.get(TestRun, res.run_id)
            db.add(FindingOccurrence(finding_id=res.finding_id, source="suite", run_id=res.run_id, result_id=res.id,
                                     detected_at=run.started_at if run else utcnow(),
                                     demo_mode=run.demo_mode if run else "unknown", evidence_json=res.evidence_json))
        for rr in db.query(RegressionRun).filter_by(result_status="finding"):
            if db.query(FindingOccurrence.id).filter_by(regression_run_id=rr.id).first():
                continue
            test = db.get(RegressionTest, rr.regression_test_id)
            if test is None or db.get(Finding, test.source_finding_id) is None:
                continue
            db.add(FindingOccurrence(finding_id=test.source_finding_id, source="regression", regression_run_id=rr.id,
                                     detected_at=rr.run_at, demo_mode=rr.demo_mode, evidence_json=rr.evidence_json))
        db.commit()


def migrate(engine: Engine) -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)  # additive: creates only missing tables
    with engine.begin() as conn:
        _add_column(conn, "test_runs", "error_summary", "VARCHAR(300)")
        _add_column(conn, "regression_tests", "deleted_at", "DATETIME")
        if engine.dialect.name == "sqlite":
            conn.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")
    _backfill_occurrences(engine)
