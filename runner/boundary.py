"""What the agent actually changed, and whether it was allowed to.

Everything here reads git. Nothing here reads the agent's account of its own
work. That separation is the point of the module: an agent that edits the
suite judging it can pass anything, and an agent that reports it did not is
indistinguishable from one that did, unless somebody else looks.

The agent's report is still captured -- see `Change.reported` -- but only so
that a divergence between what it said and what it did is on the record. No
decision in this file consults it.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True)
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


# ---- globs ----------------------------------------------------------------

def glob_to_regex(glob: str) -> re.Pattern[str]:
    """Contract glob -> anchored regex.

    `**` crosses directory separators, `*` does not. The distinction matters:
    `platform/*` writable would not reach `platform/app/page.tsx`, and a
    contract author who wrote it meaning "the whole tree" should find that
    out from a rejected diff rather than from a merged one.
    """
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches_any(path: str, globs: list[str]) -> str | None:
    """The first glob that covers this path, or None."""
    for g in globs:
        if glob_to_regex(g).match(path):
            return g
    return None


# ---- the derived change ---------------------------------------------------

@dataclass
class Change:
    """What git says happened between two commits in the worktree."""
    base_sha: str
    head_sha: str
    paths: list[str] = field(default_factory=list)
    status: dict[str, str] = field(default_factory=dict)   # path -> A/M/D/R
    diff_lines: int = 0
    #: path -> added+deleted for that path. The total above is the sum, kept
    #: because it is what every recorded payload has always meant. The split
    #: lives here because `derive` has git and no contract, and which lines are
    #: the MANDATED TEST is a question only the contract can answer.
    lines: dict[str, int] = field(default_factory=dict)
    ignored_writes: list[str] = field(default_factory=list)
    reported: list[str] | None = None      # what the agent SAID. Never consulted.

    @property
    def empty(self) -> bool:
        return not self.paths

    @property
    def divergence(self) -> dict[str, list[str]]:
        """Where the agent's account and git disagree.

        Recorded, not acted on. A run whose agent under-reports is not more
        suspect than one whose agent reports nothing at all -- both are judged
        by the derived diff -- but the difference is worth being able to look
        up later.
        """
        if self.reported is None:
            return {}
        said, did = set(self.reported), set(self.paths)
        return {"claimed_but_untouched": sorted(said - did),
                "touched_but_unclaimed": sorted(did - said)}


def commit_agent_work(worktree: Path, message: str) -> bool:
    """Commit whatever the agent left behind, including files it did not add.

    The runner does this rather than asking the agent to commit, because a
    diff derived from a commit the agent composed is a diff the agent chose
    the contents of. `git add -A` picks up deletions and untracked files
    alike, so nothing the agent wrote can sit outside the comparison.
    """
    git(worktree, "add", "-A")
    staged = git(worktree, "diff", "--cached", "--name-only").strip()
    if not staged:
        return False
    git(worktree, "-c", "user.name=fleet-runner",
        "-c", "user.email=runner@fleet.local",
        "commit", "-q", "-m", message)
    return True


def derive(worktree: Path, base_sha: str) -> Change:
    """The change, from git alone."""
    head_sha = git(worktree, "rev-parse", "HEAD").strip()
    change = Change(base_sha=base_sha, head_sha=head_sha)

    if head_sha == base_sha:
        change.ignored_writes = _ignored_writes(worktree)
        return change

    raw = git(worktree, "diff", "--name-status", "-M", f"{base_sha}..{head_sha}")
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0][0]
        # A rename is two paths and both sides count: moving a file into a
        # protected tree is a write to that tree.
        for p in parts[1:]:
            change.paths.append(p)
            change.status[p] = code

    numstat = git(worktree, "diff", "--numstat", f"{base_sha}..{head_sha}")
    for line in numstat.splitlines():
        if not line.strip():
            continue
        added, deleted, path = line.split("\t")[:3]
        n = 0
        if added != "-":
            n += int(added)
        if deleted != "-":
            n += int(deleted)
        change.diff_lines += n
        change.lines[path] = change.lines.get(path, 0) + n

    change.paths = sorted(set(change.paths))
    change.ignored_writes = _ignored_writes(worktree)
    return change


def _ignored_writes(worktree: Path) -> list[str]:
    """Files the agent created that .gitignore hides.

    They never reach the branch and die with the worktree, so they are not a
    violation. They are reported because an agent writing to an ignored path
    is usually an agent that misunderstood the task.
    """
    raw = git(worktree, "status", "--porcelain", "--ignored", check=False)
    return sorted(line[3:] for line in raw.splitlines()
                  if line.startswith("!!"))


# ---- the verdict ----------------------------------------------------------

@dataclass
class Boundary:
    clean: bool
    protected_hits: dict[str, str] = field(default_factory=dict)   # path -> glob
    outside_writable: list[str] = field(default_factory=list)
    over_diff_limit: bool = False
    diff_lines: int = 0
    max_diff_lines: int = 0
    over_test_limit: bool = False
    prod_diff_lines: int = 0
    test_diff_lines: int = 0
    max_test_diff_lines: int = 0

    def reasons(self) -> list[str]:
        out = []
        for path, glob in sorted(self.protected_hits.items()):
            out.append(f"{path} is protected by {glob}")
        for path in self.outside_writable:
            out.append(f"{path} is outside every writable path")
        if self.over_diff_limit:
            # Worded without "production" when there is no test allowance,
            # because then there is no second category to distinguish from and
            # the sentence is the one this check has always printed.
            what = ("changed lines outside the added test"
                    if self.max_test_diff_lines else "changed lines")
            out.append(f"{self.prod_diff_lines} {what} exceeds the "
                       f"contract's {self.max_diff_lines}")
        if self.over_test_limit:
            out.append(f"{self.test_diff_lines} lines of added test exceeds "
                       f"the contract's {self.max_test_diff_lines}")
        return out


def enforce(change: Change, contract: dict) -> Boundary:
    """Judge the derived change against the contract.

    Four ways to fail, kept apart because they mean different things to the
    person reading the branch:

      protected      it edited something it was told not to. The suite, the
                     migrations, the deploy scripts.
      outside        it edited something the contract never mentioned. Not
                     malicious, usually -- but the contract is the statement
                     of what this task was allowed to be, and a diff wider
                     than that is a diff nobody scoped.
      over limit     more PRODUCTION lines than the contract allows. Too big
                     to review, which is what max_diff_lines asks.
      over test      the one added test is longer than its own allowance.
                     A separate question, and a much rarer answer -- see the
                     note on the two budgets below.

    CREATABLE PATHS: ADD IS PERMITTED, MODIFY IS NOT
    ------------------------------------------------
    `creatable_paths` is a third list, and it is narrower than `writable_paths`
    rather than wider: a path matching one may be ADDED and may not be modified
    or deleted, even when a protected glob also covers it.

    It exists for exactly one thing. specs/unattended-operation.md §3.2: an
    agent cannot write tests, because `api/tests/**` is on the floor as "the
    suite that judges the work" -- so a feature lands with nothing covering the
    new behaviour, and a green suite means "broke nothing", not "works". On
    auto-merge that reads as verified and is not.

    The floor's argument is about MODIFICATION. An agent that can edit an
    existing test can make it pass; an agent that adds a new file cannot weaken
    a test that already exists. So the exception is granted on the diff STATUS,
    which git supplies and the agent does not:

        A  -> allowed, if a creatable glob matches
        M, D, R, and everything else -> refused exactly as before

    This is a real widening and it is worth naming what still stops a vacuous
    test: nothing here. `contracts/checks/new_test_bites.sh` is what does, by
    requiring the added test to FAIL against the pre-change tree. The two are a
    pair, and a contract that grants `creatable_paths` without that check has
    given away the floor for nothing.
    """
    protected = list(contract.get("protected_paths", []))
    writable = list(contract.get("writable_paths", []))
    creatable = list(contract.get("creatable_paths", []))
    limit = int(contract.get("max_diff_lines", 0))

    hits: dict[str, str] = {}
    outside: list[str] = []
    for path in change.paths:
        # ADDED and matching a creatable glob: permitted, and permitted BEFORE
        # the protected check, which is the whole point -- the paths this is
        # for are protected ones.
        if change.status.get(path) == "A" and matches_any(path, creatable):
            continue
        glob = matches_any(path, protected)
        if glob:
            hits[path] = glob
            continue
        if not matches_any(path, writable):
            outside.append(path)

    # TWO BUDGETS, BECAUSE THEY ANSWER TWO QUESTIONS
    #
    # max_diff_lines asks "is this change too big to review". The test
    # allowance asks "did you write a thorough test". A single budget makes
    # them compete, and the competition has a winner: an agent near the ceiling
    # thins the test, which is the one artefact new_test_bites.sh exists to
    # make mean something. Measured 11 Sep 2026, both dd_api tasks refused on
    # size were ordinary changes carrying a mandated test -- 494 = 300 + 194
    # and 459 = 272 + 187, production code well inside the 400 they broke.
    #
    # The test side is exactly what `creatable_paths` admitted: ADDED, and
    # matching a creatable glob. That is the same predicate used above to let
    # the file in, and the same one new_test_bites.sh uses to pick the test it
    # proves, so all three agree on which file is the test by construction.
    test_limit = int(contract.get("max_test_diff_lines") or 0)
    test_lines = 0
    if test_limit:
        for path, n in change.lines.items():
            if change.status.get(path) == "A" and matches_any(path, creatable):
                test_lines += n
    # Anything the split did not claim counts against the review budget --
    # including a path git reported in numstat but not in name-status. The
    # unrecognised case lands on the stricter side on purpose.
    prod_lines = change.diff_lines - test_lines

    over = bool(limit) and prod_lines > limit
    over_test = bool(test_limit) and test_lines > test_limit
    return Boundary(
        clean=not hits and not outside and not over and not over_test,
        protected_hits=hits,
        outside_writable=sorted(outside),
        over_diff_limit=over,
        diff_lines=change.diff_lines,
        max_diff_lines=limit,
        over_test_limit=over_test,
        prod_diff_lines=prod_lines,
        test_diff_lines=test_lines,
        max_test_diff_lines=test_limit,
    )


def suite_digest(worktree: Path, ref: str, protected: list[str]) -> str:
    """A hash over the protected trees at `ref`.

    001's acceptance boundary wants a `suite_commit_sha` on a passing
    verification. The honest value is not the commit sha -- a commit sha says
    nothing about whether the suite moved -- but a digest of the protected
    trees themselves, which the runner can recompute at base and at head and
    compare. Equal digests are what makes "the suite that passed is the suite
    that was there before" checkable by someone who does not trust this code.
    """
    import hashlib

    prefixes = sorted({g.split("*")[0].rstrip("/") for g in protected})
    h = hashlib.sha256()
    for prefix in prefixes:
        if not prefix:
            continue
        out = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", f"{ref}:{prefix}"],
            capture_output=True, text=True)
        obj = out.stdout.strip() if out.returncode == 0 else "absent"
        h.update(f"{prefix}={obj}\n".encode())
    return h.hexdigest()
