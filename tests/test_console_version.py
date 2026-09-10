"""The console reports which code it is running, and refuses to decide on stale.

WHAT THIS IS FOR. `fleet-console.service` is a long-lived uvicorn process.
Python loads a module once; editing the file changes nothing about the running
process. So the console enforces the rules of whenever it was last restarted,
and every other signal on the page says "current": the database is read fresh,
the contract comes out of the task row, the timestamps are now.

On 10 Sep 2026 a process that had been up since 09-09 10:05 refused task 53
because an added test file was "protected by platform/__tests__/**". Support
for `creatable_paths`, which permits exactly that file, landed in
runner/boundary.py at 09-09 14:08 -- four hours after that process booted. The
same check run from the tree was clean. Nothing anywhere said which of the two
had answered.

THE DANGEROUS DIRECTION IS THE OTHER ONE, and these tests are written for it: a
stale console refusing a good branch is loud and costs an afternoon. A stale
console holding a LAXER boundary than the tree accepts what the current rules
refuse, and says nothing at all.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from console import version


@pytest.fixture
def client(dsns, monkeypatch):
    """The app, as tests/test_console.py builds it."""
    from console import app as app_module
    monkeypatch.setattr(app_module.config, "repo_root",
                        lambda: Path("/nonexistent"))
    with TestClient(app_module.app) as c:
        yield c


@pytest.fixture
def touched(tmp_path, monkeypatch):
    """A code tree this test owns, snapshotted, then edited under the process."""
    root = tmp_path / "tree"
    (root / "console").mkdir(parents=True)
    (root / "runner").mkdir(parents=True)
    (root / "console" / "app.py").write_text("x = 1\n")
    (root / "runner" / "boundary.py").write_text("y = 2\n")
    monkeypatch.setattr(version.config, "PROJECT_ROOT", root)
    loaded = version.snapshot()
    monkeypatch.setattr(version, "LOADED", loaded)
    return root


class TestItKnowsWhatItLoaded:

    def test_an_untouched_tree_is_not_stale(self, touched):
        s = version.status()
        assert s["stale"] is False
        assert s["changed"] == []
        assert s["loaded"] == s["on_disk"]

    def test_an_edited_file_is_named(self, touched):
        time.sleep(0.01)
        (touched / "console" / "app.py").write_text("x = 2\n")
        s = version.status()
        assert s["stale"] is True
        assert s["changed"] == ["console/app.py"]

    def test_a_touched_file_counts_even_with_identical_content(self, touched):
        """mtime is part of the digest, and that is the safe direction.

        A false positive costs a restart. A false negative is a process
        enforcing rules nobody can see. runner/worktree.Untouched makes the
        same trade for the same reason.
        """
        p = touched / "runner" / "boundary.py"
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        assert version.status()["changed"] == ["runner/boundary.py"]

    def test_a_new_file_is_stale_too(self, touched):
        """The 10 Sep failure was a FUNCTION appearing, not a line changing."""
        (touched / "runner" / "verify.py").write_text("z = 3\n")
        s = version.status()
        assert s["stale"] is True
        assert s["changed"] == ["runner/verify.py (added)"]

    def test_a_removed_file_is_stale_too(self, touched):
        (touched / "runner" / "boundary.py").unlink()
        assert version.status()["changed"] == ["runner/boundary.py (removed)"]

    def test_pycache_does_not_count(self, touched):
        """Python writes .pyc on first import, so counting them would report
        drift the moment anything ran -- an alarm that is always on."""
        cache = touched / "console" / "__pycache__"
        cache.mkdir()
        (cache / "app.cpython-312.pyc").write_bytes(b"\x00\x01")
        assert version.status()["stale"] is False

    def test_only_python_counts(self, touched):
        """A template or a yaml is re-read from disk; it is not loaded once."""
        (touched / "console" / "notes.md").write_text("hello")
        assert version.status()["stale"] is False


class TestItRefusesToDecideOnStaleCode:

    def test_healthz_reports_the_version_either_way(self, client):
        body = client.get("/healthz").text
        assert "code loaded" in body and "code on disk" in body

    def test_healthz_says_STALE_when_it_is(self, client, monkeypatch):
        monkeypatch.setattr(version, "status", lambda: {
            "stale": True, "loaded": "aaa (39 files) at bbb",
            "on_disk": "ccc (40 files) at ddd",
            "changed": ["runner/boundary.py"]})
        body = client.get("/healthz").text
        assert "STALE" in body and "runner/boundary.py" in body

    def test_accept_is_refused_and_nothing_is_decided(self, client, monkeypatch):
        """409, not 200 with a sad message: this is a conflict with the tree."""
        monkeypatch.setattr(version, "is_stale", lambda: True)
        r = client.post("/tasks/1/accept",
                        data={"branch": "fleet/task-1", "rendered_at": "1.0"},
                        headers={"Origin": "http://testserver",
                                 "Host": "testserver"},
                        follow_redirects=False)
        assert r.status_code == 409
        assert "stale code" in r.text

    def test_reject_is_refused_too(self, client, monkeypatch):
        """Recording a rejection under retired rules is the same defect."""
        monkeypatch.setattr(version, "is_stale", lambda: True)
        r = client.post("/tasks/1/reject",
                        data={"reason": "WRONG_APPROACH", "rendered_at": "1.0"},
                        headers={"Origin": "http://testserver",
                                 "Host": "testserver"},
                        follow_redirects=False)
        assert r.status_code == 409

    def test_the_refusal_says_how_to_fix_it(self, client, monkeypatch):
        monkeypatch.setattr(version, "is_stale", lambda: True)
        r = client.post("/tasks/1/accept",
                        data={"branch": "fleet/task-1", "rendered_at": "1.0"},
                        headers={"Origin": "http://testserver",
                                 "Host": "testserver"},
                        follow_redirects=False)
        assert "systemctl restart fleet-console" in r.text

    def test_a_fresh_console_decides_normally(self, client, monkeypatch):
        """The guard must not be the thing that stops every accept forever."""
        monkeypatch.setattr(version, "is_stale", lambda: False)
        r = client.post("/tasks/999999/accept",
                        data={"branch": "fleet/task-999999", "rendered_at": "1.0"},
                        headers={"Origin": "http://testserver",
                                 "Host": "testserver"},
                        follow_redirects=False)
        # 404 for the missing task, which means it got past the staleness gate.
        assert r.status_code == 404


class TestTheBannerIsOnEveryPage:

    def test_a_stale_process_says_so_above_the_content(self, client, monkeypatch):
        monkeypatch.setattr(version, "status", lambda: {
            "stale": True, "loaded": "aaa (39 files) at bbb",
            "on_disk": "ccc (40 files) at ddd",
            "changed": ["runner/boundary.py"]})
        body = client.get("/tasks").text
        assert "running stale code" in body
        assert "runner/boundary.py" in body
        assert "systemctl restart fleet-console" in body

    def test_a_fresh_process_renders_no_banner(self, client):
        assert "running stale code" not in client.get("/tasks").text
