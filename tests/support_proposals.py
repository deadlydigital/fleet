"""Arrangement helpers for the proposal layer's tests.

Everything here writes as the superuser fixture, because these are histories
the layer itself is not allowed to create: detector runs, issues,
observations and verdicts all belong to track 1 or to a human. Track 2's own
writes always go through the real roles, so that what the tests exercise is
the same privilege boundary production has.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Any, Sequence

RECONCILIATION = "dd_analytics_reconciliation"
HEARTBEAT = "fleet_heartbeat"
PRODUCT = "deadly_digital"

# The tenant the fixture history is about, in track 1's subject spelling.
DEFAULT_SUBJECTS = ("tenant:2",)


def registry(admin, detector_key: str = RECONCILIATION) -> dict[str, Any]:
    return admin.execute(
        "SELECT * FROM detector_registry WHERE detector_key = %s", (detector_key,)
    ).fetchone()


def slot_ends(admin, detector_key: str = RECONCILIATION, count: int = 3,
              skip_newest: int = 0) -> list[datetime]:
    """On-grid, already-settled slot ends, oldest first.

    Derived from the registry the same way open_scheduled_run() derives it.
    Computing a window in Python would be inventing geometry the database
    owns.
    """
    rows = admin.execute(
        """
        WITH reg AS (
            SELECT schedule_epoch, cadence, settle_lag
              FROM detector_registry WHERE detector_key = %(k)s
        ), latest AS (
            SELECT floor(extract(epoch FROM (now() - settle_lag - schedule_epoch))
                         / extract(epoch FROM cadence))::bigint AS n,
                   schedule_epoch, cadence
              FROM reg
        )
        SELECT schedule_epoch + ((n - %(skip)s - i) * cadence) AS slot_end
          FROM latest, generate_series(0, %(c)s - 1) AS i
         ORDER BY 1
        """, {"k": detector_key, "c": count, "skip": skip_newest}).fetchall()
    return [r["slot_end"] for r in rows]


def arrange_run(admin, detector_key: str, slot_end: datetime, *,
                status: str = "OK", subjects: Sequence[str] | None = None,
                failed: Sequence[str] | None = None,
                completed_at: datetime | None = None) -> int:
    reg = registry(admin, detector_key)
    # An ENUMERATED run that closes OK must carry the subjects it evaluated;
    # the constraint in 001 says so, and a test that worked around it would
    # be arranging a history the real detector cannot produce.
    if (subjects is None and reg["coverage_mode"] == "ENUMERATED"
            and status in ("OK", "PARTIAL", "RUNNING")):
        subjects = DEFAULT_SUBJECTS
    row = admin.execute(
        """
        INSERT INTO detector_runs
            (detector_key, detector_version, issue_key_version, product,
             semantics, run_mode, coverage_mode, subjects_evaluated,
             subjects_failed, window_start, window_end, started_at,
             completed_at, status)
        VALUES (%(k)s, %(dv)s, %(v)s, %(p)s, %(sem)s, 'SCHEDULED', %(cov)s,
                %(subj)s, %(failed)s, %(ws)s, %(we)s, %(we)s,
                coalesce(%(done)s, %(we)s), %(status)s)
        RETURNING id
        """,
        {"k": detector_key, "dv": reg["current_detector_version"],
         "v": reg["issue_key_version"], "p": reg["product"],
         "sem": reg["semantics"], "cov": reg["coverage_mode"],
         "subj": list(subjects) if subjects is not None else None,
         "failed": list(failed) if failed is not None else None,
         "ws": slot_end - reg["evaluation_window"], "we": slot_end,
         "done": completed_at, "status": status}).fetchone()
    return row["id"]


def arrange_runs(admin, detector_key: str, slots: Sequence[datetime], **kwargs) -> list[int]:
    return [arrange_run(admin, detector_key, slot, **kwargs) for slot in slots]


def fingerprint(detector_key: str, issue_key_version: int, product: str,
                subject_type: str, subject_id: str, observation_type: str) -> str:
    material = "|".join((detector_key, str(issue_key_version), product,
                         subject_type, subject_id, observation_type))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def arrange_issue(admin, *, detector_key: str = RECONCILIATION,
                  issue_type: str = "MISSING_ANALYTICS_ORDER",
                  subject_type: str = "tenant", subject_id: str = "2",
                  severity: str = "CRITICAL", first_seen: datetime | None = None,
                  last_seen: datetime | None = None, magnitude: int = 100,
                  unit: str = "orders", occurrence_count: int = 1) -> dict[str, Any]:
    reg = registry(admin, detector_key)
    fp = fingerprint(detector_key, reg["issue_key_version"], reg["product"],
                     subject_type, subject_id, issue_type)
    now = admin.execute("SELECT now() AS t").fetchone()["t"]
    first_seen = first_seen or now
    last_seen = last_seen or first_seen
    return admin.execute(
        """
        INSERT INTO issues
            (fingerprint, product, issue_type, subject_type, subject_id,
             detector_key, issue_key_version, first_seen, last_seen,
             occurrence_count, current_magnitude, current_unit, severity)
        VALUES (%(fp)s, %(p)s, %(t)s, %(st)s, %(sid)s, %(k)s, %(v)s, %(first)s,
                %(last)s, %(n)s, %(mag)s, %(unit)s, %(sev)s)
        RETURNING *
        """,
        {"fp": fp, "p": reg["product"], "t": issue_type, "st": subject_type,
         "sid": subject_id, "k": detector_key, "v": reg["issue_key_version"],
         "first": first_seen, "last": last_seen, "n": occurrence_count,
         "mag": magnitude, "unit": unit, "sev": severity}).fetchone()


def arrange_observations(admin, detector_key: str, slot_end: datetime, *,
                         observation_type: str = "MISSING_ANALYTICS_ORDER",
                         subject_type: str = "tenant", subject_id: str = "2",
                         count: int = 1, verdict: str | None = None,
                         subjects: Sequence[str] | None = None,
                         magnitude: int | None = None,
                         detector_version: int | None = None) -> list[int]:
    """Observations on a run, optionally with a verdict already recorded.

    The run is opened RUNNING, observed against, then closed: an observation
    can only be inserted into a RUNNING run, which is track 1's rule and not
    one to work around here.

    `magnitude` and `detector_version` are set at INSERT rather than by a
    later UPDATE, because reject_mutation() refuses to let an observation be
    edited. An observation is evidence; a test that could rewrite one would be
    testing something the system does not permit.
    """
    reg = registry(admin, detector_key)
    run_id = arrange_run(admin, detector_key, slot_end, status="RUNNING",
                         subjects=subjects)
    ids: list[int] = []
    for n in range(count):
        fp = fingerprint(detector_key, reg["issue_key_version"], reg["product"],
                         subject_type, f"{subject_id}", observation_type)
        row = admin.execute(
            """
            INSERT INTO observations
                (detector_run_id, detector_key, detector_version,
                 issue_key_version, product, observation_type, observed_at,
                 subject_type, subject_id, fingerprint, magnitude, unit)
            VALUES (%(run)s, %(k)s, %(dv)s, %(v)s, %(p)s, %(type)s, %(at)s,
                    %(st)s, %(sid)s, %(fp)s, %(mag)s, 'orders')
            RETURNING id
            """,
            {"run": run_id, "k": detector_key,
             "dv": (detector_version if detector_version is not None
                    else reg["current_detector_version"]),
             "v": reg["issue_key_version"],
             "p": reg["product"], "type": observation_type, "at": slot_end,
             "st": subject_type, "sid": f"{subject_id}",
             "fp": f"{fp}-{n}" if count > 1 else fp,
             "mag": magnitude if magnitude is not None else 100 + n}).fetchone()
        ids.append(row["id"])

    admin.execute("UPDATE detector_runs SET status = 'OK', completed_at = %s "
                  "WHERE id = %s", (slot_end, run_id))

    if verdict is not None:
        for observation_id in ids:
            record_verdict(admin, observation_id, verdict)
    return ids


def record_verdict(admin, observation_id: int, verdict: str,
                   created_at: datetime | None = None) -> None:
    admin.execute(
        """
        INSERT INTO observation_verdicts
            (observation_id, detector_key, detector_version, issue_key_version,
             observation_type, verdict, verdict_by, created_at)
        SELECT o.id, o.detector_key, o.detector_version, o.issue_key_version,
               o.observation_type, %(verdict)s, 'test',
               coalesce(%(at)s, now())
          FROM observations o WHERE o.id = %(id)s
        """, {"id": observation_id, "verdict": verdict, "at": created_at})


def insert_proposal(conn, *, cycle_id: uuid.UUID | None = None,
                    kind: str = "OBSERVATION", area: str = PRODUCT,
                    finding_key: str = "test:1", title: str = "a title",
                    product: str = PRODUCT,
                    body: str = "a body", objective_ref: str | None = "dd-trustworthy",
                    reversibility: str = "TRIVIAL", confidence: str = "1.0",
                    evidence: int = 1, created_at: datetime | None = None) -> int:
    """Insert through whatever role the caller connected as."""
    cycle_id = cycle_id or uuid.uuid4()
    with conn.transaction():
        row = conn.execute(
            """
            INSERT INTO proposals
                (cycle_id, kind, product, area, finding_key, title, body,
                 objective_ref, reversibility, confidence, created_at)
            VALUES (%(c)s, %(kind)s, %(product)s, %(area)s, %(key)s, %(title)s,
                    %(body)s, %(obj)s, %(rev)s, %(conf)s,
                    coalesce(%(at)s, now()))
            RETURNING id
            """,
            {"c": cycle_id, "kind": kind, "product": product, "area": area,
             "key": finding_key,
             "title": title, "body": body, "obj": objective_ref,
             "rev": reversibility, "conf": confidence, "at": created_at}).fetchone()
        proposal_id = row["id"] if isinstance(row, dict) else row[0]
        for n in range(evidence):
            conn.execute(
                """
                INSERT INTO proposal_evidence
                    (proposal_id, adapter, query_key, value, fetched_at,
                     freshness_bound)
                VALUES (%(pid)s, 'detectors', 'open_issues',
                        %(value)s::jsonb, now(), interval '1 hour')
                """, {"pid": proposal_id, "value": f'{{"n": {n}}}'})
    return proposal_id
