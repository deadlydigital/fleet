"""Shared helpers. Nothing here decides anything a test should assert."""
from __future__ import annotations

from datetime import datetime

from detectors import base
from detectors.reconciliation import ReconciliationDetector


def settled_slots(conn, count: int = 4, cadence: str = "1 hour",
                  settle_lag: str = "15 minutes") -> list[datetime]:
    """On-grid, already-settled slot ends, newest first."""
    rows = conn.execute(
        """
        SELECT date_trunc('hour', now() - %(lag)s::interval)
               - (i * %(cad)s::interval) AS slot
          FROM generate_series(0, %(n)s - 1) AS i
        """,
        {"lag": settle_lag, "cad": cadence, "n": count}).fetchall()
    return [r["slot"] for r in rows]


def heartbeat_slots(conn, count: int = 4) -> list[datetime]:
    rows = conn.execute(
        """
        SELECT date_trunc('hour', now())
               + (floor(extract(minute FROM now()) / 5) * interval '5 minutes')
               - (i * interval '5 minutes') AS slot
          FROM generate_series(0, %(n)s - 1) AS i
        """, {"n": count}).fetchall()
    return [r["slot"] for r in rows]


def run_reconciliation(fleet, dd_dsn: str, slot_end: datetime | None = None):
    return base.execute(ReconciliationDetector(dd_dsn), fleet, slot_end=slot_end)


def observations(conn, run_id: int | None = None,
                 observation_type: str | None = None,
                 subject_id: str | None = None) -> list[dict]:
    return conn.execute(
        """
        SELECT * FROM observations
         WHERE (%(run)s::bigint IS NULL OR detector_run_id = %(run)s)
           AND (%(type)s::text  IS NULL OR observation_type = %(type)s)
           AND (%(subj)s::text  IS NULL OR subject_id = %(subj)s)
         ORDER BY id
        """,
        {"run": run_id, "type": observation_type, "subj": subject_id}).fetchall()


def run_row(conn, run_id: int) -> dict:
    return conn.execute("SELECT * FROM detector_runs WHERE id = %s",
                        (run_id,)).fetchone()


def issue(conn, fingerprint: str) -> dict | None:
    return conn.execute("SELECT * FROM issues WHERE fingerprint = %s",
                        (fingerprint,)).fetchone()
