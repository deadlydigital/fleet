"""Re-verifying against the merged tree, before the merge is made."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from console import merge, reverify

REPO = "deadly-digital-platform"
FLOOR = ["api/tests/**", "api/pytest.ini", "api/ruff.toml", "api/alembic/**",
         "api/analytics/migrations/**", "platform/__tests__/**",
         "platform/vitest.config.ts", "platform/playwright.config.ts"]


def contract(**over) -> dict:
    c = {"work_type": "dd_feature", "repo": REPO, "base_branch": "main",
         "contract_version": 1, "writable_paths": ["api/**"],
         "protected_paths": list(FLOOR),
         # A check that reads the MERGED tree: it fails if main's marker and
         # the branch's marker disagree, which is a clean merge into a broken
         # combination.
         "verification": ["test \"$(cat api/expects.txt)\" = \"$(cat api/provides.txt)\""],
         "max_diff_lines": 500, "max_cost_gbp": 3.00}
    c.update(over)
    return c


def sh(cwd: Path, *args: str) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"{' '.join(args)}: {r.stderr}"
    return r.stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "repos" / REPO
    (r / "api").mkdir(parents=True)
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.email", "t@t")
    sh(r, "git", "config", "user.name", "t")
    (r / "api" / "expects.txt").write_text("v1\n")
    (r / "api" / "provides.txt").write_text("v1\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-q", "-m", "base")
    return r


@pytest.fixture
def wt_root(tmp_path) -> Path:
    p = tmp_path / "wt"
    p.mkdir()
    return p


def task_for(repo: Path, tid: int = 1) -> dict:
    return {"id": tid, "base_branch": "main", "repo": REPO,
            "status": "READY_FOR_REVIEW", "branch_name": f"fleet/task-{tid}"}


def branch_with(repo: Path, name: str, changes: dict[str, str]) -> tuple[str, str]:
    point = sh(repo, "git", "rev-parse", "HEAD").strip()
    sh(repo, "git", "checkout", "-q", "-b", name)
    for path, body in changes.items():
        (repo / path).write_text(body)
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "work")
    tip = sh(repo, "git", "rev-parse", "HEAD").strip()
    sh(repo, "git", "checkout", "-q", "main")
    return point, tip


def advance_main(repo: Path, changes: dict[str, str], msg: str = "main moves"):
    for path, body in changes.items():
        (repo / path).write_text(body)
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", msg)


# ---- the failure that becomes routine overnight --------------------------

def test_a_clean_merge_into_broken_code_is_caught(repo, wt_root):
    """The branch verifies on its own. Main verifies on its own. The merge is
    clean and the result is broken -- different files, no conflict."""
    point, tip = branch_with(repo, "fleet/task-1", {"api/provides.txt": "v2\n"})
    advance_main(repo, {"api/expects.txt": "v3\n"})

    r = reverify.run(repo, wt_root, task_for(repo), contract(), "fleet/task-1",
                     recorded_base=point, changed_files=["api/provides.txt"])
    assert not r.ok
    assert not r.conflicted, "this is not a conflict; git merged it happily"
    assert "FAILS when merged" in r.reason
    assert sh(repo, "git", "status", "--porcelain").strip() == ""
    assert sh(repo, "git", "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def test_the_same_branch_passes_when_the_base_has_not_moved(repo, wt_root):
    """The proof the check above is about the MERGE and not the branch."""
    point, tip = branch_with(repo, "fleet/task-1",
                             {"api/provides.txt": "v2\n", "api/expects.txt": "v2\n"})
    r = reverify.run(repo, wt_root, task_for(repo), contract(), "fleet/task-1",
                     recorded_base=point, changed_files=["api/provides.txt"])
    assert r.ok, r.reason
    assert r.merged_sha and r.merged_sha != r.base_sha


def test_it_verifies_the_merged_tree_not_the_branch(repo, wt_root):
    """A check that passes on the branch and fails on the merge must fail.

    If this ran against the branch it would pass, and prove nothing new.
    """
    point, tip = branch_with(repo, "fleet/task-1", {"api/provides.txt": "v9\n"})
    # On the branch alone, expects is still v1 -> mismatch either way, so make
    # the branch self-consistent and let main break it.
    sh(repo, "git", "checkout", "-q", "fleet/task-1")
    (repo / "api" / "expects.txt").write_text("v9\n")
    sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "consistent")
    sh(repo, "git", "checkout", "-q", "main")
    advance_main(repo, {"api/expects.txt": "v4\n"})

    r = reverify.run(repo, wt_root, task_for(repo), contract(), "fleet/task-1",
                     recorded_base=point, changed_files=["api/provides.txt"])
    assert not r.ok, "verified the branch instead of the merge"


# ---- a failure leaves nothing behind -------------------------------------

def test_a_failure_records_nothing_and_leaves_the_tree_clean(repo, wt_root):
    point, tip = branch_with(repo, "fleet/task-1", {"api/provides.txt": "v2\n"})
    advance_main(repo, {"api/expects.txt": "v3\n"})
    before_main = sh(repo, "git", "rev-parse", "main").strip()

    reverify.run(repo, wt_root, task_for(repo), contract(), "fleet/task-1",
                 recorded_base=point, changed_files=["api/provides.txt"])

    assert sh(repo, "git", "rev-parse", "main").strip() == before_main
    assert sh(repo, "git", "status", "--porcelain").strip() == ""
    assert not any(p.name.startswith(reverify.TRIAL_PREFIX)
                   for p in wt_root.iterdir()), "the trial worktree survived"


def test_a_conflicting_merge_is_reported_as_one(repo, wt_root):
    point, tip = branch_with(repo, "fleet/task-1", {"api/provides.txt": "branch\n"})
    advance_main(repo, {"api/provides.txt": "main\n"})
    r = reverify.run(repo, wt_root, task_for(repo), contract(), "fleet/task-1",
                     recorded_base=point, changed_files=["api/provides.txt"])
    assert not r.ok and r.conflicted
    assert "does not merge cleanly" in r.reason
    assert sh(repo, "git", "status", "--porcelain").strip() == ""


def test_a_contract_with_no_verification_is_skipped_not_passed(repo, wt_root):
    point, tip = branch_with(repo, "fleet/task-1", {"api/provides.txt": "v2\n"})
    r = reverify.run(repo, wt_root, task_for(repo), contract(verification=[]),
                     "fleet/task-1", recorded_base=point, changed_files=[])
    assert r.ok and r.skipped_reason


# ---- the tip guard, now primary ------------------------------------------

def test_a_commit_appended_after_verification_is_refused(repo, wt_root):
    """The hole the merge-base check left open: appending to a branch leaves
    the merge base untouched."""
    point, tip = branch_with(repo, "fleet/task-1", {"api/provides.txt": "v2\n"})
    mb_before = sh(repo, "git", "merge-base", "main", "fleet/task-1").strip()
    sh(repo, "git", "checkout", "-q", "fleet/task-1")
    (repo / "api" / "sneaky.txt").write_text("added after the run\n")
    sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-q", "-m", "appended")
    sh(repo, "git", "checkout", "-q", "main")
    assert sh(repo, "git", "merge-base", "main", "fleet/task-1").strip() == mb_before

    out = merge.preflight(repo, task_for(repo), "fleet/task-1",
                          recorded_base=point, recorded_patch=tip,
                          branch_point=point)
    assert not out.ok
    assert "not what was checked" in out.reason


def test_an_advancing_base_does_not_trip_the_guard(repo, wt_root):
    """Measured, because the whole premise turned on it."""
    point, tip = branch_with(repo, "fleet/task-1", {"api/provides.txt": "v2\n"})
    advance_main(repo, {"api/other.txt": "x\n"})
    advance_main(repo, {"api/other.txt": "y\n"}, msg="and again")
    out = merge.preflight(repo, task_for(repo), "fleet/task-1",
                          recorded_base=point, recorded_patch=tip,
                          branch_point=point)
    assert out.ok, out.reason


def test_a_rebased_branch_is_still_refused(repo, wt_root):
    point, tip = branch_with(repo, "fleet/task-1", {"api/provides.txt": "v2\n"})
    advance_main(repo, {"api/other.txt": "x\n"})
    sh(repo, "git", "checkout", "-q", "fleet/task-1")
    sh(repo, "git", "rebase", "-q", "main")
    new_tip = sh(repo, "git", "rev-parse", "HEAD").strip()
    sh(repo, "git", "checkout", "-q", "main")
    out = merge.preflight(repo, task_for(repo), "fleet/task-1",
                          recorded_base=point, recorded_patch=new_tip,
                          branch_point=point)
    assert not out.ok
    assert "rebased" in out.reason or "cut from" in out.reason


def test_a_run_with_no_branch_point_skips_that_check(repo, wt_root):
    """Runs recorded before branch_point_sha existed. The tip check and the
    re-verification carry the argument instead of a guess."""
    point, tip = branch_with(repo, "fleet/task-1", {"api/provides.txt": "v2\n"})
    advance_main(repo, {"api/other.txt": "x\n"})
    out = merge.preflight(repo, task_for(repo), "fleet/task-1",
                          recorded_base="0" * 40, recorded_patch=tip,
                          branch_point="")
    assert out.ok, out.reason
    assert any("no branch point" in d for d in out.detail)


# ---- a checker that is not there ------------------------------------------

def test_a_missing_checker_is_could_not_run_not_a_failing_check(repo, wt_root):
    """Task 22, as the worked example.

    Its contract names /home/ubuntu/fleet/contracts/checks/draft_spec_shape.py,
    which exists only on the `spec/daily-brief` branch of a repository that has
    nothing to do with the merge. With ~/fleet checked out elsewhere the
    command exits 2 -- the shape of a failing check -- and Accept said "the
    branch verifies on its own and FAILS when merged into <base>". The branch
    is fine. Nothing about it was ever looked at.
    """
    point, tip = branch_with(repo, "fleet/task-1", {"api/provides.txt": "v2\n"})

    r = reverify.run(
        repo, wt_root, task_for(repo),
        contract(verification=["/nonexistent/python /nonexistent/shape.py"]),
        "fleet/task-1", recorded_base=point, changed_files=["api/provides.txt"])

    assert not r.ok
    assert r.could_not_run, "a missing checker is not a verdict about the branch"
    assert "/nonexistent/shape.py" in r.reason
    assert "FAILS when merged" not in r.reason, (
        "this is the sentence that sends a reviewer to read a diff that is fine")
    # And nothing was touched, exactly as for any other refusal.
    assert sh(repo, "git", "status", "--porcelain").strip() == ""
    assert sh(repo, "git", "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"


def test_a_missing_checker_does_not_merge_by_looking_like_a_skip(repo, wt_root):
    """The dangerous reading, asserted against at the outcome.

    An unresolved check does not `ran`, and skips are treated as passes, so
    conflating the two would let a merge through unverified -- worse than
    either wrong report. Two independent things refuse it: `Check.passed`
    returns False for unresolved, and `Verification.passed` requires that
    some check actually ran. This asserts the outcome rather than either
    mechanism, which is why the reversion guard for the first one points at a
    unit test instead of here.
    """
    point, _ = branch_with(repo, "fleet/task-1", {"api/provides.txt": "v2\n"})
    r = reverify.run(
        repo, wt_root, task_for(repo),
        contract(verification=["/nonexistent/shape.py"]),
        "fleet/task-1", recorded_base=point, changed_files=["api/provides.txt"])
    assert not r.ok, "an unresolvable contract must never re-verify as OK"
