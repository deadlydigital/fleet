"""Moving a checkout forward, and the one condition that forbids it.

`console/pull.py` is what lets anything other than a person move a checkout,
and `console/autodeploy` now depends on it: a deploy reads `rev-parse HEAD`,
so a pull that does not happen ships the wrong tree and a pull that happens at
the wrong moment fails a build after the spend. Both directions are asserted
here.

Task 96, 14 Sep 2026, is the failure this module exists to stop: claimed
12:00:13, a `git pull --ff-only` at 12:15:28, five checks green and the branch
pushed at 12:26:07, FAILED at 12:26:09 because the checkout had moved. £3.29.
"""
from __future__ import annotations

import datetime as dt
import subprocess

import pytest

from console import pull


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def behind(tmp_path, monkeypatch):
    """A clone one commit behind its origin, and nothing building."""
    origin = tmp_path / "origin"
    origin.mkdir()
    sh(origin, "git", "init", "-q", "-b", "main")
    sh(origin, "git", "config", "user.email", "t@t")
    sh(origin, "git", "config", "user.name", "t")
    (origin / "a.txt").write_text("one\n")
    sh(origin, "git", "add", "-A")
    sh(origin, "git", "commit", "-q", "-m", "one")

    clone = tmp_path / "clone"
    sh(tmp_path, "git", "clone", "-q", str(origin), str(clone))

    (origin / "a.txt").write_text("two\n")
    sh(origin, "git", "add", "-A")
    sh(origin, "git", "commit", "-q", "-m", "two")

    monkeypatch.setattr(pull, "building", lambda log=None: [])
    return clone


# ---- the dry run must move nothing ----------------------------------------

def test_a_dry_run_reports_what_it_would_do_and_moves_nothing(behind):
    """A dry run that fast-forwarded would be a deployment performed by the
    command whose whole promise is that it performs none."""
    was = pull.head(behind)
    out = pull.catch_up(behind, log=lambda m: None, dry_run=True)
    assert out.ok
    assert not out.already_current
    assert "would fast-forward" in out.reason
    assert pull.head(behind) == was, "the dry run moved the checkout"


def test_a_dry_run_on_a_current_checkout_says_so(behind):
    pull.catch_up(behind, log=lambda m: None)          # bring it up
    out = pull.catch_up(behind, log=lambda m: None, dry_run=True)
    assert out.ok and out.already_current


# ---- and the real thing must move ------------------------------------------

def test_it_fast_forwards_and_reports_what_moved(behind):
    was = pull.head(behind)
    out = pull.catch_up(behind, log=lambda m: None)
    assert out.ok and not out.already_current
    assert out.was == was and out.now != was
    assert out.commits == 1
    assert pull.head(behind) != was


def test_a_checkout_already_current_is_not_an_error(behind):
    pull.catch_up(behind, log=lambda m: None)
    out = pull.catch_up(behind, log=lambda m: None)
    assert out.ok and out.already_current


# ---- the condition that forbids it -----------------------------------------

class TestABuildInFlightForbidsIt:
    """The whole reason this module can be called by a program at all."""

    def _busy(self, monkeypatch):
        monkeypatch.setattr(pull, "building", lambda log=None: [
            {"id": 96, "title": "Accept repeated query parameters",
             "claimed_at": dt.datetime(2026, 9, 14, 12, 0, 13)}])

    def test_it_refuses_and_the_checkout_does_not_move(self, behind, monkeypatch):
        was = pull.head(behind)
        self._busy(monkeypatch)
        out = pull.catch_up(behind, log=lambda m: None)
        assert not out.ok
        assert "task 96 is building" in out.reason
        assert pull.head(behind) == was

    def test_a_dry_run_refuses_for_the_same_reason(self, behind, monkeypatch):
        """Not because it would move anything -- it would not -- but because
        the answer it would give is about a checkout it may not read as
        settled."""
        self._busy(monkeypatch)
        out = pull.catch_up(behind, log=lambda m: None, dry_run=True)
        assert not out.ok and "is building" in out.reason

    def test_the_refusal_names_the_task_and_what_it_would_cost(
            self, behind, monkeypatch):
        self._busy(monkeypatch)
        out = pull.catch_up(behind, log=lambda m: None)
        assert "96" in out.reason
        assert "12:00:13" in out.reason
        assert "after the spend" in out.reason, (
            "a refusal that does not say what it is protecting gets "
            "--wait'ed around without the reader learning anything")


# ---- the database being unreachable must not silently disarm it ------------

def test_a_failed_query_allows_the_pull_and_says_so(behind, monkeypatch):
    """A run cannot be in flight without the database -- claim_task() is what
    makes a task RUNNING. But silence would turn this into a guard that had
    stopped working and said nothing."""
    said = []

    def boom(log=None):
        if log:
            log("could not ask the database whether a build is in flight: "
                "OSError: connection refused. Continuing.")
        return []

    monkeypatch.setattr(pull, "building", boom)
    out = pull.catch_up(behind, log=said.append)
    assert out.ok
    assert any("could not ask the database" in m for m in said)
