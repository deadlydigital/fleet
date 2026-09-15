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

def test_BEHIND_is_the_state_that_means_deploy(repo):
    """15 Sep 2026, and it is why this unit had never deployed anything.

    `DRIFT` means production is BEHIND origin/main. This refused on it until
    today, so it refused precisely when it had work -- and since any merge
    touching api/ puts production behind within 15 minutes of the next drift
    check, the 04:15 timer could only ever have fired in a window it cannot
    hit. journalctl for 9-15 Sep: seven runs, seven refusals, nothing deployed.
    """
    base = _sha(repo)
    sha = _commit(repo, "api/x.py", "y\n", "fleet merge")
    d = autodeploy.should_deploy(repo, _dep(status="DRIFT", sha=base), {sha})
    assert d.ok, d.reason
    assert d.running == base and d.target == sha


def test_AHEAD_is_the_case_refusal_one_was_written_for(repo):
    """DEPLOY-003: production is running a commit that is not on origin/main.
    Deploying over it buries whatever that is instead of identifying it."""
    base = _sha(repo)
    sha = _commit(repo, "api/x.py", "y\n", "fleet merge")
    d = autodeploy.should_deploy(repo, _dep(status="AHEAD", sha=base), {sha})
    assert not d.ok
    assert "AHEAD" in d.reason and "DEPLOY-003" in d.reason


def test_a_status_that_is_neither_still_refuses(repo):
    """UNKNOWN means the container is missing, stopped, or could not be asked.
    Nothing is known about what is running, and not knowing is not permission
    -- the same rule verify.py applies to a check that did not answer."""
    base = _sha(repo)
    sha = _commit(repo, "api/x.py", "y\n", "fleet merge")
    d = autodeploy.should_deploy(repo, _dep(status="UNKNOWN", sha=base), {sha})
    assert not d.ok
    assert "neither OK nor" in d.reason


def test_BEHIND_still_meets_every_other_refusal(repo):
    """Proceeding past refusal 1 is not skipping the rest. A BEHIND reading
    that is stale, or whose range carries a migration, or whose range is
    entirely human work, still refuses -- which is what makes the change above
    safe rather than merely correct."""
    base = _sha(repo)
    mig = _commit(repo, "api/alembic/versions/v1.py", "m\n", "a migration")
    assert not autodeploy.should_deploy(
        repo, _dep(status="DRIFT", sha=base), {mig}).ok
    stale = _dep(status="DRIFT", sha=base, age_minutes=120)
    assert not autodeploy.should_deploy(repo, stale, {mig}).ok
    human = _commit(repo, "api/y.py", "h\n", "a person's commit")
    assert not autodeploy.should_deploy(
        repo, _dep(status="DRIFT", sha=base), set()).ok


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

def test_production_already_on_the_checkouts_head_is_not_an_error(repo):
    """It said "already running main" until 14 Sep 2026, and `target` is the
    CHECKOUT's HEAD -- nothing in should_deploy reads the remote. On a stale
    checkout that reported the fleet's work as shipped while it sat unbuilt on
    the remote, and it was the reason given on three of the six nights this
    ran. The refusal now names what it compared; `run()` fast-forwards first,
    which is what makes the two the same thing rather than the sentence
    asserting it."""
    d = autodeploy.should_deploy(repo, _dep(sha=_sha(repo)), set())
    assert not d.ok
    assert "already running" in d.reason
    assert "this checkout's HEAD" in d.reason
    assert "main" not in d.reason, (
        "the refusal must not claim main -- it compared the working tree")


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


# ---- a run of refusals is a number, not seven identical silences ----------

class TestEveryRunLeavesARow:
    """15 Sep 2026, and it is the reason the bug above survived seven days.

    A refused deploy wrote nothing anywhere but journalctl, so these three left
    an identical trace -- none:

        the timer did not fire
        the timer fired and there was nothing to deploy
        the timer fired and refused, for the seventh day running

    console/approve.py had already solved this for the approval path and its
    docstring says why in four words: SILENCE CANNOT BE COUNTED. This is the
    same fix at the second unit that needed it.
    """

    def _dec(self, ok, reason="because"):
        return autodeploy.DeployDecision(
            ok, reason, running="b" * 40, target="c" * 40,
            commits=["c" * 40], unattended=[])

    def test_a_refusal_is_written_down(self, dsns, console, monkeypatch):
        rid = autodeploy.record(self._dec(False, "drift-check says AHEAD"),
                                running="b" * 40, target="c" * 40,
                                drift=_dep(status="AHEAD"))
        assert rid
        row = console.execute(
            "SELECT product, decision, decided_via, reason, mechanics"
            " FROM decision_log WHERE id=%s", (rid,)).fetchone()
        assert row["product"] == autodeploy.DEPLOY_PRODUCT
        assert row["decision"] == autodeploy.REFUSED
        assert row["decided_via"] == "unattended"
        assert "AHEAD" in row["reason"]
        # The reading it was made against, so the row can be checked rather
        # than believed -- and so a run of refusals can be read back by cause.
        assert row["mechanics"]["drift"]["status"] == "AHEAD"
        assert row["mechanics"]["outcome"] == "refused"

    def test_a_deploy_is_written_down_too(self, dsns, console, monkeypatch):
        """A streak needs something to reset it. With only refusals recorded
        there is nothing to count FROM."""
        rid = autodeploy.record(self._dec(True, "deployed"),
                                running="b" * 40, target="c" * 40,
                                drift=_dep(status="DRIFT"))
        row = console.execute("SELECT decision, mechanics FROM decision_log"
                              " WHERE id=%s", (rid,)).fetchone()
        assert row["decision"] == autodeploy.DEPLOYED
        assert row["mechanics"]["outcome"] == "deployed"

    def test_the_streak_counts_refusals_since_the_last_deploy(
            self, dsns, console, monkeypatch):
        """Seven in a row is the number that would have surfaced this bug on
        day two instead of day seven."""
        for _ in range(7):
            autodeploy.record(self._dec(False), running="b" * 40,
                              target="c" * 40, drift=_dep(status="DRIFT"))
        assert autodeploy.refusal_streak(console) >= 7
        autodeploy.record(self._dec(True), running="b" * 40, target="c" * 40,
                          drift=_dep(status="DRIFT"))
        assert autodeploy.refusal_streak(console) == 0
        autodeploy.record(self._dec(False), running="b" * 40, target="c" * 40,
                          drift=_dep(status="DRIFT"))
        assert autodeploy.refusal_streak(console) == 1

    def test_it_does_not_collide_with_the_approval_refusals(
            self, dsns, console, monkeypatch):
        """brief/pass_.py counts approval refusals as product='fleet'. A deploy
        refusal must not render as 'approved nothing', and an approval refusal
        must not reset the deploy streak."""
        console.execute(
            "INSERT INTO decision_log (product, subject, decision, reason,"
            " decided_by, decided_via, mechanics)"
            " VALUES ('fleet','Approved none of 3','DEFERRED','no key',"
            " current_user,'unattended','{\"cut\": {}}'::jsonb)")
        console.commit()
        before = autodeploy.refusal_streak(console)
        autodeploy.record(self._dec(False), running="b" * 40,
                          target="c" * 40, drift=_dep(status="DRIFT"))
        assert autodeploy.refusal_streak(console) == before + 1

    def test_a_failed_deploy_does_not_reset_the_streak(
            self, dsns, console, monkeypatch):
        """What the streak counts is runs that did not ship. A build that broke
        did not ship, and recording it as a deploy would reset the count on the
        strength of an attempt."""
        autodeploy.record(self._dec(False, "deploy.sh exited 1"),
                          running="b" * 40, target="c" * 40,
                          drift=_dep(status="DRIFT"))
        assert autodeploy.refusal_streak(console) >= 1

    def test_a_record_that_fails_does_not_change_what_happened(
            self, monkeypatch):
        """It runs after deploy.sh. Raising here would turn a successful deploy
        into a traceback and a failed one into two problems."""
        import console.db as _db
        def boom(*a, **k):
            raise RuntimeError("no database today")
        monkeypatch.setattr(_db, "writer", boom)
        said = []
        assert autodeploy.record(self._dec(True), running="b" * 40,
                                 target="c" * 40, drift=_dep(),
                                 log=said.append) is None
        assert any("not recorded" in m for m in said)
        assert any("hid seven refusals" in m for m in said)
