"""Merging an accepted branch, and pushing its base.

This is the first outward-facing write in the system, so it is the most
guarded thing in it. Every check below refuses rather than repairs: if the
world is not in the state the run recorded, the answer is to stop and say so,
not to reconcile it.

WHAT IT WILL NOT DO
    no force, ever
    no rebase, ever
    no push of anything but the base branch, by explicit refspec
    no branch switching -- if the checkout is not already on the base branch
      it refuses, rather than moving a checkout somebody else may be using
    no merge if the working tree is dirty
    nothing at all if the merge conflicts: the merge is aborted and no verdict
      is recorded, because a failed merge is not a decision

THE PUSH IS VERIFIED, NOT TRUSTED
    `git push` exiting 0 is a claim. After it, the remote ref is fetched and
    compared against the local base. Same principle as the runner deriving its
    own diff: the thing that did the work does not get to report on it.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

BRANCH_RE = re.compile(r"^fleet/task-\d+(\.\d+)?$")
TIMEOUT = 120


@dataclass
class MergeOutcome:
    ok: bool
    reason: str = ""
    merged: bool = False            # a merge commit was actually made
    already_merged: bool = False    # it was in the base before we started
    pushed: bool = False
    push_verified: bool = False
    base_sha_before: str = ""
    base_sha_after: str = ""
    remote_sha: str = ""
    branch_tip: str = ""
    detail: list[str] = field(default_factory=list)

    def note(self, line: str) -> None:
        self.detail.append(line)


def _git(repo: Path, *args: str, timeout: int = TIMEOUT) -> subprocess.CompletedProcess:
    """argv, never a shell, with a wall clock -- the runner's protections."""
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=timeout)


def _sha(repo: Path, ref: str) -> str:
    out = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return out.stdout.strip()


def preflight(repo: Path, task: dict, branch: str, recorded_base: str,
              recorded_patch: str) -> MergeOutcome:
    """Everything that must hold before a merge is attempted.

    Returns an outcome whose `ok` says whether to proceed; `already_merged`
    says which of the two shapes it is.
    """
    r = MergeOutcome(ok=False)
    base = task["base_branch"]

    if task["status"] != "READY_FOR_REVIEW":
        return MergeOutcome(False, f"task {task['id']} is {task['status']}, "
                                   f"not READY_FOR_REVIEW")
    if not task["branch_name"]:
        return MergeOutcome(False, "the task records no branch")
    if branch != task["branch_name"]:
        return MergeOutcome(False, f"branch {branch!r} is not the branch this task "
                                   f"recorded ({task['branch_name']!r})")
    # Base-branch first: it is the refusal that matters most, and checking the
    # name shape first would report "main" as a malformed branch name rather
    # than as the thing this must never merge. Same ordering, same reason, as
    # worktree.push in the runner.
    if branch == base:
        return MergeOutcome(False, f"refusing to merge {base} into itself")
    if not BRANCH_RE.match(branch):
        return MergeOutcome(False, f"{branch!r} is not a fleet task branch name")
    if not (repo / ".git").exists():
        return MergeOutcome(False, f"no git repository at {repo}")

    head = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if head != base:
        return MergeOutcome(False, f"the checkout is on {head}, not {base}. "
                                   f"Refusing to switch a branch under whoever "
                                   f"is using it.")

    dirty = _git(repo, "status", "--porcelain").stdout.strip()
    if dirty:
        return MergeOutcome(False, f"the working tree is not clean "
                                   f"({len(dirty.splitlines())} changed paths)")

    tip = _sha(repo, branch)
    if not tip:
        return MergeOutcome(False, f"branch {branch} is not in this checkout")
    r.branch_tip = tip
    r.base_sha_before = _sha(repo, base)

    ancestor = _git(repo, "merge-base", "--is-ancestor", branch, base).returncode == 0
    if ancestor:
        # The merge would be a no-op, so the merge-base check cannot apply:
        # once a branch is merged its merge base with the base IS its own tip.
        # The stronger claim is available instead -- that what is already in
        # the base is the exact commit the run verified.
        if tip != recorded_patch:
            return MergeOutcome(
                False,
                f"{branch} is already in {base}, but its tip ({tip[:12]}) is not "
                f"the commit this run verified ({(recorded_patch or '?')[:12]}). "
                f"Something rewrote the branch after verification.")
        r.already_merged = True
        r.ok = True
        r.note(f"{branch} is already an ancestor of {base}; no merge is required")
        r.note(f"its tip {tip[:12]} is the commit the run recorded as verified")
        return r

    merge_base = _git(repo, "merge-base", base, branch).stdout.strip()
    if not recorded_base:
        return MergeOutcome(False, "the run recorded no base commit, so there is "
                                   "nothing to check the merge base against")
    if merge_base != recorded_base:
        return MergeOutcome(
            False,
            f"the merge base is {merge_base[:12]} but the run recorded "
            f"{recorded_base[:12]}. The branch has been rebased or rewritten "
            f"since it was verified.")
    r.ok = True
    r.note(f"merge base {merge_base[:12]} matches what the run recorded")
    return r


def merge_and_push(repo: Path, task: dict, branch: str, recorded_base: str,
                   recorded_patch: str, remote: str = "origin") -> MergeOutcome:
    """Preflight, merge, push, then verify the push against the remote."""
    r = preflight(repo, task, branch, recorded_base, recorded_patch)
    if not r.ok:
        return r
    base = task["base_branch"]

    if not r.already_merged:
        merged = _git(repo, "-c", "user.name=fleet-console",
                      "-c", "user.email=console@fleet.local",
                      "merge", "--no-ff", "--no-edit", branch)
        if merged.returncode != 0:
            # A failed merge is not necessarily a conflicted one, and saying
            # "conflicted" when it was not sends the reader to look at the
            # diff instead of at the actual error. This was not hypothetical:
            # a read-only bind mount produced "cannot lock ref 'ORIG_HEAD'",
            # which was reported as a conflict and cost real diagnosis time.
            output = (merged.stdout or "") + (merged.stderr or "")
            conflicted = ("CONFLICT" in output
                          or "Automatic merge failed" in output
                          or (repo / ".git" / "MERGE_HEAD").exists())
            if conflicted:
                _git(repo, "merge", "--abort")
                headline = "the merge conflicted and was aborted"
            else:
                # Nothing to abort if it never began; try anyway and say so,
                # because the alternative is leaving a half-merge unmentioned.
                _git(repo, "merge", "--abort")
                headline = ("the merge could not be attempted -- this is not a "
                            "conflict, it is git failing outright")
            still_dirty = _git(repo, "status", "--porcelain").stdout.strip()
            mid_merge = (repo / ".git" / "MERGE_HEAD").exists()
            return MergeOutcome(
                False,
                f"{headline}; nothing was recorded"
                + ("" if not (still_dirty or mid_merge) else
                   " -- WARNING: the checkout is not back to a clean state, "
                   "look at it before doing anything else"),
                base_sha_before=r.base_sha_before, branch_tip=r.branch_tip,
                detail=[d for d in (merged.stdout.strip()[-1500:],
                                    merged.stderr.strip()[-1500:]) if d])
        r.merged = True
        r.note("merged with --no-ff; no rebase and no force")

    r.base_sha_after = _sha(repo, base)

    # The only push this system makes, by explicit refspec and never forced.
    push = _git(repo, "push", remote, f"refs/heads/{base}:refs/heads/{base}")
    if push.returncode != 0:
        return MergeOutcome(
            False,
            f"the merge succeeded locally but the push failed. {base} and "
            f"{remote}/{base} now disagree, and that is worse than either "
            f"failing alone -- resolve it by hand before recording anything.",
            merged=r.merged, already_merged=r.already_merged,
            base_sha_before=r.base_sha_before, base_sha_after=r.base_sha_after,
            branch_tip=r.branch_tip,
            detail=r.detail + [push.stderr.strip()[-1500:]])
    r.pushed = True

    # Verified, not trusted: exit 0 is a claim about what happened.
    _git(repo, "fetch", remote, base)
    r.remote_sha = _sha(repo, f"{remote}/{base}")
    r.push_verified = bool(r.remote_sha) and r.remote_sha == r.base_sha_after
    if not r.push_verified:
        return MergeOutcome(
            False,
            f"the push reported success but {remote}/{base} is "
            f"{(r.remote_sha or 'unreadable')[:12]} and local {base} is "
            f"{r.base_sha_after[:12]}. Do not record a verdict against this.",
            merged=r.merged, already_merged=r.already_merged, pushed=True,
            base_sha_before=r.base_sha_before, base_sha_after=r.base_sha_after,
            remote_sha=r.remote_sha, branch_tip=r.branch_tip, detail=r.detail)
    r.note(f"{remote}/{base} verified at {r.remote_sha[:12]} by re-reading it")
    r.ok = True
    return r
