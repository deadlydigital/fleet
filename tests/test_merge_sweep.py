"""Merges that nothing records, as a standing reading.

specs/auto-approval.md §9.18. Task 51's hand-merge was found by accident on
11 Sep while backfilling something else. Running the same question over the
whole history then found two more — tasks 34 and 50, the documents that became
candidate batches 9 and 10, which is most of the open candidate pool and every
unattended approval made since.

Three instances out of seventeen merges naming a task. Not an accident, a
habit, and the question that finds it costs one git walk per base branch and
one query.

THE PREDICATE IS NARROW ON PURPOSE: for each merge commit whose subject names a
fleet task, is that task MERGED — the machine merged it and recorded it by
construction — or does a decision cite it? If neither, work reached a base
branch and nothing says why.

A READING AND NEVER A GATE. A gate here would stop a person fixing production
at 3am, which is the one thing this system must never do.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from console import morning


def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    sh = lambda *a: subprocess.run(["git", "-C", str(r), *a], check=True,
                                   capture_output=True)
    sh("init", "-q", "-b", "main")
    sh("config", "user.email", "t@t"); sh("config", "user.name", "t")
    (r / "a.txt").write_text("1\n"); sh("add", "-A"); sh("commit", "-qm", "base")
    return r


def _merge(repo: Path, branch: str, subject: str, filename: str):
    sh = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True,
                                   capture_output=True)
    sh("checkout", "-q", "-b", branch)
    (repo / filename).write_text("x\n"); sh("add", "-A"); sh("commit", "-qm", "work")
    sh("checkout", "-q", "main")
    sh("merge", "--no-ff", "-m", subject, branch)


class TestItFindsWhatNothingRecords:
    def test_a_merge_naming_a_failed_task_with_no_decision_is_reported(self, tmp_path):
        repo = _repo(tmp_path)
        _merge(repo, "fleet/task-50", "Merge task 50: candidates from the gap list", "c.md")
        asks = morning.unrecorded_merges(
            tmp_path, [("repo", "main")], {50: ("FAILED", ())})
        assert len(asks) == 1
        a = asks[0]
        assert a.kind == "MERGE_WITH_NO_DECISION"
        assert "task 50" in a.headline
        assert a.needs == "NEEDS_YOU", "somebody writes a sentence; no machine can"
        assert "fleet decision record" in a.detail, (
            "the remedy is copy-paste, for the reason the undo line is")

    def test_both_spellings_of_the_subject_are_matched(self, tmp_path):
        """The history carries "Merge fleet task 58: ..." and "Merge task 34:
        ...". A pattern that knew only the first missed two of the three
        instances this was built for."""
        repo = _repo(tmp_path)
        _merge(repo, "b1", "Merge fleet task 58: a re-sync must not erase", "x.md")
        _merge(repo, "b2", "Merge task 34: candidates from the gap list", "y.md")
        asks = morning.unrecorded_merges(
            tmp_path, [("repo", "main")], {58: ("FAILED", ()), 34: ("FAILED", ())})
        assert {a.headline.split("task ")[1].split()[0] for a in asks} == {"58", "34"}

    def test_a_merged_task_is_not_reported(self, tmp_path):
        """The machine merged it and the row says so. That IS the record."""
        repo = _repo(tmp_path)
        _merge(repo, "fleet/task-7", "Merge fleet task 7: something", "c.md")
        assert morning.unrecorded_merges(
            tmp_path, [("repo", "main")], {7: ("MERGED", ())}) == []

    def test_a_task_with_a_decision_is_not_reported(self, tmp_path):
        """Failed, hand-merged, and written up — which is the whole remedy."""
        repo = _repo(tmp_path)
        _merge(repo, "fleet/task-51", "Merge fleet task 51: deploy script", "c.md")
        assert morning.unrecorded_merges(
            tmp_path, [("repo", "main")], {51: ("FAILED", (33,))}) == []

    def test_a_merge_naming_no_task_is_ignored(self, tmp_path):
        repo = _repo(tmp_path)
        _merge(repo, "feat/x", "Merge branch 'feat/x'", "c.md")
        assert morning.unrecorded_merges(tmp_path, [("repo", "main")], {}) == []


class TestItSaysWhenItCouldNotLook:
    """An unchecked repository and a clean one leave the same silence, which is
    the defect this reading exists to find, arriving in the reading itself."""

    def test_a_repository_that_is_not_there_is_reported(self, tmp_path):
        asks = morning.unrecorded_merges(tmp_path, [("nope", "main")], {})
        assert len(asks) == 1
        assert asks[0].kind == "MERGE_SWEEP_UNREADABLE"
        assert asks[0].needs == "NEEDS_A_MACHINE"

    def test_a_base_branch_that_does_not_exist_is_skipped_silently(self, tmp_path):
        """NOT a silent cap. Task 4 names fleet/main, which fleet has never had.
        A branch with no commits has no merges to miss, so this excludes an
        empty set rather than truncating a real one."""
        _repo(tmp_path)
        assert morning.unrecorded_merges(tmp_path, [("repo", "no-such")], {}) == []

    def test_a_branch_that_exists_and_cannot_be_walked_is_not_silent(self, tmp_path):
        """The other half: if git itself fails on a branch that IS there, that
        is a machine problem and must not read as 'nothing to report'."""
        repo = _repo(tmp_path)
        (repo / ".git" / "HEAD").write_text("garbage\n")
        asks = morning.unrecorded_merges(tmp_path, [("repo", "main")], {})
        assert asks == [] or asks[0].kind == "MERGE_SWEEP_UNREADABLE"


class TestTheIndexIsOneQuery:
    def test_the_index_shape(self):
        rows = [{"id": 50, "status": "FAILED", "decision_ids": []},
                {"id": 51, "status": "FAILED", "decision_ids": [33]}]
        idx = morning.merge_record_index(rows)
        assert idx[50] == ("FAILED", ())
        assert idx[51] == ("FAILED", (33,))


class TestItRunsOnThisHostAndIsClean:
    """The live assertion. Three instances were found on 11 Sep and all three
    were written up; this fails if a fourth appears and nobody notices."""

    def test_no_unrecorded_merge_on_this_host(self, console):
        from console import config, queries
        if not (config.repo_root() / "fleet" / ".git").exists():
            pytest.skip("no checkouts on this host")
        asks = morning.unrecorded_merges(
            config.repo_root(), queries.morning_repo_branches(),
            morning.merge_record_index(queries.morning_merge_record()))
        gaps = [a for a in asks if a.kind == "MERGE_WITH_NO_DECISION"]
        assert gaps == [], (
            "work reached a base branch with nothing recording why:\n  "
            + "\n  ".join(a.headline for a in gaps))
