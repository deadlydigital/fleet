"""dd_analytics_reconciliation.

Compares public.orders against analytics_<tenant_id>.orders inside
deadly_digital. One connection, one read-only REPEATABLE READ transaction,
one snapshot -- so every tenant and every invariant is judged against the
same instant, and a sync that lands mid-run cannot manufacture a difference
that never existed.

Whole population, never windowed: created_at in public.orders starts at
2026-08-18 because of a table rebuild, so a window on it would never see the
gap that is already there.

Read-only by role as well as by construction. This process cannot write to
deadly_digital, and that is the point.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Sequence

import psycopg
from psycopg.rows import dict_row

from . import config, sqlfile
from .base import Detector, RunContext, Subject
from .emit import MAX_EVIDENCE_SAMPLE, Observation, emit, evidence_sample

log = logging.getLogger(__name__)

SUBJECT_TYPE = "tenant"

# observation_type -> (count query key, sample query key, what the sample holds)
INVARIANTS = (
    ("MISSING_ANALYTICS_ORDER",  "missing_analytics_order",  "missing_analytics_order_sample"),
    ("ORPHANED_ANALYTICS_ORDER", "orphaned_analytics_order", "orphaned_analytics_order_sample"),
    ("ORDER_FIELD_DRIFT",        "order_field_drift",        "order_field_drift_sample"),
    ("UNMATCHABLE_ORDER",        "unmatchable_order",        "unmatchable_order_sample"),
)

# Queries pinned to something other than v1. A superseded version stays on
# disk: an observation records the query key and version that produced it,
# and evidence whose query text cannot be recovered is not evidence.
QUERY_VERSIONS = {"missing_analytics_order_sample": 2}


def _load(key: str) -> "sqlfile.Query":
    return sqlfile.load(key, QUERY_VERSIONS.get(key, 1))


class SubjectUnreadable(Exception):
    """The tenant's analytics schema is missing or not readable."""


@dataclass(frozen=True)
class Timing:
    """One timed statement. Logged at the end of the run and then discarded.

    Deliberately not persisted: the schema has no column for it, and adding
    one would make a performance note look like evidence.
    """
    subject: str
    phase: str
    ms: float
    ok: bool = True


class ReconciliationDetector(Detector):
    key = "dd_analytics_reconciliation"

    def __init__(self, dd_dsn: str | None = None) -> None:
        self._dsn = dd_dsn or config.dd_dsn()
        self._dd: psycopg.Connection | None = None
        self._tx = None
        self._timings: list[Timing] = []

    @contextmanager
    def _timed(self, subject: Any, phase: str) -> Iterator[None]:
        """Wall-clock around one statement, recorded and logged, never stored."""
        start = time.perf_counter()
        ok = True
        try:
            yield
        except BaseException:
            ok = False
            raise
        finally:
            ms = (time.perf_counter() - start) * 1000.0
            self._timings.append(Timing(str(subject), phase, ms, ok))
            log.info("timing subject=%s query=%s ms=%.1f%s",
                     subject, phase, ms, "" if ok else " FAILED")

    # ---- lifecycle --------------------------------------------------------

    def setup(self, ctx: RunContext) -> None:
        self._timings.clear()
        with self._timed("-", "connect+snapshot"):
            conn = psycopg.connect(self._dsn, row_factory=dict_row,
                                   application_name="fleet-detector/reconciliation")
            conn.autocommit = False
            conn.read_only = True
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            self._dd = conn
            self._tx = conn.transaction()
            self._tx.__enter__()
            # Materialise the snapshot now, so every tenant below sees the same one.
            conn.execute("SELECT 1")

    def teardown(self, ctx: RunContext) -> None:
        if self._tx is not None:
            try:
                self._tx.__exit__(None, None, None)
            except Exception:
                log.exception("closing the deadly_digital snapshot failed")
            self._tx = None
        if self._dd is not None:
            self._dd.close()
            self._dd = None
        self._log_timing_summary()

    # ---- enumeration ------------------------------------------------------

    def enumerate_subjects(self, ctx: RunContext) -> Sequence[Subject]:
        query = _load("tenants_active")
        with self._timed("-", query.key):
            rows = self._dd.execute(query.sql).fetchall()
        return [Subject(SUBJECT_TYPE, str(r["tenant_id"]),
                        {"tenant_id": r["tenant_id"]}) for r in rows]

    # ---- evaluation -------------------------------------------------------

    def evaluate(self, ctx: RunContext, subject: Subject) -> None:
        tenant_id = subject.payload["tenant_id"]
        schema = sqlfile.analytics_schema(tenant_id)
        self._require_readable(tenant_id, schema)

        source = f"deadly_digital:public.orders+{schema}.orders"
        for observation_type, count_key, sample_key in INVARIANTS:
            count_query = _load(count_key).bind_schema(schema)
            # A savepoint per query: a failure must not destroy the snapshot
            # the remaining tenants are being judged against. It also keeps a
            # failed query from ever being reported as a count of zero -- the
            # exception propagates and the subject is marked failed instead.
            with self._timed(tenant_id, count_query.key), self._dd.transaction():
                n = int(self._dd.execute(count_query.sql, {"t": tenant_id}).fetchone()["n"])

            if n == 0:
                continue

            sample_query = _load(sample_key).bind_schema(schema)
            with self._timed(tenant_id, sample_query.key), self._dd.transaction():
                ids = [r["offending_id"] for r in self._dd.execute(
                    sample_query.sql,
                    {"t": tenant_id, "limit": MAX_EVIDENCE_SAMPLE}).fetchall()]

            result = emit(ctx, Observation(
                observation_type=observation_type,
                subject_type=SUBJECT_TYPE,
                subject_id=str(tenant_id),
                magnitude=n,
                unit="orders",
                actual=n,
                expected=0,
                delta=n,
                evidence_query_key=count_query.key,
                evidence_query_version=count_query.version,
                evidence_params={"tenant_id": int(tenant_id),
                                 "analytics_schema": schema},
                evidence_sample=evidence_sample(ids, offending_count=n),
                evidence_source=source,
            ))
            log.info("tenant %s %s magnitude=%s severity=%s new=%s",
                     tenant_id, observation_type, n, result.severity, result.inserted)

    def _require_readable(self, tenant_id: int, schema: str) -> None:
        """A tenant whose analytics schema is missing or unreadable fails.

        Raising here means the subject lands in subjects_failed and is left
        out of subjects_evaluated -- never both -- so its open issues cannot
        be cleared by a run that did not actually look at it.
        """
        probe = _load("analytics_schema_probe")
        with self._timed(tenant_id, probe.key), self._dd.transaction():
            row = self._dd.execute(probe.sql,
                                   {"qualified": f"{schema}.orders"}).fetchone()
        if not row["table_exists"]:
            raise SubjectUnreadable(f"{schema}.orders does not exist")
        if not row["readable"]:
            raise SubjectUnreadable(f"{schema}.orders is not readable")

    # ---- timing -----------------------------------------------------------

    def _log_timing_summary(self) -> None:
        """Where the wall clock went, per subject per invariant.

        Logged, never stored. The run's duration_ms is the number of record;
        this is a note for whoever is deciding what to index next, and it
        will not match duration_ms exactly because that also covers the
        fleet-side open and close.
        """
        if not self._timings:
            return
        total = sum(t.ms for t in self._timings)
        log.info("timing summary: %d statements, %.0f ms in deadly_digital",
                 len(self._timings), total)

        for t in sorted(self._timings, key=lambda t: t.ms, reverse=True):
            log.info("timing   %8.1f ms  %5.1f%%  subject=%s %s%s",
                     t.ms, (100.0 * t.ms / total) if total else 0.0,
                     t.subject, t.phase, "" if t.ok else "  FAILED")

        by_query: dict[str, float] = {}
        by_subject: dict[str, float] = {}
        for t in self._timings:
            by_query[t.phase] = by_query.get(t.phase, 0.0) + t.ms
            by_subject[t.subject] = by_subject.get(t.subject, 0.0) + t.ms
        for phase, ms in sorted(by_query.items(), key=lambda kv: -kv[1]):
            log.info("timing   by query    %8.1f ms  %5.1f%%  %s",
                     ms, (100.0 * ms / total) if total else 0.0, phase)
        for subject, ms in sorted(by_subject.items(), key=lambda kv: -kv[1]):
            log.info("timing   by subject  %8.1f ms  %5.1f%%  subject=%s",
                     ms, (100.0 * ms / total) if total else 0.0, subject)
