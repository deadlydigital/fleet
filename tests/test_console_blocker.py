"""A refusal that reaches only one browser tab is a silent failure.

Task 26 was accepted five times. Every POST returned 303, no HUMAN_DECISION
row was written, `origin/main` never moved, and the journal showed nothing but
the redirect. The merge was refusing correctly -- the checkout was on another
branch -- and the reason lived in a process-memory dict that is popped by the
next page load and logged nowhere.

Two properties close that:

  * an outcome CANNOT BE SET WITHOUT BEING LOGGED. `_record_outcome` is the
    only writer of `_OUTCOMES`, and it logs first. A helper that silently
    does nothing when nobody reads it is the shape being removed.
  * the refusal is shown BEFORE the button. `preflight` reads git and writes
    nothing, so the page can ask it on the GET and turn a refusal from a
    result into a precondition.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

import pytest

from console import app as app_module
from console import merge

FLEET = Path.home() / "fleet"


# ---- the logging guard -----------------------------------------------------

class TestAnOutcomeCannotBeSetWithoutBeingLogged:

    def test_a_refusal_is_logged_at_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="console"):
            app_module._record_outcome(99, {
                "ok": False, "headline": "Not merged, and nothing recorded",
                "detail": ["the checkout is on another branch"]})
        assert "task 99 REFUSED" in caplog.text
        assert "another branch" in caplog.text
        app_module._OUTCOMES.pop(99, None)

    def test_a_success_is_logged_too(self, caplog):
        with caplog.at_level(logging.INFO, logger="console"):
            app_module._record_outcome(98, {
                "ok": True, "headline": "Merged, pushed and recorded",
                "detail": []})
        assert "task 98" in caplog.text
        app_module._OUTCOMES.pop(98, None)

    def test_it_is_logged_even_when_nobody_ever_reads_it(self, caplog):
        """The whole defect: five refusals, none rendered, none logged."""
        with caplog.at_level(logging.WARNING, logger="console"):
            for _ in range(5):
                app_module._record_outcome(97, {
                    "ok": False, "headline": "Not merged", "detail": ["why"]})
        assert caplog.text.count("task 97 REFUSED") == 5
        assert app_module._take_outcome(97) is not None    # one survives
        assert app_module._take_outcome(97) is None        # pop-once, still

    def test_nothing_else_writes_the_dict(self):
        """THE GUARD. A second writer would bypass the logging and restore
        the silence, which is exactly how this was reachable before."""
        src = (FLEET / "console" / "app.py").read_text()
        writes = re.findall(r"_OUTCOMES\[[^\]]+\]\s*=", src)
        assert len(writes) == 1, (
            f"{len(writes)} assignments to _OUTCOMES; only _record_outcome "
            f"may write it, or a refusal can be set without being logged")
        helper = src[src.index("def _record_outcome"):]
        assert "_OUTCOMES[task_id] = outcome" in helper[:1200]


# ---- the message -----------------------------------------------------------

class TestACheckoutOnAnotherBranchIsNoLongerARefusal:
    """The refusal this class used to test was REMOVED on 9 Sep 2026.

    `preflight` used to refuse when the checkout was not on the task's base
    branch, and three tests here asserted that its message named the state,
    the reason and the fix. The message was good. The refusal should not have
    existed: it was needed only because the merge was made in that checkout,
    and the merge is now built and verified in a throwaway clone and published
    from there.

    The cost of the old behaviour was not a bad message. It was that pressing
    Accept required switching a production checkout onto a task's base branch
    -- and on the morning of 9 Sep 2026 doing exactly that took out three
    systemd timers, because the fleet's own units run from that tree.

    See specs/merge-outside-the-checkout.md and console/merge.py.
    """

    @pytest.fixture
    def repo(self, tmp_path):
        r = tmp_path / "repo"
        r.mkdir()
        run = lambda *a: subprocess.run(a, cwd=r, capture_output=True)
        run("git", "init", "-q", "-b", "main")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        (r / "f.txt").write_text("x")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "base")
        run("git", "checkout", "-q", "-b", "fleet/task-26")
        (r / "f.txt").write_text("y")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "work")
        run("git", "checkout", "-q", "-b", "somebody-elses-work")
        return r

    def test_where_the_checkout_points_is_not_mentioned_at_all(self, repo):
        """Not "it is allowed"; it is not a subject preflight has an opinion on."""
        tip = subprocess.run(["git", "-C", str(repo), "rev-parse", "fleet/task-26"],
                             capture_output=True, text=True).stdout.strip()
        task = {"id": 26, "repo": repo.name, "status": "READY_FOR_REVIEW",
                "branch_name": "fleet/task-26", "base_branch": "main"}
        out = merge.preflight(repo, task, "fleet/task-26", "", tip, "")
        assert out.ok, out.reason
        assert "somebody-elses-work" not in (out.reason or "")
        assert not any("checkout main" in d for d in out.detail)
