"""What stops a deploy nobody watched.

specs/unattended-operation.md §6.2. `deploy.sh` decides HOW; this decides
WHETHER, and every branch below is a refusal.
"""
from __future__ import annotations

import subprocess
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from console import autodeploy


def _dep(status="OK", sha="a" * 40, age_minutes=5, detail=None):
    return SimpleNamespace(name="api", status=status, sha=sha, detail=detail,
                           checked_at=None, age=timedelta(minutes=age_minutes))


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "deadly-digital-platform"
    (r / "api" / "alembic" / "versions").mkdir(parents=True)
    (r / "api" / "analytics").mkdir(parents=True)
    run = lambda *a: subprocess.run(a, cwd=r, capture_output=True)
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "t")
    (r / "api" / "app.py").write_text("x = 1\n")
    run("git", "add", "-A"); run("git", "commit", "-q", "-m", "base")
    return r


def _sha(repo, ref="HEAD"):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", ref],
                          capture_output=True, text=True).stdout.strip()


def _commit(repo, path, body, msg):
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", msg],
                   capture_output=True)
    return _sha(repo)


# ---- the one that deploys -------------------------------------------------

def test_it_deploys_when_the_fleet_merged_something(repo):
    base = _sha(repo)
    sha = _commit(repo, "api/analytics/routes/orders.py", "y = 2\n", "fleet merge")
    d = autodeploy.should_deploy(repo, _dep(sha=base), {sha})
    assert d.ok, d.reason
    assert d.running == base and d.target == sha
    assert len(d.commits) == 1


# ---- drift -----------------------------------------------------------------

def test_a_drifted_production_is_not_deployed_onto(repo):
    base = _sha(repo)
    sha = _commit(repo, "api/x.py", "y\n", "fleet merge")
    d = autodeploy.should_deploy(repo, _dep(status="DRIFT", sha=base), {sha})
    assert not d.ok
    assert "already disagree" in d.reason


def test_no_drift_reading_at_all_is_a_refusal(repo):
    assert not autodeploy.should_deploy(repo, None, set()).ok


def test_a_stale_reading_is_not_an_OK(repo):
    """The check runs every 15 minutes. An hour-old OK is the answer from
    whenever it stopped."""
    base = _sha(repo)
    sha = _commit(repo, "api/x.py", "y\n", "fleet merge")
    d = autodeploy.should_deploy(repo, _dep(sha=base, age_minutes=90), {sha})
    assert not d.ok
    assert "stale OK is not an OK" in d.reason


# ---- migrations ------------------------------------------------------------

def test_a_migration_in_the_range_is_never_deployed_unattended(repo):
    base = _sha(repo)
    sha = _commit(repo, "api/alembic/versions/0001_x.py", "rev = 'x'\n", "migration")
    d = autodeploy.should_deploy(repo, _dep(sha=base), {sha})
    assert not d.ok
    assert "never deploys one" in d.reason
    assert "alembic" in d.reason


def test_an_analytics_migration_counts_too(repo):
    base = _sha(repo)
    sha = _commit(repo, "api/analytics/migrations/v1.py", "x\n", "tenant migration")
    d = autodeploy.should_deploy(repo, _dep(sha=base), {sha})
    assert not d.ok
    assert "never deploys one" in d.reason


# ---- provenance ------------------------------------------------------------

def test_human_commits_alone_do_not_trigger_a_deploy(repo):
    """Pushing to main is not asking for a deploy at 04:00."""
    base = _sha(repo)
    _commit(repo, "api/x.py", "y\n", "a person's commit")
    d = autodeploy.should_deploy(repo, _dep(sha=base), set())
    assert not d.ok
    assert "none of them is a merge this fleet made" in d.reason


def test_a_fleet_merge_carries_the_human_commits_with_it(repo):
    """Stated rather than discovered: you cannot deploy a subset of main."""
    base = _sha(repo)
    _commit(repo, "api/x.py", "y\n", "a person's commit")
    sha = _commit(repo, "api/analytics/routes/orders.py", "z\n", "fleet merge")
    d = autodeploy.should_deploy(repo, _dep(sha=base), {sha})
    assert d.ok
    assert len(d.commits) == 2, "the human commit ships too, and is listed"


# ---- nothing to do ---------------------------------------------------------

def test_production_already_on_main_is_not_an_error(repo):
    d = autodeploy.should_deploy(repo, _dep(sha=_sha(repo)), set())
    assert not d.ok
    assert "already running main" in d.reason


def test_every_refusal_says_why_in_a_sentence(repo):
    base = _sha(repo)
    sha = _commit(repo, "api/alembic/versions/1.py", "x\n", "m")
    for dep, shas in ((None, set()),
                      (_dep(status="DRIFT", sha=base), {sha}),
                      (_dep(sha=base, age_minutes=90), {sha}),
                      (_dep(sha=base), {sha}),
                      (_dep(sha=base), set())):
        d = autodeploy.should_deploy(repo, dep, shas)
        assert not d.ok
        assert len(d.reason.split()) >= 8, f"terse: {d.reason!r}"
