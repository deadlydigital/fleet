#!/usr/bin/env python3
"""Refuse to move HEAD in the main checkout while the runner is building.

    git config core.hooksPath tools/githooks

WHAT IT IS FOR, AND IT COST £2.70 AND TEN MINUTES TO LEARN

`runner/worktree.Untouched` snapshots the watched checkouts before a run and
compares them afterwards: HEAD, `status --porcelain`, and (path, size,
mtime_ns) for every file. ~/fleet is one of the watched checkouts, because an
agent writing outside its worktree is exactly what the guard exists to catch.

A plain `git commit` here moves HEAD, and the guard cannot tell it from the
thing it is watching for. On 14 Sep 2026 task 89's agent exited 0, the boundary
was clean, all five contract checks passed and the branch was pushed as
be9e2e97 -- and 0.46s later the run was failed with

    GitError: the fleet checkout moved from 71bd403c57b7 to 5ee9d1a50e0c

naming a commit made in this checkout while the build ran. The branch was
correct and already on the remote; the run was thrown away anyway. Keeping the
working tree untouched is NOT enough protection -- that commit staged blobs
directly and never wrote a file -- because HEAD is what moved.

WHAT IT COVERS, STATED SO IT IS NOT OVERSOLD

`pre-commit`, `pre-merge-commit` and `pre-rebase`. Those are the HEAD-moving
operations git offers a REFUSING hook for, and they are the ones a person
reaches for by hand.

It does not and cannot cover the class. `git checkout`, `git reset --hard` and
`git pull`'s fast-forward all move HEAD; git offers only post-hooks for the
first two and none for a fast-forward, so a hook can notice afterwards but
never refuse. A write to an untracked path -- an editor, a build, a stray
`tee` -- trips `Untouched` too and no hook sees it at all.

So this enforces the habit at the point it is usually broken. It is not a
boundary, and the thing that would actually fix the class is the runner
checking its snapshot EARLY and often rather than once at the end: a run that
dies at second two because somebody is committing costs nothing, and this one
died after the spend, the checks and the push.

NOT IN A LINKED WORKTREE, WHICH IS THE DETAIL THAT MATTERS MOST

The runner builds fleet-repo tasks in worktrees of this repository -- task 88
on 14 Sep was one -- and the agent commits in its worktree as its normal work.
A worktree inherits `core.hooksPath` from the shared config, so a guard that
only asked "is a task RUNNING" would refuse the agent's own commits inside the
very run that made it RUNNING, and no fleet-repo task could ever be built
again.

`--git-dir` equals `--git-common-dir` only in the main checkout; in a linked
worktree the first points into `.git/worktrees/<name>`. That is the test, and
it is made first, before anything is read and before the database is opened.

WHY A FAILURE HERE ALLOWS THE COMMIT

A run cannot be in flight without the database: `claim_task()` is what makes a
task RUNNING and every step of a run writes rows as it goes. So "the database
could not be reached" and "no run can be active" are the same state, and
refusing every commit whenever postgres hiccups would be a worse failure than
the one this prevents. It says so loudly rather than failing open in silence.

THE RACE IS REAL AND SMALL. A task claimed between this query and the commit
that follows it is not caught. This is a guard against a habit, not a lock.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          timeout=10).stdout.strip()


def in_main_checkout() -> bool:
    """False in a linked worktree, where the runner's agent does its work."""
    common = _git("rev-parse", "--path-format=absolute", "--git-common-dir")
    this = _git("rev-parse", "--path-format=absolute", "--git-dir")
    return bool(common) and common == this


def running_tasks() -> list[dict]:
    """Every task the runner currently has claimed."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from console import db
    with db.connect() as conn:
        return list(conn.execute(
            "SELECT id, title, claimed_at FROM tasks WHERE status = 'RUNNING'"
            " ORDER BY id"))


def main() -> int:
    if not in_main_checkout():
        return 0

    try:
        building = running_tasks()
    except Exception as exc:                       # noqa: BLE001 -- see docstring
        print(f"[fleet] the run guard could not ask the database: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        print("[fleet] allowing the commit -- a run cannot be in flight "
              "without the database. If postgres is up, this guard is not "
              "working and should be fixed rather than left.", file=sys.stderr)
        return 0

    if not building:
        return 0

    hook = Path(sys.argv[0]).name if sys.argv else "hook"
    print(f"REFUSED by {hook}: the runner is building, and moving HEAD here "
          f"fails the run it is building.", file=sys.stderr)
    for t in building:
        print(f"  task {t['id']}  claimed {t['claimed_at']:%H:%M:%S}  "
              f"{(t['title'] or '')[:60]}", file=sys.stderr)
    print("", file=sys.stderr)
    print("  runner/worktree.Untouched snapshots this checkout before the run "
          "and fails it if HEAD moves. It cannot tell your commit from an "
          "agent writing outside its worktree, which is its job.",
          file=sys.stderr)
    print("  Wait for the build, or `git commit --no-verify` if you have "
          "decided the run is expendable.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
