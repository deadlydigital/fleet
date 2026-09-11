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
from typing import Sequence

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
    # The command names something that is not there. NOT the same as a
    # skip and NOT the same as a failure -- see `passed`.
    unresolved_reason: str | None = None
    #: The check DIED rather than answered, so its exit code is not a verdict.
    #:
    #: A process killed by a signal did not decide anything about the tree it
    #: was pointed at. Read as a failure it produces the worst sentence this
    #: system can produce -- a specific, confident claim about a branch,
    #: derived from an event that had nothing to do with the branch.
    #:
    #: THIS IS NOT HYPOTHETICAL AND IT IS NOT RARE. Measured 11 Sep 2026,
    #: re-verifying task 53 under fleet-automerge.service's own confinement:
    #:
    #:     cd platform && ./node_modules/.bin/tsc --noEmit   exit 134
    #:
    #: 134 is 128+6, SIGABRT: V8 aborting because the 512M cgroup would not
    #: give it memory. `could_not_run` was False, `ok` was False, and the
    #: accept path reported "the branch verifies on its own and FAILS when
    #: merged into main as it stands now. The base moved under it." The base
    #: had not moved. Nothing was wrong with the branch.
    #:
    #: The two most likely environment failures in this system are exactly
    #: this and the read-only filesystem, and neither was in the class that
    #: exists to hold them.
    undecided_reason: str | None = None

    @property
    def ran(self) -> bool:
        """Did this check look at the tree AND answer?

        A killed check is not `ran`: it looked and was interrupted, which
        establishes nothing, and `Verification.passed` requires that at least
        one check established something.
        """
        return (self.skipped_reason is None
                and self.unresolved_reason is None
                and self.undecided_reason is None)

    @property
    def passed(self) -> bool:
        """A check with nothing to look at has not failed.

        It has also not established anything, which is why `Verification`
        refuses a pass when every check was skipped.

        AN UNRESOLVED CHECK IS THE OPPOSITE OF A SKIP and the order of these
        two branches is the whole point. A skip means the check looked and
        there was nothing for it: safe to pass over. Unresolved means the
        check could not be looked at -- its interpreter or its script is not
        on disk -- so nothing is known. Falling through to the skip branch
        would turn a checker that has gone missing into a PASS, which is the
        worst of the three possible readings.
        """
        if self.unresolved_reason is not None:
            return False
        # AHEAD OF THE SKIP BRANCH, for the reason the unresolved branch is:
        # falling through would turn a check the kernel killed into a PASS.
        if self.undecided_reason is not None:
            return False
        if not self.ran:
            return True
        return self.exit_code == 0 and not self.timed_out


#: Signal numbers whose 128+N exit code is read as "this was killed", never
#: as a verdict. `sh` reports a child terminated by signal N as 128+N, and
#: that convention is the only thing a caller of `subprocess.run(shell=True)`
#: has to go on: the shell has already exited normally by then.
#:
#: WHY THE WHOLE RANGE AND NOT A SHORT LIST. The error directions are not
#: symmetric. A killed check misread as a failure produces a confident false
#: statement about a branch and refuses it with the wrong reason. A genuine
#: failure misread as a kill refuses the merge too -- not knowing is not
#: permission -- and says so in a sentence that sends the reader to the
#: environment. The second is recoverable by reading; the first is what sent
#: somebody to read a clean diff on 10 Sep.
#:
#: SIGPIPE (13 -> 141) IS THE KNOWN AMBIGUITY and it is in the set anyway. A
#: shell pipeline whose last stage dies on SIGPIPE is a normal thing to write
#: and a check that ends that way still did not answer. If that misfires it
#: misfires loudly, as a refusal naming the signal.
#:
#: A program that deliberately `exit(137)` is violating the same convention
#: the shell is using, and there is no way to tell it apart from here.
_SIGNAL_NAMES = {
    1: "SIGHUP", 2: "SIGINT", 3: "SIGQUIT", 4: "SIGILL", 5: "SIGTRAP",
    6: "SIGABRT", 7: "SIGBUS", 8: "SIGFPE", 9: "SIGKILL", 11: "SIGSEGV",
    13: "SIGPIPE", 15: "SIGTERM", 24: "SIGXCPU", 25: "SIGXFSZ",
}


def _cgroup_oom_kills() -> int | None:
    """How many times this cgroup has had a process OOM-killed, or None.

    AUTHORITATIVE WHERE THE EXIT CODE IS A GUESS. 128+9 says something was
    killed; this says the kernel killed it for memory, which is the sentence
    a reader can act on. Best effort and never fatal: a host without cgroup
    v2, a delegated namespace, or a missing file all mean "cannot say", and
    the exit-code reading below still applies.

    Not a substitute for it either. V8 aborts ITSELF when the cgroup refuses
    an allocation -- exit 134, no kernel OOM kill -- so the counter does not
    move for the case that is most likely here.
    """
    try:
        with open("/proc/self/cgroup") as fh:
            rel = fh.readline().strip().split(":", 2)[2]
        with open(f"/sys/fs/cgroup{rel}/memory.events") as fh:
            for line in fh:
                key, _, value = line.partition(" ")
                if key == "oom_kill":
                    return int(value)
    except (OSError, ValueError, IndexError):
        return None
    return None


def unwritable(worktree: Path, links: Sequence[Path] = ()) -> list[str]:
    """Paths a check will need to write and cannot. Empty means proceed.

    THE PRECONDITION, AND IT EXISTS BECAUSE THE EXIT CODE CANNOT CARRY THIS.

    A check that dies on the filesystem exits NORMALLY. vitest returned 1 on

        EROFS: open '<trial>/platform/node_modules/.vite/vitest/results.json'

    and nothing separated it from a test that failed. The signal classifier
    above cannot help: nothing was signalled. Reading the output for "EROFS"
    is the answer this codebase already refuses for git's wording -- an error
    string is not an API, it is localised, it changes between versions, and a
    check that never prints it fails silently anyway.

    So the question is asked BEFORE anything runs, of the filesystem, by
    writing to it. An answer obtained by doing the thing is the only kind
    that cannot be out of date: a directory can be writable by mode and
    unwritable because the mount is read-only, and `os.access` believes the
    mode.

    WHAT IS CHECKED: the worktree root, and every path `link_dependencies`
    created. The second is the one that bit -- the link is the boundary
    between a tree that is thrown away and one that must not be written to,
    and a farmed link is writable only if it was farmed.

    Returns a list of sentences rather than raising, because the caller turns
    them into `could_not_run` and the point is to name every path at once
    instead of one per attempt.
    """
    problems: list[str] = []
    for path in [worktree, *links]:
        if not path.is_dir():
            continue
        probe = path / ".fleet-write-probe"
        try:
            probe.touch()
            probe.unlink()
        except OSError as exc:
            problems.append(
                f"{path} is not writable ({exc.strerror or exc}), and a check "
                f"that needs to write there will fail in a way that looks "
                f"like the branch failing")
    return problems


#: Every check script under contracts/checks/ documents the same three-way
#: contract, and pytest and ruff use it too: 0 passed, 1 a verdict of failure,
#: 2 THE CHECK COULD NOT RUN. pytest_unit_per_file.sh states it on line 5 and
#: has eight `exit 2` paths, every one of them an environment failure -- no
#: interpreter, the services would not start, the database is not accepting
#: connections, the exclusive lock was not taken, no test files under the
#: target, less memory available than its floor. new_test_bites.sh states it
#: too and honours it INTERNALLY, distinguishing 2 from 1 when it reads its
#: own runner's exit.
COULD_NOT_RUN_EXIT = 2


def killed_by(exit_code: int, oom_kills_delta: int | None) -> str | None:
    """Why this exit code is not a verdict, or None if it is one.

    `exit_code` is what `subprocess.run(shell=True)` returned: negative when
    the shell itself was signalled, 128+N when the shell reports a signalled
    child.

    EXIT 2 JOINED THIS CLASS ON 11 Sep 2026, and it is the gap that sent a
    clean branch back as a failure. The checks already documented 2 as "could
    not run"; this function only knew about signals and OOM kills, so a 2 fell
    through as a verdict and the console reported "the branch FAILS when merged
    into main as it stands now" about a tree whose every check passes.

    WHY APPLYING IT TO EVERY COMMAND IS SAFE, stated because it is the part
    worth arguing with. A check whose 2 really did mean failure now reads as
    undecided instead -- and undecided REFUSES, exactly as a failure does:
    `Check.ok` is false either way and not knowing is not permission. So the
    cost of being wrong here is a less precise sentence, and the cost of the
    previous behaviour was a correct branch refused with a reason that sent
    the reader to the diff. Those are not symmetric.
    """
    if oom_kills_delta:
        return (f"the kernel OOM-killed a process in this check "
                f"({oom_kills_delta} kill(s) recorded by the cgroup), so its "
                f"exit code {exit_code} is not a verdict about the tree -- "
                f"the check ran out of memory, it did not decide anything")
    signum = None
    if exit_code < 0:
        signum = -exit_code
    elif 128 < exit_code < 128 + 32:
        signum = exit_code - 128
    if signum is None:
        if exit_code == COULD_NOT_RUN_EXIT:
            return (f"the check exited {COULD_NOT_RUN_EXIT}, which every check "
                    f"under contracts/checks/ documents as COULD NOT RUN "
                    f"rather than as a failure -- the gate did not decide "
                    f"anything about the tree. Its output says which "
                    f"precondition was missing.")
        return None
    name = _SIGNAL_NAMES.get(signum, f"signal {signum}")
    hint = ""
    if signum in (6, 9):
        hint = (" On this host that is usually the unit's MemoryMax: the "
                "cgroup refuses an allocation and the process aborts or is "
                "killed.")
    return (f"the check was terminated by {name} rather than returning, so "
            f"its exit code {exit_code} is not a verdict about the tree."
            f"{hint}")


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


def unresolved_paths(command: str) -> list[str]:
    """Absolute paths a command names that are not on disk.

    WHY ONLY ABSOLUTE PATHS. A relative path is resolved inside the worktree,
    which is the tree under verification and therefore the task's own
    business. An ABSOLUTE path reaches out of it -- to an interpreter, or to
    a checker in another repository entirely -- and its presence has nothing
    to do with the change being judged. Those are the ones that can go
    missing without anybody touching the task.

    ONLY WHAT THE COMMAND MUST READ TO RUN: the program, a program after a
    shell operator, and any absolute script handed to an interpreter. NOT
    every absolute token. The first draft of this flagged all of them and a
    test caught it immediately -- `touch /tmp/x/ran` names an absolute path
    that does not exist precisely because the command is about to create it,
    and refusing on that would invent a missing checker out of an output
    path.

    Unparseable commands return nothing rather than guessing. A shell string
    this cannot split is a command this has no opinion about, and inventing a
    refusal from a parse failure would be its own misreport.

    A false positive here refuses a merge that might have succeeded, and a
    false negative reports a missing checker as a failing check. The first is
    recoverable and names the exact path; the second sends a reviewer to read
    a diff that is fine. So where it is still uncertain, it errs toward
    refusing.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []

    OPERATORS = {"&&", "||", ";", "|"}
    candidates: list[str] = []
    expect_program = True
    for token in tokens:
        if token in OPERATORS:
            expect_program = True
            continue
        if expect_program:
            candidates.append(token)
            expect_program = False
        elif token.endswith((".py", ".sh")):
            # A script an interpreter is being asked to open.
            candidates.append(token)

    seen: set[str] = set()
    missing: list[str] = []
    for c in candidates:
        if c.startswith("/") and c not in seen and not Path(c).exists():
            seen.add(c)
            missing.append(c)
    return missing


@dataclass
class Verification:
    checks: list[Check] = field(default_factory=list)
    skipped_reason: str | None = None

    @property
    def ran(self) -> bool:
        return self.skipped_reason is None

    @property
    def unresolved(self) -> bool:
        """Some check could not be run at all, so nothing was established."""
        return any(c.unresolved_reason for c in self.checks)

    def unresolved_summary(self) -> str:
        return "; ".join(c.unresolved_reason for c in self.checks
                         if c.unresolved_reason)

    @property
    def undecided(self) -> bool:
        """Some check was killed, so it answered nothing.

        Kept apart from `unresolved` because they send a reader to different
        places: unresolved means the contract names a checker that is not on
        disk, undecided means the checker was there, started, and was killed.
        Both mean the same thing to the merge -- nothing is known -- and
        console/reverify.py maps both to `could_not_run`.
        """
        return any(c.undecided_reason for c in self.checks)

    def undecided_summary(self) -> str:
        return "; ".join(f"{c.command}: {c.undecided_reason}"
                         for c in self.checks if c.undecided_reason)

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
        facts: dict[str, str] | None = None,
        links: Sequence[Path] = ()) -> Verification:
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

    # RESOLVED BEFORE ANYTHING RUNS, and all of them, not one at a time.
    #
    # A checker that is not on disk makes the whole verification unable to
    # establish anything, so running the commands that do resolve would spend
    # the wall clock producing a result nobody can use -- and would report the
    # first genuine failure as THE answer when the real answer is "this could
    # not be judged". Checking up front means the report names the missing
    # path instead of an exit code from a check that never opened.
    # WRITABLE BEFORE ANYTHING RUNS, and ahead of the resolution check for
    # the same reason that one is ahead of the commands: a verification that
    # cannot establish anything should say so instead of spending the wall
    # clock proving it one check at a time.
    #
    # This is the class the signal classifier cannot reach. A check that dies
    # on the filesystem exits normally -- vitest returned 1 on EROFS -- so
    # there is nothing in the code to read. Asked here, of the filesystem,
    # before a check has had the chance to be misread as a failing one.
    problems = unwritable(worktree, links)
    if problems:
        why = ("; ".join(problems)
               + ". Nothing was run: a check that cannot write is not a "
                 "check that failed")
        for command in commands:
            result.checks.append(Check(
                command, 0, 0, "",
                expanded=expand_changed_files(command, changed)[0],
                undecided_reason=why))
        return result

    resolution = [(c, expand_changed_files(c, changed)[0]) for c in commands]
    resolution = [(c, e, unresolved_paths(e)) for c, e in resolution]
    if any(missing for _, _, missing in resolution):
        for command, expanded, missing in resolution:
            result.checks.append(Check(
                command, 0, 0, "", expanded=expanded,
                unresolved_reason=(
                    f"{', '.join(missing)} is not on disk, so this check "
                    f"could not be run") if missing else None,
                # Recorded, rather than dropped, so the report shows the whole
                # contract. Not attempted is not the same as passed, and
                # `Verification.passed` refuses anyway: no check here `ran`.
                skipped_reason=None if missing else (
                    "not attempted: another check in this contract could not "
                    "be resolved")))
        return result

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
            # NEVER STARTED, because the checks before it spent the deadline.
            # The same class for the same reason: this one did not merely fail
            # to answer, it was never asked.
            result.checks.append(Check(
                command, -1, 0, "", timed_out=True, expanded=expanded,
                undecided_reason=(
                    f"the contract's {deadline_seconds:.0f}s deadline was "
                    f"already spent by the checks before it, so this one "
                    f"never ran and there is no verdict to read")))
            break
        started = time.monotonic()
        # READ BEFORE AND AFTER, so an OOM kill is attributed to THIS check
        # rather than to whichever check happens to run when the counter is
        # next looked at. None either side means the host cannot say.
        oom_before = _cgroup_oom_kills()
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
        oom_after = _cgroup_oom_kills()
        delta = (None if oom_before is None or oom_after is None
                 else oom_after - oom_before)
        # A TIMEOUT IS IN THE SAME CLASS, since 11 Sep 2026.
        #
        # It keeps `timed_out` -- readers distinguish the three -- but it is
        # also a check that did not return a verdict, and it reached
        # console/reverify.py's failure branch as an ordinary non-zero until
        # now: "the branch verifies on its own and FAILS when merged". A
        # timeout is as often a slow or loaded host as a loop in the branch,
        # and NOTHING IN THE EXIT TELLS YOU WHICH. The deadline expiring is
        # the only fact there is, so that is what the sentence says.
        #
        # The cost, stated rather than hidden: a genuine infinite loop in a
        # branch now reads as "could not run" instead of as a failure. It is
        # still refused -- not knowing is not permission -- and the reader is
        # sent to the deadline, where the loop is also visible.
        killed = (f"the check exceeded its {deadline_seconds:.0f}s deadline "
                  f"without returning, so there is no verdict to read. That "
                  f"is a loop in the branch or a host too slow to finish in "
                  f"time, and the deadline expiring does not say which."
                  if timed_out else killed_by(code, delta))
        result.checks.append(
            Check(command, code, duration_ms, out[-4000:], timed_out,
                  expanded=expanded, undecided_reason=killed))
        if code != 0 or timed_out:
            break
    return result
