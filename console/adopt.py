"""Taking a branch the gate refused, when the gate was what was wrong.

A FAILED task whose branch verified GREEN can be moved to READY_FOR_REVIEW
instead of being rebuilt. 038 adds the edge and the database enforces the half
of the precondition that lives in the database; this module enforces the half
that lives in git, and refuses first, because a refusal that costs a
subprocess is better than one that costs a transaction.

WHAT IT COST TO FIND OUT THIS WAS MISSING. Task 69 ran four times, 12 Sep 2026.
Run 44 produced a branch that passed all six of its contract's checks and was
refused by max_test_diff_lines at a value retired the same day. There was no
way to reach that branch: FAILED leads only to QUEUED, and QUEUED means the
agent writes the change again from the spec. It does not write the same thing
-- four runs off one spec and one base gave tests of 377, 606, 439 and 385
lines -- and the rebuild failed ruff on a single new I001. £15.06, four
branches, nothing merged, and the correct one had been on disk since the third.

THE TWO QUESTIONS THIS ASKS THE TREE

  IS THIS THE COMMIT THAT WAS VERIFIED? The branch tip must equal the
  patch_commit_sha of the run being adopted. A branch that has moved since --
  amended, rebased, pushed over -- is not the artefact the checks looked at,
  and the run's greenness says nothing about it.

  HAS THE BASE MOVED? The run's base_commit_sha must still be the tip of the
  task's base branch. Green against 871f165d is not green against whatever main
  becomes: the merge that ships is `branch + base-as-it-is`, and git can merge
  a verified branch into a moved base cleanly and produce something broken.
  console/reverify.py exists because of exactly that, and this refuses rather
  than leaning on it.

THE SECOND ONE IS A FAST REFUSAL AND NOT THE ONLY DEFENCE. accept() re-runs the
contract's verification against the merged tree before merging, for every
branch, adopted or not. So a stale adoption cannot ship a broken merge; it can
only waste the human who clicked Accept. Refusing here turns that into a
sentence naming the two shas instead.

WHAT THIS DOES NOT DO. It does not merge, it does not push, and it does not
record a verdict. It moves a row to READY_FOR_REVIEW, which is where a person
decides -- the same place the runner's own branches arrive, reached by a
different edge.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from console import config, db

BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")


class NotAdoptable(RuntimeError):
    """The branch, the base or the record does not support adoption."""


@dataclass
class Adoption:
    task_id: int
    branch: str
    run_id: int
    base_sha: str
    head_sha: str
    checks: list[str] = field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise NotAdoptable(
            f"git {' '.join(args)} failed in {repo.name}: "
            f"{(r.stderr or r.stdout).strip()[:200]}")
    return r.stdout.strip()


def _check_is_green(c: dict) -> bool:
    """runner/verify.py's Check.passed, read back off the payload.

    Deliberately the same order as the original, including why: unresolved and
    undecided are failures BEFORE the skip branch is reached, so a checker that
    went missing or a check the kernel killed cannot fall through into "there
    was nothing for it to do".
    """
    if c.get("unresolved_reason") is not None:
        return False
    if c.get("undecided_reason") is not None:
        return False
    if c.get("skipped_reason") is not None:
        return True
    return c.get("exit_code") == 0 and not c.get("timed_out")


def _verification_is_green(payload: dict) -> bool:
    """Verification.passed, likewise, including the half people forget.

    Every check passed AND at least one of them actually ran. A payload of
    skips establishes nothing, and nothing is not a pass.
    """
    if payload.get("verification_skipped") is not None:
        return False
    checks = payload.get("checks") or []
    if not checks:
        return False
    if not any(c.get("skipped_reason") is None
               and c.get("unresolved_reason") is None
               and c.get("undecided_reason") is None for c in checks):
        return False
    return all(_check_is_green(c) for c in checks)


def _boundary_was_size_only(payload: dict) -> bool:
    """Nothing protected, nothing outside the contract. Size, or nothing.

    A run that touched a protected path cannot have its checks believed --
    api/tests/** is on that list, and a suite the change rewrote cannot judge
    the change. Today such a run never reaches verification, so this is
    belt-and-braces; it is here so that this module states the property it
    depends on rather than inheriting it from an ordering somewhere else.
    """
    v = payload.get("boundary_violations") or {}
    return not (v.get("protected") or {}) and not (v.get("outside_writable") or [])


def plan(task_id: int, branch: str) -> Adoption:
    """Everything that must be true, asked before anything is written."""
    if not BRANCH_RE.match(branch or ""):
        raise NotAdoptable(f"{branch!r} is not a branch name this will pass to git")

    with db.connect() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=%s",
                            (task_id,)).fetchone()
        if task is None:
            raise NotAdoptable(f"there is no task {task_id}")
        if task["status"] != "FAILED":
            raise NotAdoptable(
                f"task {task_id} is {task['status']}, not FAILED. Adoption is "
                f"for a task that ran, produced a branch, and was refused.")
        steps = conn.execute(
            "SELECT s.run_id, s.payload FROM run_steps s"
            " JOIN runs r ON r.id = s.run_id"
            " WHERE r.task_id = %s AND s.step_type = 'VERIFICATION_RUN'"
            " ORDER BY s.run_id DESC", (task_id,)).fetchall()

    repo = config.repo_root() / task["repo"]
    head = _git(repo, "rev-parse", f"{branch}^{{commit}}")
    base_now = _git(repo, "rev-parse", f"{task['base_branch']}^{{commit}}")

    # THE RUN IS IDENTIFIED BY THE TREE, NOT BY RECENCY. Picking "the last
    # green run" and hoping it matches the branch is the class of inference
    # this whole exercise has been about. The branch tip names its run.
    for step in steps:
        payload = step["payload"] or {}
        if payload.get("patch_commit_sha") != head:
            continue
        if not _verification_is_green(payload):
            raise NotAdoptable(
                f"run {step['run_id']} is the run that produced {branch}, and "
                f"its checks are not green: "
                f"{payload.get('verification_skipped') or _why_not_green(payload)}")
        if not _boundary_was_size_only(payload):
            raise NotAdoptable(
                f"run {step['run_id']} broke the boundary on something other "
                f"than size, so its checks cannot be believed")
        recorded_base = payload.get("base_commit_sha") or ""
        if recorded_base != base_now:
            raise NotAdoptable(
                f"the base has moved. {branch} was verified against "
                f"{recorded_base[:12]} and {task['base_branch']} is now at "
                f"{base_now[:12]}. Green against one base is not green against "
                f"another: re-run the task, or re-verify against this base.")
        return Adoption(
            task_id=task_id, branch=branch, run_id=step["run_id"],
            base_sha=recorded_base, head_sha=head,
            checks=[c.get("command", "") for c in (payload.get("checks") or [])])

    raise NotAdoptable(
        f"no run of task {task_id} verified {branch} at {head[:12]}. The "
        f"branch has moved since it was checked, or it was never this task's.")


def _why_not_green(payload: dict) -> str:
    checks = payload.get("checks") or []
    if not checks:
        return "the run recorded no checks at all"
    bad = [c.get("command", "?") for c in checks if not _check_is_green(c)]
    if bad:
        return "failed: " + "; ".join(bad)
    return "no check actually ran, so nothing was established"


def adopt(task_id: int, branch: str) -> Adoption:
    """Move the task to READY_FOR_REVIEW behind the branch it already built.

    The UPDATE is narrow on purpose: status and branch_name, guarded on the
    status this read it at. 038's trigger independently re-establishes the
    recorded-green precondition, so a caller that skipped `plan` still cannot
    promote a run that proved nothing.
    """
    decided = plan(task_id, branch)
    with db.writer() as conn:
        rows = conn.execute(
            "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name=%s,"
            " completed_at=now() WHERE id=%s AND status='FAILED'",
            (branch, task_id)).rowcount
        if rows != 1:
            conn.rollback()
            raise NotAdoptable(
                f"task {task_id} was not FAILED when the write landed; "
                f"nothing was changed")
        conn.commit()
    return decided


def main(argv: list[str] | None = None) -> int:
    """    python -m console.adopt --task 69 --branch fleet/task-69.3

    --dry-run asks every question and writes nothing, which is the way to find
    out whether a branch is adoptable without deciding that it is.
    """
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m console.adopt", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task", type=int, required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--dry-run", action="store_true",
                   help="check everything and change nothing")
    args = p.parse_args(argv)

    try:
        decided = (plan if args.dry_run else adopt)(args.task, args.branch)
    except NotAdoptable as exc:
        print(f"REFUSED: {exc}")
        return 1
    verb = "would adopt" if args.dry_run else "adopted"
    print(f"{verb} {decided.branch} for task {decided.task_id}")
    print(f"  run {decided.run_id}, {decided.head_sha[:12]} on "
          f"{decided.base_sha[:12]}")
    for c in decided.checks:
        print(f"  ok  {c}")
    if not args.dry_run:
        print("  -> READY_FOR_REVIEW. Nothing merged: accept() re-verifies "
              "against the base before it does.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
