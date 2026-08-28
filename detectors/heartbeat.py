"""fleet_heartbeat.

Watches the detection layer itself, from the registry. Every threshold is a
registry column; the only constant here is the three-run error streak, which
is the definition of the observation type rather than a tuning knob.

Every query filters run_mode = 'SCHEDULED'. A backfill run looks exactly
like a healthy recent execution, so counting one would let a backfill mask a
dead scheduler -- the single failure this detector exists to catch.

The dead-man's switch is pinged only after a clean run, from on_success and
never from a finally block. A ping that survives failure is a switch that
reports health while broken.
"""
from __future__ import annotations

import logging
import urllib.error
import urllib.request
from typing import Any, Sequence

from . import config, sqlfile
from .base import Detector, RunContext, Subject
from .emit import Observation, emit, evidence_sample

log = logging.getLogger(__name__)

SUBJECT_TYPE = "detector"
ERROR_STREAK_THRESHOLD = 3
PING_TIMEOUT_SECONDS = 10
# healthchecks.io says this in the body when the check UUID is unknown.
UNKNOWN_CHECK_MARKER = "not found"


class HeartbeatDetector(Detector):
    key = "fleet_heartbeat"

    def __init__(self, deadman_url: str | None = None) -> None:
        self._deadman_url = deadman_url if deadman_url is not None else config.deadman_url()

    # ---- enumeration ------------------------------------------------------

    def enumerate_subjects(self, ctx: RunContext) -> Sequence[Subject]:
        rows = ctx.fleet.execute(sqlfile.load("registered_detectors").sql,
                                 {"p": ctx.registry.product}).fetchall()
        return [Subject(SUBJECT_TYPE, r["detector_key"], dict(r)) for r in rows]

    # ---- evaluation -------------------------------------------------------

    def evaluate(self, ctx: RunContext, subject: Subject) -> None:
        params = {"k": subject.payload["detector_key"],
                  "v": subject.payload["issue_key_version"],
                  "p": subject.payload["product"]}
        self._run_missing(ctx, subject, params)
        self._error_streak(ctx, subject, params)
        self._window_abandoned(ctx, subject, params)
        self._run_stale(ctx, subject, params)

    # -- DETECTOR_RUN_MISSING ----------------------------------------------

    def _run_missing(self, ctx: RunContext, subject: Subject,
                     params: dict[str, Any]) -> None:
        # The heartbeat cannot be both running and missing, so it never
        # reports itself missing.
        if subject.subject_id == ctx.registry.detector_key:
            return
        # A detector under declared maintenance is not expected to run.
        if subject.payload.get("in_maintenance"):
            log.info("%s is in maintenance until %s; skipping RUN_MISSING",
                     subject.subject_id, subject.payload.get("maintenance_until"))
            return

        query = sqlfile.load("detector_run_missing")
        row = ctx.fleet.execute(query.sql, params).fetchone()
        if row is None or row["reference_at"] is None:
            return                      # never scheduled: nothing is overdue yet
        overdue = int(row["overdue_seconds"])
        if overdue <= 0:
            return

        self._emit(ctx, subject, "DETECTOR_RUN_MISSING", query, params,
                   magnitude=overdue, unit="seconds",
                   expected=int(row["allowance_seconds"]),
                   actual=int(row["since_seconds"]), delta=overdue,
                   sample=evidence_sample(
                       [], overdue_seconds=overdue,
                       allowance_seconds=int(row["allowance_seconds"]),
                       seconds_since_last_run=int(row["since_seconds"]),
                       ever_succeeded=bool(row["has_successful_run"])))

    # -- DETECTOR_ERROR_STREAK ---------------------------------------------

    def _error_streak(self, ctx: RunContext, subject: Subject,
                      params: dict[str, Any]) -> None:
        query = sqlfile.load("detector_error_streak")
        row = ctx.fleet.execute(query.sql, params).fetchone()
        streak = int(row["streak_length"]) if row else 0
        if streak < ERROR_STREAK_THRESHOLD:
            return
        self._emit(ctx, subject, "DETECTOR_ERROR_STREAK", query, params,
                   magnitude=streak, unit="runs",
                   expected=0, actual=streak, delta=streak,
                   sample=evidence_sample(row["run_ids"] or [],
                                          streak_length=streak,
                                          threshold=ERROR_STREAK_THRESHOLD))

    # -- DETECTOR_WINDOW_ABANDONED -----------------------------------------

    def _window_abandoned(self, ctx: RunContext, subject: Subject,
                          params: dict[str, Any]) -> None:
        query = sqlfile.load("detector_window_abandoned")
        row = ctx.fleet.execute(query.sql, params).fetchone()
        n = int(row["n"]) if row else 0
        if n == 0:
            return
        self._emit(ctx, subject, "DETECTOR_WINDOW_ABANDONED", query, params,
                   magnitude=n, unit="windows",
                   expected=0, actual=n, delta=n,
                   sample=evidence_sample(row["run_ids"] or [],
                                          abandoned_windows=n,
                                          attempts=int(row["attempts"] or 0)))

    # -- DETECTOR_RUN_STALE ------------------------------------------------

    def _run_stale(self, ctx: RunContext, subject: Subject,
                   params: dict[str, Any]) -> None:
        query = sqlfile.load("detector_run_stale")
        rows = ctx.fleet.execute(query.sql,
                                 {**params, "self_run_id": ctx.run_id}).fetchall()
        if not rows:
            return
        run_ids = [r["run_id"] for r in rows]
        longest = max(int(r["running_seconds"]) for r in rows)
        timeout = int(rows[0]["timeout_seconds"])
        self._emit(ctx, subject, "DETECTOR_RUN_STALE", query, params,
                   magnitude=len(rows), unit="runs",
                   expected=0, actual=len(rows), delta=len(rows),
                   sample=evidence_sample(run_ids, stale_runs=len(rows),
                                          longest_running_seconds=longest,
                                          execution_timeout_seconds=timeout))
        # Record the fact first, then reclaim. Reclaiming first would erase
        # the evidence the observation is about.
        for run_id in run_ids:
            verdict = ctx.fleet.execute(
                "SELECT reclaim_stale_detector_run(%s) AS v", (run_id,)).fetchone()["v"]
            log.warning("reclaim_stale_detector_run(%s) -> %s", run_id, verdict)

    # ---- helpers ----------------------------------------------------------

    def _emit(self, ctx: RunContext, subject: Subject, observation_type: str,
              query, params: dict[str, Any], *, magnitude, unit,
              expected, actual, delta, sample) -> None:
        result = emit(ctx, Observation(
            observation_type=observation_type,
            subject_type=SUBJECT_TYPE,
            subject_id=subject.subject_id,
            magnitude=magnitude, unit=unit,
            expected=expected, actual=actual, delta=delta,
            evidence_query_key=query.key, evidence_query_version=query.version,
            evidence_params={"detector_key": params["k"],
                             "issue_key_version": params["v"],
                             "product": params["p"]},
            evidence_sample=sample,
            evidence_source="fleet:detector_runs+detector_registry",
        ))
        log.info("%s %s magnitude=%s severity=%s new=%s", subject.label,
                 observation_type, magnitude, result.severity, result.inserted)

    # ---- dead-man's switch ------------------------------------------------

    def on_success(self, ctx: RunContext) -> None:
        if not self._deadman_url:
            log.info("no dead-man's switch URL configured (%s); skipping ping",
                     "/".join(config.DEADMAN_URL_KEYS))
            return
        try:
            request = urllib.request.Request(self._deadman_url, method="GET")
            with urllib.request.urlopen(request, timeout=PING_TIMEOUT_SECONDS) as resp:
                status = resp.status
                body = resp.read(200).decode("utf-8", "replace").strip()
            # HTTP 200 alone proves nothing: healthchecks.io answers an
            # unrecognised check UUID with 200 and the body "OK (not found)".
            # Trusting the status code would leave a mistyped or deleted check
            # looking healthy forever -- a switch that reports health while
            # nothing at all is watching.
            if UNKNOWN_CHECK_MARKER in body.lower():
                log.error("dead-man's switch does not recognise this check: "
                          "HTTP %s %r -- the ping was accepted but no check "
                          "exists at the far end; nothing is watching", status, body)
            else:
                log.info("dead-man's switch pinged: HTTP %s %r", status, body)
        except (urllib.error.URLError, OSError) as exc:
            # The run really did succeed. A failed ping is a monitoring
            # problem and must not rewrite the recorded outcome of the run.
            log.error("dead-man's switch ping failed: %s", exc)
