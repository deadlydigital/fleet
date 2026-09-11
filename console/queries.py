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


# ---------------------------------------------------------------------------
# Briefs — the SERIES, not one brief
# ---------------------------------------------------------------------------
#
# A single brief is a file; you do not need a web page for it. The page exists
# for the thing a file cannot show: the same metric across days, and whether
# the count of things the pass could not compute is going up.

#: The batch's own note, which records what the producer CHECKED AND DROPPED.
#: On the page rather than only in the database: a batch that silently omits
#: what it rejected loses the same thing a discarded rejection does, and a note
#: nobody sees is a note that was not written.
CANDIDATE_BATCHES_OPEN = """
    SELECT DISTINCT b.id, b.source_document, b.source_sha, b.generated_at,
           b.generated_by, b.note
      FROM candidate_batches b
      JOIN candidates c ON c.batch_id = b.id
     WHERE c.disposition IN ('PENDING','NOT_NOW')
     ORDER BY b.id DESC
"""


def candidate_batches_open() -> list[dict[str, Any]]:
    return db.rows(CANDIDATE_BATCHES_OPEN)


BRIEF_RUNS = """
    SELECT id, generated_at, compares_since, code_version,
           claims_total, claims_uncomputed,
           claims_total - claims_uncomputed AS claims_computed,
           jsonb_array_length(sources_reachable)   AS sources_ok,
           jsonb_array_length(sources_unreachable) AS sources_failed,
           sources_unreachable,
           completed_at - started_at AS took
      FROM brief_runs
     ORDER BY id DESC
     LIMIT 30
"""

#: One row per metric per brief, newest brief first. The page pivots this into
#: a series so a reader sees movement rather than a snapshot.
BRIEF_SERIES = """
    SELECT c.metric_key,
           c.statement,
           c.status,
           c.value_num,
           c.delta_num,
           c.source,
           c.as_of,
           c.uncomputed_reason,
           r.id           AS run_id,
           r.generated_at
      FROM brief_claims c
      JOIN brief_runs   r ON r.id = c.run_id
     WHERE r.id IN (SELECT id FROM brief_runs ORDER BY id DESC LIMIT 14)
     ORDER BY c.metric_key, r.id DESC
"""

BRIEF_LATEST = """
    SELECT id, generated_at, rendered_markdown, claims_total, claims_uncomputed
      FROM brief_runs
     ORDER BY id DESC
     LIMIT 1
"""


def brief_runs() -> list[dict[str, Any]]:
    return db.rows(BRIEF_RUNS)


def brief_latest() -> dict[str, Any] | None:
    return db.one(BRIEF_LATEST)


def brief_series() -> list[dict[str, Any]]:
    """Claims grouped by metric_key, newest first within each.

    Grouped here rather than in the template: a template that groups is a
    template that can silently drop a row, and the row it drops would be the
    one that stopped appearing — which is the finding.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for row in db.rows(BRIEF_SERIES):
        g = grouped.setdefault(row["metric_key"], {
            "metric_key": row["metric_key"],
            "statement": row["statement"],
            "source": row["source"],
            "points": [],
        })
        g["points"].append(row)
    # Uncomputed metrics first: what the pass cannot see is the part a reader
    # is most likely to skip and most needs to know.
    return sorted(
        grouped.values(),
        key=lambda g: (g["points"][0]["status"] != "UNCOMPUTED", g["metric_key"]))


# ---------------------------------------------------------------------------
# Candidates — the approval surface
# ---------------------------------------------------------------------------

CANDIDATES_OPEN = """
    SELECT c.id, c.batch_id, c.title, c.rationale, c.repo, c.objective_ref,
           c.evidence, c.suggested_paths, c.est_cost_gbp, c.disposition,
           b.source_document, b.source_sha, b.generated_at,
           -- How many times this has been carried without being ticked. A
           -- candidate carried five times is a finding in itself: either it is
           -- not worth doing or it is being avoided, and both are worth seeing.
           (SELECT count(*) FROM candidates o
             WHERE o.batch_id = c.batch_id AND o.id <= c.id
               AND o.disposition = 'NOT_NOW') AS times_passed_over
      FROM candidates c
      JOIN candidate_batches b ON b.id = c.batch_id
     WHERE c.disposition IN ('PENDING','NOT_NOW')
     ORDER BY c.batch_id DESC, c.id
"""

CANDIDATES_DECIDED = """
    SELECT c.id, c.title, c.repo, c.disposition, c.disposition_reason,
           c.decided_at, c.spec_task_id, c.work_task_id,
           d.reason AS batch_reason
      FROM candidates c
      LEFT JOIN decision_log d ON d.id = c.approval_decision_id
     WHERE c.disposition IN ('APPROVED','REJECTED')
     ORDER BY c.decided_at DESC NULLS LAST, c.id DESC
     LIMIT 50
"""

#: The two ceilings, read from the database rather than restated here. A
#: console that hard-coded 5 would disagree with the trigger the day the cap
#: moved, and would disagree silently.
CEILINGS = """
    SELECT fleet_max_queued_tasks()   AS max_queued,
           fleet_max_approval_batch() AS max_batch,
           (SELECT count(*) FROM tasks WHERE status = 'QUEUED') AS queued_now
"""


#: The month's credit position, or its refusal to state one. Read from the
#: database rather than recomputed here for the same reason CEILINGS is: a page
#: that did its own arithmetic would disagree with the trigger, and would
#: disagree silently. The row is COMPUTED with figures or UNCOMPUTED with a
#: reason and no figures, and the template must branch on that rather than
#: printing whatever is in remaining_gbp.
MONTH_CREDIT = "SELECT * FROM fleet_month_credit()"


def month_credit() -> dict[str, Any] | None:
    return db.one(MONTH_CREDIT)


def candidates_open() -> list[dict[str, Any]]:
    return db.rows(CANDIDATES_OPEN)


def candidates_decided() -> list[dict[str, Any]]:
    return db.rows(CANDIDATES_DECIDED)


def ceilings() -> dict[str, Any] | None:
    return db.one(CEILINGS)


# ---------------------------------------------------------------- the morning page
#
# One page, read once, by the person who owns every decision here. Everything
# below exists to fill a section of it, and each query is written so that the
# EMPTY answer is a fact rather than a gap: "no rows" must be renderable as
# "nothing is waiting on you", never as a blank panel.

#: The window. Not "today" and not "24 hours" -- the boundary is the previous
#: brief, because that is the last thing the reader was told. `compares_since`
#: on the latest run is the previous run's `generated_at`, recorded at the time
#: rather than recomputed, so a brief that ran late moves this boundary with it.
#:
#: NULL on the very first brief, and the caller renders that as "since the
#: beginning" rather than substituting now() and silently showing nothing.
MORNING_WINDOW = """
    SELECT id AS run_id, generated_at, compares_since,
           claims_total, claims_uncomputed
      FROM brief_runs ORDER BY id DESC LIMIT 1
"""

#: BLOCKERS 1 AND 2. Both are `READY_FOR_REVIEW`, and the split is on work
#: type, because a drafted spec and a built branch ask different things of a
#: reader. A spec asks "is this the right work"; a branch asks "is this the
#: right change". Collapsing them into "3 things to review" would hide which
#: question is being asked.
MORNING_AWAITING_YOU = """
    SELECT t.id, t.title, t.repo, t.branch_name, t.objective_ref,
           t.completed_at, t.attempts, t.max_attempts,
           t.acceptance_contract->>'work_type' AS work_type,
           (t.acceptance_contract->>'work_type' = 'draft_spec') AS is_spec,
           r.id AS run_id, r.committed_gbp,
           EXTRACT(EPOCH FROM (r.completed_at - r.started_at)) AS elapsed_seconds,
           agg.spent_all_runs, agg.runs_total
      FROM tasks t
      LEFT JOIN LATERAL (
          SELECT * FROM runs WHERE task_id = t.id ORDER BY id DESC LIMIT 1
      ) r ON true
      LEFT JOIN LATERAL (
          -- NOT coalesce(...,0). A task with no run has spent nothing we
          -- have a record of, which is not the same as having spent zero,
          -- and morning.money() renders NULL as the dot the rest of the page
          -- uses. The coalesce here was the one place a missing cost reached
          -- the reader as GBP 0.00.
          SELECT count(*) AS runs_total,
                 sum(committed_gbp) AS spent_all_runs
            FROM runs WHERE task_id = t.id
      ) agg ON true
     WHERE t.status = 'READY_FOR_REVIEW'
     ORDER BY t.completed_at DESC NULLS LAST, t.id DESC
"""

#: WHAT I DID, as threads. One row per candidate that has produced anything,
#: carrying both tasks and the decision that approved it.
#:
#: LEFT JOINs throughout and no WHERE on the window: a thread is filtered in
#: Python against the window because a thread STRADDLES it -- candidate 12 was
#: approved on 7 Sep and its code task was queued on 8 Sep, and a SQL window
#: over any single timestamp would either drop it or double it.
#:
#: `decided_via` IS SELECTED AND IT IS NOT DECORATION. Until 10 Sep 2026 every
#: approval on this host was a person clicking Accept, and the page said "you
#: approved it" without asking. console/autoapprove.py writes
#: `decided_via = 'unattended'`, and decisions 26 and 27 were already machine
#: approvals rendered as the reader's own act. A page that credits you with the
#: ranker's decision is wrong about the one thing it exists to tell you.
#:
#: There is no promotion step here any more. Moving a draft from drafts/ to
#: specs/ by hand stopped being part of this loop when console/autoqueue.py
#: began queueing the code task off the accepted draft; the draft stays in
#: drafts/ and the merge leaves rows like any other.
MORNING_THREADS = """
    SELECT c.id AS candidate_id, c.title, c.repo, c.objective_ref,
           c.disposition, c.decided_at, c.batch_id,

           d.id AS decision_id, d.reason AS decision_reason,
           d.decided_at AS decision_at, d.decided_by, d.decided_via,

           s.id AS spec_task_id, s.status AS spec_status,
           s.completed_at AS spec_completed_at, s.branch_name AS spec_branch,
           s.acceptance_contract->>'work_type' AS spec_work_type,
           sr.committed_gbp AS spec_cost,
           EXTRACT(EPOCH FROM (sr.completed_at - sr.started_at)) AS spec_elapsed,

           w.id AS work_task_id, w.status AS work_status,
           w.completed_at AS work_completed_at, w.branch_name AS work_branch,
           w.acceptance_contract->>'work_type' AS work_work_type,
           wr.committed_gbp AS work_cost,
           EXTRACT(EPOCH FROM (wr.completed_at - wr.started_at)) AS work_elapsed,

           -- HOW EACH MERGE HAPPENED, which `tasks.status` cannot say: it
           -- reads MERGED whoever merged it. Since 10 Sep 2026 both of these
           -- can be a timer, so the page stops assuming the reader did it.
           (SELECT hd.payload->>'decided_via'
              FROM run_steps hd JOIN runs hr ON hr.id = hd.run_id
             WHERE hr.task_id = s.id
               AND hd.step_type = 'HUMAN_DECISION'
             ORDER BY hd.id DESC LIMIT 1) AS spec_merged_via,
           (SELECT hd.payload->>'decided_via'
              FROM run_steps hd JOIN runs hr ON hr.id = hd.run_id
             WHERE hr.task_id = w.id
               AND hd.step_type = 'HUMAN_DECISION'
             ORDER BY hd.id DESC LIMIT 1) AS work_merged_via
      FROM candidates c
      LEFT JOIN decision_log d ON d.id = c.approval_decision_id
      LEFT JOIN tasks s ON s.id = c.spec_task_id
      LEFT JOIN tasks w ON w.id = c.work_task_id
      LEFT JOIN LATERAL (
          SELECT * FROM runs WHERE task_id = s.id ORDER BY id DESC LIMIT 1
      ) sr ON true
      LEFT JOIN LATERAL (
          SELECT * FROM runs WHERE task_id = w.id ORDER BY id DESC LIMIT 1
      ) wr ON true
     WHERE c.spec_task_id IS NOT NULL OR c.work_task_id IS NOT NULL
     ORDER BY c.id DESC
"""

#: Tasks that finished in the window and belong to NO candidate.
#:
#: Without this the page would be a lie by omission. Task 26 -- the net-refunds
#: code task -- was inserted directly, and a threads-only view would show its
#: candidate's thread while a directly-inserted task with no candidate at all
#: would vanish.
#:
#: WHAT LANDS HERE CHANGED ON 10 SEP 2026 and the old sentence would now
#: mislead. It said a code task has no candidate "because console/approve.py
#: only makes draft-spec tasks" -- still true of approve.py, but
#: console/autoqueue.py writes `candidates.work_task_id`, so a code task that
#: came from a ticked candidate is on that candidate's thread and not here.
#: What is left is what genuinely has no candidate: candidate-producer runs,
#: infrastructure, and anything queued by hand.
MORNING_LOOSE_TASKS = """
    SELECT t.id, t.title, t.status, t.repo, t.branch_name, t.objective_ref,
           t.completed_at, t.created_at, t.attempts,
           t.acceptance_contract->>'work_type' AS work_type,
           r.committed_gbp,
           EXTRACT(EPOCH FROM (r.completed_at - r.started_at)) AS elapsed_seconds,
           (SELECT hd.payload->>'decided_via'
              FROM run_steps hd JOIN runs hr ON hr.id = hd.run_id
             WHERE hr.task_id = t.id
               AND hd.step_type = 'HUMAN_DECISION'
             ORDER BY hd.id DESC LIMIT 1) AS merged_via
      FROM tasks t
      LEFT JOIN LATERAL (
          SELECT * FROM runs WHERE task_id = t.id ORDER BY id DESC LIMIT 1
      ) r ON true
     WHERE NOT EXISTS (SELECT 1 FROM candidates c
                        WHERE c.spec_task_id = t.id OR c.work_task_id = t.id)
     ORDER BY t.completed_at DESC NULLS LAST, t.id DESC
"""

#: Every task that reached a terminal state, with its verification failure if
#: it had one. Feeds both the thread steps and the failure-pattern detection:
#: two specs failing the same check for the same reason is one finding, not two
#: rows, and the reason lives in the VERIFICATION_RUN step rather than on the
#: task.
#: `payload->'checks'` is an ARRAY -- one entry per verification command, each
#: with its own exit_code and output_tail. A task failing two checks has two
#: reasons, and reading `payload->>'command'` off the top level (which does not
#: exist) would have silently produced no reasons at all rather than an error.
#:
#: Only non-zero checks. A run that failed its second command still ran its
#: first, and the passing one is not why the task failed.
MORNING_FAILURES = """
    SELECT t.id AS task_id, t.title, t.completed_at,
           t.acceptance_contract->>'work_type' AS work_type,
           chk->>'command'          AS command,
           (chk->>'exit_code')::int AS exit_code,
           chk->>'output_tail'      AS output_tail,
           (chk->>'timed_out')::bool AS timed_out
      FROM tasks t
      JOIN runs r ON r.task_id = t.id
      JOIN run_steps s ON s.run_id = r.id AND s.step_type = 'VERIFICATION_RUN'
      CROSS JOIN LATERAL jsonb_array_elements(s.payload->'checks') chk
     WHERE t.status = 'FAILED'
       AND coalesce((chk->>'exit_code')::int, 0) <> 0
     ORDER BY t.completed_at DESC NULLS LAST, t.id DESC
"""

#: WHAT I'M DOING NEXT: the queue in the order the runner will actually claim
#: it. `(priority, id)` is claim_task()'s own ORDER BY, so this is intent
#: rather than a listing -- the top row is the next thing that will happen.
MORNING_QUEUE = """
    SELECT t.id, t.title, t.repo, t.objective_ref, t.created_at,
           t.max_cost_gbp, t.timeout_seconds, t.priority,
           t.acceptance_contract->>'work_type' AS work_type,
           c.id AS candidate_id, c.title AS candidate_title
      FROM tasks t
      LEFT JOIN candidates c
             ON c.spec_task_id = t.id OR c.work_task_id = t.id
     WHERE t.status = 'QUEUED'
     ORDER BY t.priority, t.id
"""

#: WHAT I COULDN'T SEE. The latest brief's uncomputed claims, each with how
#: many consecutive briefs it has been uncomputed for.
#:
#: The streak is the part that matters. A claim uncomputed once is a source
#: that blinked; a claim uncomputed for eleven briefs is a standing gap nobody
#: has closed, and only the second is worth asking for reach over. Counted from
#: the newest run backwards and stopped at the first brief where the metric was
#: computed, so a gap that was closed and reopened reports the CURRENT streak.
MORNING_UNSEEN = """
    WITH latest AS (SELECT max(id) AS id FROM brief_runs)
    SELECT c.metric_key, c.statement, c.uncomputed_reason,
           (SELECT count(*) FROM brief_claims h
             WHERE h.metric_key = c.metric_key
               AND h.status = 'UNCOMPUTED'
               AND h.run_id > coalesce(
                   (SELECT max(g.run_id) FROM brief_claims g
                     WHERE g.metric_key = c.metric_key
                       AND g.status = 'COMPUTED'), 0)) AS briefs_running
      FROM brief_claims c, latest
     WHERE c.run_id = latest.id AND c.status = 'UNCOMPUTED'
     ORDER BY c.metric_key
"""

#: The month's ceiling position, for the blockers section. Distinct from
#: month_credit() only in intent: this one is asked so the page can say "you
#: need to record a reading", not so it can print a figure.
MORNING_QUEUE_DEPTH = """
    SELECT fleet_max_queued_tasks() AS max_queued,
           (SELECT count(*) FROM tasks WHERE status = 'QUEUED') AS queued_now,
           (SELECT count(*) FROM candidates
             WHERE disposition IN ('PENDING','NOT_NOW')) AS candidates_open
"""


#: Every task a merge could name, with whether anything records its delivery.
#:
#: ONE QUERY FOR THE WHOLE SWEEP. console/morning.unrecorded_merges walks git
#: for merge commits naming a task and asks, per task, "is it MERGED, or does a
#: decision cite it". Asking the database once per merge would make a reading
#: that costs a second cost a page load.
#:
#: `repo`/`base_branch` come back too, so the caller knows which repositories
#: and branches to walk without a list typed anywhere.
MORNING_MERGE_RECORD = """
    SELECT t.id, t.status, t.repo, t.base_branch,
           coalesce(array_agg(d.id) FILTER (WHERE d.id IS NOT NULL), '{}') AS decision_ids
      FROM tasks t
      LEFT JOIN decision_log d ON d.task_id = t.id
     GROUP BY t.id, t.status, t.repo, t.base_branch
"""


def morning_merge_record() -> list[dict[str, Any]]:
    return db.rows(MORNING_MERGE_RECORD)


def morning_repo_branches() -> list[tuple]:
    """The (repo, base_branch) pairs Fleet actually works in, from the tasks.

    Derived rather than typed: a repository nobody has a task in has no merge
    of Fleet's to miss, and a new one appears here the moment it has one.
    """
    seen = {(r["repo"], r["base_branch"]) for r in db.rows(MORNING_MERGE_RECORD)
            if r["repo"] and r["base_branch"]}
    return sorted(seen)


def morning_window() -> dict[str, Any] | None:
    return db.one(MORNING_WINDOW)


def morning_awaiting_you() -> list[dict[str, Any]]:
    return db.rows(MORNING_AWAITING_YOU)


def morning_threads() -> list[dict[str, Any]]:
    return db.rows(MORNING_THREADS)


def morning_loose_tasks() -> list[dict[str, Any]]:
    return db.rows(MORNING_LOOSE_TASKS)


def morning_failures() -> list[dict[str, Any]]:
    return db.rows(MORNING_FAILURES)


def morning_queue() -> list[dict[str, Any]]:
    return db.rows(MORNING_QUEUE)


def morning_unseen() -> list[dict[str, Any]]:
    return db.rows(MORNING_UNSEEN)


def morning_queue_depth() -> dict[str, Any] | None:
    return db.one(MORNING_QUEUE_DEPTH)


#: Every metric_key in the latest brief, computed AND uncomputed.
#:
#: Feeds morning.uninstrumented_objectives(), which needs "is this objective
#: represented at all" rather than "did it compute". An objective whose claim
#: failed has a broken source; one with no key here was never instrumented, and
#: those are different failures that must not be listed together.
MORNING_CLAIM_KEYS = """
    SELECT metric_key FROM brief_claims
     WHERE run_id = (SELECT max(id) FROM brief_runs)
"""


def morning_claim_keys() -> list[str]:
    return [r["metric_key"] for r in db.rows(MORNING_CLAIM_KEYS)]


#: Runs that finished inside the window. THE DENOMINATOR for a failure pattern.
#:
#: "2 of 4" has to mean two of the four things that actually ran, not two of
#: everything visible on the page. A pattern claims something about a step, and
#: a denominator counting threads that did not run in the window would dilute
#: the claim precisely when it is most worth making.
MORNING_RUNS_IN_WINDOW = """
    SELECT count(*) AS n FROM runs
     WHERE task_id IS NOT NULL
       AND completed_at IS NOT NULL
       AND (%(since)s::timestamptz IS NULL OR completed_at >= %(since)s)
"""


def morning_runs_in_window(since) -> int:
    row = db.one(MORNING_RUNS_IN_WINDOW, {"since": since})
    return int(row["n"]) if row else 0


#: WHAT THE NIGHT DECIDED, approvals AND refusals, in one list.
#:
#: THE REFUSALS ARE THE POINT. `approve.record_unattended_refusal` exists
#: because until it did, "the ranker refused because no key separated the top
#: two" and "the timer never fired" left the same trace, which is none. A page
#: reading only approvals would report both as a quiet night.
#:
#: So this returns every unattended decision in the window and the page pairs
#: it with the unit's own record of whether it ran. A row and no run is
#: impossible; a run and no row means the sweep died before it decided, and
#: neither of those is "nothing happened".
MORNING_UNATTENDED_NIGHT = """
    SELECT d.id, d.subject, d.decision, d.reason, d.decided_at, d.mechanics,
           (SELECT count(*) FROM jsonb_array_elements(d.evidence) e
             WHERE e->>'kind' = 'candidate') AS considered
      FROM decision_log d
     WHERE d.decided_via = 'unattended'
       AND (%(since)s::timestamptz IS NULL OR d.decided_at >= %(since)s)
     ORDER BY d.decided_at DESC
"""


def morning_unattended_night(since) -> list[dict[str, Any]]:
    return db.rows(MORNING_UNATTENDED_NIGHT, {"since": since})


#: EVERY MERGE NOBODY READ, with the spec it was judged against.
#:
#: specs/auto-approval.md §9.9. Four green checks establish that the tree
#: typechecks, that the suite passes, that one new test bites and that no pair
#: landed in half. They establish nothing about whether the spec was followed,
#: and since 10 Sep 2026 there is no reader on any path -- `auto_merge` is
#: `true` on the frontend contract and `draft_spec` came off
#: console/automerge.py's NEVER_UNATTENDED.
#:
#: `spec_md` comes back whole because console/requirements.py parses it. The
#: parse is deliberately not done in SQL: it is a display decision about what
#: counts as a numbered requirement, and §9.12 records what happens when that
#: judgement is made by something that cannot be read.
#:
#: The merge's own identity is on the HUMAN_DECISION step rather than on the
#: task, because `tasks.status` says MERGED whoever merged it. That column
#: cannot answer "did a person look at this", which is the only question here.
MORNING_UNREAD_SPECS = """
    SELECT t.id AS task_id, t.title, t.repo, t.spec_md, t.branch_name,
           t.acceptance_contract->>'work_type' AS work_type,
           s.created_at AS merged_at,
           s.payload->'merge'->>'merge_commit' AS merge_commit
      FROM tasks t
      JOIN runs r ON r.task_id = t.id
      JOIN run_steps s ON s.run_id = r.id AND s.step_type = 'HUMAN_DECISION'
     WHERE s.payload->>'decided_via' = 'unattended'
       AND (%(since)s::timestamptz IS NULL OR s.created_at >= %(since)s)
     ORDER BY s.created_at DESC
"""


def morning_unread_specs(since) -> list[dict[str, Any]]:
    return db.rows(MORNING_UNREAD_SPECS, {"since": since})
