"""Sending a verified branch back without destroying it.

THE INCIDENT. On 22 Sep 2026 tasks 137 and 142 were sent back by hand along
READY_FOR_REVIEW -> REWORK -> QUEUED, an edge 003 declared and nothing ever
implemented. Both had a run at AWAITING_HUMAN holding the slot
`runs_one_active_per_task` reserves, so the next claim could not open a run and
the tick died -- after `claim_task()` had spent the attempt. 137 reached 3/3
with its branch_name cleared without an agent ever running.
"""
from __future__ import annotations

import json

import psycopg
import pytest

from console import rework
from tests.support import PLATFORM_FLOOR

REPO = "deadly-digital-platform"


def contract() -> dict:
    return {"work_type": "dd_feature", "repo": REPO, "base_branch": "main",
            "contract_version": 1,
            "writable_paths": ["api/analytics/services/analytics_engine.py"],
            "protected_paths": list(PLATFORM_FLOOR),
            "verification": ["true"], "max_diff_lines": 500,
            "max_cost_gbp": 3.00}


def _task(console, admin, runner, *, status="READY_FOR_REVIEW",
          run_status="AWAITING_HUMAN", max_attempts=1):
    tid = console.execute(
        "INSERT INTO tasks (title, spec_md, repo, base_branch,"
        " acceptance_contract, max_cost_gbp, max_attempts)"
        " VALUES ('a task','# spec',%s,'main',%s,3.00,%s) RETURNING id",
        (REPO, json.dumps(contract()), max_attempts)).fetchone()["id"]
    console.commit()
    runner.execute("SELECT claim_task(NULL)")
    runner.commit()
    rid = admin.execute(
        "INSERT INTO runs (task_id, work_type, contract_version,"
        " spend_limit_gbp, committed_gbp, status, reason)"
        " VALUES (%s,'dd_feature',1,3.00,0.75,%s,'verified, branch ready')"
        " RETURNING id", (tid, run_status)).fetchone()["id"]
    runner.execute(
        "UPDATE tasks SET status=%s, branch_name=%s WHERE id=%s",
        (status, f"fleet/task-{tid}", tid))
    runner.commit()
    return tid, rid


# ---- the defect itself ----------------------------------------------------

def test_the_run_holding_the_slot_is_closed_first(dsns, console, admin, runner):
    """THE WHOLE POINT. A task requeued with its run still open cannot be
    claimed: the next tick dies on runs_one_active_per_task after claim_task()
    has already spent the attempt."""
    tid, rid = _task(console, admin, runner, max_attempts=1)

    r = rework.rework(tid, "\n\n## try again\n", extra_attempts=1)

    assert r.ok, r.reason
    assert r.closed_runs == [rid]
    row = admin.execute("SELECT status FROM runs WHERE id=%s", (rid,)).fetchone()
    assert row["status"] == "FAILED", "the slot is still held"


def test_the_requeued_task_can_actually_be_claimed(dsns, console, admin, runner):
    """The end-to-end property the incident violated: claim it and a run opens.

    Without the close above this raises UniqueViolation, which is exactly how
    task 137 reached 3/3 without an agent ever running.
    """
    tid, _ = _task(console, admin, runner, max_attempts=1)
    rework.rework(tid, "\n\n## try again\n", extra_attempts=1)

    claimed = runner.execute("SELECT claim_task(NULL) AS id").fetchone()["id"]
    runner.commit()
    assert claimed == tid
    runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version,"
        " spend_limit_gbp) VALUES (%s,'dd_feature',1,3.00)", (tid,))
    runner.commit()


def test_the_run_keeps_what_it_said_about_itself(dsns, console, admin, runner):
    """`reason` is deliberately not grantable to the console: a rework ends a
    run, it does not get to rewrite the run's account of itself."""
    tid, rid = _task(console, admin, runner)
    rework.rework(tid, "\n\n## try again\n")
    row = admin.execute("SELECT reason FROM runs WHERE id=%s", (rid,)).fetchone()
    assert row["reason"] == "verified, branch ready"


# ---- it never half-acts ---------------------------------------------------

def test_a_console_that_cannot_close_the_run_moves_nothing(
        dsns, console, admin, runner, monkeypatch):
    """The safety property that holds even before 054 is applied.

    The close is the FIRST write in the transaction, so a privilege failure
    rolls back before the task moves -- rather than leaving it QUEUED with its
    slot held, which is the state that destroyed 137.
    """
    tid, rid = _task(console, admin, runner)

    real = rework.db.writer

    class Refusing:
        def __init__(self, inner): self._inner = inner
        def __getattr__(self, n): return getattr(self._inner, n)
        def execute(self, sql, *a, **k):
            if "UPDATE runs" in sql:
                raise psycopg.errors.InsufficientPrivilege(
                    "permission denied for table runs")
            return self._inner.execute(sql, *a, **k)

    class Wrapper:
        def __init__(self): self._c = real()
        def __enter__(self): return Refusing(self._c.__enter__())
        def __exit__(self, *a): return self._c.__exit__(*a)

    monkeypatch.setattr(rework.db, "writer", Wrapper)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        rework.rework(tid, "\n\n## try again\n")

    row = admin.execute("SELECT status FROM tasks WHERE id=%s", (tid,)).fetchone()
    assert row["status"] == "READY_FOR_REVIEW", "the task moved anyway"
    assert admin.execute("SELECT status FROM runs WHERE id=%s",
                         (rid,)).fetchone()["status"] == "AWAITING_HUMAN"


def test_feedback_is_required(dsns, console, admin, runner):
    """A requeue with nothing new said buys the same attempt again."""
    tid, _ = _task(console, admin, runner)
    r = rework.rework(tid, "   ")
    assert not r.ok and "feedback" in r.reason
    assert admin.execute("SELECT status FROM tasks WHERE id=%s",
                         (tid,)).fetchone()["status"] == "READY_FOR_REVIEW"


def test_it_refuses_a_task_that_would_not_be_claimable(
        dsns, console, admin, runner):
    tid, _ = _task(console, admin, runner, max_attempts=1)
    r = rework.rework(tid, "\n\n## try\n", extra_attempts=0)
    assert not r.ok and "would not be claimable" in r.reason


def test_only_sendable_states_are_sendable(dsns, console, admin, runner):
    tid, _ = _task(console, admin, runner, status="READY_FOR_REVIEW")
    console.execute("UPDATE tasks SET status='MERGED' WHERE id=%s", (tid,))
    console.commit()
    r = rework.rework(tid, "\n\n## try\n")
    assert not r.ok and "MERGED" in r.reason


def test_spec_md_is_appended_not_replaced(dsns, console, admin, runner):
    tid, _ = _task(console, admin, runner)
    rework.rework(tid, "\n\n## the feedback\n")
    md = admin.execute("SELECT spec_md FROM tasks WHERE id=%s", (tid,)).fetchone()["spec_md"]
    assert md.startswith("# spec"), "spec_md is append-only"
    assert "the feedback" in md


def test_a_dry_run_writes_nothing(dsns, console, admin, runner):
    tid, rid = _task(console, admin, runner)
    r = rework.rework(tid, "\n\n## try\n", dry_run=True)
    assert r.ok
    assert admin.execute("SELECT status FROM tasks WHERE id=%s",
                         (tid,)).fetchone()["status"] == "READY_FOR_REVIEW"
    assert admin.execute("SELECT status FROM runs WHERE id=%s",
                         (rid,)).fetchone()["status"] == "AWAITING_HUMAN"


def test_a_failed_task_needs_no_rework_hop(dsns, console, admin, runner):
    """FAILED -> QUEUED is its own edge and skips REWORK, but it needs the same
    run-closing: a FAILED task can still have a run holding the slot."""
    tid, rid = _task(console, admin, runner, status="RUNNING", max_attempts=1)
    runner.execute("UPDATE tasks SET status='FAILED' WHERE id=%s", (tid,))
    runner.commit()

    r = rework.rework(tid, "\n\n## try\n", extra_attempts=1)

    assert r.ok, r.reason
    assert admin.execute("SELECT status FROM runs WHERE id=%s",
                         (rid,)).fetchone()["status"] == "FAILED"
    assert admin.execute("SELECT status FROM tasks WHERE id=%s",
                         (tid,)).fetchone()["status"] == "QUEUED"


# ---- what landed underneath it while it was terminal ----------------------
#
# console/rank.py gate 3 refuses a candidate that collides with a LIVE task,
# and LIVE_TASK_STATES is QUEUED/CLAIMED/RUNNING/READY_FOR_REVIEW. Reviving a
# terminal task walks past a gate that has already decided there was no
# collision. Re-running gate 3 would not have caught either incident either:
# by the time each task was revived, the work it collided with had MERGED,
# which is terminal too. The question for a revived task is what landed in its
# files while it was away, and that is a fact about git.

def _repo_with_origin(tmp_path):
    import subprocess

    def sh(cwd, *a):
        r = subprocess.run(a, cwd=cwd, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    bare = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    (repo / "api" / "analytics" / "services").mkdir(parents=True)
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(bare))
    sh(tmp_path, "git", "init", "-q", "-b", "main", str(repo))
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "t")
    eng = repo / "api" / "analytics" / "services" / "analytics_engine.py"
    eng.write_text("x = 1\n")
    (repo / "README.md").write_text("readme\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "base")
    base = sh(repo, "git", "rev-parse", "HEAD")
    sh(repo, "git", "remote", "add", "origin", str(bare))
    sh(repo, "git", "push", "-q", "origin", "main")
    return repo, base, sh, eng


def test_it_names_what_merged_into_the_declared_paths(tmp_path):
    """142's shape: the collision is with work that has already MERGED."""
    repo, base, sh, eng = _repo_with_origin(tmp_path)
    eng.write_text("x = 1\nFORECAST_MEASURE = 'new_customers'\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "fleet task 147: new customers forecast")
    sh(repo, "git", "push", "-q", "origin", "main")

    rows = rework.merged_since(
        {"repo": "r", "base_branch": "main", "spec_md": "",
         "acceptance_contract": contract()}, base, repo=repo)

    assert len(rows) == 1, rows
    assert "task 147" in rows[0]["subject"]
    assert rows[0]["files"] == ["api/analytics/services/analytics_engine.py"]


def test_a_commit_outside_the_declared_paths_is_not_reported(tmp_path):
    """Generous overlap is for the gate; this is a report and must be about
    THIS task's files, or it is noise nobody reads twice."""
    repo, base, sh, _ = _repo_with_origin(tmp_path)
    (repo / "README.md").write_text("readme\nchanged\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "docs only")
    sh(repo, "git", "push", "-q", "origin", "main")

    rows = rework.merged_since(
        {"repo": "r", "base_branch": "main", "spec_md": "",
         "acceptance_contract": contract()}, base, repo=repo)
    assert rows == []


def test_it_reads_the_remote_not_the_stale_checkout(tmp_path):
    """Since 2026-09-09 the console cannot fast-forward any checkout, so the
    local ref is routinely behind the branch the task will be re-cut from.
    Reading it would under-report exactly when the report matters."""
    repo, base, sh, eng = _repo_with_origin(tmp_path)
    eng.write_text("x = 1\nlanded = True\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "fleet task 147: landed")
    sh(repo, "git", "push", "-q", "origin", "main")
    # The checkout falls behind, exactly as the real one does.
    sh(repo, "git", "reset", "-q", "--hard", base)

    rows = rework.merged_since(
        {"repo": "r", "base_branch": "main", "spec_md": "",
         "acceptance_contract": contract()}, base, repo=repo)
    assert len(rows) == 1, "the stale local ref was read instead of origin/main"


def test_an_unknown_base_reports_nothing_rather_than_guessing(tmp_path):
    repo, _, _, _ = _repo_with_origin(tmp_path)
    assert rework.merged_since(
        {"repo": "r", "base_branch": "main", "spec_md": "",
         "acceptance_contract": contract()}, "", repo=repo) == []
