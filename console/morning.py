"""The morning page, assembled.

WHAT THIS MODULE IS FOR
-----------------------
`queries.py` reads rows. This turns them into the four things a standup says:
what is blocking me, what I did, what I am doing next, and what I could not
see. Everything here is shaping -- no module in this file decides anything, and
nothing it produces is written back.

THE EMPTY ANSWER IS THE DESIGNED ANSWER
---------------------------------------
Most mornings nothing has happened. Every function here returns a structure
that renders as a sentence when it is empty, and the template never has to test
for `None`. "Nothing, because you haven't approved anything" is a fact about the
system and is built here rather than left to a `{% else %}` in a template,
because a fact assembled from real counts can be checked and an `{% else %}`
cannot.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
A table of "things Fleet needs a human for". Every entry in `fleet_blocked()`
below is DERIVED from something that already knows -- the credit function, the
drift state file, the systemd unit. The one real blocker that is not derivable
(`wp dd sync-refunds` on a WordPress host this fleet cannot reach) stays in
specs/refund-hook.md and does NOT appear on this page.

That is a choice and it costs something: the section is shorter than the truth.
It is the choice 012_daily_brief.sql already argues for, in the words it used
about hand-maintained tallies being "wrong three times in one day on 7 Sep
2026". If this section is too short, the fix is instrumenting the missing
thing, not typing it in here where nothing can check it.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from console import config, deploys

# ---------------------------------------------------------------------------
# Small shared shapes
# ---------------------------------------------------------------------------


@dataclass
class Ask:
    """One thing waiting on the reader. The unit of the blockers section."""
    kind: str
    headline: str
    detail: str = ""
    href: Optional[str] = None
    href_label: str = ""
    meta: List[tuple] = field(default_factory=list)
    #: NEEDS_YOU or NEEDS_A_MACHINE. Both are blockers; only the first is
    #: something the reader can clear this morning, and saying which is the
    #: difference between a to-do list and a list of grievances.
    needs: str = "NEEDS_YOU"


@dataclass
class Step:
    """One step in a thread. `actor` is HUMAN or FLEET, and it is the point."""
    actor: str
    label: str
    detail: str = ""
    when: Optional[datetime] = None
    cost_gbp: Optional[float] = None
    elapsed_seconds: Optional[float] = None
    status: str = ""
    href: Optional[str] = None
    #: True when this step is known to have happened but has no record here.
    #: Rendered as a gap rather than skipped -- see promote_gap() below.
    unrecorded: bool = False


@dataclass
class Thread:
    key: str
    title: str
    repo: str
    objective_ref: Optional[str]
    steps: List[Step] = field(default_factory=list)
    candidate_id: Optional[int] = None

    @property
    def total_cost(self) -> float:
        return sum(s.cost_gbp or 0.0 for s in self.steps)

    @property
    def last_at(self) -> Optional[datetime]:
        stamps = [s.when for s in self.steps if s.when]
        return max(stamps) if stamps else None


# ---------------------------------------------------------------------------
# Blockers
# ---------------------------------------------------------------------------


def _timer_enabled(unit: str = "fleet-runner.timer") -> Optional[bool]:
    """Whether a systemd timer is enabled. None when the question cannot be put.

    `systemctl is-enabled` rather than looking for the symlink in
    timers.target.wants: the symlink is what enablement currently IS, not what
    it is defined as, and a unit can be enabled through other mechanisms. The
    authority answers in one word; reimplementing its rules here would be a
    second definition of "enabled" that could disagree with the first.

    Shells out for the same reason gitdiff.py does, on the same terms: argv,
    never a shell, and a fixed unit name that never comes from a request.
    None on any failure, and the caller treats None as "cannot say" rather than
    as "enabled" -- an unknown that resolves to the reassuring answer is how a
    monitor becomes decoration.
    """
    try:
        p = subprocess.run(["systemctl", "is-enabled", unit],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    out = p.stdout.strip()
    if out in ("enabled", "enabled-runtime", "static", "alias", "indirect"):
        return True
    if out in ("disabled", "masked", "masked-runtime"):
        return False
    return None


def fleet_blocked(credit: Optional[Dict[str, Any]],
                  deployments: Dict[str, deploys.Deployment]) -> List[Ask]:
    """What Fleet cannot do itself, derived from three things that know.

    Not a list anybody maintains. If one of these clears, it disappears from
    the page because the thing that knows it started saying something else.
    """
    asks: List[Ask] = []

    # 1. The monthly credit reading. fleet_month_credit() answers UNCOMPUTED
    #    when no reading exists for the month, and refuses every task insert
    #    while it does -- so this is not advisory, it is the queue being shut.
    if credit is not None and credit.get("status") == "UNCOMPUTED":
        asks.append(Ask(
            kind="CREDIT_READING",
            headline="Record this month's credit pool reading",
            detail=(credit.get("uncomputed_reason") or "")
            + " Until it is recorded nothing can be queued at all: the "
              "ceiling refuses rather than assuming a number nobody read.",
            needs="NEEDS_YOU",
            meta=[("committed so far",
                   f"£{float(credit.get('committed_gbp') or 0):.2f}")]))

    # 2. The frontend deploy stamp. drift-frontend.state answers UNKNOWN
    #    because the image carries no GIT_SHA, so no merged frontend branch can
    #    be shown as shipped. A machine change, not a decision.
    front = deployments.get("frontend")
    if front is not None and not front.usable:
        asks.append(Ask(
            kind="DEPLOY_STAMP",
            headline="Fleet cannot tell whether the frontend has shipped",
            detail=front.detail or f"the frontend deploy check reads "
                                   f"{front.status}",
            needs="NEEDS_A_MACHINE",
            meta=[("check last ran", deploys.ago(front.age) + " ago"),
                  ("state", front.status)]))

    # 3. The runner timer. Installed and disabled is a real state and a
    #    deliberate one; the page states it so it is a decision that stays
    #    made rather than one that quietly lapses.
    enabled = _timer_enabled()
    if enabled is False:
        asks.append(Ask(
            kind="RUNNER_TIMER",
            headline="The runner timer is installed and disabled",
            detail="Nothing runs unless you start it by hand. "
                   "specs/approval-surface.md §6.1 made the three ceilings a "
                   "precondition for enabling it; enable with "
                   "`systemctl enable --now fleet-runner.timer` once you are "
                   "satisfied they hold.",
            needs="NEEDS_YOU"))
    elif enabled is None:
        asks.append(Ask(
            kind="RUNNER_TIMER",
            headline="Fleet cannot tell whether the runner timer is enabled",
            detail="`systemctl is-enabled fleet-runner.timer` did not answer. "
                   "Reported rather than assumed: an unknown that resolves to "
                   "'enabled' is how a monitor becomes decoration.",
            needs="NEEDS_A_MACHINE"))

    return asks


def awaiting_you(rows: List[Dict[str, Any]]) -> Dict[str, List[Ask]]:
    """READY_FOR_REVIEW, split on work type.

    A drafted spec and a built branch are both "ready for review" and they ask
    different questions. A spec asks whether this is the right work; a branch
    asks whether this is the right change. One count covering both would hide
    which question is being put.
    """
    specs: List[Ask] = []
    branches: List[Ask] = []
    for r in rows:
        meta = [("cost", f"£{float(r['spent_all_runs'] or 0):.2f}"),
                ("elapsed", human_elapsed(r["elapsed_seconds"]))]
        if (r["runs_total"] or 1) > 1:
            meta.append(("attempts", f"{r['runs_total']}"))
        ask = Ask(
            kind="APPROVE_SPEC" if r["is_spec"] else "REVIEW_BRANCH",
            headline=r["title"],
            detail=r["branch_name"] or "",
            href=f"/tasks/{r['id']}",
            href_label=f"task {r['id']}",
            meta=meta)
        (specs if r["is_spec"] else branches).append(ask)
    return {"specs": specs, "branches": branches}


# ---------------------------------------------------------------------------
# What I did
# ---------------------------------------------------------------------------


def human_elapsed(seconds: Optional[float]) -> str:
    """A duration, or a dot. NEVER a zero.

    The rule /briefs already follows: a missing value renders as `·` because a
    blank shown as 0 erases the difference between "took no time" and "we have
    no record of how long it took". Same reasoning as the brief's absent-metric
    dot, in the one other place on this page where a number can be missing.
    """
    if seconds is None:
        return "·"
    seconds = float(seconds)
    if seconds < 90:
        return f"{seconds:.0f}s"
    return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"


def money(value: Optional[float]) -> str:
    """Cost, or a dot. Same rule."""
    return "·" if value is None else f"£{float(value):.2f}"


def excerpt(text: Optional[str], limit: int = 155) -> str:
    """A first sentence, or a clipped one. Never a silent truncation.

    The ellipsis is load-bearing: a reason cut off without one reads as a
    complete thought that happens to be terse, which misrepresents what the
    person actually wrote.
    """
    if not text:
        return ""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    stop = cut.rfind(". ")
    if stop > 60:
        return cut[:stop + 1] + " …"
    return cut.rsplit(" ", 1)[0] + " …"


def promote_gap() -> Step:
    """The step between a drafted spec and the code task it produced.

    Promoting a draft from drafts/ to specs/ is a human act with no database
    row, and that is by design: contracts/draft-spec.yaml keeps specs/**
    protected so a task cannot write the instructions it is judged against, and
    the promotion is therefore a person and a git commit.

    Rendered as a visible gap rather than omitted. A thread that jumped from a
    FAILED spec task straight to a queued code task would read as though Fleet
    did that itself, which is the one claim on this page it must not make.
    """
    return Step(actor="HUMAN", label="Promoted the draft to specs/",
                detail="a human act with no database row — drafts/ to specs/ "
                       "is a git commit, because specs/** is protected from "
                       "the task that would otherwise write its own brief",
                unrecorded=True)


def build_threads(rows: List[Dict[str, Any]],
                  failures_by_task: Dict[int, List[Dict[str, Any]]],
                  deployments: Dict[str, deploys.Deployment]) -> List[Thread]:
    """candidate → spec task → your approval → code task → branch → shipped."""
    threads: List[Thread] = []
    for r in rows:
        t = Thread(key=f"c{r['candidate_id']}", title=r["title"],
                   repo=r["repo"], objective_ref=r["objective_ref"],
                   candidate_id=r["candidate_id"])

        t.steps.append(Step(
            actor="FLEET", label="Proposed as a candidate",
            detail=f"batch {r['batch_id']}", href="/candidates"))

        if r["decision_id"]:
            # EXCERPTED, not printed whole. A batch reason is about the
            # SELECTION -- one reason covering up to five candidates, which is
            # the cap's whole purpose -- so the full text is identical on every
            # thread in the batch and printing it five times buries the threads
            # in a paragraph the reader already read. The link goes to the
            # decision, where it belongs entire.
            t.steps.append(Step(
                actor="HUMAN", label="You approved it",
                detail=excerpt(r["decision_reason"]), when=r["decision_at"],
                href="/decisions", status=r["disposition"]))

        if r["spec_task_id"]:
            t.steps.append(_task_step(
                "Wrote a draft spec", r["spec_task_id"], r["spec_status"],
                r["spec_completed_at"], r["spec_cost"], r["spec_elapsed"],
                failures_by_task))

        if r["work_task_id"]:
            # The promotion only happened if a code task exists at all.
            t.steps.append(promote_gap())
            t.steps.append(_task_step(
                "Built the change", r["work_task_id"], r["work_status"],
                r["work_completed_at"], r["work_cost"], r["work_elapsed"],
                failures_by_task))
            t.steps.extend(_ship_steps(
                r["work_status"], r["work_work_type"], r["work_branch"],
                r["work_completed_at"], deployments))

        threads.append(t)
    return threads


def _task_step(label: str, task_id: int, status: str,
               when: Optional[datetime], cost: Optional[float],
               elapsed: Optional[float],
               failures_by_task: Dict[int, List[Dict[str, Any]]]) -> Step:
    detail = ""
    for f in failures_by_task.get(task_id, []):
        detail = (f.get("output_tail") or "").strip()
        break
    return Step(actor="FLEET", label=label, detail=detail, when=when,
                cost_gbp=float(cost) if cost is not None else None,
                elapsed_seconds=elapsed, status=status,
                href=f"/tasks/{task_id}")


def _ship_steps(status: str, work_type: Optional[str], branch: Optional[str],
                completed_at: Optional[datetime],
                deployments: Dict[str, deploys.Deployment]) -> List[Step]:
    """MERGED and DEPLOYED, kept apart.

    Built, merged and deployed are three states. `tasks.status = 'MERGED'`
    means a person merged a branch; whether it is running is a different
    question with a different source, and on this host the frontend cannot
    answer it at all.
    """
    if status != "MERGED":
        return []
    steps = [Step(actor="HUMAN", label="You merged it",
                  detail=branch or "", when=completed_at, status="MERGED")]
    verdict, why = deploys.shipped(work_type, completed_at, deployments)
    steps.append(Step(
        actor="FLEET" if verdict == "SHIPPED" else "GAP",
        label={"SHIPPED": "Running in production",
               "NOT_SHIPPED": "Merged, NOT deployed",
               "NOTHING_TO_SHIP": "Nothing to deploy",
               "CANNOT_SAY": "Cannot tell whether it shipped"}[verdict],
        detail=why, status=verdict))
    return steps


def loose_threads(rows: List[Dict[str, Any]],
                  failures_by_task: Dict[int, List[Dict[str, Any]]],
                  deployments: Dict[str, deploys.Deployment]) -> List[Thread]:
    """Tasks belonging to no candidate, as one-step threads.

    Task 26 is why this exists: it was inserted directly, because approve.py
    only makes draft-spec tasks. A threads-only page would have shown its
    candidate's thread and silently dropped any task that had no candidate.
    """
    out: List[Thread] = []
    for r in rows:
        t = Thread(key=f"t{r['id']}", title=r["title"], repo=r["repo"],
                   objective_ref=r["objective_ref"])
        t.steps.append(Step(
            actor="HUMAN", label="Queued directly",
            detail="not from a candidate — the approval surface only makes "
                   "draft-spec tasks",
            when=r["created_at"]))
        t.steps.append(_task_step(
            "Built the change", r["id"], r["status"], r["completed_at"],
            r["committed_gbp"], r["elapsed_seconds"], failures_by_task))
        t.steps.extend(_ship_steps(r["status"], r["work_type"],
                                   r["branch_name"], r["completed_at"],
                                   deployments))
        out.append(t)
    return out


def in_window(threads: List[Thread], since: Optional[datetime]) -> List[Thread]:
    """Threads that moved since the last brief.

    Filtered here rather than in SQL because a thread STRADDLES the boundary:
    candidate 12 was approved on 7 Sep and its code task queued on 8 Sep, and a
    window over any single timestamp would either drop it or count it twice.
    """
    if since is None:
        return threads
    return [t for t in threads if t.last_at and t.last_at >= since]


# ---------------------------------------------------------------------------
# Patterns — the same failure twice is one finding
# ---------------------------------------------------------------------------

#: Strip the parts of a failure message that vary between instances of the SAME
#: failure: the file being judged, and the list of offending paths. What is
#: left is the shape of the complaint.
_VARIABLE = re.compile(r"\[[^\]]*\]|\S*[/.](?:py|md|ts|tsx|sql|yaml)\b")


def _signature(command: str, output_tail: str) -> str:
    body = _VARIABLE.sub("", output_tail or "")
    body = re.sub(r"\s+", " ", body).strip(" :,")
    return f"{Path(command.split()[-1]).name}|{body[:90]}"


@dataclass
class Pattern:
    check: str
    gist: str
    task_ids: List[int]
    examples: List[str]
    of_total: int

    @property
    def n(self) -> int:
        return len(self.task_ids)


def failure_patterns(failures: List[Dict[str, Any]], since: Optional[datetime],
                     attempted: int) -> List[Pattern]:
    """Repeated failures, grouped by what actually went wrong.

    Two draft specs failing the same check for the same reason is ONE finding
    about the spec-writing step, not two rows saying FAILED. The rows are still
    on /tasks; what belongs on a morning page is the pattern, because "two of
    four got paths wrong" is a statement about the step and "task 23 FAILED,
    task 24 FAILED" is not.

    The signature is a display heuristic and decides nothing. Two failures that
    should have grouped and did not are two bullets instead of one; nothing is
    hidden either way, which is the only property a heuristic on this page is
    allowed to need.
    """
    groups: Dict[str, Pattern] = {}
    for f in failures:
        when = f.get("completed_at")
        if since is not None and (when is None or when < since):
            continue
        sig = _signature(f.get("command") or "", f.get("output_tail") or "")
        instance = re.sub(r"\s+", " ", (f.get("output_tail") or "").strip())
        p = groups.get(sig)
        if p is None:
            # The gist is the SHAPE -- the complaint with the varying file and
            # path list stripped out. Quoting one instance would make a claim
            # about the step read as a claim about one task, which is the thing
            # this whole function exists to stop doing.
            p = groups[sig] = Pattern(
                check=Path((f.get("command") or " ").split()[-1]).name,
                gist=sig.split("|", 1)[1] or instance,
                task_ids=[], examples=[], of_total=attempted)
        if f["task_id"] not in p.task_ids:
            p.task_ids.append(f["task_id"])
            p.examples.append(instance)
    # Only repeats. A single failure is a task that failed and reads better as
    # its own thread; a pattern claims something about the step.
    return sorted((p for p in groups.values() if p.n > 1),
                  key=lambda p: -p.n)


# ---------------------------------------------------------------------------
# What I couldn't see
# ---------------------------------------------------------------------------

#: objective id prefix -> the brief metric_key prefix that would carry it.
OBJECTIVE_METRIC_PREFIX = {"dd": "dd.", "pi": "pi.", "cost": "cost."}


def uninstrumented_objectives(objectives_path: Optional[Path] = None,
                              claim_keys: Optional[List[str]] = None
                              ) -> List[Dict[str, Any]]:
    """Objectives the brief carries NO claim for, computed or uncomputed.

    THE DISTINCTION THIS DRAWS IS THE WHOLE FUNCTION. An objective with a claim
    that failed to compute has a source that broke: cost-discipline is here,
    represented, as `cost.aws.monthly_gbp` reading UNCOMPUTED with a reason. An
    objective with NO claim of either kind was never instrumented at all, and
    nothing on the page would otherwise say so -- it does not appear as a gap
    because it does not appear.

    Today that is `pi-revenue`, which is 0.25 of the quarter. Collapsing it
    into the uncomputed list would file a quarter of the objectives among four
    minor gaps.

    Read from objectives-2026-Q4.yaml rather than named here, so an objective
    added to the file appears without a code change -- and so the weight quoted
    on the page is the weight in the file.
    """
    path = objectives_path or (config.PROJECT_ROOT / "objectives-2026-Q4.yaml")
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except OSError:
        return []
    keys = claim_keys or []
    out = []
    for obj in data.get("objectives", []) or []:
        oid = str(obj.get("id", ""))
        prefix = OBJECTIVE_METRIC_PREFIX.get(oid.split("-", 1)[0])
        if prefix is None:
            continue
        if any(k.startswith(prefix) for k in keys):
            continue
        out.append({
            "id": oid,
            "weight": obj.get("weight"),
            "statement": " ".join((obj.get("statement") or "").split()),
            "signals": obj.get("signals") or [],
        })
    return sorted(out, key=lambda o: -(o.get("weight") or 0))
