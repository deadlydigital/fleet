"""The daily pass: read, claim, render, record.

TWO CONNECTIONS, TWO IDENTITIES, AND THAT IS THE DESIGN
--------------------------------------------------------
Reads go through `dd_detector_login`, which holds SELECT and nothing else, on
`deadly_digital` and `fleet`. The write goes through `fleet_brief_writer_login`,
which holds INSERT on two tables and can read nothing at all -- not the brief
tables, not the business.

One identity doing both is the boundary the rest of this system spends effort
defending, and collapsing it here for the convenience of a single connection
string would undo `detectors/reconciliation.py`'s read-only guarantee and
RECONCILIATION-RUNS §4.2 in one step.

A consequence, stated because it is real: the read and the write are not one
transaction and cannot be. Every claim carries its own `as_of` for that reason.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import psycopg

from . import sources as S
from .claims import Claim
from .todo import read_todo
from .render import render

log = logging.getLogger(__name__)

FLEET_REPO = "/home/ubuntu/fleet"
PLATFORM_REPO = "/home/ubuntu/deadly-digital-platform"
OBJECTIVES = Path(FLEET_REPO) / "objectives-2026-Q4.yaml"

#: Briefs on disk, beside the database copy. Not a cache and not a fallback:
#: the same text, in the form you would actually reach for three weeks later
#: when something looks off — greppable across days, diffable between them, and
#: still there if the database is not.
#:
#: The database copy stays canonical for comparison, because the claims carry
#: the structure the file does not.
BRIEF_DIR = Path(FLEET_REPO) / "briefs"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _write_to_disk(generated: datetime, markdown: str) -> Optional[str]:
    """Write briefs/YYYY-MM-DD.md. Never raises; a failure is reported, not fatal.

    A brief that reached the database and not the disk is still a brief. Losing
    the pass over the second copy would trade the record for the convenience.

    Two passes on one day overwrite rather than accumulate: the file is named
    for the day it describes, and the database holds every pass. A `-2` suffix
    would put the ordering question on a filename, and the run ids already
    answer it.
    """
    try:
        BRIEF_DIR.mkdir(parents=True, exist_ok=True)
        path = BRIEF_DIR / f"{generated.date().isoformat()}.md"
        path.write_text(markdown, encoding="utf-8")
        return str(path)
    except Exception as exc:
        log.warning("brief not written to disk: %s", exc)
        return None


def _objectives_version() -> str:
    try:
        return hashlib.sha256(OBJECTIVES.read_bytes()).hexdigest()[:16]
    except Exception:
        return "unreadable"


# ---------------------------------------------------------------------------
# Standing uncomputed claims — the ones that are true every single day
# ---------------------------------------------------------------------------
#
# These are not failures of the pass. They are the honest state of what is
# reachable from this host, and they appear in every brief until that changes.
# Printing them daily is the point: a gap that is only mentioned once is a gap
# everyone forgets.


# ---------------------------------------------------------------------------
# OVERNIGHT — what the fleet itself did
#
# specs/unattended-operation.md §4. The rest of this pass reports how the
# world's numbers moved; this reports what this system DID, which on an
# unattended night is the only section a reader must not miss.
#
# It is description, not judgement. LOOKS_WRONG stays empty for the reasons
# brief/render.py gives. "Three merged, one failed" is a fact; whether that
# was a good night is the reader's call.
# ---------------------------------------------------------------------------

_OVERNIGHT_RUNS_SQL = """
    SELECT r.id, r.task_id, t.title, t.repo, t.status AS task_status,
           r.status AS run_status, r.committed_gbp, r.completed_at,
           (SELECT s.payload->>'result' FROM run_steps s
             WHERE s.run_id = r.id AND s.step_type = 'VERIFICATION_RUN'
             ORDER BY s.id DESC LIMIT 1) AS verdict,
           (SELECT s.payload->>'verification_unresolved' FROM run_steps s
             WHERE s.run_id = r.id AND s.step_type = 'VERIFICATION_RUN'
             ORDER BY s.id DESC LIMIT 1) AS unresolved,
           (SELECT s.payload->'boundary_violations' FROM run_steps s
             WHERE s.run_id = r.id AND s.step_type = 'VERIFICATION_RUN'
             ORDER BY s.id DESC LIMIT 1) AS violations
      FROM runs r JOIN tasks t ON t.id = r.task_id
     WHERE r.completed_at > %(since)s
     ORDER BY r.completed_at
"""


def _failure_class(row) -> str:
    """Why a run ended badly, as a CLASS rather than a message.

    Boundary violation, could-not-verify and verification-failed are three
    different mornings and must not read alike -- the first is the task
    exceeding its contract, the second is the fleet unable to judge, and only
    the third is the code being wrong. Reading them as one is how a missing
    checker got reported as a failing check on 9 Sep.
    """
    if row["violations"]:
        v = row["violations"]
        if v.get("protected") or v.get("outside_writable"):
            return "wrote outside its contract"
        if v.get("over_diff_limit"):
            return "exceeded its diff limit"
    if row["unresolved"]:
        return "could not be verified (a checker was missing)"
    if row["verdict"] == "FAIL":
        return "verification failed"
    return "failed before verification"


def _overnight_claims(r: S.Reader, since) -> List[Claim]:
    out: List[Claim] = []
    key = "overnight.runs"
    label = "what the fleet did since the last brief"

    if since is None:
        return [Claim.uncomputed(key, label, reason=(
            "there is no previous brief, so there is no window to report over. "
            "This is the first pass, not a quiet night"))]

    rows = r.probe("fleet:runs/overnight",
                   S.rows(_OVERNIGHT_RUNS_SQL, {"since": since}))
    if rows is None:
        return [Claim.uncomputed(key, label, reason=(
            r.failed("fleet:runs/overnight")
            or "the runs table could not be read, so what happened overnight "
               "is unknown. An unreadable night is not a quiet one"))]

    now = _utcnow()
    if not rows:
        out.append(Claim.overnight(
            key, "nothing ran since the last brief", source="fleet:runs",
            as_of=now, value_num=0, query_key="overnight_runs",
            query_version=1))
        return out

    merged = [x for x in rows if x["task_status"] == "MERGED"]
    failed = [x for x in rows if x["task_status"] == "FAILED"]
    waiting = [x for x in rows if x["task_status"] == "READY_FOR_REVIEW"]
    spent = sum((x["committed_gbp"] or 0) for x in rows)

    parts = [f"{len(merged)} merged", f"{len(failed)} failed"]
    if waiting:
        parts.append(f"{len(waiting)} waiting for review")
    out.append(Claim.overnight(
        key, f"{len(rows)} run(s) finished: " + ", ".join(parts),
        source="fleet:runs", as_of=now, value_num=len(rows),
        query_key="overnight_runs", query_version=1))

    # One line per run, so a bad night is legible without opening the console.
    for x in rows:
        verdict = x["task_status"]
        detail = _failure_class(x) if x["task_status"] == "FAILED" else verdict.lower()
        out.append(Claim.overnight(
            f"overnight.task.{x['task_id']}",
            f"task {x['task_id']} ({x['repo']}) — {detail}: "
            f"{(x['title'] or '')[:70]} — GBP {x['committed_gbp']}",
            source="fleet:runs", as_of=x["completed_at"] or now,
            value_text=verdict, query_key="overnight_task", query_version=1))

    # SPEND AS A RATE. "GBP 141 left" is useless without "how many nights".
    # A number that only becomes alarming on the last day is not a control.
    credit = r.probe("fleet:model_credit_pool",
                     S.row("SELECT * FROM fleet_month_credit()"))
    if credit is None or credit[1] != "COMPUTED":
        out.append(Claim.uncomputed(
            "overnight.spend", "spend since the last brief, against the pool",
            reason=("the monthly credit position is unknown, so what was spent "
                    "cannot be set against what remains")))
    else:
        remaining = credit[6]
        nights = int(remaining / spent) if spent else None
        statement = f"GBP {spent:.2f} spent since the last brief; GBP {remaining:.2f} remains"
        if nights is not None:
            statement += f" — {nights} more night(s) at this rate"
        out.append(Claim.overnight(
            "overnight.spend", statement, source="fleet:model_credit_pool",
            as_of=now, value_num=spent, query_key="overnight_spend",
            query_version=1))

    return out


def _deploy_claims() -> List[Claim]:
    """Is production running what main says? Read from outside the database.

    No run ever reaches DEPLOYED and the runner is not a deployer, so the
    fleet database cannot answer this. console/deploys.py already reads the
    cron'd drift checks, and its freshness rule matters more here than on the
    page: a state file nobody has written for an hour is the answer from
    whenever the CHECK died, not today's answer.
    """
    key = "overnight.deployed"
    try:
        from console import deploys
        found = deploys.all_deployments()
    except Exception as exc:                                  # noqa: BLE001
        return [Claim.uncomputed(key, "whether production is running main",
                                 reason=f"the deploy state could not be read: {exc}")]
    if not found:
        return [Claim.uncomputed(key, "whether production is running main",
                                 reason="no deploy state files were found")]
    out: List[Claim] = []
    for name, d in sorted(found.items()):
        if d.status in ("UNKNOWN", None):
            out.append(Claim.uncomputed(
                f"{key}.{name}", f"whether {name} is running main",
                reason=d.detail or "the drift check reported no verdict"))
            continue
        out.append(Claim.overnight(
            f"{key}.{name}",
            f"{name}: production {'matches' if d.status == 'OK' else 'DOES NOT match'} "
            f"main ({d.status})",
            source=f"file:drift-{name}.state", as_of=d.checked_at or _utcnow(),
            value_text=d.status, query_key="deploy_drift", query_version=1))
    return out


def _standing_gaps() -> List[Claim]:
    return [
        Claim.uncomputed(
            "ci.build_status",
            "whether the build is green",
            reason=("GitHub Actions is unreadable from this host: `gh` is not "
                    "installed and the repository is private")),
        Claim.uncomputed(
            "dd.daily_metrics",
            "revenue trend from daily_metrics",
            reason=("dd_detector_login has SELECT on analytics_<t>.orders only. "
                    "Order-derived counts appear above and are labelled as "
                    "such rather than presented as revenue")),
    ]


# ---------------------------------------------------------------------------
# The reads
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Sentry
#
# THE GUARANTEE THIS FUNCTION EXISTS FOR:
#   "no unresolved issues" can never be printed while the query cannot run.
#
# It is structural, not a matter of care. The claim is derived from the newest
# RUN and its status, never from the newest OBSERVATION. Reading the newest
# observation would print yesterday's zero on a day the token expired -- the
# number would be real, correctly recorded, and describing a moment nobody
# asked about. That is the exact shape of every defect this system has spent
# its time removing, and it renders as reassurance.
#
# Four states, and only one of them prints a number:
#   no run ever      -> UNCOMPUTED, the detector has never run
#   newest run not OK-> UNCOMPUTED, carrying the run's own error text
#   newest run stale -> UNCOMPUTED, naming how old it is
#   newest run OK    -> COMPUTED, and a zero here is a zero the run
#                       established rather than one it failed to disprove
# ---------------------------------------------------------------------------

SENTRY_DETECTOR = "dd_api_errors"

#: A run older than this is not today's answer. Derived from the registry
#: rather than typed: cadence + grace is exactly when the heartbeat considers
#: the detector overdue, so the brief and the heartbeat agree by construction
#: instead of by two numbers that drift.
_SENTRY_RUN_SQL = """
SELECT r.id, r.status, r.completed_at, r.window_end, r.error,
       r.subjects_failed,
       reg.cadence + reg.grace AS allowance,
       now() - r.window_end    AS age,
       -- ISSUES from the evidence, EVENTS from magnitude. Magnitude is the
       -- event volume that severity bands on; the count of issues is what a
       -- person reads first, and it is deliberately not the same number.
       (SELECT sum((o.evidence_sample ->> 'unresolved_issues')::int)
          FROM observations o
         WHERE o.detector_run_id = r.id
           AND o.observation_type = 'SENTRY_UNRESOLVED_ISSUES') AS unresolved,
       (SELECT sum(o.magnitude)::bigint FROM observations o
         WHERE o.detector_run_id = r.id
           AND o.observation_type = 'SENTRY_UNRESOLVED_ISSUES') AS events,
       (SELECT max(o.evidence_sample ->> 'worst_short_id') FROM observations o
         WHERE o.detector_run_id = r.id
           AND o.observation_type = 'SENTRY_UNRESOLVED_ISSUES') AS worst
  FROM detector_runs r
  JOIN detector_registry reg
    ON reg.detector_key = r.detector_key
   AND reg.issue_key_version = r.issue_key_version
   AND reg.product = r.product
 WHERE r.detector_key = %(k)s
   AND r.run_mode = 'SCHEDULED'
   AND r.status <> 'RUNNING'
 ORDER BY r.window_end DESC
 LIMIT 1
"""


# ---------------------------------------------------------------------------
# AWS cost
#
# `cost-discipline` carried a STANDING UNCOMPUTED claim on every brief ever
# written, because nothing on this host could read the bill. Cost Explorer
# access closed that, and this reports what dd_aws_cost established.
#
# It reads the RUN, for the reason `_sentry_claims` does: a stale figure from
# the last successful check, printed on a morning the check failed, is a true
# number about a moment nobody asked about.
#
# WHAT IT CANNOT SAY, AND THIS IS A REAL LIMIT
#
# Below the ceiling the detector emits NO observation -- an observation
# creates an issue, and an always-open issue for ordinary spend is noise. So
# on a healthy month the brief can say the objective is being met and cannot
# say by how much. The percent appears only once the ceiling is crossed,
# which is the moment the number starts mattering. Reporting the daily figure
# regardless would need somewhere to put a level that is not an issue, and
# that is a table nobody has asked for yet.
# ---------------------------------------------------------------------------

AWS_DETECTOR = "dd_aws_cost"

_AWS_RUN_SQL = """
SELECT r.status, r.completed_at, r.error, r.subjects_failed,
       reg.cadence + reg.grace AS allowance,
       -- completed_at, not window_end. See _sentry_claims: settle_lag makes
       -- the window legitimately old while the run is fresh, and this
       -- detector's settle_lag is a full day.
       now() - r.completed_at  AS age,
       (SELECT max(o.magnitude) FROM observations o
         WHERE o.detector_run_id = r.id
           AND o.observation_type = 'AWS_SPEND_VS_CEILING') AS percent,
       (SELECT max(o.evidence_sample ->> 'spend_quote') FROM observations o
         WHERE o.detector_run_id = r.id
           AND o.observation_type = 'AWS_SPEND_VS_CEILING') AS spend_quote
  FROM detector_runs r
  JOIN detector_registry reg
    ON reg.detector_key = r.detector_key
   AND reg.issue_key_version = r.issue_key_version
   AND reg.product = r.product
 WHERE r.detector_key = %(k)s
   AND r.run_mode = 'SCHEDULED'
   AND r.status <> 'RUNNING'
 ORDER BY r.window_end DESC
 LIMIT 1
"""


def _aws_cost_claims(r: S.Reader) -> List[Claim]:
    key = "cost.aws.vs_ceiling"
    try:
        from proposer import config as pconfig
        from proposer.objectives import load as load_objectives
        ceiling = load_objectives(
            pconfig.PROJECT_ROOT / "objectives-2026-Q4.yaml"
        ).require("cost-discipline").ceiling
        ceiling_text = ceiling.describe()
    except Exception as exc:                                  # noqa: BLE001
        return [Claim.uncomputed(
            key, "AWS spend against the cost-discipline ceiling",
            reason=f"the objectives file could not be read: {exc}")]

    label = f"AWS spend against the {ceiling_text} ceiling"
    name = "fleet:detector_runs/dd_aws_cost"
    row = r.probe(name, S.row(_AWS_RUN_SQL, {"k": AWS_DETECTOR}))
    if row is None:
        failed = r.failed(name)
        return [Claim.uncomputed(key, label, reason=failed or (
            f"the {AWS_DETECTOR} detector has never completed a scheduled "
            f"run, so nothing has read Cost Explorer. This is not a report "
            f"that spend is within the ceiling"))]

    status, completed_at, error, failed_subjects, allowance, age, percent, spend = row

    if status != "OK":
        detail = (error or "").strip() or "no error text was recorded"
        return [Claim.uncomputed(key, label, reason=(
            f"the newest {AWS_DETECTOR} run closed {status}: {detail[:240]}. "
            f"A month with no recorded fx_rate reading lands here, and that "
            f"is the detector refusing to compare dollars to pounds rather "
            f"than a report that spend is fine"))]

    if allowance is not None and age is not None and age > allowance:
        return [Claim.uncomputed(key, label, reason=(
            f"the newest {AWS_DETECTOR} run completed {_age(age)} ago, past "
            f"its {_age(allowance)} cadence and grace"))]

    if percent is None:
        # Under the ceiling. A fact the run established, with no number
        # behind it -- see the note above.
        return [Claim.computed(
            key, f"AWS spend is within the {ceiling_text} ceiling",
            source=f"aws:cost-explorer via fleet:{AWS_DETECTOR}",
            as_of=completed_at or _utcnow(),
            value_text=f"under {ceiling_text}",
            query_key="aws_cost_vs_ceiling", query_version=1)]

    pct = int(percent)
    statement = f"AWS spend is {pct}% of the {ceiling_text} ceiling"
    if spend:
        statement += f" ({spend} {ceiling.currency} month to date)"
    return [Claim.computed(
        key, statement, source=f"aws:cost-explorer via fleet:{AWS_DETECTOR}",
        as_of=completed_at or _utcnow(), value_num=pct,
        query_key="aws_cost_vs_ceiling", query_version=1)]


def _sentry_claims(r: S.Reader) -> List[Claim]:
    name = "fleet:detector_runs/dd_api_errors"
    key = "sentry.unresolved_issues"
    label = "unresolved Sentry issues in the API project"

    row = r.probe(name, S.row(_SENTRY_RUN_SQL, {"k": SENTRY_DETECTOR}))
    if row is None:
        failed = r.failed(name)
        if failed:
            return [Claim.uncomputed(key, label, reason=failed)]
        return [Claim.uncomputed(
            key, label,
            reason=(f"the {SENTRY_DETECTOR} detector has never completed a "
                    f"scheduled run, so nothing has read Sentry. This is not "
                    f"a report of zero errors"))]

    (_id, status, completed_at, _window_end, error, failed_subjects,
     allowance, age, unresolved, events, worst) = row

    if status != "OK":
        detail = (error or "").strip() or "no error text was recorded"
        who = (", ".join(failed_subjects) if failed_subjects else "the project")
        return [Claim.uncomputed(
            key, label,
            reason=(f"the newest {SENTRY_DETECTOR} run closed {status} and "
                    f"could not read {who}: {detail[:220]}. Sentry may hold "
                    f"errors that are not counted here"))]

    if allowance is not None and age is not None and age > allowance:
        return [Claim.uncomputed(
            key, label,
            reason=(f"the newest {SENTRY_DETECTOR} run covers a window that "
                    f"closed {_age(age)} ago, past its {_age(allowance)} "
                    f"cadence and grace, so it is not today's answer"))]

    count = int(unresolved or 0)
    statement = f"{count} {label}"
    if count:
        statement += f" over {int(events or 0)} event(s)"
        if worst:
            statement += f"; largest is {worst}"
    return [Claim.computed(
        key, statement, source=f"sentry via fleet:{SENTRY_DETECTOR}",
        # as_of is when the RUN established it, not when the brief read the
        # row. A brief at 07:45 reporting a 07:30 detector run is as_of 07:30.
        as_of=completed_at or _utcnow(), value_num=count,
        query_key="sentry_unresolved_issues", query_version=1)]


def _age(delta) -> str:
    total = int(delta.total_seconds())
    if total >= 86400:
        return f"{total // 86400}d {(total % 86400) // 3600}h"
    if total >= 3600:
        return f"{total // 3600}h {(total % 3600) // 60}m"
    return f"{total // 60}m"



def _business_claims(r: S.Reader) -> List[Claim]:
    """What the platform looks like. Three tables and orders, per the grants."""
    out: List[Claim] = []

    tenants = r.probe("deadly_digital:public.tenants",
                      S.scalar("SELECT count(*) FROM tenants WHERE is_active"))
    if tenants is not None:
        out.append(Claim.computed(
            "dd.tenants.active", f"{tenants} active tenants",
            source="deadly_digital:public.tenants", as_of=_utcnow(),
            value_num=tenants, query_key="tenants_active", query_version=1))
    else:
        out.append(Claim.uncomputed(
            "dd.tenants.active", "active tenant count",
            reason=r.failed("deadly_digital:public.tenants") or "unreadable"))

    for tenant_id in (1, 2):
        key = f"dd.analytics_{tenant_id}.orders"
        name = f"deadly_digital:analytics_{tenant_id}.orders"
        # as_of is MAX(created_at), not now(): the instant the value DESCRIBES.
        res = r.probe(name, S.row(
            f"SELECT count(*), max(created_at) FROM analytics_{tenant_id}.orders"))
        if res is not None and res[0] is not None:
            count, newest = res
            out.append(Claim.computed(
                f"{key}.count",
                f"analytics_{tenant_id} holds {count} orders "
                f"(order rows, not revenue)",
                source=name, as_of=newest or _utcnow(), value_num=count,
                query_key="orders_count", query_version=1))
        else:
            out.append(Claim.uncomputed(
                f"{key}.count", f"order count for analytics_{tenant_id}",
                reason=r.failed(name) or "unreadable"))
    return out


def _fleet_claims(r: S.Reader, since: Optional[datetime]) -> List[Claim]:
    """What fleet did, decided, and is carrying."""
    out: List[Claim] = []
    window = since or (_utcnow() - timedelta(days=1))

    probes = [
        ("fleet:decision_log", "fleet.decisions.total",
         "decisions recorded", "SELECT count(*) FROM decision_log"),
        ("fleet:issues", "fleet.issues.open",
         "open issues", "SELECT count(*) FROM issues WHERE status='OPEN'"),
        ("fleet:proposals", "fleet.proposals.total",
         "proposals raised", "SELECT count(*) FROM proposals"),
        ("fleet:tasks", "fleet.tasks.total",
         "tasks recorded", "SELECT count(*) FROM tasks"),
        ("fleet:observations", "fleet.observations.total",
         "observations recorded", "SELECT count(*) FROM observations"),
    ]
    for name, key, label, sql in probes:
        value = r.probe(name, S.scalar(sql))
        if value is not None:
            out.append(Claim.computed(
                key, f"{value} {label}", source=name, as_of=_utcnow(),
                value_num=value, query_key=key, query_version=1))
        else:
            out.append(Claim.uncomputed(
                key, label, reason=r.failed(name) or "unreadable"))

    # The one decision_log question worth asking daily, and the reason the
    # grant was worth making: of what was decided, what has actually happened?
    name = "fleet:decision_outcomes"
    res = r.probe(name, S.row(
        "SELECT count(*) FILTER (WHERE decision='DEFERRED'), count(*) "
        "FROM decision_outcomes"))
    if res is not None:
        deferred, total = res
        out.append(Claim.computed(
            "fleet.decisions.deferred",
            f"{deferred} of {total} recorded decisions are still DEFERRED",
            source=name, as_of=_utcnow(), value_num=deferred,
            query_key="decisions_deferred", query_version=1))
    else:
        out.append(Claim.uncomputed(
            "fleet.decisions.deferred", "deferred decisions",
            reason=r.failed(name) or "unreadable"))

    # Detector activity. A detector that stopped running is invisible in every
    # other figure, because its absence looks like a quiet day.
    name = "fleet:detector_runs"
    res = r.probe(name, S.row(
        "SELECT count(*), max(started_at) FROM detector_runs "
        "WHERE started_at > %(since)s", {"since": window}))
    if res is not None:
        n, newest = res
        out.append(Claim.computed(
            "fleet.detector_runs.recent",
            f"{n} detector run(s) since the last brief",
            source=name, as_of=newest or _utcnow(), value_num=n,
            query_key="detector_runs_recent", query_version=1))
    else:
        out.append(Claim.uncomputed(
            "fleet.detector_runs.recent", "recent detector runs",
            reason=r.failed(name) or "unreadable"))
    return out


def _git_claims(since: Optional[datetime]) -> List[Claim]:
    """Engineering time, which the objectives call the binding constraint."""
    out: List[Claim] = []
    window = since or (_utcnow() - timedelta(days=1))
    for label, repo in (("fleet", FLEET_REPO), ("platform", PLATFORM_REPO)):
        n = S.commits_since(repo, window)
        at = S.last_commit_at(repo)
        key = f"git.{label}.commits"
        if n is None or at is None:
            out.append(Claim.uncomputed(
                key, f"commits in the {label} repo",
                reason=f"git in {repo} did not answer"))
            continue
        out.append(Claim.computed(
            key, f"{n} commit(s) in the {label} repo since the last brief",
            source=f"git:{label}", as_of=at, value_num=n,
            query_key="commits_since", query_version=1))
    return out


def _todo_claims() -> List[Claim]:
    """docs/TODO.md, the real issue tracker, with its gaps named.

    Two claims and one refusal. The refusal is the interesting one: over half
    the entries carry no `**Status:**` line, and this reports that count rather
    than treating "no status" as OPEN or dropping them from the total.
    """
    out: List[Claim] = []
    r = read_todo(f"{PLATFORM_REPO}/docs/TODO.md")

    if r.error or r.as_of is None:
        return [Claim.uncomputed("todo.entries", "the TODO.md issue tracker",
                                 reason=r.error or "unreadable")]

    out.append(Claim.computed(
        "todo.entries",
        f"{r.entries} dated entries in docs/TODO.md",
        source="file:docs/TODO.md", as_of=r.as_of, value_num=r.entries,
        query_key="todo_entries", query_version=1))

    out.append(Claim.computed(
        "todo.open",
        f"{r.open_entries} of them are marked OPEN "
        f"({sum(r.by_status.values())} declare a status this parser knows)",
        source="file:docs/TODO.md", as_of=r.as_of, value_num=r.open_entries,
        query_key="todo_open", query_version=1))

    if r.uncounted:
        sample = ", ".join(r.entries_without_status[:5])
        more = "" if len(r.entries_without_status) <= 5 else ", ..."
        out.append(Claim.uncomputed(
            "todo.uncounted",
            f"the status of {r.uncounted} TODO.md entries",
            reason=(f"{len(r.entries_without_status)} entries carry no "
                    f"**Status:** line ({sample}{more}) and "
                    f"{len(r.unrecognised_statuses)} declare a status this "
                    "parser does not recognise. Not inferred from position or "
                    "from nearby text — an entry with no stated status is "
                    "uncounted, not OPEN")))
    return out


# ---------------------------------------------------------------------------
# Carrying yesterday forward
# ---------------------------------------------------------------------------

def _previous_values(conn) -> Dict[str, object]:
    """The last brief's value per metric_key.

    Read from the STORED rows, never recomputed. A backfilled source would
    otherwise let today's brief silently restate yesterday's history.
    """
    rows = conn.execute(
        "SELECT DISTINCT ON (metric_key) metric_key, value_num "
        "FROM brief_claims WHERE status='COMPUTED' AND value_num IS NOT NULL "
        "ORDER BY metric_key, id DESC").fetchall()
    return {r[0]: r[1] for r in rows}


def run_pass(fleet_dsn: str, dd_dsn: str, write_dsn: str, *,
             dry_run: bool = False) -> Dict:
    """One pass. Returns a summary; writes one brief unless `dry_run`.

    THREE CONNECTIONS. `fleet` and `deadly_digital` are separate DATABASES on
    the same instance, so the business reads and the fleet reads cannot share a
    connection even though they share an identity — the first version of this
    pointed both at FLEET_DSN and reported every business figure as
    "relation does not exist". It did not crash and it did not omit them, which
    is the discipline working; it was still wrong.

    Both reads are `dd_detector_login`. The write is the other identity.
    """
    started = _utcnow()
    claims: List[Claim] = []
    results = []

    with psycopg.connect(fleet_dsn, autocommit=False) as rc:
        rc.read_only = True
        reader = S.Reader(rc, "dd_detector_login@fleet")

        last = reader.probe("fleet:brief_runs", S.scalar(
            "SELECT max(generated_at) FROM brief_runs"))
        previous = reader.probe("fleet:brief_claims",
                                lambda c: _previous_values(c)) or {}
        claims += _overnight_claims(reader, last)
        claims += _fleet_claims(reader, last)
        claims += _sentry_claims(reader)
        claims += _aws_cost_claims(reader)
        results += reader.results

    # A failure here must not lose the fleet claims already gathered, which is
    # why the connection is opened separately rather than nested.
    try:
        with psycopg.connect(dd_dsn, autocommit=False) as dc:
            dc.read_only = True
            dd_reader = S.Reader(dc, "dd_detector_login@deadly_digital")
            claims += _business_claims(dd_reader)
            results += dd_reader.results
    except Exception as exc:
        detail = str(exc).strip().split("\n")[0][:200]
        log.warning("deadly_digital unreachable: %s", detail)
        results.append(S.SourceResult(
            "deadly_digital", "dd_detector_login", False, detail=detail))
        for key, label in (("dd.tenants.active", "active tenant count"),
                           ("dd.analytics_1.orders.count",
                            "order count for analytics_1"),
                           ("dd.analytics_2.orders.count",
                            "order count for analytics_2")):
            claims.append(Claim.uncomputed(
                key, label, reason=f"deadly_digital unreachable: {detail}"))

    claims += _git_claims(last)
    claims += _todo_claims()
    claims += _deploy_claims()
    claims += _standing_gaps()

    claims = [c.with_previous(previous.get(c.metric_key)) for c in claims]

    generated = _utcnow()
    ok = [r for r in results if r.ok]
    bad = [r for r in results if not r.ok]
    markdown = render(claims, generated_at=generated, compares_since=last,
                      sources_ok=len(ok), sources_failed=len(bad))
    completed = _utcnow()

    # NOT under dry_run. `run_brief.py --dry-run` documents itself as
    # "render to stdout, write nothing", `run_pass` says "writes one brief
    # unless dry_run", and the run line prints "(dry run, nothing written)" --
    # while this call sat ABOVE the dry_run return and overwrote
    # briefs/YYYY-MM-DD.md every time. Found when a dry run replaced a brief
    # that had already been committed. Three statements of a guarantee and one
    # line that broke all three.
    disk_path = None if dry_run else _write_to_disk(generated, markdown)

    summary = {
        "disk_path": disk_path,
        "claims_total": len(claims),
        "claims_uncomputed": sum(1 for c in claims if c.status == "UNCOMPUTED"),
        "sources_ok": len(ok), "sources_failed": len(bad),
        "markdown": markdown,
    }
    if dry_run:
        return summary

    with psycopg.connect(write_dsn, autocommit=False) as wc:
        # NOT `RETURNING id`. RETURNING requires SELECT on the returned
        # column, and the writer deliberately has none — the "writer can read
        # nothing" property is stricter than it first looks, and the first
        # version of this failed on exactly that with `permission denied for
        # table brief_runs` on an INSERT the role was allowed to make.
        #
        # `currval` needs only USAGE/SELECT on the SEQUENCE, which the writer
        # has, and is session-local: it returns the value this connection just
        # generated, never another writer's.
        wc.execute(
            "INSERT INTO brief_runs (generated_at, compares_since, code_version,"
            " objectives_version, sources_reachable, sources_unreachable,"
            " claims_total, claims_uncomputed, rendered_markdown, started_at,"
            " completed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (generated, last, S.head_sha(FLEET_REPO) or "unknown",
             _objectives_version(),
             json.dumps([r.as_dict() for r in ok]),
             json.dumps([r.as_dict() for r in bad]),
             summary["claims_total"], summary["claims_uncomputed"],
             markdown, started, completed))
        run_id = wc.execute("SELECT currval('brief_runs_id_seq')").fetchone()[0]

        for c in claims:
            wc.execute(
                "INSERT INTO brief_claims (run_id, section, metric_key,"
                " statement, source, as_of, value_num, value_text,"
                " previous_num, delta_num, query_key, query_version, status,"
                " uncomputed_reason) VALUES"
                " (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (run_id, c.section, c.metric_key, c.statement, c.source,
                 c.as_of, c.value_num, c.value_text, c.previous_num,
                 c.delta_num, c.query_key, c.query_version, c.status,
                 c.uncomputed_reason))
        wc.commit()

    summary["run_id"] = run_id
    return summary
