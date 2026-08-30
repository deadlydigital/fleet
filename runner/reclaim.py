"""Recovering a tick that died.

The database half decides WHETHER a task is stale and moves it; this half
removes the worktree, which is filesystem state no trigger can reach. The
order matters and is the same order the tick itself uses: the git side is
cleaned first, then the database is moved, so a crash between them leaves a
task still RUNNING and reclaimable again rather than a task QUEUED with a
worktree still pinning its branch.

WHAT COUNTS AS STALE is `stale_tasks()`, in the database, next to
`reclaim_stale_task()` which acts on it. Deriving the deadline here as well
would be two pieces of arithmetic that have to agree and eventually would not.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row

from runner import config, worktree

DEFAULT_GRACE_SECONDS = 15 * 60

#: The floor the database enforces too. Mirrored here so an unsafe grace is
#: refused with a message rather than silently finding nothing -- the SQL guard
#: only fires when a candidate exists, so on a quiet queue `--grace 0` looked
#: like it had worked.
MIN_GRACE_SECONDS = 300


@dataclass
class Reclaimed:
    task_id: int
    outcome: str
    worktree_removed: str = ""
    branch_kept: str = ""
    stale_for: str = ""
    detail: list[str] = field(default_factory=list)


def _connect() -> psycopg.Connection:
    return psycopg.connect(config.task_runner_dsn(), row_factory=dict_row,
                           autocommit=True)


def orphaned_worktrees(repo: Path, live_branches: set[str]) -> list[tuple[str, Path]]:
    """Worktrees of task branches with no task still RUNNING on them.

    Read from `git worktree list --porcelain` rather than by globbing the
    worktree root: a directory somebody left behind is not a worktree, and
    removing it with `git worktree remove` would fail confusingly. Git's own
    registry is the list of things git will object to later.
    """
    out: list[tuple[str, Path]] = []
    raw = worktree.git(repo, "worktree", "list", "--porcelain", check=False)
    path: Path | None = None
    for line in raw.splitlines():
        if line.startswith("worktree "):
            path = Path(line.split(" ", 1)[1])
        elif line.startswith("branch ") and path is not None:
            branch = line.split(" ", 1)[1].removeprefix("refs/heads/")
            if branch.startswith("fleet/task-") and branch not in live_branches:
                out.append((branch, path))
            path = None
    return out


def reclaim(*, grace_seconds: int = DEFAULT_GRACE_SECONDS,
            only_task: int | None = None,
            log: Callable[[str], None] = print) -> list[Reclaimed]:
    """Reclaim every stale task, and sweep the worktrees they left."""
    if grace_seconds < MIN_GRACE_SECONDS:
        raise ValueError(
            f"refusing a grace of {grace_seconds}s: under {MIN_GRACE_SECONDS}s a "
            f"live tick would be reclaimed out from under itself, and the "
            f"worktree is removed before the database is asked.")
    settings = config.load_runner_config()
    grace = f"{int(grace_seconds)} seconds"
    results: list[Reclaimed] = []

    with _connect() as conn:
        candidates = conn.execute("SELECT * FROM stale_tasks(%s::interval)",
                                  (grace,)).fetchall()
        if only_task is not None:
            candidates = [c for c in candidates if c["task_id"] == only_task]
        if not candidates:
            log("nothing stale")

        for row in candidates:
            r = Reclaimed(task_id=row["task_id"],
                          outcome="", stale_for=str(row["stale_for"]))
            repo = Path(settings["repo_root"]) / row["repo"]
            log(f"task {row['task_id']}  RUNNING and {row['stale_for']} past its "
                f"wall clock, {row['open_runs']} open run(s)")

            # Git first: a crash after this leaves the task RUNNING and stale,
            # which is recoverable. The other order leaves a QUEUED task whose
            # branch is still checked out somewhere.
            for branch, path in orphaned_worktrees(repo, live_branches=set()):
                if not branch.startswith(f"fleet/task-{row['task_id']}"):
                    continue
                worktree.remove(repo, path)
                r.worktree_removed = str(path)
                r.branch_kept = branch
                log(f"  removed worktree {path}")
                log(f"  kept branch {branch} -- whatever the dead tick wrote is "
                    f"still there to look at")

            outcome = conn.execute(
                "SELECT reclaim_stale_task(%s, %s::interval) AS outcome",
                (row["task_id"], grace)).fetchone()["outcome"]
            r.outcome = outcome
            log(f"  -> {outcome}")
            results.append(r)

    return results


def sweep_worktrees(log: Callable[[str], None] = print) -> list[str]:
    """Remove worktrees for task branches no task is RUNNING on.

    Separate from reclaiming a task because the two failures are separate: a
    worktree can survive a tick that completed perfectly well if the removal
    itself failed, and that one is not a stuck task, just litter that will
    confuse the next `git worktree list`.
    """
    settings = config.load_runner_config()
    removed: list[str] = []
    with _connect() as conn:
        live = {r["branch"] for r in conn.execute(
            "SELECT 'fleet/task-' || id::text AS branch FROM tasks"
            " WHERE status = 'RUNNING'")}
        repos = {r["repo"] for r in conn.execute(
            "SELECT DISTINCT repo FROM tasks")}
    for name in sorted(repos):
        repo = Path(settings["repo_root"]) / name
        if not (repo / ".git").exists():
            continue
        for branch, path in orphaned_worktrees(repo, live_branches=live):
            # fleet/task-5.3 belongs to task 5; compare on the id, not the name.
            task_id = branch.removeprefix("fleet/task-").split(".")[0]
            if f"fleet/task-{task_id}" in live:
                continue
            worktree.remove(repo, path)
            removed.append(str(path))
            log(f"  swept {path} ({branch})")
    if not removed:
        log("  no orphaned worktrees")
    return removed
