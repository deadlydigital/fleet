"""Recovering a tick that died.

The centrepiece is test_a_killed_tick_is_recovered: it starts a real runner
subprocess against a real repository, kills it while the agent is working, and
then recovers the task. Everything else here is a property of that path
checked in isolation.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psycopg
import pytest

from runner import reclaim, worktree

REPO = "deadly-digital-platform"
FLOOR = ["api/tests/**", "api/pytest.ini", "api/ruff.toml", "api/alembic/**",
         "api/analytics/migrations/**", "platform/__tests__/**",
         "platform/vitest.config.ts", "platform/playwright.config.ts"]


def contract(**over) -> dict:
    c = {"work_type": "dd_feature", "repo": REPO, "base_branch": "main",
         "contract_version": 1, "writable_paths": ["api/app.py"],
         "protected_paths": list(FLOOR), "verification": ["true"],
         "max_diff_lines": 200, "max_cost_gbp": 3.00}
    c.update(over)
    return c


def sh(cwd: Path, *args: str) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"{' '.join(args)}: {r.stderr}"
    return r.stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "repos" / REPO
    r.mkdir(parents=True)
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.email", "t@t")
    sh(r, "git", "config", "user.name", "t")
    (r / "api").mkdir()
    (r / "api" / "app.py").write_text("x = 1\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-q", "-m", "base")
    return r


@pytest.fixture
def settings(tmp_path, repo, monkeypatch):
    cfg = {"worktree_root": str(tmp_path / "wt"), "repo_root": str(repo.parent),
           "remote": "origin", "agent_tools": ["Read"], "usd_to_gbp": 0.79}
    monkeypatch.setattr(reclaim.config, "load_runner_config", lambda path=None: cfg)
    return cfg


def queue(console, **over) -> int:
    fields = {"title": "a task", "spec_md": "# spec", "repo": REPO,
              "base_branch": "main",
              "acceptance_contract": json.dumps(contract()),
              "max_cost_gbp": "3.00", "timeout_seconds": 300, "max_attempts": 2}
    fields.update(over)
    cols = ", ".join(fields)
    marks = ", ".join(f"%({k})s" for k in fields)
    row = console.execute(
        f"INSERT INTO tasks ({cols}) VALUES ({marks}) RETURNING id", fields
    ).fetchone()
    console.commit()
    return row["id"]


def make_stale(admin, task_id: int, seconds_ago: int = 4000) -> None:
    """Age the claim so the task is past its wall clock plus the grace."""
    admin.execute(
        "UPDATE tasks SET claimed_at = now() - make_interval(secs => %s)"
        " WHERE id = %s", (seconds_ago, task_id))


# ---- the age guard --------------------------------------------------------

def test_a_live_tick_is_not_reclaimed(dsns, console, runner):
    """The guard that stops this eating a working run."""
    tid = queue(console)
    runner.execute("SELECT claim_task(NULL)")
    runner.commit()
    out = runner.execute("SELECT reclaim_stale_task(%s) AS o", (tid,)).fetchone()["o"]
    assert out == "still_live"
    assert console.execute("SELECT status FROM tasks WHERE id=%s",
                           (tid,)).fetchone()["status"] == "RUNNING"


def test_a_grace_under_five_minutes_is_refused(dsns, console, runner):
    tid = queue(console)
    runner.execute("SELECT claim_task(NULL)")
    runner.commit()
    with pytest.raises(psycopg.errors.RaiseException, match="under five minutes"):
        runner.execute("SELECT reclaim_stale_task(%s, interval '0')", (tid,))


def test_the_deadline_is_the_tasks_own_wall_clock(dsns, console, runner, admin):
    """Not a constant: a task given an hour and a task given five minutes go
    stale at different times."""
    short = queue(console, timeout_seconds=300)
    runner.execute("SELECT claim_task(NULL)")
    runner.commit()
    admin.execute("UPDATE tasks SET claimed_at = now() - interval '20 minutes'"
                  " WHERE id = %s", (short,))
    stale = [r["task_id"] for r in
             runner.execute("SELECT * FROM stale_tasks()").fetchall()]
    assert short in stale

    admin.execute("UPDATE tasks SET timeout_seconds = 3600 WHERE id = %s", (short,))
    stale = [r["task_id"] for r in
             runner.execute("SELECT * FROM stale_tasks()").fetchall()]
    assert short not in stale, "an hour-long task went stale after 20 minutes"


def test_a_task_that_is_not_running_is_not_reclaimed(dsns, console, runner):
    tid = queue(console)
    out = runner.execute("SELECT reclaim_stale_task(%s) AS o", (tid,)).fetchone()["o"]
    assert out == "not_running"


# ---- what reclaiming does -------------------------------------------------

def test_it_requeues_below_max_attempts(dsns, console, runner, admin):
    tid = queue(console, max_attempts=2)
    runner.execute("SELECT claim_task(NULL)")
    runner.commit()
    make_stale(admin, tid)
    out = runner.execute("SELECT reclaim_stale_task(%s) AS o", (tid,)).fetchone()["o"]
    runner.commit()          # a separate connection cannot see an open transaction
    assert out == "requeued"
    row = console.execute("SELECT status, attempts, claimed_at FROM tasks WHERE id=%s",
                          (tid,)).fetchone()
    assert row["status"] == "QUEUED"
    assert row["claimed_at"] is None
    assert row["attempts"] == 1, "reclaim charged the attempt a second time"


def test_it_fails_the_task_at_the_limit(dsns, console, runner, admin):
    tid = queue(console, max_attempts=1)
    runner.execute("SELECT claim_task(NULL)")
    runner.commit()
    make_stale(admin, tid)
    out = runner.execute("SELECT reclaim_stale_task(%s) AS o", (tid,)).fetchone()["o"]
    runner.commit()
    assert out == "failed"
    assert console.execute("SELECT status FROM tasks WHERE id=%s",
                           (tid,)).fetchone()["status"] == "FAILED"


def test_it_closes_the_run_holding_the_one_per_task_slot(dsns, console, runner,
                                                         admin):
    """The reason a stuck task could not simply be requeued by hand: the
    abandoned ACTIVE run holds runs_one_active_per_task, and the next tick
    dies on the unique index."""
    tid = queue(console, max_attempts=2)
    runner.execute("SELECT claim_task(NULL)")
    # Commit BEFORE admin touches runs: claim_task holds a row lock on the
    # task, and the foreign key on runs.task_id needs that same row. Leaving
    # the claim open deadlocks the two connections against each other.
    runner.commit()
    admin.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s,'dd_feature',1,3.00)", (tid,))
    make_stale(admin, tid)
    runner.execute("SELECT reclaim_stale_task(%s)", (tid,))
    runner.commit()

    assert admin.execute(
        "SELECT count(*) AS n FROM runs WHERE task_id=%s AND status='ACTIVE'",
        (tid,)).fetchone()["n"] == 0
    # and a fresh run can now be opened, which is the whole point
    runner.execute("SELECT claim_task(NULL)")
    runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s,'dd_feature',1,3.00)", (tid,))
    runner.commit()


def test_attempts_are_not_double_counted_across_reclaims(dsns, console, runner,
                                                         admin):
    """claim_task() counts the try. Two claims and two reclaims spend two
    attempts, not four."""
    tid = queue(console, max_attempts=3)
    for _ in range(2):
        runner.execute("SELECT claim_task(NULL)")
        runner.commit()
        make_stale(admin, tid)
        runner.execute("SELECT reclaim_stale_task(%s)", (tid,))
        runner.commit()
    assert console.execute("SELECT attempts FROM tasks WHERE id=%s",
                           (tid,)).fetchone()["attempts"] == 2


# ---- worktrees ------------------------------------------------------------

def test_the_worktree_is_removed_and_the_branch_kept(dsns, settings, console,
                                                     runner, admin, repo, tmp_path):
    tid = queue(console, max_attempts=2)
    runner.execute("SELECT claim_task(NULL)")
    runner.commit()
    branch = worktree.branch_name(tid, 1)
    wt_root = Path(settings["worktree_root"])
    wt_root.mkdir(parents=True, exist_ok=True)
    wt_path, _ = worktree.create(repo, wt_root, branch, "main")
    (wt_path / "api" / "app.py").write_text("what the dead tick wrote\n")
    make_stale(admin, tid)

    results = reclaim.reclaim(log=lambda *_: None)
    assert [r.outcome for r in results] == ["requeued"]
    assert not wt_path.exists(), "the worktree was left pinning the branch"
    # The branch survives: whatever the dead tick wrote is still inspectable.
    assert sh(repo, "git", "rev-parse", "--verify", branch).strip()


def test_a_sweep_removes_orphans_and_spares_live_ones(dsns, settings, console,
                                                      runner, repo, tmp_path):
    live = queue(console)
    runner.execute("SELECT claim_task(NULL)")
    runner.commit()
    wt_root = Path(settings["worktree_root"])
    wt_root.mkdir(parents=True, exist_ok=True)
    live_wt, _ = worktree.create(repo, wt_root, worktree.branch_name(live, 1), "main")
    orphan_wt, _ = worktree.create(repo, wt_root, "fleet/task-999", "main")

    removed = reclaim.sweep_worktrees(log=lambda *_: None)
    assert str(orphan_wt) in removed
    assert live_wt.exists(), "a live task's worktree was swept"


# ---- the real thing: kill a tick mid-flight -------------------------------

def test_a_killed_tick_is_recovered(dsns, settings, console, runner, admin,
                                    repo, tmp_path, monkeypatch):
    """Start a real runner, kill it while the agent is working, recover it.

    The agent is a script that sleeps, so the kill lands mid-tick with the
    worktree created and the run open -- which is the state that could not be
    retried before, because the ACTIVE run held runs_one_active_per_task.
    """
    tid = queue(console, max_attempts=2, timeout_seconds=300)

    slow = tmp_path / "slow-claude"
    slow.write_text("#!/bin/bash\nsleep 600\n")
    slow.chmod(0o755)

    cfg = tmp_path / "runner.yaml"
    cfg.write_text(json.dumps(settings))

    env = dict(os.environ,
               FLEET_CLAUDE_BIN=str(slow),
               FLEET_RUNNER_CONFIG=str(cfg),
               FLEET_DSN=dsns["fleet"],
               FLEET_TASK_RUNNER_DSN=dsns["runner"],
               FLEET_AGENT_DSN=dsns["agent"],
               FLEET_VERIFIER_DSN=dsns["verifier"],
               FLEET_MODEL_GATEWAY_DSN=dsns["gateway"],
               FLEET_CONSOLE_DSN=dsns["console"],
               FLEET_CONSOLE_READER_DSN=dsns["console_reader"])
    proc = subprocess.Popen(
        [sys.executable, "run_task.py", "--task", str(tid), "--no-push"],
        cwd="/home/ubuntu/fleet", env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, start_new_session=True)

    # Wait until the tick has actually got going: worktree made, run opened.
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        row = admin.execute(
            "SELECT count(*) AS n FROM runs WHERE task_id=%s AND status='ACTIVE'",
            (tid,)).fetchone()
        if row["n"]:
            break
        time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("the tick never opened a run")

    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    proc.wait(timeout=30)

    # The wreckage: RUNNING task, ACTIVE run, worktree on disk.
    assert admin.execute("SELECT status FROM tasks WHERE id=%s",
                         (tid,)).fetchone()["status"] == "RUNNING"
    assert admin.execute(
        "SELECT count(*) AS n FROM runs WHERE task_id=%s AND status='ACTIVE'",
        (tid,)).fetchone()["n"] == 1
    wt_path = Path(settings["worktree_root"]) / f"fleet-task-{tid}"
    assert wt_path.exists(), "the killed tick left no worktree to reclaim"

    # Not yet stale, and reclaim must refuse.
    assert reclaim.reclaim(log=lambda *_: None) == []

    make_stale(admin, tid)
    lines: list[str] = []
    results = reclaim.reclaim(log=lines.append)
    print("\n".join("      " + l for l in lines))
    assert [r.outcome for r in results] == ["requeued"]
    assert any("removed worktree" in l for l in lines)
    assert not wt_path.exists()
    row = admin.execute("SELECT status, attempts FROM tasks WHERE id=%s",
                        (tid,)).fetchone()
    assert row["status"] == "QUEUED"
    assert row["attempts"] == 1
    assert admin.execute(
        "SELECT count(*) AS n FROM runs WHERE task_id=%s AND status='ACTIVE'",
        (tid,)).fetchone()["n"] == 0

    # And the recovered task can actually be claimed and opened again, which
    # is what "recovered" has to mean.
    runner.execute("SELECT claim_task(NULL)")
    runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s,'dd_feature',1,3.00)", (tid,))
    runner.commit()


def test_stale_tasks_cannot_name_a_live_tick_either(dsns, console, runner):
    """The worktree is removed before the database is asked, so the listing
    function needs the same floor the acting one has."""
    tid = queue(console)
    runner.execute("SELECT claim_task(NULL)")
    runner.commit()
    rows = runner.execute("SELECT * FROM stale_tasks(interval '0')").fetchall()
    assert rows == [], "a zero grace listed a live tick as reclaimable"


def test_an_unsafe_grace_is_refused_before_anything_is_touched(dsns, settings):
    """On a quiet queue the SQL guard never fires, because it is only reached
    when a candidate exists. So the refusal has to happen here."""
    with pytest.raises(ValueError, match="refusing a grace"):
        reclaim.reclaim(grace_seconds=10, log=lambda *_: None)
