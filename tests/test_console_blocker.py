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

class TestTheRefusalSaysWhatToDo:

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
        run("git", "checkout", "-q", "-b", "somebody-elses-work")
        return r

    def test_it_names_the_state_the_reason_and_the_fix(self, repo):
        task = {"id": 26, "repo": repo.name, "status": "READY_FOR_REVIEW",
                "branch_name": "fleet/task-26", "base_branch": "main"}
        out = merge.preflight(repo, task, "fleet/task-26", "", "", "")
        assert out.ok is False
        # the state
        assert "somebody-elses-work" in out.reason and "main" in out.reason
        # the reason it is not the branch's fault
        assert "nothing needs re-running" in out.reason
        # the fix
        assert any("checkout main" in d for d in out.detail)

    def test_it_does_not_blame_the_branch_or_the_base(self, repo):
        task = {"id": 26, "repo": repo.name, "status": "READY_FOR_REVIEW",
                "branch_name": "fleet/task-26", "base_branch": "main"}
        out = merge.preflight(repo, task, "fleet/task-26", "", "", "")
        assert "stale" not in out.reason.lower()
        assert "rebase" not in out.reason.lower()
