"""Sending a verified branch back, and requeueing it, in one operation.

WHAT THIS EXISTS BECAUSE OF. `task_transitions` has carried
READY_FOR_REVIEW -> REWORK ('you sent it back') and REWORK -> QUEUED
('requeued with feedback') since 003. Nothing ever implemented them: there is
no other caller of REWORK in this repository. On 22 Sep 2026 two tasks were
sent back by hand along that edge, and both were destroyed by the same defect.

    task 137: FAILED -- UniqueViolation: duplicate key value violates
                        unique constraint "runs_one_active_per_task"

A task at READY_FOR_REVIEW has a run at AWAITING_HUMAN, and
`runs_one_active_per_task` is a unique index over `runs(task_id) WHERE status
IN ('ACTIVE','AWAITING_HUMAN')`. Move the task to QUEUED and the old run still
holds the slot, so the next claim cannot open a run and the tick dies three
seconds in -- after `claim_task()` has already spent the attempt. 137 went to
3/3 with its branch_name cleared without an agent ever running.

`reclaim_stale_task` has always known this. It closes the slot-holding run
before it requeues, and says why: "Without this the requeue below succeeds and
the next tick dies on the unique index instead, which is how this presented the
first time." That was 008. This module is that same step for the edge a person
uses.

THE CLOSE GOES FIRST, AND THAT IS THE WHOLE SAFETY PROPERTY. It is the first
write in the transaction, so a console that may not close the run raises before
anything moves and the task stays exactly where it was. The failure mode this
replaces -- a task QUEUED with its slot held -- is unreachable rather than
merely unlikely.

    fleet_task_runner   UPDATE (status, completed_at, reason, ...) ON runs
    fleet_console       -- nothing, until 054 grants the two columns

So before 054 is applied this module refuses and explains; it never half-acts.

THE RUN IS CLOSED AS FAILED, WHICH IS reclaim's WORD AND NOT A JUDGEMENT. The
run's `reason` is left alone -- "verified, branch ready" stays on the row --
because what is being recorded is that the run is over, not that it was bad.

WHAT MERGED UNDERNEATH IT, WHICH IS THE PART A PERSON CANNOT SEE

console/rank.py gate 3 (`path_overlap`) refuses a candidate whose paths collide
with a LIVE task, and `LIVE_TASK_STATES` is QUEUED, CLAIMED, RUNNING,
READY_FOR_REVIEW. A task in a terminal state is invisible to it, so reviving
one walks past a gate that has already decided there was no collision --
nothing re-checks on the way back in.

Both incidents came in through that door, and neither would have been caught by
re-running gate 3 either: by the time each task was revived, the work it
collided with had MERGED, which is terminal too. 137's branch was cut before
136 landed in `orders.py`; 142's before 147 landed in `analytics_engine.py`.
The question that matters for a revived task is therefore not "does anything
live overlap me" but "what landed in my files while I was away", and the answer
is a fact about git, not about the queue. `merged_since()` reports it and this
module prints it. It does not refuse on it: the remedy is a sentence in the
feedback, which the person writing the feedback is already here to write.
"""
from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from console import config, db, rank

#: The statuses a run holds the one-active-per-task slot in. Spelled here as
#: 003 spells it in the index, because a third spelling is a third thing to
#: keep in step.
SLOT_HELD_BY = ("ACTIVE", "AWAITING_HUMAN")

#: Where a task may be sent back from. REWORK is reachable only from
#: READY_FOR_REVIEW; FAILED goes straight to QUEUED by its own edge and needs
#: no REWORK hop, but it needs the same run-closing, so it is handled here too.
FROM_READY = "READY_FOR_REVIEW"
FROM_FAILED = "FAILED"


@dataclass
class Rework:
    ok: bool
    reason: str = ""
    task_id: int = 0
    was: str = ""
    attempts: int = 0
    max_attempts: int = 0
    new_max_attempts: int = 0
    branch: str = ""
    closed_runs: List[int] = field(default_factory=list)
    merged_since: List[Dict[str, Any]] = field(default_factory=list)
    detail: List[str] = field(default_factory=list)

    def note(self, line: str) -> None:
        self.detail.append(line)


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=120)
    return r.stdout.strip() if r.returncode == 0 else ""


def merged_since(task: Dict[str, Any], base_sha: str,
                 repo: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Commits that landed in this task's declared paths since `base_sha`.

    The question a revived task actually needs answered. Read against the
    REMOTE's base branch, not the checkout's: since 2026-09-09 the console
    cannot fast-forward any checkout, so the local ref is routinely behind the
    branch this task will be re-cut from and would under-report.

    Returns [] when the base is unknown or git cannot answer -- an empty list
    here means "nothing to tell you", and the caller must not read it as
    "nothing landed". It is a report, not a gate.
    """
    if not base_sha:
        return []
    repo = repo or (Path(config.repo_root()) / task["repo"])
    paths, _ = rank.declared_paths(task)
    if not paths:
        return []
    base_branch = task.get("base_branch") or "main"
    # The remote's tip, by name, so a stale checkout does not shrink the answer.
    tip = _git(repo, "rev-parse", f"origin/{base_branch}") or \
        _git(repo, "rev-parse", base_branch)
    if not tip:
        return []
    # Globs are not pathspecs git understands the same way; hand it the
    # directory prefix and let the caller read the file list.
    out = _git(repo, "log", "--format=%H%x00%s", f"{base_sha}..{tip}",
               "--", *[p.split("*")[0].rstrip("/") or "." for p in paths])
    rows: List[Dict[str, Any]] = []
    for line in out.splitlines():
        if "\x00" not in line:
            continue
        sha, subject = line.split("\x00", 1)
        files = _git(repo, "show", "--name-only", "--format=", sha).splitlines()
        hit = sorted({f for f in files
                      if any(rank.paths_overlap(f, p) for p in paths)})
        if hit:
            rows.append({"sha": sha[:12], "subject": subject, "files": hit})
    return rows


def plan(task_id: int) -> Rework:
    """Everything that must hold, and what the person should know, before it
    is done. Reads only."""
    with db.connect() as conn:
        task = conn.execute(
            "SELECT id, status, attempts, max_attempts, branch_name, repo,"
            "       base_branch, spec_md, acceptance_contract"
            "  FROM tasks WHERE id=%s", (task_id,)).fetchone()
        if task is None:
            return Rework(False, f"there is no task {task_id}")
        r = Rework(True, task_id=task_id, was=task["status"],
                   attempts=task["attempts"],
                   max_attempts=task["max_attempts"],
                   branch=task["branch_name"] or "")
        if task["status"] not in (FROM_READY, FROM_FAILED):
            return Rework(False, f"task {task_id} is {task['status']}; only "
                                 f"{FROM_READY} and {FROM_FAILED} can be sent back",
                          task_id=task_id, was=task["status"])
        open_runs = conn.execute(
            "SELECT id, status, reason FROM runs"
            "  WHERE task_id=%s AND status = ANY(%s) ORDER BY id",
            (task_id, list(SLOT_HELD_BY))).fetchall()
        r.closed_runs = [x["id"] for x in open_runs]
        for x in open_runs:
            r.note(f"run {x['id']} is {x['status']} and holds the "
                   f"one-active-per-task slot; it will be closed first")
        last = conn.execute(
            "SELECT payload FROM run_steps"
            "  WHERE run_id IN (SELECT id FROM runs WHERE task_id=%s)"
            "    AND step_type='PATCH_PROPOSED'"
            "  ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
    base = (last or {}).get("payload", {}).get("base_commit_sha", "") if last else ""
    r.merged_since = merged_since(task, base)
    if r.merged_since:
        r.note(f"{len(r.merged_since)} commit(s) landed in this task's declared "
               f"paths since it was cut at {base[:12]}")
    elif base:
        r.note(f"nothing has landed in its declared paths since {base[:12]}")
    return r


def rework(task_id: int, feedback: str, extra_attempts: int = 1,
           dry_run: bool = False) -> Rework:
    """Close the run, send the task back, requeue it with the feedback."""
    r = plan(task_id)
    if not r.ok:
        return r
    if not (feedback or "").strip():
        return Rework(False, "rework needs feedback: a requeue with nothing "
                             "new said buys the same attempt again",
                      task_id=task_id, was=r.was)
    r.new_max_attempts = max(r.max_attempts, r.attempts + max(extra_attempts, 0))
    if r.attempts >= r.new_max_attempts:
        return Rework(False, f"task {task_id} is at {r.attempts}/"
                             f"{r.new_max_attempts} and would not be claimable; "
                             f"raise the attempts", task_id=task_id, was=r.was)
    if dry_run:
        r.note("dry run: nothing was written")
        return r

    with db.writer() as conn:
        with conn.transaction():
            # FIRST, AND THAT IS THE POINT. A console that may not close the
            # run raises here, the transaction rolls back, and the task is
            # exactly where it was. See the module docstring.
            if r.closed_runs:
                conn.execute(
                    "UPDATE runs SET status='FAILED',"
                    "       completed_at=coalesce(completed_at, now())"
                    "  WHERE task_id=%s AND status = ANY(%s)",
                    (task_id, list(SLOT_HELD_BY)))
            if r.was == FROM_READY:
                conn.execute("UPDATE tasks SET status='REWORK' WHERE id=%s",
                             (task_id,))
            conn.execute(
                "UPDATE tasks SET status='QUEUED', claimed_at=NULL,"
                "       max_attempts=%s, spec_md = spec_md || %s"
                "  WHERE id=%s", (r.new_max_attempts, feedback, task_id))
    r.note(f"{r.was} -> QUEUED at {r.attempts}/{r.new_max_attempts}")
    return r


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m console.rework",
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task", type=int, required=True)
    p.add_argument("--feedback-file", type=Path, required=True,
                   help="markdown appended to spec_md; spec_md is append-only")
    p.add_argument("--extra-attempts", type=int, default=1)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)

    feedback = a.feedback_file.read_text() if a.feedback_file.exists() else ""
    r = rework(a.task, feedback, a.extra_attempts, dry_run=a.dry_run)
    head = "would send back" if a.dry_run else "sent back"
    print(f"{head} task {r.task_id}" if r.ok else f"REFUSED: {r.reason}")
    for line in r.detail:
        print(f"  {line}")
    for m in r.merged_since:
        print(f"  ! {m['sha']} {m['subject'][:72]}")
        for f in m["files"]:
            print(f"      {f}")
    return 0 if r.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
