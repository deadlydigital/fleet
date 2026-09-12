"""Merging an accepted branch, and pushing its base.

This is the first outward-facing write in the system, so it is the most
guarded thing in it. Every check below refuses rather than repairs: if the
world is not in the state the run recorded, the answer is to stop and say so,
not to reconcile it.

THE MERGE DOES NOT HAPPEN IN THE CHECKOUT, AND THAT IS THE POINT
    It used to. `git merge` ran in the working copy the console reads diffs
    from, which is also the tree the fleet's own units run from -- so the
    console needed write access to a production checkout, and a task in a
    repository it may only read could not be accepted at all. On 9 Sep 2026
    task 22 failed exactly there: `cannot lock ref 'ORIG_HEAD': Read-only
    file system`, after both the preflight and the re-verification had
    passed.

    Re-verification already builds the merge in a throwaway clone and checks
    it there. That clone is now PROMOTED rather than discarded: the commit
    that was verified is the commit that is pushed, by identity rather than
    by being built a second time somewhere else and expected to match.

    Two guards are gone with it, deliberately, because each existed only to
    make a dangerous location safe and the location is no longer used:
    `head != base` (the checkout must be on the base branch) and `dirty` (the
    working tree must be clean). Neither says anything about the merge now.
    The first is what forced a branch switch in a production checkout in
    order to press Accept.

WHAT IT WILL NOT DO
    no force, ever
    no rebase, ever
    no push of anything but the base branch, by explicit refspec
    no write of any kind to the checkout -- not a fetch, not a merge, not a
      ref update. The checkout is read, and only read.
    nothing at all if the merge conflicts: the trial is deleted and no verdict
      is recorded, because a failed merge is not a decision

THE PUSH IS VERIFIED, NOT TRUSTED
    `git push` exiting 0 is a claim. After it, the remote ref is fetched and
    compared against the commit that was pushed. Same principle as the runner
    deriving its own diff: the thing that did the work does not get to report
    on it.

WHAT THIS LEAVES FOR SOMEONE ELSE
    The checkout does not receive the merge, so after a successful Accept it
    is BEHIND the remote by the merge commit. That is reported rather than
    fixed: the console cannot write there, and deciding when a production
    tree moves is deploy-from-a-ref's job, not this module's. See
    specs/deploy-from-a-ref.md.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


def branch_tip(repo: Path, branch: str) -> str:
    """What the branch is actually on, or "" if git does not have it.

    Exported because the readers now pick a run BY this rather than by
    recency, and asking the tree is the same discipline preflight uses three
    lines further down: the tip is a fact, the newest row is a guess that
    happened to be right until adoption existed.
    """
    if not BRANCH_RE.match(branch or ""):
        return ""
    return _sha(repo, branch)


def _count(repo: Path, spec: str) -> int | None:
    """`git rev-list --count`, or None when the range could not be resolved.

    NOT 0 ON FAILURE. Returning zero would make "I could not look" identical
    to "they agree", and the caller would proceed into a merge on the
    strength of a question that was never answered -- the same silent default
    that made a refused merge invisible one layer up.
    """
    r = _git(repo, "rev-list", "--count", spec)
    if r.returncode != 0:
        return None
    try:
        return int(r.stdout.strip())
    except (ValueError, AttributeError):
        return None


def preflight(repo: Path, task: dict, branch: str, recorded_base: str,
              recorded_patch: str, branch_point: str = "",
              remote: str = "origin") -> MergeOutcome:
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

    # WHAT IS NO LONGER CHECKED HERE, AND WHY THAT IS NOT A RELAXATION.
    #
    # Two guards used to live at this point: the checkout must be ON the base
    # branch, and its working tree must be CLEAN. Both existed because the
    # merge was made here, in a live checkout, where being on the wrong branch
    # or carrying uncommitted work would have turned a merge into damage.
    #
    # The merge is now made in a throwaway clone and published from there --
    # see `publish`. The console does not write to this checkout at all, so
    # neither condition can affect the outcome, and asserting them would only
    # refuse merges that are perfectly safe. The first of the two is what
    # forced a production checkout to be switched to a task's base branch
    # before Accept could be pressed.
    #
    # The remote-agreement check has MOVED rather than gone: it now runs in
    # the clone, against a remote that has just been fetched, immediately
    # before the push. Here it could only ever compare against a
    # remote-tracking ref this module may no longer refresh -- the fetch was
    # itself a write to the checkout -- and a stale answer to that question is
    # what it exists to prevent.

    tip = _sha(repo, branch)
    if not tip:
        return MergeOutcome(False, f"branch {branch} is not in this checkout")
    r.branch_tip = tip
    r.base_sha_before = _sha(repo, base)

    # THE PRIMARY GUARD: the branch is the commit that was verified.
    #
    # This used to be the merge base matching what the run recorded, with the
    # tip check reserved for already-merged branches. That was the weaker test
    # of the two. A commit APPENDED to a branch after verification leaves the
    # merge base untouched and moves the tip, so the merge-base check passed
    # code nobody had verified. Measured: merge base identical before and
    # after, tip changed.
    #
    # It is also the check that says what anyone actually wants to know. "The
    # branch was cut where the run said" is a fact about history; "this is the
    # code that was verified" is a fact about what is about to be merged.
    if not recorded_patch:
        return MergeOutcome(False, "the run recorded no patch commit, so there "
                                   "is nothing to check this branch against")
    if tip != recorded_patch:
        return MergeOutcome(
            False,
            f"{branch} is at {tip[:12]} but the run verified {recorded_patch[:12]}. "
            f"Something has been committed to the branch since it was verified, "
            f"so what would merge is not what was checked.")

    ancestor = _git(repo, "merge-base", "--is-ancestor", branch, base).returncode == 0
    if ancestor:
        # The merge would be a no-op, so the merge-base check cannot apply:
        # once a branch is merged its merge base with the base IS its own tip.
        #
        # This used to repeat the tip check here, because the tip was the
        # substitution reserved for exactly this case. It is now the primary
        # guard above and runs for every branch, so repeating it would be dead
        # code -- and a second copy of a rule is a second place for it to drift.
        r.already_merged = True
        r.ok = True
        r.note(f"{branch} is already an ancestor of {base}; no merge is required")
        r.note(f"its tip {tip[:12]} is the commit the run recorded as verified")
        return r

    r.note(f"tip {tip[:12]} is the commit the run verified")

    # Secondary, and against branch_point_sha -- NOT base_commit_sha. The two
    # are different things and conflating them is what made task 5
    # unacceptable: its recorded base was the evidence-pack commit, which sits
    # on the branch, so no merge base could ever equal it.
    #
    # A base that merely ADVANCES does not move the merge base -- measured, in
    # a toy repository: two commits on the base, merge base unchanged. So this
    # fires for a rebase or a rewritten base, not for the overnight case.
    #
    # Runs recorded before branch_point_sha existed carry no branch point, and
    # this is skipped rather than guessed at. The tip check above already
    # establishes what is being merged, and the re-verification establishes
    # that it works there.
    merge_base = _git(repo, "merge-base", base, branch).stdout.strip()
    if branch_point:
        if merge_base != branch_point:
            return MergeOutcome(
                False,
                f"the merge base is {merge_base[:12]} but this branch was cut "
                f"from {branch_point[:12]}. Either the branch was rebased or "
                f"{base} was rewritten; in both cases what would merge is not "
                f"what the run reasoned about.")
        r.note(f"merge base {merge_base[:12]} is where the branch was cut")
    else:
        r.note("this run recorded no branch point, so the merge base was not "
               "checked; the tip and the re-verification carry the argument")
    r.ok = True
    return r


#: The remote name given to the REAL remote inside a trial clone.
#:
#: Not "origin": inside a clone taken from the checkout, `origin` already
#: means the checkout. Pushing to `origin` there would push INTO the working
#: copy -- refused by git for the checked-out branch, and a write to the very
#: tree this module now exists not to touch. A separate name makes the two
#: impossible to confuse in a command or in a message.
PUBLISH_REMOTE = "publish"


def remote_url(repo: Path, remote: str = "origin") -> str:
    out = _git(repo, "remote", "get-url", remote)
    return out.stdout.strip() if out.returncode == 0 else ""


def publish(clone: Path, base: str, url: str, commit: str,
            remote_name: str = PUBLISH_REMOTE) -> MergeOutcome:
    """Push `commit` to `base` on the real remote, from the trial clone.

    The clone is the one re-verification built and passed, so `commit` is the
    merge that was actually tested. Nothing is rebuilt here.
    """
    r = MergeOutcome(ok=False)
    add = _git(clone, "remote", "add", remote_name, url)
    if add.returncode != 0:
        return MergeOutcome(False, f"could not point the trial at {url}: "
                                   f"{add.stderr.strip()[-300:]}")

    fetched = _git(clone, "fetch", "--quiet", remote_name, base)
    remote_ref = f"refs/remotes/{remote_name}/{base}"
    have_remote_base = _git(clone, "rev-parse", "--verify", "--quiet",
                            remote_ref).returncode == 0

    if have_remote_base:
        # THE DIVERGENCE CHECK, MOVED HERE FROM PREFLIGHT AND STRENGTHENED.
        #
        # In preflight it compared against a remote-tracking ref that might be
        # any age. Here the fetch has just happened, and the question is the
        # exact one that matters: is what we are about to push a descendant of
        # what is there? If not, the base moved under the trial and the merge
        # that was verified is a merge into a base that no longer exists.
        #
        # On 8 Sep 2026 a local `main` sat two commits behind `origin/main`,
        # the console merged into it, and the push could not be made. Asking
        # here means that is refused before anything is sent.
        descends = _git(clone, "merge-base", "--is-ancestor",
                        remote_ref, commit).returncode == 0
        if not descends:
            behind = _count(clone, f"{commit}..{remote_ref}")
            return MergeOutcome(
                False,
                f"{remote_name}/{base} has moved: it holds "
                f"{behind if behind is not None else 'some'} commit(s) the "
                f"verified merge does not, so what was tested is a merge into "
                f"a base that no longer exists. Nothing was pushed and nothing "
                f"was recorded.",
                detail=["Re-run Accept: re-verification will rebuild the trial "
                        "against the base as it now stands."])
    elif fetched.returncode != 0:
        r.note(f"there is no {base} on the remote yet, so this push creates it")

    # The only push this system makes, by explicit refspec and never forced.
    push = _git(clone, "push", remote_name, f"{commit}:refs/heads/{base}")
    if push.returncode != 0:
        return MergeOutcome(
            False,
            f"the merge verified but the push failed, so nothing landed and "
            f"nothing was recorded. The checkout was not touched either -- "
            f"this is a clean failure, not a half-done one.",
            detail=r.detail + [push.stderr.strip()[-1500:]])
    r.pushed = True

    # Verified, not trusted: exit 0 is a claim about what happened.
    _git(clone, "fetch", "--quiet", remote_name, base)
    r.remote_sha = _sha(clone, f"{remote_name}/{base}")
    r.push_verified = bool(r.remote_sha) and r.remote_sha == commit
    if not r.push_verified:
        return MergeOutcome(
            False,
            f"the push reported success but {base} on the remote is "
            f"{(r.remote_sha or 'unreadable')[:12]} and the commit pushed was "
            f"{commit[:12]}. Do not record a verdict against this.",
            pushed=True, remote_sha=r.remote_sha)
    r.note(f"{base} on the remote verified at {r.remote_sha[:12]} by re-reading it")
    r.ok = True
    return r


def merge_and_push(repo: Path, task: dict, branch: str, recorded_base: str,
                   recorded_patch: str, remote: str = "origin",
                   branch_point: str = "",
                   reverification: Any = None) -> MergeOutcome:
    """Preflight, then publish the verified trial. Never writes to `repo`.

    `reverification` is the already-completed trial: the caller runs it
    BEFORE this, because a merge that only verifies afterwards has already
    happened by the time it is refused. Its `trial_path` is the clone that
    passed, and it is what gets pushed -- so the commit that ships is the
    commit that was tested, rather than one built again here and assumed
    equal.
    """
    r = preflight(repo, task, branch, recorded_base, recorded_patch, branch_point,
                  remote=remote)
    if not r.ok:
        return r
    if reverification is not None and not reverification.ok:
        return MergeOutcome(False, reverification.reason,
                            base_sha_before=r.base_sha_before,
                            branch_tip=r.branch_tip)
    base = task["base_branch"]

    if r.already_merged:
        # Nothing to build: the branch is already in the base. This path
        # records a merge somebody else made -- task 26 on 8 Sep 2026 is the
        # case it exists for.
        #
        # IT USED TO PUSH, and now it cannot: pushing needs a clone, and there
        # is no trial here because re-verification is skipped when there is
        # nothing to merge. So the remote is READ instead, with `ls-remote`,
        # which touches nothing locally. Recording MERGED while the remote
        # does not have the commit would be a verdict about a state that only
        # exists on one machine.
        r.base_sha_after = r.base_sha_before
        url = remote_url(repo, remote)
        if not url:
            r.note(f"{task['repo']} has no {remote} remote, so there was no "
                   f"remote state to check this against")
            r.ok = True
            return r
        ls = _git(repo, "ls-remote", url, f"refs/heads/{base}")
        remote_sha = ls.stdout.split()[0] if ls.returncode == 0 and ls.stdout.strip() else ""
        if not remote_sha:
            r.note(f"{base} is not on {remote} yet, so the merge is recorded as "
                   f"local-only; nothing here can publish it")
            r.ok = True
            return r
        r.remote_sha = remote_sha
        contains = _git(repo, "merge-base", "--is-ancestor",
                        r.branch_tip, remote_sha)
        if contains.returncode == 0:
            r.push_verified = True
            r.note(f"{remote}/{base} already contains {r.branch_tip[:12]}, "
                   f"read from the remote rather than from a tracking ref")
            r.ok = True
            return r
        if contains.returncode == 1:
            return MergeOutcome(
                False,
                f"{branch} is merged into the local {base} but {remote} does "
                f"not have it: {base} there is {remote_sha[:12]}. Recording "
                f"MERGED would claim a state that exists on this machine "
                f"only. Push it, or resolve why it was not pushed.",
                already_merged=True, base_sha_before=r.base_sha_before,
                branch_tip=r.branch_tip, remote_sha=remote_sha)
        # Could not decide -- typically the remote commit is not in this
        # checkout. Not the same as agreement, and said so rather than assumed.
        return MergeOutcome(
            False,
            f"could not determine whether {remote} has {branch}: {base} there "
            f"is {remote_sha[:12]}, which is not a commit this checkout knows. "
            f"That is not the same as it being absent, and not the same as it "
            f"being present.",
            already_merged=True, base_sha_before=r.base_sha_before,
            branch_tip=r.branch_tip, remote_sha=remote_sha,
            detail=[f"try: git -C {repo} fetch {remote} {base}"])

    trial = getattr(reverification, "trial_path", "") if reverification else ""
    if not trial:
        # No verified trial to promote. Refusing rather than merging in the
        # checkout: that fallback is the whole defect this module was changed
        # to remove, and having it here would mean the safe path is the one
        # that happens to be taken rather than the only one available.
        return MergeOutcome(
            False,
            "there is no verified trial to publish, so this merge was not "
            "made. Accept builds the merge in a trial clone and pushes that "
            "clone; without one there is nothing whose verification is known.",
            base_sha_before=r.base_sha_before, branch_tip=r.branch_tip,
            detail=["This happens when the contract declares no verification "
                    "commands, so no trial was built. Give the contract a "
                    "check -- even `true` states the intent -- or merge by "
                    "hand and record it with decided_via='by_hand'."])

    url = remote_url(repo, remote)
    if not url:
        return MergeOutcome(
            False,
            f"{task['repo']} has no {remote} remote, so there is nowhere to "
            f"publish the merge to. The console does not write to the "
            f"checkout, so a repository with no remote has no path to a "
            f"recorded merge.",
            base_sha_before=r.base_sha_before, branch_tip=r.branch_tip)

    merged_sha = getattr(reverification, "merged_sha", "")
    out = publish(Path(trial), base, url, merged_sha)
    out.branch_tip = r.branch_tip
    out.base_sha_before = r.base_sha_before
    out.detail = r.detail + out.detail
    if not out.ok:
        return out

    out.merged = True
    out.base_sha_after = merged_sha
    out.note(f"published the commit re-verification tested ({merged_sha[:12]}); "
             f"no merge was rebuilt and the checkout was not written to")
    out.note(f"{repo} is now behind {remote}/{base} by this merge -- the "
             f"console cannot fast-forward it, see specs/deploy-from-a-ref.md")
    return out
