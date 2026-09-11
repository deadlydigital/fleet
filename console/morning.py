"""The morning page, assembled.

WHAT THIS MODULE IS FOR
-----------------------
`queries.py` reads rows. This turns them into the three things the page says:
what shipped overnight, what needs the reader, and what it could not see.
Everything here is shaping -- no function in this file decides anything, and
nothing it produces is written back.

It was four until 10 Sep 2026, and the one that went was "what I'm doing
next". That was a section while a queue only filled if the reader filled it;
console/autoapprove.py fills it on a timer now, so the queue is a line in the
overnight chain and a bullet under it, not a heading.

THE EMPTY ANSWER IS THE DESIGNED ANSWER
---------------------------------------
Most mornings nothing has happened. Every function here returns a structure
that renders as a sentence when it is empty, and the template never has to test
for `None`. An empty answer is assembled here from real counts rather than left
to a `{% else %}` in a template, because a fact can be checked and an
`{% else %}` cannot.

This page said "Nothing, because you haven't approved anything -- the queue is
empty and only an approval fills it" until 10 Sep 2026, and it was assembled
exactly that way. It was still wrong, because the sentence outlived the loop it
described: `fleet_task_runner` still holds no INSERT on `tasks`, but
`fleet_console` fills the queue on a timer now, and the clause that was true
was carrying a conclusion that was not. A fact built from counts is checkable;
the ENGLISH AROUND IT IS NOT, and that is the failure this module is most prone
to. Prose here should state what a source says and stop.

AN EMPTY ANSWER IS NOT AN UNASKED QUESTION
-------------------------------------------
Three of the things this page reports -- whether the night approved anything,
whether the merge sweep ran, whether production is where main is -- can each
come back as "no", as "nothing", or as "I could not find out". The third is not
the second. `overnight_chain()` and `units()` below keep them apart by pairing
every database answer with the unit's own record of whether it ran, and both
of them return None rather than a reassuring default when the question cannot
be put at all.

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

WHAT THE PAGE IS FOR, SINCE THE SECTIONS FOLLOW FROM IT
--------------------------------------------------------
It is the one thing opened in the morning. It says what shipped overnight, what
needs the reader, and what it could not see, in that order, and it is meant to
be finished in ten seconds with the detail one click away. The order is not the
order the data arrives in and is not the order a standup is spoken in; it is
the order the questions are actually asked in.

The four rules it holds, unchanged and worth restating because every function
below is constrained by one of them:

  * a missing value renders as a dot and NEVER as zero -- human_elapsed() and
    money() own this, and since 10 Sep 2026 every caller uses them;
  * the uncomputed count carries the same weight as the computed count;
  * a claim carries its source and its recency;
  * the page never says "nothing is wrong" when it means "I could not look".
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from console import config, deploys, requirements

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
    """One step in a thread. `actor` is who did it, and it is the point.

    FOUR ACTORS, AND THE THIRD IS NEW
    ----------------------------------
    HUMAN   a person, at a keyboard, at a known moment
    AUTO    a timer, unattended -- an approval at 01:30, a merge at 03:30
    FLEET   the runner doing the work it was given
    GAP     something that is known to have happened, or known NOT to have,
            with no record of it here

    AUTO exists because until 10 Sep 2026 there was no such thing, and the
    page said "you approved it" over a row `console/autoapprove.py` had
    written. Decisions 26 and 27 were already machine approvals rendered as
    the reader's own act. The actor is now taken from `decided_via` on the
    row rather than assumed from which column it arrived in.
    """
    actor: str
    label: str
    detail: str = ""
    when: Optional[datetime] = None
    cost_gbp: Optional[float] = None
    elapsed_seconds: Optional[float] = None
    status: str = ""
    href: Optional[str] = None


def actor_of(decided_via: Optional[str]) -> str:
    """HUMAN or AUTO, from the column that records which.

    None is HUMAN, and that is a considered default rather than a convenience:
    every decision written before 026 added the column was a person clicking
    Accept, so NULL means "before there was any other kind". A new row always
    carries a value -- `approve.DECIDED_VIA` constrains it and 026 constrains
    it again at the database -- so this default cannot silently absorb a
    machine decision written today.
    """
    return "AUTO" if decided_via == "unattended" else "HUMAN"


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

    @property
    def outcome(self) -> str:
        """Where this thread got to. The word the answer line counts.

        SHIPPED > MERGED > FAILED > MOVED, and the order is deliberate: a
        thread whose code task failed and was then merged by hand has both
        statuses on it, and the furthest one it reached is what happened. A
        counter that took the LAST step instead would report a thread as
        failed because its deploy check could not answer.

        NOT_QUEUED sits above FAILED because a draft that merged and queued
        nothing is a stall, not a failure -- nothing went wrong, which is
        exactly what makes it easy to miss.
        """
        seen = {s.status for s in self.steps}
        if "SHIPPED" in seen:
            return "SHIPPED"
        if "MERGED" in seen:
            return "MERGED"
        if "NOT_QUEUED" in seen:
            return "NOT_QUEUED"
        if "FAILED" in seen:
            return "FAILED"
        return "MOVED"

    def progressed_since(self, since: Optional[datetime]) -> bool:
        """Did FLEET actually finish something here, in the window?

        AN APPROVAL IS NOT PROGRESS. This is the distinction that keeps a
        thread out of two sections at once: "Payment method breakdown" was
        approved at 23:08 and its task has never run, so its only in-window
        event is the approval. It belongs under what happens NEXT, and listing
        it under what got DONE claims work that has not happened.

        Terminal statuses only. QUEUED and RUNNING are the future; APPROVED is
        a decision and its consequence is the queue -- which since 10 Sep 2026
        is more often the ranker's decision than the reader's, and is no more
        progress for being made by a timer.
        """
        for s in self.steps:
            if s.status not in ("FAILED", "READY_FOR_REVIEW", "MERGED"):
                continue
            if s.when is None:
                continue
            if since is None or s.when >= since:
                return True
        return False


# ---------------------------------------------------------------------------
# Blockers
# ---------------------------------------------------------------------------


#: The four units the loop is made of, in the order they fire. Named here
#: rather than discovered, because a unit that has been REMOVED must still
#: appear -- `systemctl show` on a unit that does not exist answers happily
#: with empty values, and a chain that lists only what it can find would drop
#: a stage the night depends on and look complete doing it.
CHAIN = (
    ("approve", "Ranked the pool and ticked", "fleet-autoapprove"),
    ("run", "Ran the work", "fleet-runner"),
    ("merge", "Merged what was eligible", "fleet-automerge"),
    ("deploy", "Deployed what merged", "fleet-autodeploy"),
)

#: Properties read off each unit. `ExecStart` is here for one reason: a unit
#: running with `--dry-run` decides everything and does nothing, and for two
#: months this page would have reported its decisions as events. The flag is a
#: fact about the unit, so it is read from the unit.
_SERVICE_PROPS = ("Result", "ExecMainStartTimestamp", "ExecMainExitTimestamp",
                  "ExecMainStatus", "ExecStart", "LoadState")
_TIMER_PROPS = ("UnitFileState", "LastTriggerUSec", "NextElapseUSecRealtime",
                "TimersCalendar", "LoadState")


def _show(unit: str, props: tuple) -> Optional[Dict[str, str]]:
    """`systemctl show`, parsed. None when the question could not be put.

    Shells out for the same reason gitdiff.py does, on the same terms: argv,
    never a shell, and unit names that come from CHAIN above and never from a
    request.

    None on any failure, and every caller treats None as "cannot say" rather
    than as a value -- an unknown that resolves to the reassuring answer is
    how a monitor becomes decoration. That sentence was written here for
    `is-enabled` and it is the whole reason this function does not return {}.
    """
    try:
        args = ["systemctl", "show", unit]
        for k in props:
            args += ["-p", k]
        r = subprocess.run(args, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out: Dict[str, str] = {}
    for line in r.stdout.splitlines():
        k, _, v = line.partition("=")
        if k:
            out[k] = v.strip()
    return out or None


def _stamp(value: Optional[str]) -> Optional[datetime]:
    """A systemd timestamp, or None. `n/a` and the empty string are both None.

    systemd prints `ExecMainExitTimestamp=` with nothing after it for a unit
    that has never run, and `n/a` in some other places. Both mean the same
    thing and neither is a time.
    """
    if not value or value in ("n/a", "0"):
        return None
    for fmt in ("%a %Y-%m-%d %H:%M:%S %Z", "%a %Y-%m-%d %H:%M:%S"):
        try:
            t = datetime.strptime(value, fmt)
        except ValueError:
            continue
        return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
    return None


@dataclass
class Stage:
    """One unit of the overnight chain, as read from systemd and the database.

    THE TWO SOURCES ARE KEPT APART ON PURPOSE. `ran` comes from the unit and
    answers "did this fire"; `said` comes from the database and answers "what
    did it decide". A stage that ran and decided nothing and a stage that
    never fired are the same silence in the database and different facts, and
    telling them apart is this dataclass's entire reason to exist.
    """
    key: str
    name: str
    unit: str
    schedule: str = ""
    enabled: Optional[bool] = None
    last_at: Optional[datetime] = None
    #: When the last run STARTED, which is the only thing that can scope a
    #: database answer to that run. `last_at` is ExecMainExitTimestamp and
    #: every row a run writes is written BEFORE it, so scoping on `last_at`
    #: would discard exactly the decisions the run made.
    last_start: Optional[datetime] = None
    ok: Optional[bool] = None
    dry_run: bool = False
    installed: bool = True
    said: str = ""
    #: Set when the unit could not be read at all. The template renders this
    #: as a gap and NOT as a stage that did nothing.
    unreadable: bool = False

    @property
    def schedule_short(self) -> str:
        """The OnCalendar line, with the seconds off a plain daily time.

        ONLY a plain `HH:MM:00`. The runner's is `02..04:00/20:00`, where the
        trailing `:00` is part of a repeat expression and cutting it would
        turn "every twenty minutes between two and four" into something that
        is not a schedule at all. A shortener that cannot tell those apart
        should shorten neither.
        """
        m = re.fullmatch(r"(\d{2}:\d{2}):00", self.schedule or "")
        return m.group(1) if m else (self.schedule or "")


def units() -> Dict[str, Stage]:
    """Every stage of the chain, read from systemd. Never partial silently.

    A unit that cannot be read comes back with `unreadable=True` rather than
    absent, so the page renders four stages whatever happens and a missing
    answer is visible as a missing answer.
    """
    out: Dict[str, Stage] = {}
    for key, name, unit in CHAIN:
        st = Stage(key=key, name=name, unit=unit)
        svc = _show(f"{unit}.service", _SERVICE_PROPS)
        tmr = _show(f"{unit}.timer", _TIMER_PROPS)
        if svc is None and tmr is None:
            st.unreadable = True
            out[key] = st
            continue
        if svc is not None:
            st.installed = svc.get("LoadState") != "not-found"
            st.last_at = _stamp(svc.get("ExecMainExitTimestamp"))
            st.last_start = _stamp(svc.get("ExecMainStartTimestamp"))
            result = svc.get("Result")
            st.ok = None if not result else (result == "success")
            # `--dry-run` as its own word, not a substring: a path containing
            # the text would otherwise mark a live unit as a dry run, which
            # errs towards telling the reader less happened than did.
            st.dry_run = "--dry-run" in (svc.get("ExecStart") or "").split()
        if tmr is not None:
            state = tmr.get("UnitFileState", "")
            if state in ("enabled", "enabled-runtime", "static"):
                st.enabled = True
            elif state in ("disabled", "masked", "masked-runtime"):
                st.enabled = False
            cal = tmr.get("TimersCalendar") or ""
            m = re.search(r"OnCalendar=([^;}]+)", cal)
            if m:
                # `*-*-* ` is "every day" and every unit here carries it, so
                # it is noise in four cells out of four. The rest is kept
                # verbatim -- see Stage.schedule_short for why it is not
                # tidied any further than this.
                st.schedule = re.sub(r"^\*-\*-\*\s+", "", m.group(1).strip())
        out[key] = st
    return out


def describe_night(stages: Dict[str, Stage],
                   decisions: List[Dict[str, Any]]) -> None:
    """Fill in each stage's `said` from the database. Mutates `stages`.

    ONLY THE APPROVE STAGE HAS A DATABASE ANSWER OF ITS OWN, and pretending
    otherwise is how a page grows a number nobody can trace. What the runner,
    the merge sweep and the deploy did is already on the threads below and in
    `deployments`; repeating a count here would be a second tally of the same
    rows, which is the thing 012 argues against in the words it used about
    hand-maintained numbers being wrong three times in one day.

    A refusal is as much of an answer as an approval. `approve
    .record_unattended_refusal` exists so that a night the ranker declined
    leaves a row -- without it, declining and not running are the same
    silence.

    SCOPED TO THE RUN THE ROW DESCRIBES, SINCE 11 SEP 2026
    -------------------------------------------------------
    `decisions` is every `decided_via='unattended'` row since the last brief,
    which is a WINDOW, and the template prints this immediately after "failed
    when it last ran", which is ONE RUN. Joining a window to a run with an em
    dash asserts they are the same event.

    On 11 Sep 2026 that read "failed when it last ran - 2 approvals". Both
    halves were true and the sentence was not: the sweep died in `plan()` at
    01:30:02 and wrote no row at all, and the two approvals were decisions 26
    and 27, made at 11:31 and 14:11 THE PREVIOUS DAY by hand runs of
    run_autoapprove.py. `journalctl` has the unit activating three times
    total, none of them then.

    So the count is taken over the rows this run wrote, and nothing else. The
    window still decides which decisions the page loads; this decides which of
    them the STAGE may speak for.

    THE SCOPE IS THE RUN'S LIFETIME, `last_start` TO `last_at`, and both ends
    are load-bearing.

    `last_start` is ExecMainStartTimestamp and `last_at` is
    ExecMainExitTimestamp. A run writes its decision BEFORE it exits, so a
    lower bound of `last_at` would discard every row the run actually made and
    report a good night as a dead one. And a process that has exited cannot
    write, so a row stamped after `last_at` is somebody else's -- which is not
    hypothetical: the hand run that re-ran this sweep at 08:36 on 11 Sep,
    after the 01:30 unit had died, was attributed to the 01:30 unit by an
    open-ended upper bound and rendered "failed when it last ran - 1
    approval". The same sentence, the same day, by the same mistake.

    `last_at` is only an upper bound when it is ONE, which means at or after
    `last_start`. A unit that is running right now carries the PREVIOUS exit
    stamp, and treating that as the ceiling would close the window before it
    opened.

    IT DOES NOT FIX THE PROVENANCE, and that is deliberate. A hand run started
    while the timer's own run is in flight still lands inside the lifetime and
    is still counted, because `decided_via` records the CODE PATH and no
    column records the TRIGGER. That is a much smaller hole than the one this
    closes and it is not closable from the reading side. See
    specs/auto-approval.md §9.14; it wants a column, not a reinterpretation.
    """
    approve = stages.get("approve")
    if approve is None:
        return
    if approve.last_start is None:
        # NEVER RAN, or systemd could not say when. No run means no row can be
        # attributed to one, and "approved nothing" would be a claim about a
        # run that did not happen. The template renders "has never run" from
        # `last_at`, which is the honest answer and is not this function's.
        approve.said = ""
        return
    ends = (approve.last_at
            if approve.last_at is not None
            and approve.last_at >= approve.last_start else None)
    mine = [d for d in decisions
            if d["decided_at"] is not None
            and d["decided_at"] >= approve.last_start
            and (ends is None or d["decided_at"] <= ends)]
    if not mine:
        # THE RUN WROTE NOTHING, and by construction that means it did not get
        # as far as deciding: a sweep that decides writes either an approval
        # (approve_batch) or a refusal (record_unattended_refusal), and §9.5
        # exists so that the second of those cannot be silent. Paired with
        # "failed when it last ran" this is the whole truth about 11 Sep.
        approve.said = "approved nothing"
        return
    took = [d for d in mine if d["decision"] == "APPROVED"]
    passed = [d for d in mine if d["decision"] != "APPROVED"]
    parts = []
    if took:
        parts.append(f"{len(took)} approval{'' if len(took) == 1 else 's'}")
    if passed:
        # ONE RUN, so this is no longer a count of nights. It used to read
        # "2 nights it declined to choose" because it was summing a window,
        # and a single run cannot decline twice.
        parts.append("declined to choose")
    approve.said = ", ".join(parts)


#: A merge subject that names a fleet task. Both spellings are in the history
#: -- "Merge fleet task 58: ..." and "Merge task 34: ..." -- and a pattern that
#: knew only the first missed two of the three instances this was built for.
_MERGE_NAMES_TASK = re.compile(r"\btask[ -](\d+)\b", re.I)


def unrecorded_merges(repo_root: Path, pairs: Sequence[tuple],
                      recorded: Dict[int, tuple]) -> List[Ask]:
    """Merges naming a task that nothing in the database accounts for.

    THE ONLY THING THAT WOULD HAVE CAUGHT §9.18, AND IT TAKES ABOUT A SECOND.

    For every merge commit on a base branch whose subject names a fleet task,
    ask one question: is that task MERGED -- in which case the machine did it
    and recorded it by construction -- or does a decision cite it? If neither,
    work reached a base branch and nothing anywhere says why.

    THREE INSTANCES, AND TWO WERE FOUND BY RUNNING THIS RATHER THAN BY LUCK.
    Task 51 was noticed by accident on 11 Sep while backfilling something else.
    The same sweep then found tasks 34 and 50 -- the two documents that became
    candidate batches 9 and 10, which is to say most of the open pool and every
    unattended approval made since descends from two merges nothing recorded.

    THE SHAPE IS NARROW AND WORTH STATING, because it is what makes this cheap:
    every unrecorded merge so far is a HAND-MERGE OF A TASK WHOSE ROW READS
    FAILED. A MERGED row is written by the machine that merged it; the gap is
    exactly the population §9.17's pointer was built for.

    A READING AND NEVER A GATE. specs/auto-approval.md §9.18: a gate here would
    stop a person fixing production at 3am, which is the one thing this system
    must never do. This reports, and the remedy is a sentence somebody writes.

    `recorded` is passed in rather than read here, so the git walk and the
    database question stay separable and the caller does one query rather than
    one per merge.
    """
    out: List[Ask] = []
    for repo, base in pairs:
        path = repo_root / repo
        # A BASE BRANCH THAT DOES NOT EXIST IS SKIPPED, AND THAT IS NOT A
        # SILENT CAP. Task 4 names fleet/main, which fleet has never had under
        # that name; a branch with no commits has no merges to miss, so this
        # excludes an empty set rather than truncating a real one. A branch
        # that exists and cannot be walked is a different thing and is
        # reported below.
        if (path / ".git").exists() and subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--verify", "--quiet",
                 f"refs/heads/{base}"],
                capture_output=True, text=True, timeout=30).returncode != 0:
            continue
        if not (path / ".git").exists():
            out.append(Ask(
                kind="MERGE_SWEEP_UNREADABLE",
                headline=f"{repo} could not be read, so merges into {base} "
                         f"were not checked for a record",
                detail="Reported rather than skipped: an unchecked repository "
                       "and a clean one leave the same silence here, which is "
                       "the defect this reading exists to find.",
                needs="NEEDS_A_MACHINE"))
            continue
        proc = subprocess.run(
            ["git", "-C", str(path), "log", "--merges",
             "--format=%h%x00%cI%x00%s", base],
            capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            out.append(Ask(
                kind="MERGE_SWEEP_UNREADABLE",
                headline=f"`git log` failed on {repo}, so merges into {base} "
                         f"were not checked",
                detail=(proc.stderr or "").strip()[:300],
                needs="NEEDS_A_MACHINE"))
            continue
        for line in proc.stdout.splitlines():
            parts = line.split("\x00") if "\x00" in line else line.split("\0")
            if len(parts) != 3:
                continue
            sha, when, subject = parts
            m = _MERGE_NAMES_TASK.search(subject)
            if not m:
                continue
            tid = int(m.group(1))
            status, decisions = recorded.get(tid, (None, ()))
            if status == "MERGED" or decisions:
                continue
            out.append(Ask(
                kind="MERGE_WITH_NO_DECISION",
                headline=f"{repo} {sha} merged task {tid} into {base} and "
                         f"nothing records why",
                detail=(f"The task row reads {status or 'no task row'}, and no "
                        f"decision cites task {tid}. So the work is on {base} "
                        f"and the only account of it is this commit. Write the "
                        f"decision — what shipped, when, and that it was found "
                        f"afterwards rather than decided at the time — with "
                        f"`fleet decision record --task {tid} "
                        f"--shipped-task {tid}`."),
                href=f"/tasks/{tid}", href_label=f"task {tid}",
                meta=[("merged", when[:16].replace("T", " ")),
                      ("subject", subject[:60])],
                needs="NEEDS_YOU"))
    return out


def merge_record_index(rows: Sequence[Dict[str, Any]]) -> Dict[int, tuple]:
    """{task_id: (status, (decision ids,))}, for unrecorded_merges."""
    idx: Dict[int, tuple] = {}
    for r in rows:
        idx[r["id"]] = (r["status"], tuple(r["decision_ids"] or ()))
    return idx


def fleet_blocked(credit: Optional[Dict[str, Any]],
                  deployments: Dict[str, deploys.Deployment],
                  stages: Optional[Dict[str, Stage]] = None) -> List[Ask]:
    """What Fleet cannot do itself, derived from things that know.

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
            meta=[("committed so far", money(credit.get("committed_gbp")))]))

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

    # 3. EVERY STAGE OF THE CHAIN, not just the runner.
    #
    #    This watched `fleet-runner.timer` alone until 10 Sep 2026, which was
    #    right while the runner was the only thing that ran unattended. Three
    #    more units now decide things with nobody watching, and a page that
    #    checked one of four would have reported a silent night as a quiet
    #    one -- which is the failure this page's fourth rule exists to stop.
    #
    #    Three distinct answers, and they must not collapse into two:
    #      disabled     a decision, possibly a deliberate one, that stays made
    #      failed       it ran and did not finish
    #      unreadable   the question could not be put, which is not "fine"
    for st in (stages or {}).values():
        if st.unreadable or not st.installed:
            asks.append(Ask(
                kind="UNIT_UNREADABLE",
                headline=f"Fleet cannot tell whether {st.unit} is running",
                detail=f"`systemctl show {st.unit}` did not answer, or the "
                       f"unit is not installed. Reported rather than assumed: "
                       f"an unknown that resolves to 'enabled' is how a "
                       f"monitor becomes decoration.",
                needs="NEEDS_A_MACHINE"))
            continue
        if st.enabled is False:
            asks.append(Ask(
                kind="UNIT_DISABLED",
                headline=f"{st.unit}.timer is installed and disabled",
                detail=f"{st.name.lower()} does not happen unless you start "
                       f"it by hand. Enable with `systemctl enable --now "
                       f"{st.unit}.timer` once you are satisfied it should "
                       f"run.",
                needs="NEEDS_YOU",
                meta=[("scheduled", st.schedule or "\u00b7")]))
        elif st.enabled is None:
            asks.append(Ask(
                kind="UNIT_UNREADABLE",
                headline=f"Fleet cannot tell whether {st.unit}.timer is "
                         f"enabled",
                detail="systemd did not give a state this page recognises.",
                needs="NEEDS_A_MACHINE"))
        if st.ok is False:
            asks.append(Ask(
                kind="UNIT_FAILED",
                headline=f"{st.unit} failed the last time it ran",
                detail=f"`systemctl status {st.unit}` and `journalctl -u "
                       f"{st.unit}` say why. The stage did not do its work, "
                       f"so whatever depended on it did not happen either.",
                needs="NEEDS_YOU",
                meta=[("last ran", st.last_at.strftime("%d %b %H:%M")
                       if st.last_at else "\u00b7")]))

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
        # money(), not a format string. This line read
        # `£{float(r['spent_all_runs'] or 0):.2f}` until 10 Sep 2026 and put
        # £0.00 beside a task with no run -- in the same meta list where
        # human_elapsed was correctly rendering a dot for the same absence.
        meta = [("cost", money(r["spent_all_runs"])),
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


@dataclass
class UnreadSpec:
    """A feature that shipped with nobody reading its spec against its diff."""
    task_id: int
    title: str
    repo: str
    merged_at: Optional[datetime]
    merge_commit: str
    reqs: List[Any] = field(default_factory=list)


def unread_specs(rows: List[Dict[str, Any]]) -> List[UnreadSpec]:
    """The numbered requirements of everything that merged unattended.

    WHAT THIS IS, STATED SO IT IS NOT OVERSOLD
    -------------------------------------------
    It is a list. It checks nothing, ticks nothing, and matches nothing to the
    diff. specs/auto-approval.md §9.12 measured the cheap matcher that would:
    grepping task 53's real diff for the requirement number scored 1 for §2.1
    and §2.5 (both stray digits) and 0 for §2.2 and §2.3, which were
    implemented -- so it would have refused working changes and passed the one
    that was missing, and been believed. A list that makes no claim is worth
    more than a matcher that makes a wrong one.

    WHY IT IS AN ASK AND NOT A NOTE
    --------------------------------
    §9.9: four green checks establish that the tree typechecks, that the suite
    passes, that one new test bites, and that no pair landed in half. They
    establish nothing about whether the spec was followed. `auto_merge: false`
    was the only reader in the path and it is gone; `draft_spec` came off
    NEVER_UNATTENDED on 10 Sep 2026 and the last reading with it. So this is
    the only place a person is put in front of what a feature promised, and it
    happens AFTER the feature shipped, which is the whole of what is on offer
    once the merge is automatic.

    The brief carries the same list (`brief/pass_.py`). It is here as well
    because the brief is read once and this page is read every morning, and a
    thing that must be caught within a day should not depend on which of the
    two the reader opened.

    WHAT THE MARKER CONVENTION CHANGED, AND WHAT IT DID NOT
    --------------------------------------------------------
    §9.12's convention was built on 10 Sep 2026:
    `contracts/checks/spec_requirements_cited.py` refuses a change whose
    numbered requirements are cited nowhere in its diff, and
    `draft_spec_shape.py` refuses a draft that numbers none.

    So on the two contracts that carry it, a merge can no longer happen with
    a requirement unmentioned. That is NOT the same as the requirement being
    built: an agent can write `// spec:2.5` and change nothing. What it buys
    is that the omission is now written down and attributable in the diff.

    This list therefore stays exactly as long as it was -- every numbered
    requirement of every unattended merge -- and its job has narrowed from
    "find what was skipped" to "check that the claims are true". That is
    still a reading job. Anything shorter would need something that reads
    the spec against the diff and means it, and nothing cheap does that.
    """
    out: List[UnreadSpec] = []
    for r in rows:
        reqs = requirements.parse(r.get("spec_md"))
        if not reqs:
            # A spec with no numbered requirements is not a spec this can say
            # anything about, and an empty checklist beside a merge reads as
            # "nothing to check" -- which is a claim, and the wrong one.
            continue
        out.append(UnreadSpec(
            task_id=r["task_id"], title=r["title"], repo=r["repo"],
            merged_at=r.get("merged_at"),
            merge_commit=(r.get("merge_commit") or "")[:12],
            reqs=reqs))
    return out


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


def build_threads(rows: List[Dict[str, Any]],
                  failures_by_task: Dict[int, List[Dict[str, Any]]],
                  deployments: Dict[str, deploys.Deployment]) -> List[Thread]:
    """candidate -> spec -> the draft merges -> code task -> merge -> shipped.

    THE PROMOTION STEP IS GONE, AND ITS ABSENCE IS THE CHANGE
    ----------------------------------------------------------
    Every thread used to carry `promote_gap()`: "Promoted the draft to specs/
    -- a human act with no database row". That was true of the loop as it was
    designed on 7 Sep and false by 10 Sep. `console/autoqueue.py` queues the
    code task off the accepted draft; the draft stays in `drafts/`; nothing is
    copied into `specs/`; and the act it described leaves two rows, a merge
    verdict and a task.

    It was also drawn wrong for its whole life. It set `actor="HUMAN"`, and
    the template tests the actor before it tests `unrecorded`, so the one step
    on the page that existed to be a HOLE IN THE RECORD rendered as a solid
    "you did this" dot and `.rail li.gap::before` never fired for it.

    What replaces it is not a step. It is the pair of merge steps below, each
    taking its actor from `decided_via`, and a real gap when the draft merged
    and no code task followed.
    """
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
            auto = actor_of(r["decided_via"])
            t.steps.append(Step(
                actor=auto,
                label=("The ranker ticked it" if auto == "AUTO"
                       else "You approved it"),
                detail=excerpt(r["decision_reason"]), when=r["decision_at"],
                href="/decisions", status=r["disposition"]))

        if r["spec_task_id"]:
            t.steps.append(_task_step(
                "Wrote a draft spec", r["spec_task_id"], r["spec_status"],
                r["spec_completed_at"], r["spec_cost"], r["spec_elapsed"],
                failures_by_task))
            t.steps.extend(_merge_step(
                r["spec_status"], r["spec_merged_via"], r["spec_branch"],
                r["spec_completed_at"], what="the draft"))

        if r["work_task_id"]:
            t.steps.append(_task_step(
                "Built the change", r["work_task_id"], r["work_status"],
                r["work_completed_at"], r["work_cost"], r["work_elapsed"],
                failures_by_task))
            t.steps.extend(_merge_step(
                r["work_status"], r["work_merged_via"], r["work_branch"],
                r["work_completed_at"], what="it"))
            t.steps.extend(_ship_steps(
                r["work_status"], r["work_work_type"],
                r["work_completed_at"], deployments))
        elif r["spec_status"] == "MERGED":
            # THE ONE STATE IN THIS LOOP WHERE NOTHING IS WRONG AND NOTHING
            # HAPPENS EITHER. console/automerge.py names it: a refusal from
            # autoqueue is logged and does not fail the sweep, because the
            # draft is merged and pushed either way. That leaves a merged
            # spec with no work queued, and it is invisible everywhere else --
            # no task failed, no check went red, no revert triggered.
            t.steps.append(Step(
                actor="GAP", label="No code task was queued from this draft",
                detail="the draft merged and `autoqueue.from_accepted_draft` "
                       "did not produce a task. Nothing failed; the chain "
                       "simply stopped. `journalctl -u fleet-automerge` "
                       "carries the refusal, and `./fleet task add` queues "
                       "the work by hand.",
                status="NOT_QUEUED"))

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


def _merge_step(status: str, decided_via: Optional[str],
                branch: Optional[str], when: Optional[datetime],
                what: str) -> List[Step]:
    """Who merged it, from the row rather than from the assumption.

    "You merged it" was hardcoded here, and it was correct only for as long as
    a person was the only thing that could merge. `console/automerge.py` came
    off `--dry-run` on 10 Sep 2026 and `draft_spec` came off its
    NEVER_UNATTENDED tuple the same day, so both of these merges can now be a
    timer at 03:30. A page that says "you" about a merge nobody made is wrong
    about the only thing it is for.
    """
    if status != "MERGED":
        return []
    auto = actor_of(decided_via)
    return [Step(
        actor=auto,
        label=(f"Merged {what} unattended" if auto == "AUTO"
               else f"You merged {what}"),
        detail=branch or "", when=when, status="MERGED")]


def _ship_steps(status: str, work_type: Optional[str],
                completed_at: Optional[datetime],
                deployments: Dict[str, deploys.Deployment]) -> List[Step]:
    """Whether it is RUNNING, which is a different question from merged.

    Built, merged and deployed are three states. `tasks.status = 'MERGED'`
    means a branch went into the base; whether it is running is a different
    question with a different source, and on this host the frontend cannot
    always answer it at all.
    """
    if status != "MERGED":
        return []
    verdict, why = deploys.shipped(work_type, completed_at, deployments)
    return [Step(
        actor="FLEET" if verdict == "SHIPPED" else "GAP",
        label={"SHIPPED": "Running in production",
               "NOT_SHIPPED": "Merged, NOT deployed",
               "NOTHING_TO_SHIP": "Nothing to deploy",
               "CANNOT_SAY": "Cannot tell whether it shipped"}[verdict],
        detail=why, status=verdict)]


def loose_threads(rows: List[Dict[str, Any]],
                  failures_by_task: Dict[int, List[Dict[str, Any]]],
                  deployments: Dict[str, deploys.Deployment]) -> List[Thread]:
    """Tasks belonging to no candidate, as short threads.

    Task 26 is why this exists: it was inserted directly, because approve.py
    only makes draft-spec tasks. A threads-only page would have shown its
    candidate's thread and silently dropped any task that had no candidate.

    IT NO LONGER MEANS "a person typed this". `console/autoqueue.py` writes
    `candidates.work_task_id`, so a code task that came from a draft is on its
    candidate's thread and not here. What lands here now is what genuinely has
    no candidate: a candidate-producer run, a piece of infrastructure, a task
    somebody queued by hand. The step says that rather than the older sentence
    about the approval surface, which described a route that has one more exit
    than it did.
    """
    out: List[Thread] = []
    for r in rows:
        t = Thread(key=f"t{r['id']}", title=r["title"], repo=r["repo"],
                   objective_ref=r["objective_ref"])
        t.steps.append(Step(
            actor="HUMAN", label="Queued directly",
            detail="not from a candidate - no ticked candidate produced it",
            when=r["created_at"]))
        t.steps.append(_task_step(
            "Built the change", r["id"], r["status"], r["completed_at"],
            r["committed_gbp"], r["elapsed_seconds"], failures_by_task))
        t.steps.extend(_merge_step(r["status"], r["merged_via"],
                                   r["branch_name"], r["completed_at"],
                                   what="it"))
        t.steps.extend(_ship_steps(r["status"], r["work_type"],
                                   r["completed_at"], deployments))
        out.append(t)
    return out


def in_window(threads: List[Thread], since: Optional[datetime]) -> List[Thread]:
    """Threads that moved since the last brief.

    Filtered here rather than in SQL because a thread STRADDLES the boundary:
    candidate 12 was approved on 7 Sep and its code task queued on 8 Sep, and a
    window over any single timestamp would either drop it or count it twice.
    """
    return [t for t in threads if t.progressed_since(since)]


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
