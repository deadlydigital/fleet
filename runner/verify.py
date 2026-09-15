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
    #: The check RAN, answered, and its answer is not about the code.
    #:
    #: THE THIRD THING A REFUSAL CAN MEAN. `unresolved` is "the checker is not
    #: on disk"; `undecided` is "the checker was there and was killed". Both
    #: mean nothing is known. A non-zero exit means "the tree is wrong". This
    #: is the fourth case and until 15 Sep 2026 it was filed as the third:
    #:
    #:     the check ran, the tree is fine as far as it can tell, and what is
    #:     missing is an OBLIGATION THE BRANCH OWED -- cite your requirements,
    #:     state your premise, name the dataset your figure came from.
    #:
    #: Task 102 is why it exists. Five checks green over a 530-line diff --
    #: compileall, ruff, tests/unit, new_test_bites and a 15.4-minute analytics
    #: suite -- and `spec_requirements_cited.py` refused in 76ms because
    #: requirements 5, 6 and 7 carried no citation. Two of those asked for a
    #: measurement on production data that the agent, which is granted no
    #: shell, could not take; the third was conditional on the second and the
    #: spec authorised leaving it unbuilt. The agent said all of that in its
    #: reply, which is exactly what the check's own failure text asks for.
    #:
    #: The run was recorded as "verification failed" -- a sentence about the
    #: code -- and died at max_attempts 1, GBP 4.74. The absence was real. "The
    #: code is wrong" was not.
    #:
    #: IT STILL REFUSES. `passed` is False, so nothing merges unattended on an
    #: unmet obligation; that is the half that keeps the gate a gate. What
    #: changes is the sentence, and that a person can be shown a branch whose
    #: code checks all passed and be told what it owes.
    obligation_reason: str | None = None

    @property
    def ran(self) -> bool:
        """Did this check look at the tree AND answer?

        A killed check is not `ran`: it looked and was interrupted, which
        establishes nothing, and `Verification.passed` requires that at least
        one check established something.
        """
        # An UNMET OBLIGATION is `ran`. It looked and it answered -- the
        # answer is simply not about the code. That matters beyond wording:
        # `Verification.passed` requires at least one check to have
        # established something, and a contract whose only speaking check
        # reported an obligation has had something established about it.
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
        # AN UNMET OBLIGATION IS NOT A PASS. Not knowing is not permission and
        # neither is knowing that something was not written down. The branch is
        # refused here exactly as it was before this class existed; what the
        # class buys is that the refusal can say what it is about.
        if self.obligation_reason is not None:
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

    WHAT IS CHECKED: the worktree root, and every link the contract does NOT
    declare read-only. The link is the boundary between a tree that is thrown
    away and one that must not be written to, and a farmed link is writable
    only if it was farmed.

    NOT EVERY LINK, SINCE 12 SEP 2026, and the reason is a finding about this
    function rather than about a contract. It probed every link, including the
    `reference/` checkout draft-spec links to be READ -- and refused the accept
    of task 71 because the console cannot write to /home, which is correct and
    deliberate. Nothing writes through that link; the probe was the only writer.
    See worktree.writable_links for the three ways the tree says so.

    THE RUNNER HAS BEEN MAKING THAT WRITE ALL ALONG, and it succeeded, which is
    why nobody saw it. `fleet-runner.service` carries
    `ReadWritePaths=/home/ubuntu/deadly-digital-platform`, so on every
    draft-spec verification this function created and deleted
    `.fleet-write-probe` inside the live production checkout.

    It went unnoticed because cycle.py excludes link SOURCES from the drift
    guard -- `link_sources = list(contract["worktree_links"].values())` -- which
    for the frontend contracts is `platform/node_modules` and for draft-spec is
    the entire platform checkout. That exclusion was added for task 49, where
    vitest's 131 bytes into a watched tree failed a task that had passed every
    check and already pushed its branch. It has been covering this probe too.

    So: a check whose job is to predict writes was making the only write there
    was, in the one tree the guard had been told not to look at. Harmless in
    effect -- the file is created and removed in the same call -- and worth
    writing down, because the reason it was invisible is a guard doing exactly
    what it was asked.

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

#: 3 THE BRANCH OWES AN OBLIGATION. The check ran, it has no complaint about
#: the tree, and what is missing is something the branch was required to write
#: down. See Check.obligation_reason for the case that named this and what it
#: cost.
#:
#: WHY A NEW EXIT CODE AND NOT A FLAG IN THE OUTPUT. The three readers of a
#: check -- runner/verify.py, console/adopt.py and 042's SQL -- agree on
#: exactly two things about a check they did not run: its command and its exit
#: code. Anything carried in the output tail is read by one of them and not by
#: the others, and the whole of the corroborate defect was two layers matching
#: on an exit code while the distinguishing fact sat in the output.
#:
#: A CHECK THAT DOES NOT KNOW ABOUT THIS STILL WORKS. 3 is not a code any
#: existing check emits; every one of them documents 0, 1 and 2. A check that
#: never returns 3 behaves exactly as it did.
OBLIGATION_EXIT = 3


def obligation_of(exit_code: int) -> str | None:
    """Why this exit code is an unmet obligation rather than a verdict.

    Deliberately thin, and deliberately not consulted before `killed_by`: a
    check killed by a signal that happens to produce 3 never reaches here,
    because 3 is not in the 128+N range and a negative code is not 3 either.
    The one real ambiguity is a check that exits 3 for its own unrelated
    reasons, and the answer is the same as COULD_NOT_RUN_EXIT's: the contract
    for checks under contracts/checks/ documents what the codes mean, and a
    check that means something else by 3 is wrong in the way a check that
    means something else by 2 is wrong.
    """
    if exit_code != OBLIGATION_EXIT:
        return None
    return (f"the check exited {OBLIGATION_EXIT}, which contracts/checks/ "
            f"documents as AN OBLIGATION THE BRANCH OWES rather than as a "
            f"fault in the code -- it ran, it has no complaint about the "
            f"tree, and something the branch was required to state is not "
            f"there. Its output says what. This refuses the merge exactly as "
            f"a failure does; it does not claim the code is broken.")


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
    def failed_outright(self) -> bool:
        """Some check looked at the tree and returned a verdict of failure.

        THE DIFFERENCE BETWEEN "THIS IS BROKEN" AND "NOTHING IS KNOWN", asked
        of a run that can now hold both. Until 14 Sep 2026 `run` stopped at the
        first failure, so a verification had at most one terminal check: either
        a failure or a killed one, never both, and `undecided` alone was a safe
        thing for a caller to branch on.

        It is not safe now. A genuine failure followed by a later check the
        cgroup kills would read as `undecided` and be reported as "this says
        nothing about the branch" -- which would be false, and would throw away
        the one finding the run did establish. Callers ask this first and keep
        the verdict they have.
        """
        return any(c.ran and not c.passed and c.obligation_reason is None
                   for c in self.checks)

    @property
    def unmet_obligation(self) -> bool:
        """Some check ran, refused, and its refusal is not about the code.

        KEPT APART FROM `failed_outright` FOR THE SAME REASON `undecided` IS
        KEPT APART FROM `unresolved`: they send a reader to different places.
        A failure sends them to the diff. An unmet obligation sends them to the
        branch's own reply, where the agent has usually already said why --
        task 102's did, at length, and was recorded as "verification failed".

        BOTH REFUSE THE MERGE. `Verification.passed` is False either way, and
        that is not a compromise: an obligation nobody wrote down is not
        permission to merge, it is a question for a person. What this property
        exists to do is let the caller ASK the question instead of asserting
        that the code is broken.

        Callers ask `failed_outright` FIRST and keep the verdict they have, on
        the argument that property already makes: a run can hold both, and a
        genuine failure beside an unmet obligation is a failing branch that
        also owes something.
        """
        return any(c.obligation_reason for c in self.checks)

    def obligation_summary(self) -> str:
        return "; ".join(f"{c.command}: {c.obligation_reason}"
                         for c in self.checks if c.obligation_reason)

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
            ("skip" if not c.ran else "ok" if c.passed
             else "OWES" if c.obligation_reason else "FAIL")
            + f" {c.command}" for c in self.checks)


def run(worktree: Path, commands: list[str], deadline_seconds: float,
        changed: list[str] | None = None,
        facts: dict[str, str] | None = None,
        links: Sequence[Path] = ()) -> Verification:
    """Every command in turn, and a failing one does not stop the rest.

    IT STOPPED AT THE FIRST FAILURE UNTIL 14 Sep 2026, and the reason it gave
    was: "the second command's output is not evidence about a tree the first
    command already rejected, and the wall clock is better spent ending the
    tick."

    That holds when the first command judged the TREE. It does not when the
    first command judged the ANNOTATION, and this contract's cheapest check
    does exactly that. `contracts/checks/spec_requirements_cited.py` says so
    in its own docstring -- "that a claim was made, not that it was met" --
    and lists, under a heading written so nobody would oversell it, that it
    establishes nothing about "whether the requirement was implemented
    correctly, or at all".

    WHAT IT COST. Task 87 was refused on 13 Sep at 21:03:17 by that check,
    exit 1 in 72ms, and that is the whole of what run 62 recorded. tsc,
    vitest, the bite check and proxy_passthrough never ran against the
    branch. The citation error was real and one character wide; it was fixed
    by hand the same evening and the branch was then believed to be done. It
    had never passed its own test -- `getByText('£0.00')` matching three
    elements, 1 failed and 6 passed against the branch alone -- and the check
    that would have found that out was never reached. A day of believing a
    broken branch was nearly landed, and a re-queue, for want of 143 seconds.

    THE SAME DECISION WAS ALREADY MADE ONE LAYER UP. `boundary.size_only`
    stopped a cheap structural refusal from pre-empting evidence collection,
    on task 69's measured £7.97 where "because both died here neither test was
    ever executed", and ends: "this only decides whether the evidence gets
    collected first". That is this sentence too. The refusal is unchanged --
    `passed` is False either way and the caller still returns FAILED.

    NOT A REORDERING, which was the alternative. Whichever check runs first
    would still be the only fact recorded; "cheap" is not the property that
    matters ("establishes nothing about the tree" is, and the two correlate
    only by accident); and an order maintained by hand across every contract
    is the shape this repository has watched go stale while being believed.

    WHAT IT COSTS. Nothing on a green run -- one has always executed every
    check, because this only ever stopped on failure. No model spend, since
    verification runs after the agent is billed. On a failing run it is
    bounded by `deadline_seconds`, which is the whole verification phase's
    budget and not a per-check one: `remaining` below subtracts what the
    earlier checks already spent, so N checks cannot burn N deadlines. The
    measured worst case on the frontend contract is ~143s against a 1800s
    tick.

    See specs/verification-collects-its-evidence.md.
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

    for index, command in enumerate(commands):
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
            #
            # THE CEILING THAT KEEPS "RUN THEM ALL" HONEST, and it is this one
            # rather than a new one: `deadline_seconds` is the budget for the
            # whole phase, and `remaining` is what the earlier checks left of
            # it. So continuing past a failure spends the contract's existing
            # allowance and cannot exceed it -- N checks never burn N
            # deadlines, which is the one way this change could have been
            # worse than the fail-fast it replaces.
            #
            # EVERY REMAINING COMMAND IS RECORDED, not just this one. The
            # unresolved branch above already made that argument -- "recorded,
            # rather than dropped, so the report shows the whole contract" --
            # and it bites harder now: a run that stops early no longer means
            # "everything after this is unknown by convention", because the
            # ordinary case is that everything after it ran.
            for later in commands[index:]:
                result.checks.append(Check(
                    later, -1, 0, "", timed_out=True,
                    expanded=expand_changed_files(later, changed)[0],
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
        # AFTER killed_by, never before. A signalled process reports 128+N and
        # a negative code, so nothing that was killed can look like a 3 -- but
        # the order is fixed here anyway so that a future widening of either
        # rule cannot make a kill read as an obligation. Not knowing beats
        # knowing the wrong thing, in that direction and not the other.
        obligation = None if killed else obligation_of(code)
        result.checks.append(
            Check(command, code, duration_ms, out[-4000:], timed_out,
                  expanded=expanded, undecided_reason=killed,
                  obligation_reason=obligation))
        # AND ON TO THE NEXT ONE, FAILED OR NOT. The `break` that stood here
        # is what made the first failure the only fact a run recorded; the
        # docstring carries the argument and what it cost.
    return result
