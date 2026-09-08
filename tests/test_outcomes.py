"""Merged and deployed, and the two places the obvious version goes wrong.

`decision_outcomes` stops at what the task did. These are the two questions
after it, and both are answered from outside the database: git for whether a
commit is in its base branch, the drift state files for whether it is in a
running container.

Two properties carry the file:

  * STATUS AND ANCESTRY ARE BOTH RETURNED. A task marked MERGED whose patch
    is not in the base branch is the finding; one number cannot hold it.
  * A FRONTEND TASK IS `CANNOT_SAY`, NOT `SHIPPED`. Its commit really is an
    ancestor of the running API's commit, because they share a repository,
    and the frontend container is not instrumented. Asking git one global
    question gets this confidently wrong.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import outcomes
from console import deploys as deploys_module


def run(cwd: Path, *args: str) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"{' '.join(args)}: {r.stderr}"
    return r.stdout


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    """A repository with a landed commit and an unlanded one.

    `main` holds the landed commit; `side` holds one that never reached it,
    which is the shape a branch abandoned mid-review leaves behind.
    """
    r = tmp_path / "repo"
    r.mkdir()
    run(r, "git", "init", "-q", "-b", "main")
    run(r, "git", "config", "user.email", "t@t")
    run(r, "git", "config", "user.name", "t")
    (r / "a.txt").write_text("one\n")
    run(r, "git", "add", "-A")
    run(r, "git", "commit", "-q", "-m", "base")
    (r / "b.txt").write_text("two\n")
    run(r, "git", "add", "-A")
    run(r, "git", "commit", "-q", "-m", "landed")
    run(r, "git", "checkout", "-q", "-b", "side", "HEAD~1")
    (r / "c.txt").write_text("three\n")
    run(r, "git", "add", "-A")
    run(r, "git", "commit", "-q", "-m", "never landed")
    run(r, "git", "checkout", "-q", "main")
    monkeypatch.setitem(outcomes.REPO_PATHS, "testrepo", r)
    return r


def sha(repo: Path, ref: str) -> str:
    return run(repo, "git", "rev-parse", ref).strip()


def deployment(name: str, status: str, detail: str = "",
               age_minutes: int = 5) -> deploys_module.Deployment:
    checked = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return deploys_module.Deployment(
        name, status, detail,
        detail if len(detail) == 40 else None, checked,
        timedelta(minutes=age_minutes))


# ---- merged ----------------------------------------------------------------

class TestMergeEvidenceCarriesBothClaims:

    def test_a_landed_commit_marked_merged_agrees(self, repo):
        ev = outcomes.merge_evidence("testrepo", sha(repo, "main"),
                                     status="MERGED", base_branch="main")
        assert ev.ancestry == outcomes.IN_MAIN
        assert ev.status_says_merged is True
        assert ev.disagrees is False

    def test_a_commit_that_never_landed_but_reads_merged_is_the_finding(self, repo):
        """The case the pair exists for, and the reason neither is dropped."""
        ev = outcomes.merge_evidence("testrepo", sha(repo, "side"),
                                     status="MERGED", base_branch="main")
        assert ev.ancestry == outcomes.NOT_IN_MAIN
        assert ev.status_says_merged is True
        assert ev.disagrees is True

    def test_an_unlanded_commit_not_marked_merged_is_not_a_disagreement(self, repo):
        ev = outcomes.merge_evidence("testrepo", sha(repo, "side"),
                                     status="FAILED", base_branch="main")
        assert ev.ancestry == outcomes.NOT_IN_MAIN
        assert ev.disagrees is False

    def test_an_unreadable_answer_is_never_a_disagreement(self, repo):
        """Absence of evidence must not read as evidence of contradiction."""
        for ev in (
            outcomes.merge_evidence("testrepo", None, status="MERGED"),
            outcomes.merge_evidence("nosuchrepo", sha(repo, "main"), status="MERGED"),
            outcomes.merge_evidence("testrepo", "0" * 40, status="MERGED",
                                    base_branch="main"),
            outcomes.merge_evidence("testrepo", sha(repo, "main"),
                                    status="MERGED", base_branch="nosuchbranch"),
        ):
            assert ev.computable is False
            assert ev.disagrees is False


class TestTheBaselineComesFromTheData:
    """`tasks.base_branch` differs per repo, and a constant answers wrongly."""

    def test_the_task_base_branch_is_what_is_compared(self, repo):
        ev = outcomes.merge_evidence("testrepo", sha(repo, "side"),
                                     status="MERGED", base_branch="side")
        assert ev.ancestry == outcomes.IN_MAIN      # in ITS base, which is side
        assert ev.baseline_ref == "side"

    def test_a_local_branch_answers_a_weaker_question_and_says_so(self, repo):
        """No remote here, so `side` resolves locally and must be labelled.

        "In origin/main" is a claim about the shared repository. "In the
        local branch" is a claim about this checkout, which nobody else can
        see. Substituting one for the other silently is how work that exists
        only on this host reads as landed.
        """
        ev = outcomes.merge_evidence("testrepo", sha(repo, "main"),
                                     status="MERGED", base_branch="main")
        assert ev.baseline_is_local is True
        assert "LOCAL branch" in ev.detail

    def test_a_remote_ref_is_preferred_over_a_local_one(self, repo, tmp_path):
        origin = tmp_path / "origin.git"
        run(repo, "git", "init", "-q", "--bare", str(origin))
        run(repo, "git", "remote", "add", "origin", str(origin))
        run(repo, "git", "push", "-q", "origin", "main")
        run(repo, "git", "fetch", "-q", "origin")
        ev = outcomes.merge_evidence("testrepo", sha(repo, "main"),
                                     status="MERGED", base_branch="main")
        assert ev.baseline_ref == "origin/main"
        assert ev.baseline_is_local is False


class TestWhichCommitIsAskedAbout:
    """The merge commit is the fact; the branch tip is only consistent with it.

    A tip that is an ancestor of main is equally an ancestor after a merge,
    after a cherry-pick, and after somebody else merged the branch. Asking
    about the commit that performed the merge is what makes "which merge
    produced this" a fact rather than an inference, and `sha_kind` says which
    question was actually answered so the two never read alike.
    """

    def test_the_merge_commit_is_preferred_over_the_branch_tip(self, repo):
        ev = outcomes.merge_evidence(
            "testrepo", sha(repo, "side"), status="MERGED", base_branch="main",
            merge_commit=sha(repo, "main"), already_merged=False)
        assert ev.sha == sha(repo, "main")
        assert ev.sha_kind == outcomes.MERGE_COMMIT
        assert ev.identifies_the_merge is True
        assert ev.ancestry == outcomes.IN_MAIN

    def test_without_one_it_falls_back_to_the_tip_and_says_so(self, repo):
        ev = outcomes.merge_evidence("testrepo", sha(repo, "main"),
                                     status="MERGED", base_branch="main")
        assert ev.sha_kind == outcomes.BRANCH_TIP
        assert ev.identifies_the_merge is False
        assert "not proof of it" in ev.summary

    def test_already_merged_refuses_the_recorded_sha(self, repo):
        """THE TRAP IN THE STORED FIELD.

        `merge_commit` is `base_sha_after` -- the base AFTER the operation.
        When the branch was already in the base there was no operation, so
        that sha is wherever the base stood and belongs to whatever landed
        last. Task 1 on the live record carries `already_merged: true` and a
        merge_commit of "Merge branch 'docs/backend-gate-findings'". Using it
        credits a task with another branch's merge.
        """
        ev = outcomes.merge_evidence(
            "testrepo", sha(repo, "side"), status="MERGED", base_branch="main",
            merge_commit=sha(repo, "main"), already_merged=True)
        assert ev.sha == sha(repo, "side")          # the tip, not the base
        assert ev.sha_kind == outcomes.BRANCH_TIP
        assert ev.identifies_the_merge is False

    def test_choose_sha_is_the_whole_rule_and_is_directly_stated(self, repo):
        pick = outcomes.choose_sha
        assert pick("tip", "merge", False) == ("merge", outcomes.MERGE_COMMIT)
        assert pick("tip", "merge", True) == ("tip", outcomes.BRANCH_TIP)
        assert pick("tip", None, None) == ("tip", outcomes.BRANCH_TIP)
        assert pick(None, "merge", False) == ("merge", outcomes.MERGE_COMMIT)
        assert pick(None, None, None) == (None, None)

    def test_a_task_with_neither_commit_has_nothing_to_look_for(self, repo):
        ev = outcomes.merge_evidence("testrepo", None, status="MERGED")
        assert ev.ancestry == outcomes.NO_SHA
        assert ev.computable is False


# ---- deployed --------------------------------------------------------------

class TestDeployEvidence:

    def test_a_work_type_nothing_deploys_is_not_a_gap(self, repo):
        """`dd_docs` has no running copy to be behind. Not "not deployed"."""
        ev = outcomes.deploy_evidence(
            "dd_docs", repo_name="testrepo", sha=sha(repo, "main"),
            deployments={"api": deployment("api", "OK", "a" * 40)})
        assert ev.verdict == "NOTHING_TO_SHIP"

    def test_a_fresh_ok_on_the_governing_deployment_ships(self, repo):
        head = sha(repo, "main")
        ev = outcomes.deploy_evidence(
            "dd_api", repo_name="testrepo", sha=head,
            deployments={"api": deployment("api", "OK", head)})
        assert ev.verdict == "SHIPPED"
        assert ev.in_running_commit is True

    def test_an_uninstrumented_frontend_cannot_say_even_though_git_agrees(
            self, repo):
        """THE CASE THAT DECIDES THE SHAPE OF THIS MODULE.

        The frontend and the API live in one repository, so a merged
        frontend commit IS an ancestor of the running API's commit. The
        frontend container carries no GIT_SHA and its check reads UNKNOWN.
        A global ancestry question answers SHIPPED; the truthful answer is
        that nobody has looked.
        """
        head = sha(repo, "main")
        deployments = {
            "api": deployment("api", "OK", head),
            "frontend": deployment(
                "frontend", "UNKNOWN",
                "carries no GIT_SHA (not instrumented yet)"),
        }
        api = outcomes.deploy_evidence("dd_api", repo_name="testrepo",
                                       sha=head, deployments=deployments)
        frontend = outcomes.deploy_evidence("dd_frontend", repo_name="testrepo",
                                            sha=head, deployments=deployments)
        assert api.verdict == "SHIPPED"
        assert frontend.verdict == "CANNOT_SAY"
        assert frontend.cannot_say and not frontend.shipped

    def test_a_stale_check_cannot_say(self, repo):
        head = sha(repo, "main")
        ev = outcomes.deploy_evidence(
            "dd_api", repo_name="testrepo", sha=head,
            deployments={"api": deployment("api", "STALE", head, age_minutes=600)})
        assert ev.verdict == "CANNOT_SAY"

    def test_a_check_that_last_ran_before_the_merge_cannot_say(self, repo):
        """An OK from 09:30 says nothing about a branch merged at 09:35."""
        head = sha(repo, "main")
        merged_at = datetime.now(timezone.utc)
        ev = outcomes.deploy_evidence(
            "dd_api", repo_name="testrepo", sha=head, merged_at=merged_at,
            deployments={"api": deployment("api", "OK", head, age_minutes=30)})
        assert ev.verdict == "CANNOT_SAY"

    def test_ancestry_never_overrides_the_verdict(self, repo):
        """A repository on this host knows nothing about a container.

        The corroboration is carried beside the verdict and may disagree
        with it; it must never be promoted into it.
        """
        head = sha(repo, "main")
        ev = outcomes.deploy_evidence(
            "dd_api", repo_name="testrepo", sha=head,
            deployments={"api": deployment("api", "UNKNOWN", head)})
        assert ev.verdict == "CANNOT_SAY"
        assert ev.shipped is False
