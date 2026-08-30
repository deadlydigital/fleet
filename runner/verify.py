"""Running the contract's verification commands.

The commands come from the acceptance contract, which is written by a person
and frozen by the database once the task leaves QUEUED. The agent has no
write on `tasks` at all, so it cannot edit what will be run against it -- and
because the suite and its configuration are protected paths, it cannot edit
what those commands will find either.

Verification runs only after the boundary has been derived and found clean.
A suite executed in a tree where the suite itself may have been edited
returns a result about the agent's tests, not about the project's, and a PASS
from it is worse than no result at all.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Check:
    command: str
    exit_code: int
    duration_ms: int
    output_tail: str
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@dataclass
class Verification:
    checks: list[Check] = field(default_factory=list)
    skipped_reason: str | None = None

    @property
    def ran(self) -> bool:
        return self.skipped_reason is None

    @property
    def passed(self) -> bool:
        return self.ran and bool(self.checks) and all(c.passed for c in self.checks)

    def summary(self) -> str:
        if not self.ran:
            return f"not run ({self.skipped_reason})"
        return "  ".join(
            f"{'ok' if c.passed else 'FAIL'} {c.command}" for c in self.checks)


def run(worktree: Path, commands: list[str], deadline_seconds: float) -> Verification:
    """Each command in turn, stopping at the first failure.

    Stopping early is deliberate: the second command's output is not evidence
    about a tree the first command already rejected, and the wall clock is
    better spent ending the tick.
    """
    result = Verification()
    for command in commands:
        remaining = deadline_seconds - sum(c.duration_ms for c in result.checks) / 1000
        if remaining <= 0:
            result.checks.append(Check(command, -1, 0, "", timed_out=True))
            break
        started = time.monotonic()
        try:
            proc = subprocess.run(
                command, shell=True, cwd=str(worktree),
                capture_output=True, text=True, timeout=remaining,
                start_new_session=True)
            code, out = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            code = -1
            out = ((exc.stdout or b"").decode(errors="replace")
                   + (exc.stderr or b"").decode(errors="replace")
                   if isinstance(exc.stdout, bytes) else str(exc.stdout or ""))
            timed_out = True
        duration_ms = int((time.monotonic() - started) * 1000)
        result.checks.append(
            Check(command, code, duration_ms, out[-4000:], timed_out))
        if code != 0 or timed_out:
            break
    return result
