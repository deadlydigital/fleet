"""The lint ratchet, and the root it judges against.

contracts/checks/ruff_no_new_findings.py tolerates findings present at the base
commit and refuses findings the change introduces. It passed `--config
api/ruff.toml` to ruff, and that does not mean what it reads like: `--config`
also sets ruff's PROJECT ROOT to the current directory, and the project root is
what isort resolves first-party imports against.

Run from the worktree root, the checker got

    linter.project_root = /home/ubuntu/deadly-digital-platform

where discovery -- what a developer's own `ruff check` does -- gives
`.../api`. Under the wrong root `analytics` is not a first-party package, so a
correctly-grouped `from analytics...` is sorted into the third-party block and
the file reports I001.

WHY IT WENT UNNOTICED FOR EXISTING FILES AND KILLED A CREATED ONE

The spurious finding appears in the base content and the head content alike,
so the ratchet subtracts it and nobody sees it. A file the change CREATES has
no base content, so the same spurious finding counts as new.

Task 58 died that way on 11 Sep 2026: a correct one-line upsert fix, refused
over the import order of the test file the contract's own bite check obliged it
to create. £1.90 and a terminal failure. The imports were right; the checker
was holding them to a rule the project does not use.

AND AUTO-FIXING WOULD HAVE BEEN WORSE THAN REFUSING. Measured: applying what
the misrooted checker wanted produced a file that the project's own ruff then
reports as I001. The two roots disagree permanently, so "just let it fix
itself" oscillates.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

CHECK = Path(__file__).resolve().parent.parent / "contracts" / "checks" / "ruff_no_new_findings.py"
PLATFORM = Path("/home/ubuntu/deadly-digital-platform")
RUFF = PLATFORM / "api" / ".venv" / "bin" / "ruff"

pytestmark = pytest.mark.skipif(
    not RUFF.exists() or not (PLATFORM / "api" / "ruff.toml").exists(),
    reason="the platform checkout or its ruff is not on this host")


def _load():
    """Import the checker as a module, so its pieces can be called directly."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ruff_ratchet", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestItJudgesByTheProjectsOwnRoot:
    def test_the_checker_does_not_pass_config_to_ruff(self):
        """The regression in one line. `--config <path>` reroots ruff at the
        cwd; discovery from --stdin-filename is what gives the developer's
        answer."""
        src = CHECK.read_text()
        assert '"--config"' not in src, (
            "--config reroots ruff at the cwd, which changes which imports "
            "count as first-party and makes correctly-sorted files report I001")
        assert "--stdin-filename" in src, (
            "discovery needs the filename to walk up from")

    def test_a_wrong_root_refuses_to_judge(self, monkeypatch, tmp_path):
        """The guard that would have caught this bug. Asked of ruff, not
        assumed, so a future ruff that changes discovery fails loudly instead
        of silently rejecting correct files again."""
        mod = _load()
        monkeypatch.chdir(PLATFORM)
        # CONFIG pointing at the repo root while ruff will resolve .../api
        monkeypatch.setattr(mod, "CONFIG", "ruff.toml")
        with pytest.raises(SystemExit) as e:
            mod._assert_project_root("api/analytics/services/sync_engine.py")
        assert e.value.code == 2, "a wrong root must be could-not-run, not a pass"

    def test_the_real_root_is_accepted(self, monkeypatch):
        mod = _load()
        monkeypatch.chdir(PLATFORM)
        mod._assert_project_root("api/analytics/services/sync_engine.py")  # no exit

    def test_a_missing_config_refuses_to_judge(self, tmp_path):
        """Without it ruff lints with its own defaults, which is a different
        and laxer gate than the one this claims to be."""
        (tmp_path / "api").mkdir()
        f = tmp_path / "api" / "x.py"
        f.write_text("import os\n")
        r = subprocess.run(
            [sys.executable, str(CHECK)], cwd=tmp_path, capture_output=True, text=True,
            env={"FLEET_BASE_SHA": "HEAD", "FLEET_CHANGED_FILES": "api/x.py",
                 "PATH": "/usr/bin:/bin"})
        assert r.returncode == 2, r.stdout
        assert "laxer gate" in r.stdout


class TestTheRatchetStillBites:
    """The property that must not be weakened by any of the above."""

    def _correctly_sorted_first_party(self):
        return ("from decimal import Decimal\n\n"
                "import pytest\n"
                "from sqlalchemy import text\n\n"
                "from analytics.schema_manager import drop_analytics_schema\n")

    def test_a_correctly_sorted_new_file_is_clean(self):
        """Task 58's test file, in miniature: first-party `analytics` grouped
        after third-party `sqlalchemy`, which is what the project's config
        asks for and what the misrooted check rejected."""
        mod = _load()
        import os
        cwd = os.getcwd()
        os.chdir(PLATFORM)
        try:
            got = mod.findings(self._correctly_sorted_first_party(),
                               "api/tests/analytics/test_fleet_x.py")
        finally:
            os.chdir(cwd)
        assert "I001" not in got, got

    def test_a_genuinely_unsorted_new_file_is_not(self):
        mod = _load()
        import os
        cwd = os.getcwd()
        os.chdir(PLATFORM)
        try:
            got = mod.findings("import sys\nimport os\nfrom decimal import Decimal\n"
                               "import pytest\n",
                               "api/tests/analytics/test_fleet_x.py")
        finally:
            os.chdir(cwd)
        assert "I001" in got, (
            "the ratchet must still catch real import disorder; this change "
            "aims it correctly, it does not switch it off")
