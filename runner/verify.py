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

import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

# {changed_files} expands to the paths the RUNNER derived from git, never to
# the agent's account of what it changed. {changed_files:.py} narrows to a
# comma-separated list of suffixes.
#
# The filter is suffix matching rather than a glob on purpose. Contract globs
# treat `*` as not crossing a separator, so `*.py` under those semantics would
# not match `api/app.py` -- a surprise that would silently lint nothing. A
# suffix has one meaning.
CHANGED_FILES_RE = re.compile(r"\{changed_files(?::([^}]*))?\}")


@dataclass
class Check:
    command: str
    exit_code: int
    duration_ms: int
    output_tail: str
    timed_out: bool = False
    expanded: str | None = None      # what actually ran, after expansion
    skipped_reason: str | None = None

    @property
    def ran(self) -> bool:
        return self.skipped_reason is None

    @property
    def passed(self) -> bool:
        """A check with nothing to look at has not failed.

        It has also not established anything, which is why `Verification`
        refuses a pass when every check was skipped.
        """
        if not self.ran:
            return True
        return self.exit_code == 0 and not self.timed_out


def expand_changed_files(command: str, changed: list[str]) -> tuple[str, bool, int]:
    """Substitute {changed_files[:suffixes]} into a command.

    Returns the expanded command, whether the command contained a
    placeholder at all, and how many paths it expanded to.
    """
    matched_total = 0
    found = False

    def substitute(match: re.Match[str]) -> str:
        nonlocal matched_total, found
        found = True
        raw = (match.group(1) or "").strip()
        suffixes = [s.strip() for s in raw.split(",") if s.strip()]
        paths = [p for p in changed
                 if not suffixes or any(p.endswith(s) for s in suffixes)]
        matched_total += len(paths)
        return " ".join(shlex.quote(p) for p in paths)

    return CHANGED_FILES_RE.sub(substitute, command), found, matched_total


@dataclass
class Verification:
    checks: list[Check] = field(default_factory=list)
    skipped_reason: str | None = None

    @property
    def ran(self) -> bool:
        return self.skipped_reason is None

    @property
    def passed(self) -> bool:
        """Every check passed, and at least one of them actually ran.

        The second half matters. A contract whose commands all target file
        types the task did not touch would otherwise pass having established
        nothing, and "nothing could look at this change" is not a pass.
        """
        if not self.ran or not self.checks:
            return False
        if not any(c.ran for c in self.checks):
            return False
        return all(c.passed for c in self.checks)

    def summary(self) -> str:
        if not self.ran:
            return f"not run ({self.skipped_reason})"
        return "  ".join(
            ("skip" if not c.ran else "ok" if c.passed else "FAIL")
            + f" {c.command}" for c in self.checks)


def run(worktree: Path, commands: list[str], deadline_seconds: float,
        changed: list[str] | None = None,
        facts: dict[str, str] | None = None) -> Verification:
    """Each command in turn, stopping at the first failure.

    Stopping early is deliberate: the second command's output is not evidence
    about a tree the first command already rejected, and the wall clock is
    better spent ending the tick.
    """
    result = Verification()
    changed = changed or []

    # The runner's own derived facts, handed to the checks. A check that
    # needs to know what changed, or what it changed from, gets it from here
    # rather than from the agent or from re-deriving it and possibly
    # disagreeing.
    env = dict(os.environ)
    env.update(facts or {})
    env["FLEET_CHANGED_FILES"] = "\n".join(changed)

    for command in commands:
        expanded, has_placeholder, matched = expand_changed_files(command, changed)
        if has_placeholder and matched == 0:
            # Linting nothing is not a failure, but neither is it a result.
            # Recorded so the report can say which checks had no input --
            # and note that a bare `ruff check` with no paths would lint the
            # whole tree, which is exactly the repo-wide gate this replaces.
            result.checks.append(Check(
                command, 0, 0, "", expanded=expanded,
                skipped_reason="no changed file matched this check's filter"))
            continue

        remaining = deadline_seconds - sum(c.duration_ms for c in result.checks) / 1000
        if remaining <= 0:
            result.checks.append(Check(command, -1, 0, "", timed_out=True,
                                       expanded=expanded))
            break
        started = time.monotonic()
        try:
            proc = subprocess.run(
                expanded, shell=True, cwd=str(worktree), env=env,
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
            Check(command, code, duration_ms, out[-4000:], timed_out,
                  expanded=expanded))
        if code != 0 or timed_out:
            break
    return result
