"""The console's reads.

WHY THESE ARE HERE AND NOT IN queries/<key>.v<n>.sql
----------------------------------------------------
Track 1 and track 2 version every query in its own file because those
queries produce evidence: a number that ends up in an observation or a
proposal has to be traceable to the exact SQL that produced it, at the
version it was produced by. Nothing here produces evidence. These queries
render a page, and a page that changes is a page that changes. Putting them
in a versioned directory would claim a guarantee this module does not need
and would not honour.

Every threshold in this file comes from `detector_registry`. There is no
hardcoded cadence, grace or lateness number anywhere -- the whole point of
the health colours is that they are judged against each detector's own
geometry, so a detector retuned in the registry is retuned on this page
without a deploy.
"""
from __future__ import annotations

from typing import Any

from console import db

# ---------------------------------------------------------------- page 1

TASK_LIST = """
SELECT t.id, t.title, t.status, t.queue, t.objective_ref, t.branch_name,
       t.max_cost_gbp, t.attempts, t.max_attempts, t.created_at,
       t.claimed_at, t.completed_at, t.priority, t.repo, t.base_branch,
       r.id AS run_id, r.committed_gbp, r.status AS run_status,
       EXTRACT(EPOCH FROM (r.completed_at - r.started_at)) AS elapsed_seconds
  FROM tasks t
  LEFT JOIN runs r ON r.task_id = t.id
 WHERE (%(status)s::text IS NULL OR t.status = %(status)s::text)
 ORDER BY t.created_at DESC, t.id DESC
"""

TASK_STATUS_COUNTS = """
SELECT status, count(*) AS n FROM tasks GROUP BY status
"""

TASK_DETAIL = """
SELECT t.*, r.id AS run_id, r.status AS run_status, r.work_type,
       r.contract_version, r.spend_limit_gbp, r.committed_gbp,
       r.started_at AS run_started_at, r.completed_at AS run_completed_at,
       EXTRACT(EPOCH FROM (r.completed_at - r.started_at)) AS elapsed_seconds
  FROM tasks t
  LEFT JOIN runs r ON r.task_id = t.id
 WHERE t.id = %(task_id)s
"""

RUN_STEPS = """
SELECT sequence, step_type, actor, created_at, payload
  FROM run_steps WHERE run_id = %(run_id)s ORDER BY sequence
"""

# Both sides of the budget. `runs.committed_gbp` cannot say on its own whether
# a reservation was exceeded: settle_model_budget refuses an actual above the
# reservation and settles at the cap, so the overspend is only visible by
# comparing the reservation to what the call actually reported.
RUN_BUDGET = """
SELECT br.id, br.estimate_gbp, br.status, br.created_at, br.settled_at,
       br.voided_reason, mc.marginal_cost_gbp, mc.model, mc.provider,
       mc.total_duration_ms, mc.ok
  FROM budget_reservations br
  LEFT JOIN model_calls mc ON mc.reservation_id = br.id
 WHERE br.run_id = %(run_id)s
 ORDER BY br.created_at
"""

# ---------------------------------------------------------------- page 2

# Health, judged against the registry rather than against a number here.
#
# `due_at` is the moment the next window's run should have completed: the last
# window's end, plus one cadence for the next window, plus the settle lag it
# has to wait out, plus the grace the registry allows. A detector past that is
# late; one past it by more than a further cadence has missed a whole slot.
DETECTOR_HEALTH = """
WITH last_ok AS (
    SELECT DISTINCT ON (detector_key)
           detector_key, status, window_start, window_end, started_at,
           completed_at, duration_ms, attempt_count, error
      FROM detector_runs
     ORDER BY detector_key, window_end DESC, id DESC
), last_success AS (
    SELECT DISTINCT ON (detector_key) detector_key, window_end AS ok_window_end
      FROM detector_runs
     WHERE status IN ('OK', 'PARTIAL')
     ORDER BY detector_key, window_end DESC, id DESC
)
SELECT reg.detector_key, reg.cadence, reg.grace, reg.settle_lag,
       reg.current_detector_version, reg.retired_at, reg.maintenance_until,
       lr.status, lr.window_start, lr.window_end, lr.completed_at,
       lr.duration_ms, lr.attempt_count, lr.error,
       ls.ok_window_end,
       ls.ok_window_end + reg.cadence                    AS next_window_end,
       ls.ok_window_end + reg.cadence + reg.settle_lag
                        + reg.grace                      AS due_at,
       now() > (ls.ok_window_end + reg.cadence + reg.settle_lag + reg.grace)
                                                         AS is_late,
       now() > (ls.ok_window_end + 2 * reg.cadence + reg.settle_lag + reg.grace)
                                                         AS missed_a_slot
  FROM detector_registry reg
  LEFT JOIN last_ok      lr ON lr.detector_key = reg.detector_key
  LEFT JOIN last_success ls ON ls.detector_key = reg.detector_key
 WHERE reg.retired_at IS NULL
 ORDER BY reg.detector_key
"""

# Why an issue is still open. `coverage_horizon_valid` is the predicate the
# resolver itself consults, so asking it here answers "why is this still open"
# with the same function that decided, rather than with a re-implementation
# that could disagree.
OPEN_ISSUES = """
SELECT i.id, i.fingerprint, i.issue_type, i.subject_type, i.subject_id,
       i.severity, i.current_magnitude, i.current_unit, i.occurrence_count,
       i.reopen_count, i.first_seen, i.last_seen, i.detector_key,
       i.issue_key_version, i.product,
       now() - i.first_seen AS age,
       reg.required_clear_runs,
       coverage_horizon_valid(i.detector_key, i.issue_key_version, i.product,
                              i.last_seen, now(), now()) AS coverage_ok,
       (SELECT count(*) FROM detector_runs dr
         WHERE dr.detector_key = i.detector_key
           AND dr.status IN ('OK','PARTIAL')
           AND dr.window_start > i.last_seen)            AS clear_runs_since
  FROM issues i
  LEFT JOIN detector_registry reg ON reg.detector_key = i.detector_key
 WHERE i.status = 'OPEN'
 ORDER BY i.severity DESC, i.last_seen DESC
"""

UNTRIAGED = """
SELECT o.id, o.detector_key, o.detector_version, o.observation_type,
       o.subject_type, o.subject_id, o.magnitude, o.unit, o.observed_at,
       o.fingerprint
  FROM observations o
  LEFT JOIN observation_verdicts v ON v.observation_id = o.id
 WHERE v.id IS NULL
 ORDER BY o.observed_at DESC
"""

# The denominator is shown, always. A rate over three observations is not a
# rate, and `2 of 3` refuses the decision that `67%` invites.
FALSE_POSITIVE_RATE = """
SELECT v.detector_key, v.detector_version, v.observation_type,
       count(*)                                                AS judged,
       count(*) FILTER (WHERE v.verdict = 'FALSE_POSITIVE')     AS false_positive,
       count(*) FILTER (WHERE v.verdict = 'VALID')              AS valid,
       count(*) FILTER (WHERE v.verdict = 'INCONCLUSIVE')       AS inconclusive
  FROM observation_verdicts v
 GROUP BY v.detector_key, v.detector_version, v.observation_type
 ORDER BY 1, 2, 3
"""

# ---------------------------------------------------------------- page 3

PROPOSALS = """
SELECT p.id, p.cycle_id, p.kind, p.area, p.finding_key, p.title, p.body,
       p.objective_ref, p.est_effort, p.est_impact, p.reversibility,
       p.confidence, p.created_at,
       d.id AS decision_id, d.verdict, d.reason_code, d.decided_at,
       d.decision_seconds, d.executed, d.outcome_note
  FROM proposals p
  LEFT JOIN decisions d ON d.proposal_id = p.id
 ORDER BY p.created_at DESC, p.id DESC
"""

PROPOSAL_EVIDENCE = """
SELECT proposal_id, adapter, query_key, value, fetched_at, stale
  FROM proposal_evidence
 ORDER BY proposal_id, id
"""

CYCLES = """
SELECT cycle_id, min(created_at) AS started_at, count(*) AS proposals
  FROM proposals GROUP BY cycle_id ORDER BY 2 DESC
"""


def task_list(status: str | None) -> list[dict[str, Any]]:
    return db.rows(TASK_LIST, {"status": status})


def status_counts() -> dict[str, int]:
    return {r["status"]: r["n"] for r in db.rows(TASK_STATUS_COUNTS)}


def task_detail(task_id: int) -> dict[str, Any] | None:
    return db.one(TASK_DETAIL, {"task_id": task_id})


def run_steps(run_id: int) -> list[dict[str, Any]]:
    return db.rows(RUN_STEPS, {"run_id": run_id}) if run_id else []


def run_budget(run_id: int) -> list[dict[str, Any]]:
    return db.rows(RUN_BUDGET, {"run_id": run_id}) if run_id else []


def detector_health() -> list[dict[str, Any]]:
    return db.rows(DETECTOR_HEALTH)


def open_issues() -> list[dict[str, Any]]:
    return db.rows(OPEN_ISSUES)


def untriaged() -> list[dict[str, Any]]:
    return db.rows(UNTRIAGED)


def false_positive_rate() -> list[dict[str, Any]]:
    return db.rows(FALSE_POSITIVE_RATE)


def proposals() -> list[dict[str, Any]]:
    return db.rows(PROPOSALS)


def proposal_evidence() -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in db.rows(PROPOSAL_EVIDENCE):
        grouped.setdefault(row["proposal_id"], []).append(row)
    return grouped


def cycles() -> list[dict[str, Any]]:
    return db.rows(CYCLES)
