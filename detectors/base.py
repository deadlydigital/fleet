"""Detector run lifecycle.

Rules this module exists to enforce, all of them learned the hard way:

  * A SCHEDULED run is opened only by open_scheduled_run(). The window is
    derived by the database from registry geometry; nothing here computes a
    window, and a direct INSERT into detector_runs is rejected by trigger.
  * Every threshold -- cadence, grace, settle_lag, execution_timeout,
    coverage_mode, required_clear_runs -- is read from detector_registry.
    None of them appear as literals in Python.
  * The run is always closed, including on an unhandled exception.
  * observations_created is recomputed at close with
    SELECT count(*) FROM observations WHERE detector_run_id = %s.
    A reclaimed run's in-process counter starts at zero and would
    under-report the work the previous attempt already persisted.
  * A failed query never yields a zero-count observation. Failure is
    recorded as a failed subject, never as an observation of absence.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

import psycopg
from psycopg.rows import dict_row

from . import config

log = logging.getLogger(__name__)

# Advisory-lock namespace for "this process owns this detector run".
# Two-argument form, so it cannot collide with the single-argument
# pg_advisory_xact_lock(detector_run_id) taken inside the cardinality trigger.
RUN_LOCK_NAMESPACE = 0x464C5400  # 'FLT\0'

STATUS_OK = "OK"
STATUS_PARTIAL = "PARTIAL"
STATUS_ERROR = "ERROR"


class RunSkipped(Exception):
    """The slot is not ours to execute; no state was changed."""


@dataclass(frozen=True)
class Registry:
    """A detector_registry row. The only source of thresholds."""

    detector_key: str
    issue_key_version: int
    product: str
    semantics: str
    coverage_mode: str
    cadence: timedelta
    grace: timedelta
    settle_lag: timedelta
    evaluation_window: timedelta
    schedule_epoch: datetime
    required_clear_runs: int
    max_attempts: int
    execution_timeout: timedelta
    max_open_issues: int
    max_observations_per_run: int
    current_detector_version: int
    maintenance_until: datetime | None
    retired_at: datetime | None


@dataclass
class Subject:
    """One enumerable unit of work. label is what lands in the run arrays."""

    subject_type: str
    subject_id: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.subject_type}:{self.subject_id}"


@dataclass
class RunContext:
    fleet: psycopg.Connection
    registry: Registry
    run_id: int
    detector_version: int
    window_start: datetime
    window_end: datetime
    attempt_count: int
    _evaluated: list[str] = field(default_factory=list)
    _failed: list[str] = field(default_factory=list)

    @property
    def subjects_evaluated(self) -> list[str]:
        return list(self._evaluated)

    @property
    def subjects_failed(self) -> list[str]:
        return list(self._failed)

    def mark_evaluated(self, label: str) -> None:
        if label in self._failed:
            return
        if label not in self._evaluated:
            self._evaluated.append(label)

    def mark_failed(self, label: str) -> None:
        # A subject must never appear in both arrays: the coverage predicates
        # read them as a claim about what was actually established.
        if label in self._evaluated:
            self._evaluated.remove(label)
        if label not in self._failed:
            self._failed.append(label)


class Detector:
    """Base class. Subclasses supply enumeration and per-subject evaluation."""

    key: str = ""

    def setup(self, ctx: RunContext) -> None:
        """Acquire resources. Failure here means the run could not proceed."""

    def enumerate_subjects(self, ctx: RunContext) -> Sequence[Subject]:
        raise NotImplementedError

    def evaluate(self, ctx: RunContext, subject: Subject) -> None:
        raise NotImplementedError

    def teardown(self, ctx: RunContext) -> None:
        """Release resources. Runs whatever happened."""

    def on_success(self, ctx: RunContext) -> None:
        """Called after a clean close, never from a finally block."""


def connect_fleet(dsn: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(dsn or config.fleet_dsn(), row_factory=dict_row,
                           application_name="fleet-detector")
    conn.autocommit = True
    return conn


def read_registry(conn: psycopg.Connection, detector_key: str,
                  issue_key_version: int | None = None,
                  product: str | None = None) -> Registry:
    """Resolve exactly one registry row. Thresholds come from here or nowhere."""
    sql = """
        SELECT detector_key, issue_key_version, product, semantics, coverage_mode,
               cadence, grace, settle_lag, evaluation_window, schedule_epoch,
               required_clear_runs, max_attempts, execution_timeout,
               max_open_issues, max_observations_per_run,
               current_detector_version, maintenance_until, retired_at
          FROM detector_registry
         WHERE detector_key = %(k)s
           AND (%(v)s::int  IS NULL OR issue_key_version = %(v)s)
           AND (%(p)s::text IS NULL OR product = %(p)s)
         ORDER BY issue_key_version DESC
    """
    rows = conn.execute(sql, {"k": detector_key, "v": issue_key_version,
                              "p": product}).fetchall()
    live = [r for r in rows if r["retired_at"] is None]
    if not rows:
        raise RuntimeError(f"no detector_registry row for {detector_key}")
    if not live:
        raise RuntimeError(f"detector {detector_key} is retired")
    if len({(r["issue_key_version"], r["product"]) for r in live}) > 1:
        raise RuntimeError(
            f"{detector_key} resolves to multiple registry rows; "
            "pass --issue-key-version and --product")
    return Registry(**live[0])


def _run_row(conn: psycopg.Connection, run_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, status, window_start, window_end, attempt_count,"
        "       detector_version, last_attempt_at, started_at"
        "  FROM detector_runs WHERE id = %s", (run_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"detector_run {run_id} vanished")
    return row


def _observations_created(conn: psycopg.Connection, run_id: int) -> int:
    """The persisted truth. Never an in-process counter."""
    row = conn.execute(
        "SELECT count(*) AS n FROM observations WHERE detector_run_id = %s",
        (run_id,)).fetchone()
    return int(row["n"])


def _close_run(conn: psycopg.Connection, ctx: RunContext, status: str,
               duration_ms: int, error: str | None) -> int:
    created = _observations_created(conn, ctx.run_id)
    conn.execute(
        """
        UPDATE detector_runs
           SET status = %(status)s,
               completed_at = now(),
               duration_ms = %(duration_ms)s,
               subjects_evaluated = %(evaluated)s,
               subjects_failed = %(failed)s,
               observations_created = %(created)s,
               error = %(error)s
         WHERE id = %(id)s
        """,
        {"status": status, "duration_ms": duration_ms,
         "evaluated": ctx.subjects_evaluated,
         "failed": ctx.subjects_failed or None,
         "created": created, "error": error, "id": ctx.run_id},
    )
    return created


@dataclass
class RunResult:
    run_id: int | None
    status: str
    observations_created: int
    subjects_evaluated: list[str]
    subjects_failed: list[str]
    duration_ms: int
    error: str | None = None
    skipped_reason: str | None = None


def execute(detector: Detector, fleet: psycopg.Connection,
            issue_key_version: int | None = None, product: str | None = None,
            slot_end: datetime | None = None) -> RunResult:
    """Open a scheduled run, evaluate, and close it whatever happens."""
    started = time.monotonic()
    registry = read_registry(fleet, detector.key, issue_key_version, product)

    run_id = fleet.execute(
        "SELECT open_scheduled_run(%s, %s, %s, %s) AS id",
        (registry.detector_key, registry.issue_key_version, registry.product,
         slot_end)).fetchone()["id"]

    # open_scheduled_run resolves a conflict to the existing logical run and
    # performs no state transition, so the row we get back may be one another
    # process owns, one already closed, or one abandoned mid-flight.
    locked = fleet.execute("SELECT pg_try_advisory_lock(%s, %s) AS got",
                           (RUN_LOCK_NAMESPACE, run_id)).fetchone()["got"]
    if not locked:
        log.info("run %s is held by another process; skipping", run_id)
        return RunResult(run_id, "SKIPPED", 0, [], [], 0,
                         skipped_reason="held_by_another_process")

    try:
        row = _run_row(fleet, run_id)
        if row["status"] != "RUNNING":
            # The window has already been executed and closed. Re-running it
            # is a no-op by design; the idempotency indexes would reject the
            # observations anyway.
            log.info("run %s for window_end %s is already %s; nothing to do",
                     run_id, row["window_end"], row["status"])
            return RunResult(run_id, "SKIPPED",
                             _observations_created(fleet, run_id), [], [], 0,
                             skipped_reason=f"already_{row['status'].lower()}")

        verdict = fleet.execute("SELECT reclaim_stale_detector_run(%s) AS v",
                                (run_id,)).fetchone()["v"]
        if verdict == "abandoned":
            log.warning("run %s abandoned at max_attempts; not executing", run_id)
            return RunResult(run_id, "SKIPPED",
                             _observations_created(fleet, run_id), [], [], 0,
                             skipped_reason="abandoned")
        if verdict == "reclaimed":
            log.warning("run %s reclaimed from a previous attempt", run_id)
            row = _run_row(fleet, run_id)

        ctx = RunContext(fleet=fleet, registry=registry, run_id=run_id,
                         detector_version=row["detector_version"],
                         window_start=row["window_start"],
                         window_end=row["window_end"],
                         attempt_count=row["attempt_count"])

        status = STATUS_ERROR
        error: str | None = None
        try:
            try:
                detector.setup(ctx)
                subjects = list(detector.enumerate_subjects(ctx))
            except Exception as exc:      # enumeration failed: nothing is known
                status, error = STATUS_ERROR, f"enumeration failed: {exc}"
                log.exception("enumeration failed for %s", detector.key)
            else:
                for subject in subjects:
                    try:
                        detector.evaluate(ctx, subject)
                    except Exception as exc:
                        ctx.mark_failed(subject.label)
                        log.exception("subject %s failed: %s", subject.label, exc)
                    else:
                        ctx.mark_evaluated(subject.label)
                if ctx.subjects_failed:
                    status = STATUS_PARTIAL
                    error = (f"{len(ctx.subjects_failed)} subject(s) failed: "
                             + ",".join(ctx.subjects_failed))
                else:
                    status = STATUS_OK
        except BaseException as exc:      # includes KeyboardInterrupt/SystemExit
            status, error = STATUS_ERROR, f"unhandled: {exc}"
            raise
        finally:
            try:
                detector.teardown(ctx)
            except Exception:
                log.exception("teardown failed for %s", detector.key)
            duration_ms = int((time.monotonic() - started) * 1000)
            created = _close_run(fleet, ctx, status, duration_ms, error)
            log.info("run %s closed status=%s observations=%s evaluated=%s failed=%s",
                     run_id, status, created, len(ctx.subjects_evaluated),
                     len(ctx.subjects_failed))

        result = RunResult(run_id, status, created, ctx.subjects_evaluated,
                           ctx.subjects_failed, duration_ms, error)
        if status == STATUS_OK:
            # Outside the finally block, and only on a clean run. A ping that
            # survives failure is a switch that reports health while broken.
            detector.on_success(ctx)
        return result
    finally:
        fleet.execute("SELECT pg_advisory_unlock(%s, %s)",
                      (RUN_LOCK_NAMESPACE, run_id))
