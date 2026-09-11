"""What this layer has decided before, stated plainly and never ranked on.

The cycle reads the decision log before it ranks anything, and prints what
the record says above the ranking. That is the whole feature. It is not a
score, not a rate and not a prior: twelve or twenty decisions is a record you
read, not a distribution you sample, and a percentage over it would be
exactly the false precision this system refuses everywhere else.

    PRECEDENT IS AN OUTPUT, NEVER AN INPUT.

`rank()` does not receive it, `findings.compute()` does not receive it, and
the suppression loop does not consult it. See
`tests/test_precedent.py::test_precedent_cannot_change_what_is_proposed`,
which is the condition on which this module was allowed to exist at all --
010 refuses the layer's own read identity any sight of the log precisely so
that a proposer cannot learn what gets approved and propose that instead.

WHAT A THIN RECORD DOES TO THIS

The hazard is not that the facts are wrong. Each is a count over rows that
exist. The hazard is that a record this small is not representative of
anything, and a true sentence read as a pattern misleads harder than a false
one. Four guards, all of them printed rather than assumed:

  * every block carries a `basis:` line -- how many rows, over what span, how
    many backfilled, how many with no derivable outcome -- so the size of the
    record is in the same place as the claim
  * ZERO REJECTIONS IS PRINTED UNDER EVERY APPROVAL SENTENCE, not once at the
    top. It is the most misleading thing in the record and it should be
    impossible to read an approval count without it
  * below a floor in cycle.yaml a group is LISTED, not compared -- the counts
    still print, the summarising sentence does not
  * a claim the record cannot support is UNCOMPUTED with a reason, in the
    same shape a brief claim uses. A guard that can never fire is decoration,
    so `regression` is UNCOMPUTED today and says which detectors exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Sequence

import psycopg
from psycopg.rows import dict_row

from . import config
from .adapter import load_query

ADAPTER = "decisions"

PRECEDENT = "decision_precedent"
REACH = "decision_reach"
SURFACE = "observing_surface"

COMPUTED = "COMPUTED"
UNCOMPUTED = "UNCOMPUTED"

#: Statuses that mean the work is over, one way or the other.
_DELIVERED = ("MERGED",)
_NOT_DELIVERED = ("ABANDONED", "REJECTED", "FAILED")


def _delivered(task: dict) -> bool:
    """Did this task's work reach its base branch?

    A DELIBERATE COPY OF `decision_outcomes.task_outcome`, on the same terms as
    console/rank._inside: the rule lives in SQL, this is Python, and the only
    thing that makes a second implementation acceptable is a test asserting the
    two agree. See tests/test_shipped_pointer.py.

    IT IS NOT `task_status == 'MERGED'`, AND THAT WAS THE DEFECT. Until 11 Sep
    2026 this module read the status alone, so tasks 49, 51, 55 and 58 -- all
    merged by hand, all still reading FAILED -- were counted as failures by the
    precedent block while the console counted them as delivered. Two answers to
    one question, on exactly the rows a person would be asking about.

    specs/auto-approval.md §9.17. The pointer is nullable and NULL is the
    ordinary state; a MERGED task needs nobody to vouch for it.
    """
    return (task.get("task_status") in _DELIVERED
            or task.get("shipped_by_decision_id") is not None)


def _not_delivered(task: dict) -> bool:
    """Over, and it did not ship. The pointer wins over the status."""
    return (not _delivered(task)
            and task.get("task_status") in _NOT_DELIVERED)


@dataclass(frozen=True)
class Basis:
    """What a block was computed over. Printed with it, never separately."""
    rows: int
    first: Optional[datetime] = None
    last: Optional[datetime] = None
    backfilled: int = 0
    unlinked: int = 0
    note: str = ""

    def render(self) -> str:
        parts = [f"{self.rows} rows"]
        if self.first and self.last:
            parts.append(f"{self.first:%Y-%m-%d}…{self.last:%Y-%m-%d}")
        if self.backfilled:
            parts.append(f"{self.backfilled} backfilled (reason UNRECORDED)")
        if self.unlinked:
            parts.append(f"{self.unlinked} with no linked work")
        if self.note:
            parts.append(self.note)
        return "basis: " + " · ".join(parts)


@dataclass(frozen=True)
class Fact:
    """One statement about the record, or one refusal to make it."""
    key: str
    statement: str
    status: str = COMPUTED
    detail: tuple[str, ...] = ()
    basis: Optional[Basis] = None
    uncomputed_reason: Optional[str] = None
    #: True when the statement contains a count of approvals. The zero-
    #: rejection caveat is attached to every one of these at render time.
    approval_claim: bool = False

    @staticmethod
    def uncomputed(key: str, statement: str, *, reason: str,
                   basis: Optional[Basis] = None) -> "Fact":
        if not reason or not reason.strip():
            raise ValueError(f"{key}: an uncomputed fact must say why")
        return Fact(key=key, statement=statement, status=UNCOMPUTED,
                    uncomputed_reason=reason, basis=basis)


@dataclass
class Precedent:
    """The record, as the cycle found it this morning."""
    read_at: datetime
    read_as: str
    total: int = 0
    approved: int = 0
    rejected: int = 0
    deferred: int = 0
    facts: tuple[Fact, ...] = ()
    unavailable_reason: Optional[str] = None

    @property
    def has_no_rejections(self) -> bool:
        return self.total > 0 and self.rejected == 0

    #: Printed beneath EVERY approval sentence, deliberately not once at the
    #: top. 010 was built because "every rejection Fleet has ever produced
    #: left no trace at all"; a log that has since recorded none is either a
    #: record of unbroken agreement or a record that is still not receiving
    #: them, and nothing in the log distinguishes those two.
    REJECTION_CAVEAT = (
        "0 rejections in the whole record — either none has been made or "
        "none is reaching the log, so every approval count here is one side "
        "of a two-sided question")

    def render(self) -> list[str]:
        lines = ["PRECEDENT — the record this layer is proposing into",
                 f"  read {self.read_at:%Y-%m-%dT%H:%M:%SZ} as {self.read_as}"]
        if self.unavailable_reason:
            lines.append(f"  UNCOMPUTED: {self.unavailable_reason}")
            return lines
        for fact in self.facts:
            lines.append("")
            if fact.status == UNCOMPUTED:
                lines.append(f"  {fact.statement}")
                lines.append(f"    UNCOMPUTED: {fact.uncomputed_reason}")
            else:
                lines.append(f"  {fact.statement}")
                lines.extend(f"    {d}" for d in fact.detail)
                if fact.approval_claim and self.has_no_rejections:
                    # UNDER EVERY ONE, not once at the top. Every count in
                    # these blocks is a count over approved decisions --
                    # only an approval produces a task -- so each of them
                    # can be read as "this is how decisions turn out" by
                    # someone who never sees the missing half. The
                    # repetition is the mechanism, not an oversight: a
                    # caveat stated once is a caveat scrolled past.
                    lines.append(f"    ! {self.REJECTION_CAVEAT}")
            if fact.basis is not None:
                lines.append(f"    {fact.basis.render()}")
        return lines


# ---- reading ---------------------------------------------------------------

def read(dsn: str, *, cycle_config: dict[str, Any],
         deployments: Any = None) -> Precedent:
    """Open the log on its own connection and compute the facts.

    A THIRD connection, as the detector identity. 010 refuses
    `fleet_detector_reader` -- the identity this layer reads track 1 with --
    any sight of the log, and that refusal is kept: the read side of the
    proposal layer still cannot see it and the write side certainly cannot.
    What this uses is the identity 012 already granted for the daily brief,
    which can read the log and cannot write anything anywhere.

    Read-only on the connection as well as by grant. The grant is the
    guarantee; this is the statement of intent that survives a grant being
    widened by someone solving a different problem.
    """
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.read_only = True
        read_at = conn.execute("SELECT now() AS t").fetchone()["t"]
        who = conn.execute("SELECT current_user AS u").fetchone()["u"]
        summary = conn.execute(load_query(PRECEDENT).sql).fetchone()
        # v2 carries tasks.shipped_by_decision_id; v1 could only see the
        # status, and so disagreed with decision_outcomes about four tasks.
        reach = conn.execute(load_query(REACH, 2).sql).fetchall()
        surface = conn.execute(load_query(SURFACE).sql).fetchall()

    return _compute(read_at, who, summary, reach, surface,
                    cycle_config=cycle_config, deployments=deployments)


def _compute(read_at, who, summary, reach, surface, *,
             cycle_config: dict[str, Any], deployments=None) -> Precedent:
    settings = (cycle_config.get("precedent") or {})
    floor = int(settings.get("compare_floor", 6))

    total = int(summary["total"] or 0)
    p = Precedent(read_at=read_at, read_as=who, total=total,
                  approved=int(summary["approved"] or 0),
                  rejected=int(summary["rejected"] or 0),
                  deferred=int(summary["deferred"] or 0))

    if total == 0:
        p.unavailable_reason = (
            "the decision log is empty; there is no precedent to state, "
            "which is a fact about the record and not a failure to read it")
        return p

    decisions = _by_decision(reach)
    tasks = _tasks(reach)
    unlinked = sum(1 for d in decisions.values() if not d["task_ids"])
    basis = Basis(rows=total, first=summary["first_decided_at"],
                  last=summary["last_decided_at"],
                  backfilled=int(summary["backfilled"] or 0),
                  unlinked=unlinked)

    facts: list[Fact] = [
        _shape_fact(p, summary, basis),
        _reach_fact(decisions, tasks, basis, unlinked),
        _objective_fact(decisions, tasks, floor),
        _deferral_fact(decisions),
        _delivery_fact(tasks, deployments, floor),
        _regression_fact(surface, basis),
    ]
    p.facts = tuple(f for f in facts if f is not None)
    return p


def _by_decision(rows: Sequence[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for r in rows:
        d = out.setdefault(r["decision_id"], {
            "decision": r["decision"], "product": r["product"],
            "subject": r["subject"], "decided_at": r["decided_at"],
            "origin": r["origin"], "task_ids": [], "links": set()})
        if r["task_id"] is not None:
            d["task_ids"].append(r["task_id"])
            d["links"].add(r["link"])
    return out


def _tasks(rows: Sequence[dict]) -> dict[int, dict]:
    """One entry per linked task. A task reachable twice is still one task."""
    out: dict[int, dict] = {}
    for r in rows:
        if r["task_id"] is not None:
            out.setdefault(r["task_id"], r)
    return out


def _split(tasks: Sequence[dict]) -> tuple[int, int, int]:
    """Delivered, not delivered, still in flight.

    `_delivered` rather than a status test: a task shipped by hand reads FAILED
    and delivered the work, and counting it as a failure here while the console
    calls it DELIVERED_BY_HAND is the disagreement §9.17 exists to end.
    """
    merged = sum(1 for t in tasks if _delivered(t))
    failed = sum(1 for t in tasks if _not_delivered(t))
    return merged, failed, len(tasks) - merged - failed


def _shape_fact(p: Precedent, summary, basis: Basis) -> Fact:
    span = ""
    if summary["first_decided_at"] and summary["last_decided_at"]:
        span = (f", {summary['first_decided_at']:%Y-%m-%d} to "
                f"{summary['last_decided_at']:%Y-%m-%d}")
    detail = []
    days = int(summary["distinct_days"] or 0)
    if days:
        detail.append(f"made on {days} distinct day(s), across "
                      f"{int(summary['products'] or 0)} product(s)")
    return Fact(
        key="shape",
        statement=(f"{p.total} decision(s){span}: {p.approved} approved, "
                   f"{p.deferred} deferred, {p.rejected} rejected."),
        detail=tuple(detail), basis=basis, approval_claim=True)


def _reach_fact(decisions, tasks, basis: Basis, unlinked: int) -> Fact:
    linked = len(decisions) - unlinked
    merged, failed, in_flight = _split(list(tasks.values()))
    via_candidate = sum(1 for d in decisions.values()
                        if "CANDIDATE" in d["links"])
    detail = [
        f"{len(tasks)} linked task(s): {merged} merged, "
        f"{failed} failed or abandoned, {in_flight} in flight",
    ]
    if via_candidate:
        detail.append(
            f"{via_candidate} decision(s) reach their work only through "
            f"candidates.approval_decision_id — decision_outcomes joins on "
            f"decision_log.task_id alone and reports those as unknown")
    if unlinked:
        detail.append(
            f"{unlinked} decision(s) cite no proposal, issue or task, so "
            f"nothing about their outcome is derivable at all")
    return Fact(key="reach",
                statement=f"{linked} of {len(decisions)} decision(s) link to work.",
                detail=tuple(detail), basis=basis, approval_claim=True)


def _objective_fact(decisions, tasks, floor: int) -> Optional[Fact]:
    groups: dict[Optional[str], list] = {}
    for t in tasks.values():
        groups.setdefault(t["objective_ref"], []).append(t)
    if not groups:
        return None
    detail = []
    for ref, rows in sorted(groups.items(), key=lambda kv: (-len(kv[1]), str(kv[0]))):
        merged, failed, in_flight = _split(rows)
        name = ref or "no objective"
        counts = f"{merged} merged, {failed} failed, {in_flight} in flight"
        if len(rows) < floor:
            # LISTED, NOT COMPARED. The counts are true; a summarising
            # sentence over this few rows is a pattern claim the record
            # cannot support, so it is withheld rather than softened.
            detail.append(f"{name}: {len(rows)} linked task(s) — {counts}. "
                          f"Below the {floor}-task floor, listed not compared.")
        else:
            detail.append(f"{name}: {len(rows)} linked task(s), {counts}.")
    return Fact(key="by_objective",
                statement="By objective, through the linked work:",
                detail=tuple(detail), approval_claim=True,
                basis=Basis(rows=len(tasks), note=f"linked tasks; compare floor {floor}"))


def _deferral_fact(decisions) -> Optional[Fact]:
    deferred = [d for d in decisions.values() if d["decision"] == "DEFERRED"]
    if not deferred:
        return None
    detail = [f"{d['decided_at']:%Y-%m-%d} {d['product']}: {d['subject']}"
              for d in sorted(deferred, key=lambda d: d["decided_at"])]
    return Fact(key="deferrals",
                statement=f"{len(deferred)} deferral(s), still deferred:",
                detail=tuple(detail))


def _delivery_fact(tasks, deployments, floor: int) -> Fact:
    """Merged and deployed, from git and the drift checks, never collapsed."""
    import outcomes as outcomes_module

    if not tasks:
        return Fact.uncomputed(
            "delivery", "Reached production:",
            reason="no decision links to a task, so there is no commit to "
                   "look for in a repository or in a running container")

    deployments = (deployments if deployments is not None
                   else outcomes_module.deploys_module.all_deployments())

    shipped = cannot_say = nothing_to_ship = with_sha = by_merge_commit = 0
    disagreements: list[str] = []
    for t in sorted(tasks.values(), key=lambda r: r["task_id"]):
        merge = outcomes_module.merge_evidence(
            t["task_repo"], t["patch_commit_sha"], status=t["task_status"],
            base_branch=t["base_branch"], merge_commit=t.get("merge_commit"),
            already_merged=t.get("already_merged"))
        if merge.identifies_the_merge:
            by_merge_commit += 1
        if t["patch_commit_sha"]:
            with_sha += 1
        if merge.disagrees:
            disagreements.append(
                f"task {t['task_id']}: {merge.summary} — {merge.detail}")
        deploy = outcomes_module.deploy_evidence(
            t["work_type"], repo_name=t["task_repo"],
            sha=merge.sha, deployments=deployments)
        if deploy.verdict == "SHIPPED":
            shipped += 1
        elif deploy.verdict == "NOTHING_TO_SHIP":
            nothing_to_ship += 1
        else:
            cannot_say += 1

    detail = [
        f"{shipped} verified in a running container; {cannot_say} cannot be "
        f"said; {nothing_to_ship} governed by nothing that deploys",
        "a deploy check that reads UNKNOWN or STALE, or that last ran before "
        "the merge, gives CANNOT SAY — it is never read as not-deployed and "
        "never as deployed",
    ]
    # The status column and the repository are two claims and both are
    # carried. Where they disagree that IS the finding, and collapsing them
    # into one number is what would hide it.
    detail.append(
        f"{by_merge_commit} answered from the merge commit itself; the rest "
        f"from the branch tip, which is consistent with a merge and does not "
        f"identify one")
    detail.append(
        f"{len(disagreements)} task(s) where tasks.status and git disagree"
        + (":" if disagreements else ""))
    detail.extend(f"  {d}" for d in disagreements)
    return Fact(key="delivery",
                statement=f"Of {len(tasks)} linked task(s), reaching production:",
                detail=tuple(detail), approval_claim=True,
                basis=Basis(rows=len(tasks),
                            note=f"{with_sha} with a recorded commit to look for"))


def _regression_fact(surface, basis: Basis) -> Fact:
    """Always a refusal today, and the reason is the list of detectors.

    Counting `issues.first_seen > decided_at` is one predicate and returns
    zero for every decision in the log. The zero is worthless: the observing
    surface does not overlap the changed surface. Publishing it would be a
    confident sentence about something nobody measured, which is the failure
    the brief spec exists to prevent, so the count is not computed at all
    rather than computed and hedged.
    """
    watchers = ", ".join(f"{r['detector_key']} ({r['product']})"
                         for r in surface) or "none"
    return Fact.uncomputed(
        "regression",
        "Whether anything broke afterwards:",
        reason=(f"the registered detectors are {watchers}. Nothing observes "
                f"CI, the frontend, or the routes and documents these "
                f"decisions changed, so an absence of new issues is a "
                f"statement about the observing surface and not about the "
                f"code. A clean bill computed here would be worse than no "
                f"number"))
