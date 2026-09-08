"""Did a decision reach main, and did it reach production.

`decision_outcomes` derives what the TASK did -- its status, its cost, its
attempts. It stops there, and the two questions after it are answered from
outside the database on purpose:

    merged     tasks.status says a person merged a branch. Git says whether
               the commit is in main. These are different claims and this
               module returns BOTH, never one collapsed into the other.
    deployed   no run ever reaches DEPLOYED and the runner is not a deployer,
               so the fleet database cannot answer this at all. The drift
               checks can, for the trees they cover.

WHICH COMMIT IS ASKED ABOUT, AND WHY IT IS NOT THE BRANCH TIP

Three commits describe one merged task and they answer different questions:

    patch_commit_sha  what the AGENT wrote -- the branch tip, from the
                      PATCH_PROPOSED step
    merge_commit      what LANDED -- `base_sha_after`, verified against the
                      remote before any verdict was written, recorded by
                      console/app.py on the HUMAN_DECISION step
    base_before       where the base stood before the operation

A branch tip that is an ancestor of main is CONSISTENT with the merge but
does not identify it: the same tip is an ancestor after a merge, after a
cherry-pick, and after somebody else merged the branch. The merge commit is
the fact. So it is preferred, and `sha_kind` says which was used, because an
answer derived from the tip is an inference and must not read as one derived
from the merge.

`already_merged` IS PART OF READING IT. `merge_commit` is the base branch
AFTER the operation, and when the branch was already in the base there was no
operation -- the sha is simply where the base stood and belongs to whatever
landed last. Task 1 on this record reads `already_merged: true` with a
`merge_commit` of 63130ad7, which is "Merge branch 'docs/backend-gate-findings'"
and is nothing to do with it. Using it unconditionally credits a task with
another branch's merge.

WHY STATUS AND ANCESTRY ARE BOTH RETURNED

A task marked MERGED whose patch is not an ancestor of main is the finding
that collapsing them would hide: either the merge did not happen, or it
happened onto something that is not main, or the branch was rebuilt and the
recorded sha is not what landed. None of those is visible from the status
column, which is a word somebody typed, and none is visible from git alone,
which does not know what anybody intended. `MergeEvidence.disagrees` is the
whole reason the pair is carried.

WHY THE DEPLOY ANSWER GOES THROUGH `console.deploys`

Because it is already right, and because a second copy of it would be a
second definition to drift. `GOVERNED_BY` maps a work type to the deployment
that governs it and `Deployment.usable` refuses to let anything but a fresh
OK support a claim. Both matter and the frontend is why: `drift-frontend.state`
reads UNKNOWN -- the container carries no GIT_SHA and is not instrumented --
so a merged frontend task's commit IS an ancestor of the running API's commit
while the truthful answer about the frontend is CANNOT SAY. Asking git one
global question gets that wrong; asking it per governing deployment does not.

The import direction is a known compromise. `console/deploys.py` is the only
place on this host that parses those state files, and duplicating it here to
keep the layers clean would trade a real second-definition risk for a
tidiness one. If a third caller appears, lift the module to the root.

THE BASELINE COMES FROM `tasks.base_branch`, NEVER FROM A CONSTANT

The two repositories do not agree and neither matches a guess. The platform
repo's tasks are based on `main`; fleet's seven are based on
`track-2-foundation`, which has no remote-tracking ref at all, and its one
`main` task is against a repository whose remote branch is `master`. A
hardcoded `origin/main` answers NO_BASELINE for eight of twelve tasks and
looks like a data problem rather than a wrong constant.

`origin/<base>` is preferred and the local `<base>` is the fallback, and the
two are LABELLED DIFFERENTLY rather than substituted. "In origin/main" is a
claim about the shared repository; "in the local track-2-foundation" is a
claim about this checkout, which nobody else can see and which no merge has
necessarily reached. Silently accepting the second as the first is how a
branch that exists only on this host reads as landed work.

NOTHING HERE FETCHES. Git is read as it sits on disk, so the baseline is
only as current as the last fetch, and every ancestry answer carries the ref
and sha it was measured against rather than implying it is live.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from console import deploys as deploys_module

#: repo name as `tasks.repo` spells it -> where it is checked out.
#: A repo not named here is UNKNOWN_REPO rather than absent: the question was
#: asked and could not be answered, which is not the same as no question.
REPO_PATHS: Dict[str, Path] = {
    "fleet": Path(os.environ.get("FLEET_REPO_PATH", "/home/ubuntu/fleet")),
    "deadly-digital-platform": Path(os.environ.get(
        "DD_REPO_PATH", "/home/ubuntu/deadly-digital-platform")),
}

GIT_TIMEOUT = 20

IN_MAIN = "IN_MAIN"
NOT_IN_MAIN = "NOT_IN_MAIN"
NO_SHA = "NO_SHA"

MERGE_COMMIT = "MERGE_COMMIT"    # the commit that performed the merge: a fact
BRANCH_TIP = "BRANCH_TIP"        # the agent's tip: consistent with, not proof of
UNKNOWN_SHA = "UNKNOWN_SHA"
UNKNOWN_REPO = "UNKNOWN_REPO"
NO_BASELINE = "NO_BASELINE"


@dataclass(frozen=True)
class MergeEvidence:
    """Two independent answers to "did this land", kept apart."""
    status_says_merged: bool
    ancestry: str
    detail: str
    baseline_ref: Optional[str] = None
    baseline_sha: Optional[str] = None
    baseline_at: Optional[datetime] = None
    baseline_is_local: bool = False
    #: Which commit the ancestry question was actually put about.
    sha: Optional[str] = None
    sha_kind: Optional[str] = None

    @property
    def computable(self) -> bool:
        return self.ancestry in (IN_MAIN, NOT_IN_MAIN)

    @property
    def disagrees(self) -> bool:
        """The finding. A status and a repository that do not match.

        Only meaningful when git could actually answer; an unreadable repo is
        an absence of evidence and must not read as a contradiction.
        """
        if not self.computable:
            return False
        return self.status_says_merged != (self.ancestry == IN_MAIN)

    @property
    def identifies_the_merge(self) -> bool:
        """Whether this rests on the merge commit or only on the branch tip."""
        return self.sha_kind == MERGE_COMMIT

    @property
    def summary(self) -> str:
        status = "status MERGED" if self.status_says_merged else "status not MERGED"
        via = ""
        if self.sha_kind == MERGE_COMMIT:
            via = " (via the merge commit)"
        elif self.sha_kind == BRANCH_TIP:
            via = " (via the branch tip — consistent with the merge, not proof of it)"
        return f"{status}, git {self.ancestry.lower().replace('_', ' ')}{via}"


def _git(repo: Path, *args: str) -> Optional[str]:
    """A git read, or None. Never raises, never writes, never fetches."""
    try:
        done = subprocess.run(("git", "-C", str(repo)) + args,
                              capture_output=True, text=True,
                              timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def _is_ancestor(repo: Path, sha: str, of: str) -> Optional[bool]:
    """True, False, or None when the question could not be put to git."""
    try:
        done = subprocess.run(
            ("git", "-C", str(repo), "merge-base", "--is-ancestor", sha, of),
            capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode == 0:
        return True
    if done.returncode == 1:
        return False
    return None   # 128: a bad object or not a repository


def _resolve_baseline(repo: Path, base_branch: str) -> tuple[Optional[str], Optional[str], bool]:
    """(ref, sha, is_local) for the branch this task was based on.

    Remote first. A local branch answers a weaker question and says so.
    """
    for ref, is_local in ((f"origin/{base_branch}", False), (base_branch, True)):
        sha = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if sha:
            return ref, sha, is_local
    return None, None, False


def choose_sha(patch_commit_sha: Optional[str], merge_commit: Optional[str],
               already_merged: Optional[bool]) -> tuple[Optional[str], Optional[str]]:
    """(sha, kind). The merge commit when there is one, else the branch tip.

    Refuses `merge_commit` when `already_merged` is true: nothing was merged,
    so that sha names whatever landed before and is not this task's.
    """
    if merge_commit and not already_merged:
        return merge_commit, MERGE_COMMIT
    if patch_commit_sha:
        return patch_commit_sha, BRANCH_TIP
    return None, None


def merge_evidence(repo_name: Optional[str], patch_commit_sha: Optional[str], *,
                   status: Optional[str],
                   base_branch: Optional[str] = None,
                   merge_commit: Optional[str] = None,
                   already_merged: Optional[bool] = None) -> MergeEvidence:
    """Whether this task's commit is in its base branch, beside the status."""
    says_merged = status == "MERGED"
    base_branch = base_branch or "main"
    sha, kind = choose_sha(patch_commit_sha, merge_commit, already_merged)

    if not sha:
        return MergeEvidence(
            says_merged, NO_SHA,
            "no PATCH_PROPOSED or HUMAN_DECISION step recorded a commit for "
            "this task, so there is nothing to look for in the repository")

    repo = REPO_PATHS.get(repo_name or "")
    if repo is None or not (repo / ".git").exists():
        return MergeEvidence(
            says_merged, UNKNOWN_REPO,
            f"no checkout of {repo_name!r} on this host to ask",
            sha=sha, sha_kind=kind)

    if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}") is None:
        return MergeEvidence(
            says_merged, UNKNOWN_SHA,
            f"{sha[:12]} is not an object in this checkout — it was never "
            f"fetched, or the branch it was on has been pruned",
            sha=sha, sha_kind=kind)

    baseline_ref, baseline_sha, is_local = _resolve_baseline(repo, base_branch)
    if baseline_sha is None:
        return MergeEvidence(
            says_merged, NO_BASELINE,
            f"neither origin/{base_branch} nor {base_branch} resolves in this "
            f"checkout, so there is no baseline to compare against",
            sha=sha, sha_kind=kind)

    when = _git(repo, "show", "-s", "--format=%cI", baseline_sha)
    baseline_at = None
    if when:
        try:
            baseline_at = datetime.fromisoformat(when)
        except ValueError:
            baseline_at = None

    answer = _is_ancestor(repo, sha, baseline_sha)
    if answer is None:
        return MergeEvidence(
            says_merged, UNKNOWN_SHA,
            f"git could not compare {sha[:12]} against {baseline_ref}",
            baseline_ref, baseline_sha, baseline_at, is_local, sha, kind)

    local_note = (" (a LOCAL branch on this host, not the shared repository)"
                  if is_local else "")
    return MergeEvidence(
        says_merged, IN_MAIN if answer else NOT_IN_MAIN,
        f"{sha[:12]} is {'' if answer else 'not '}an ancestor of "
        f"{baseline_ref} at {baseline_sha[:12]}{local_note}",
        baseline_ref, baseline_sha, baseline_at, is_local, sha, kind)


@dataclass(frozen=True)
class DeployEvidence:
    """What can be said about this work reaching production, and why."""
    verdict: str          # NOTHING_TO_SHIP | SHIPPED | NOT_SHIPPED | CANNOT_SAY
    why: str
    in_running_commit: Optional[bool] = None   # corroboration, not the verdict

    @property
    def shipped(self) -> bool:
        return self.verdict == "SHIPPED"

    @property
    def cannot_say(self) -> bool:
        return self.verdict == "CANNOT_SAY"


def deploy_evidence(work_type: Optional[str], *, repo_name: Optional[str] = None,
                    sha: Optional[str] = None,
                    merged_at: Optional[datetime] = None,
                    deployments: Optional[Dict[str, "deploys_module.Deployment"]] = None
                    ) -> DeployEvidence:
    """`console.deploys.shipped`, plus an independent ancestry corroboration.

    The verdict is the drift check's, unchanged. The ancestry is carried
    beside it for the same reason merge status and merge ancestry are: two
    sources agreeing is worth more than either, and two sources disagreeing
    is the thing worth seeing. It NEVER overrides the verdict -- a repository
    on this host knows nothing about what a container is running.
    """
    deployments = deployments if deployments is not None \
        else deploys_module.all_deployments()
    verdict, why = deploys_module.shipped(work_type, merged_at, deployments)

    in_running = None
    which = deploys_module.GOVERNED_BY.get(work_type or "")
    if which and sha:
        dep = deployments.get(which)
        repo = REPO_PATHS.get(repo_name or "")
        if dep is not None and dep.sha and repo is not None \
                and (repo / ".git").exists():
            in_running = _is_ancestor(repo, sha, dep.sha)

    return DeployEvidence(verdict, why, in_running)


def now() -> datetime:
    return datetime.now(timezone.utc)
