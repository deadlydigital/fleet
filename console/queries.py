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

# ONE ROW PER TASK. A plain join to `runs` returns one row per RUN, and a task
# reclaimed three times then rerun rendered four times in the list -- the tab
# counts, which come from `tasks` alone, disagreed with the rows underneath
# them.
#
# The lateral takes the LATEST run, not an arbitrary one. The unordered join it
# replaces also fed the detail page, where it was worse than a duplicate row:
# task 5 showed the cost and the steps of its first, killed run beside the
# branch its fourth run produced.
#
# `runs_total` and `spent_all_runs` are here because with the latest run alone
# the page would understate a task that took four attempts -- £4.58 for a task
# that actually cost £19.95.
TASK_LIST = """
SELECT t.id, t.title, t.status, t.queue, t.objective_ref, t.branch_name,
       t.max_cost_gbp, t.attempts, t.max_attempts, t.created_at,
       t.claimed_at, t.completed_at, t.priority, t.repo, t.base_branch,
       r.id AS run_id, r.committed_gbp, r.status AS run_status,
       EXTRACT(EPOCH FROM (r.completed_at - r.started_at)) AS elapsed_seconds,
       agg.runs_total, agg.spent_all_runs
  FROM tasks t
  LEFT JOIN LATERAL (
      SELECT * FROM runs WHERE task_id = t.id ORDER BY id DESC LIMIT 1
  ) r ON true
  LEFT JOIN LATERAL (
      SELECT count(*) AS runs_total, coalesce(sum(committed_gbp), 0) AS spent_all_runs
        FROM runs WHERE task_id = t.id
  ) agg ON true
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
       EXTRACT(EPOCH FROM (r.completed_at - r.started_at)) AS elapsed_seconds,
       agg.runs_total, agg.spent_all_runs
  FROM tasks t
  LEFT JOIN LATERAL (
      SELECT * FROM runs WHERE task_id = t.id ORDER BY id DESC LIMIT 1
  ) r ON true
  LEFT JOIN LATERAL (
      SELECT count(*) AS runs_total, coalesce(sum(committed_gbp), 0) AS spent_all_runs
        FROM runs WHERE task_id = t.id
  ) agg ON true
 WHERE t.id = %(task_id)s
"""

# Every run of a task, newest first. The detail page shows the latest run in
# full and this beside it, so an earlier attempt is visible rather than
# implied by the attempt count.
TASK_RUNS = """
SELECT r.id, r.status, r.started_at, r.completed_at, r.spend_limit_gbp,
       r.committed_gbp, r.work_type, r.contract_version,
       EXTRACT(EPOCH FROM (r.completed_at - r.started_at)) AS elapsed_seconds,
       (SELECT count(*) FROM run_steps s WHERE s.run_id = r.id) AS steps
  FROM runs r WHERE r.task_id = %(task_id)s
 ORDER BY r.id DESC
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

# Reclaims: a tick that died and was recovered. Shown on the task so an
# automatic overnight retry is readable in the morning rather than inferred
# from `attempts` reading 2 instead of 1.
TASK_RECLAIMS = """
SELECT id, task_id, run_id, reclaimed_at, reclaimed_by, outcome,
       dead_claimed_at, stale_for, grace, timeout_seconds,
       attempts, max_attempts, open_runs_closed,
       worktree_removed, branch_kept
  FROM task_reclaims WHERE task_id = %(task_id)s
 ORDER BY reclaimed_at DESC, id DESC
"""

# For the list: which tasks have been reclaimed at all, and how often.
RECLAIM_COUNTS = """
SELECT task_id, count(*) AS n, max(reclaimed_at) AS last_reclaimed_at
  FROM task_reclaims GROUP BY task_id
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

# Untriaged now means "no effective verdict" -- neither judged directly nor
# covered by an earlier judgement of the same fingerprint. An hourly recurring
# issue used to refill this list every hour with the thing already ruled on.
UNTRIAGED = """
SELECT o.id, o.detector_key, o.detector_version, o.observation_type,
       o.subject_type, o.subject_id, o.magnitude, o.unit, o.observed_at,
       o.fingerprint, c.coverage_reason
  FROM observations o
  JOIN observation_coverage c ON c.observation_id = o.id
 WHERE c.effective_verdict IS NULL
 ORDER BY o.observed_at DESC
"""

# What the queue used to hold, so the page can say what coverage is saving.
COVERED = """
SELECT c.observation_id, c.detector_key, c.observation_type, c.fingerprint,
       c.observed_at, c.magnitude, c.band,
       c.covering_verdict, c.anchor_observation_id, c.anchor_observed_at,
       c.anchor_magnitude, c.relative_change, c.allowed_change,
       c.redundant_verdict, c.coverage_reason
  FROM observation_coverage c
 WHERE c.covered
 ORDER BY c.observed_at DESC
"""

# One row per fingerprint: the judgement, and how many occurrences it covers.
COVERAGE_SUMMARY = """
SELECT c.detector_key, c.observation_type, c.fingerprint,
       count(*)                                        AS occurrences,
       count(*) FILTER (WHERE c.is_judgement)          AS judgements,
       count(*) FILTER (WHERE c.covered)               AS covered,
       count(*) FILTER (WHERE c.redundant_verdict)     AS redundant_verdicts,
       count(*) FILTER (WHERE c.effective_verdict IS NULL) AS untriaged,
       min(c.observed_at)                              AS first_seen,
       max(c.observed_at)                              AS last_seen,
       min(c.magnitude)                                AS min_magnitude,
       max(c.magnitude)                                AS max_magnitude,
       max(c.effective_verdict)                        AS verdict
  FROM observation_coverage c
 GROUP BY 1, 2, 3
HAVING count(*) > 1
 ORDER BY count(*) DESC
"""

# Two rates, because they are two questions -- see 006_verdict_coverage.sql.
# The denominator is shown for both, always: `1 of 1` refuses the decision
# that `100%` invites, and the judgement denominator is small by design now.
FALSE_POSITIVE_RATE = """
SELECT c.detector_key, c.detector_version, c.observation_type,
       count(*) FILTER (WHERE c.is_judgement)                       AS judged,
       count(*) FILTER (WHERE c.is_judgement
                          AND c.own_verdict = 'FALSE_POSITIVE')     AS false_positive,
       count(*) FILTER (WHERE c.is_judgement
                          AND c.own_verdict = 'VALID')              AS valid,
       count(*) FILTER (WHERE c.is_judgement
                          AND c.own_verdict = 'INCONCLUSIVE')       AS inconclusive,
       count(*)                                                     AS occurrences,
       count(*) FILTER (WHERE c.effective_verdict IS NOT NULL)       AS occurrences_ruled,
       count(*) FILTER (WHERE c.effective_verdict = 'FALSE_POSITIVE') AS occurrences_false,
       count(*) FILTER (WHERE c.covered)                            AS occurrences_covered
  FROM observation_coverage c
 WHERE c.own_verdict IS NOT NULL OR c.covered
 GROUP BY 1, 2, 3
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


# ---------------------------------------------------------------- page 4

# EVERY OUTCOME COLUMN HERE IS A VIEW COLUMN, not a stored one. `decision_log`
# has no place to keep one; `decision_outcomes` recomputes task state, cost,
# attempts and issue state from the rows the decision cited, on every read. So
# this page cannot show a stale outcome, and there is no write route that could
# set one -- which is why this page is a GET and nothing else.
DECISIONS = """
SELECT id, product, subject, decision, reason, decided_by, decided_at,
       origin, confidence, evidence,
       proposal_id, issue_id, task_id,
       task_status, task_outcome, total_cost_gbp, runs_total,
       attempts_to_green, issue_status, issue_outcome,
       reopened_since_decision, resolved_since_decision
  FROM decision_outcomes
 WHERE (%(product)s::text IS NULL OR product = %(product)s)
 ORDER BY decided_at DESC, id DESC
"""

DECISION_PRODUCTS = """
SELECT product, count(*) AS n FROM decision_log GROUP BY product ORDER BY 1
"""

DECISION_TOTALS = """
SELECT decision::text AS decision, count(*) AS n,
       count(*) FILTER (WHERE origin = 'BACKFILLED') AS backfilled
  FROM decision_log GROUP BY decision ORDER BY 1
"""


def task_list(status: str | None) -> list[dict[str, Any]]:
    return db.rows(TASK_LIST, {"status": status})


def status_counts() -> dict[str, int]:
    return {r["status"]: r["n"] for r in db.rows(TASK_STATUS_COUNTS)}


def task_detail(task_id: int) -> dict[str, Any] | None:
    return db.one(TASK_DETAIL, {"task_id": task_id})


def task_runs(task_id: int) -> list[dict[str, Any]]:
    return db.rows(TASK_RUNS, {"task_id": task_id})


def run_steps(run_id: int) -> list[dict[str, Any]]:
    return db.rows(RUN_STEPS, {"run_id": run_id}) if run_id else []


def run_budget(run_id: int) -> list[dict[str, Any]]:
    return db.rows(RUN_BUDGET, {"run_id": run_id}) if run_id else []


def task_reclaims(task_id: int) -> list[dict[str, Any]]:
    return db.rows(TASK_RECLAIMS, {"task_id": task_id})


def reclaim_counts() -> dict[int, dict[str, Any]]:
    return {r["task_id"]: r for r in db.rows(RECLAIM_COUNTS)}


def detector_health() -> list[dict[str, Any]]:
    return db.rows(DETECTOR_HEALTH)


def open_issues() -> list[dict[str, Any]]:
    return db.rows(OPEN_ISSUES)


def untriaged() -> list[dict[str, Any]]:
    return db.rows(UNTRIAGED)


def covered() -> list[dict[str, Any]]:
    return db.rows(COVERED)


def coverage_summary() -> list[dict[str, Any]]:
    return db.rows(COVERAGE_SUMMARY)


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


def decisions(product: str | None = None) -> list[dict[str, Any]]:
    return db.rows(DECISIONS, {"product": product})


def decision_products() -> list[dict[str, Any]]:
    return db.rows(DECISION_PRODUCTS)


def decision_totals() -> list[dict[str, Any]]:
    return db.rows(DECISION_TOTALS)
