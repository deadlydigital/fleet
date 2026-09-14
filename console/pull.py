"""Moving a checkout forward, and the one condition that forbids it.

WHY THIS IS A MODULE AND NOT A LINE IN TWO PLACES

`tools/fleet-pull` is the command a person types; `console/autodeploy` needs
the same thing before it can read HEAD and mean it. A second copy would
disagree the first time one of them learned something, and the disagreement
would surface as a build failed at 04:15 by the half that had not learned it.

WHAT FORBIDS IT: A BUILD IN FLIGHT, AND THIS IS NEW SINCE 14 Sep 2026
---------------------------------------------------------------------
`runner/worktree.Untouched` snapshots every watched checkout when a run starts
and compares HEAD when it ends. A fast-forward moves HEAD, so a pull during a
build fails that build -- and it fails it at the END, after the agent has been
paid for, after the checks have run, after the branch is pushed.

Task 96, 14 Sep 2026, is the worked example and it was self-inflicted:

    12:00:13  claimed
    12:15:28  `git pull --ff-only` in the platform checkout  <- the mistake
    12:26:05  five checks green, including 963s of analytics pytest
    12:26:07  branch pushed
    12:26:09  FAILED: the deadly-digital-platform checkout moved from
              ab65311885b6 to 706ec5669d35

£3.29 and 26 minutes, for a branch that was correct and already on the remote.
It was recovered with `console.adopt`, which is a repair and not a defence.

THAT IS WHY THE CHECKOUT WAS A PERSON'S TO MOVE, AND WHY IT NEED NOT BE NOW.
Before this check existed there was no safe moment to pull that a program could
identify, so the pull was left to a human who might happen to know a build was
running -- and `console/autodeploy` could only ever deploy whatever the tree
happened to be on, which made "deploy what the fleet merged" conditional on
somebody having remembered. One query makes the moment identifiable. This
module is that query, and it is what lets anything other than a person move the
checkout.

NO GIT HOOK CAN DO THIS. A fast-forward creates no commit, so `pre-merge-commit`
never fires, and git has no `pre-pull` hook at all. The check has to live in
whatever does the pulling.

A FAILURE TO ASK ALLOWS THE PULL, on the argument `tools/githooks` makes: a run
cannot be in flight without the database, because `claim_task()` is what makes
a task RUNNING. Silence would be the wrong failure -- it would turn this into a
guard that had stopped working and said nothing.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

FLEET = Path("/home/ubuntu/fleet")
PLATFORM = Path("/home/ubuntu/deadly-digital-platform")
CHECKOUTS = {"fleet": FLEET, "platform": PLATFORM}


@dataclass
class PullOutcome:
    ok: bool
    reason: str = ""
    #: True when nothing moved because nothing was behind.
    already_current: bool = False
    was: str = ""
    now: str = ""
    commits: int = 0
    #: The tasks that forbade it, for a caller that wants to name them.
    building: list[dict[str, Any]] = field(default_factory=list)


def git(repo: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=180)
    return r.returncode, (r.stdout + r.stderr).strip()


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "--short", "HEAD")[1]


def branch(repo: Path) -> str:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD")[1]


def building(log: Callable[[str], None] | None = None) -> list[dict[str, Any]]:
    """Every task the runner has claimed. Empty when the question fails."""
    from console import db
    try:
        with db.connect() as conn:
            return list(conn.execute(
                "SELECT id, title, claimed_at FROM tasks"
                " WHERE status = 'RUNNING' ORDER BY id"))
    except Exception as exc:                       # noqa: BLE001 -- see docstring
        if log:
            log(f"could not ask the database whether a build is in flight: "
                f"{type(exc).__name__}: {exc}. Continuing -- a run cannot be "
                f"in flight without it. If postgres is up, this guard is not "
                f"working and should be fixed rather than left.")
        return []


def why_not(tasks: list[dict[str, Any]]) -> str:
    first = tasks[0]
    more = f" (and {len(tasks) - 1} more)" if len(tasks) > 1 else ""
    return (f"task {first['id']} is building, claimed "
            f"{first['claimed_at']:%H:%M:%S}{more}, and a pull moves HEAD. "
            f"Untouched fails a run whose checkout moved, after the spend and "
            f"after the push -- task 96 cost £3.29 that way on 14 Sep 2026")


def catch_up(repo: Path, *, log: Callable[[str], None] = print,
             dry_run: bool = False) -> PullOutcome:
    """Fast-forward `repo`, unless the runner is building.

    Never raises. A failed pull is reported and is not made fatal by this
    module: the caller decides whether a checkout it could not move is a
    reason to stop.

    `dry_run` ANSWERS THE SAME QUESTION AND MOVES NOTHING, which it has to:
    a dry run that fast-forwarded the checkout would be a deployment performed
    by the command whose whole promise is that it performs none. It is read
    with `ls-remote`, which writes nothing at all -- not even the
    remote-tracking refs a `fetch` would.
    """
    tasks = building(log=log)
    if tasks:
        return PullOutcome(False, why_not(tasks), building=tasks)

    if dry_run:
        was = head(repo)
        br = branch(repo)
        code, url = git(repo, "remote", "get-url", "origin")
        if code != 0:
            return PullOutcome(True, already_current=True, was=was, now=was)
        out = git(repo, "ls-remote", url, f"refs/heads/{br}")[1]
        remote = out.split("\t")[0] if out else ""
        if not remote or remote.startswith(was) or was in remote:
            return PullOutcome(True, already_current=True, was=was, now=was)
        return PullOutcome(True, reason=f"would fast-forward to {remote[:12]}",
                           was=was, now=was)

    was = head(repo)
    code, out = git(repo, "pull", "--ff-only")
    now = head(repo)
    if code != 0:
        last = out.splitlines()[-1] if out else f"exit {code}"
        return PullOutcome(False, f"pull --ff-only failed: {last}",
                           was=was, now=now)
    if was == now:
        return PullOutcome(True, already_current=True, was=was, now=now)
    n = git(repo, "rev-list", "--count", f"{was}..{now}")[1]
    return PullOutcome(True, was=was, now=now,
                       commits=int(n) if n.isdigit() else 0)
