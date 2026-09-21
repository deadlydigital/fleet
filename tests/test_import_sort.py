"""Sorting the imports the change un-sorted, instead of refusing the change.

THE CLASS. `contracts/checks/ruff_no_new_findings.py` refuses a diff that adds
an I001, which is correct and, three times, expensive: task 58 (11 Sep, £1.90,
terminal, on the test file the contract's own bite check obliged it to create),
task 87's near-miss on 13 Sep, and task 136 on 18 Sep -- one I001 in
`api/analytics/services/analytics_engine.py` and every other check green. A
re-roll does not reproduce the same diff, so the cost is a whole agent run and
the outcome is a different branch.

WHY THIS WAS REFUSED ON 11 SEP AND IS NOT NOW, and the difference is one
measurement rather than a change of mind. 62b7fc9 recorded:

    AUTO-FIXING WOULD HAVE BEEN WORSE THAN REFUSING, and this was measured
    rather than argued: applying what the misrooted checker wanted produced a
    file the project's own ruff then reports as I001.

That was true, and re-measured on 19 Sep it is STILL true -- of a misrooted
fixer. `--config api/ruff.toml` reroots ruff at the worktree, `analytics` stops
being first-party, and the two roots disagree permanently. What changed is that
the same commit removed `--config` from the checker and added
`_assert_project_root`. A fixer that resolves the root by discovery, as the
checker now does, is a fixpoint: its output passes the project's own unmodified
`ruff check`, and a second pass changes nothing.

So the oscillation was a property of the ROOT, never of fixing. These tests pin
both halves: that the sort agrees with the project, and that it refuses to
write at all if the root is ever wrong again -- because a misrooted judge
refuses correct files, while a misrooted fixer would write wrong ones into the
tree and merge them.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from runner import repair

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "contracts" / "checks" / "ruff_no_new_findings.py"
PLATFORM = Path("/home/ubuntu/deadly-digital-platform")
RUFF = PLATFORM / "api" / ".venv" / "bin" / "ruff"

#: WHERE THE FILE SITS DECIDES WHETHER THE ROOT MATTERS, and getting this
#: wrong makes the whole fixture test nothing. Ruff calls `analytics.*`
#: first-party for a file INSIDE `api/analytics/` whatever root it resolved --
#: it is the file's own package. The root only decides the question for a file
#: outside it, which is why task 58 died on a created file under
#: `api/tests/analytics/` and not on the service it was testing.
CREATED = "api/tests/analytics/test_fleet_x.py"

#: Task 58's shape: first-party `analytics` grouped after third-party
#: `sqlalchemy`, correct by the project's own rules and I001 under a misrooted
#: ruff. With task 136's shape folded in -- a comment glued to the import below
#: it, which the project wants a blank line above.
UNSORTED = (
    "import logging\n"
    "from decimal import Decimal\n"
    "\n"
    "from sqlalchemy import text\n"
    "# spec:3 -- a comment glued to the import below it\n"
    "from analytics.schema_manager import drop_analytics_schema\n"
)

#: What the project's own ruff wants of it. Written out rather than derived, so
#: a test that stops asserting anything fails instead of agreeing with itself.
SORTED = (
    "import logging\n"
    "from decimal import Decimal\n"
    "\n"
    "from sqlalchemy import text\n"
    "\n"
    "# spec:3 -- a comment glued to the import below it\n"
    "from analytics.schema_manager import drop_analytics_schema\n"
)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


def _repo(tmp_path: Path, base: dict[str, str], head: dict[str, str]) -> tuple[Path, str]:
    """A worktree with a base commit and uncommitted work on top.

    The real shape at the moment the runner sorts: the agent has finished and
    nothing is committed yet, so HEAD is still the base the ratchet compares
    against. `api/ruff.toml` is the project's own file, copied rather than
    invented -- a config written for the test would make this a test of the
    test's opinion about import order.
    """
    (tmp_path / "api" / "analytics").mkdir(parents=True)
    (tmp_path / "api" / "tests" / "analytics").mkdir(parents=True)
    (tmp_path / "api" / "ruff.toml").write_text((PLATFORM / "api" / "ruff.toml").read_text())
    # ENOUGH OF THE PACKAGE FOR RUFF TO RESOLVE IT, which is more than it
    # looks. `analytics` counts as first-party only if the whole dotted path
    # is on disk under the src root -- the package directory, its
    # `__init__.py`, AND the submodule the import names. Measured 19 Sep: drop
    # `schema_manager.py` and ruff files `analytics` with the third-party
    # block, so the fixture would agree with a misrooted checker and every
    # assertion below would pass for the wrong reason. That is the task-58
    # mistake, made in a test instead of in production.
    for pkg in ("api/analytics", "api/tests", "api/tests/analytics"):
        (tmp_path / pkg / "__init__.py").write_text("")
    (tmp_path / "api" / "analytics" / "schema_manager.py").write_text(
        "def drop_analytics_schema():\n    pass\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    for path, text in base.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    base_sha = _git(tmp_path, "rev-parse", "HEAD").strip()
    for path, text in head.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    return tmp_path, base_sha


def _run(repo: Path, base_sha: str, changed: list[str], *args: str):
    return subprocess.run(
        [sys.executable, str(CHECK), *args], cwd=repo,
        capture_output=True, text=True,
        env={"FLEET_BASE_SHA": base_sha,
             "FLEET_CHANGED_FILES": "\n".join(changed),
             "PATH": "/usr/bin:/bin"})


class TestTheRunnerAsksTheGateToRepairItself:
    """No ruff needed: this is about which command is run, and when."""

    def test_the_command_is_the_contracts_own(self):
        """Not a second configuration.

        The whole defect behind task 58 was two invocations of ruff resolving
        different roots. A repair configured separately from the gate is that
        defect with a write attached, so the command is read off the contract
        that is about to do the judging.
        """
        contract = {"verification": [
            "/x/python /home/ubuntu/fleet/contracts/checks/spec_requirements_cited.py",
            "/x/python /home/ubuntu/fleet/contracts/checks/ruff_no_new_findings.py",
        ]}
        assert repair.ratchet_command(contract) == contract["verification"][1]

    def test_a_contract_with_no_lint_gate_is_left_alone(self, tmp_path):
        contract = {"verification": ["/x/python -m compileall -q {changed_files:.py}"]}
        assert repair.ratchet_command(contract) is None
        assert repair.sort_imports(tmp_path, contract, "HEAD", print) == []

    def test_a_contract_with_no_verification_at_all(self, tmp_path):
        assert repair.ratchet_command({}) is None
        assert repair.sort_imports(tmp_path, {}, "HEAD", print) == []

    def test_nothing_it_can_do_ends_the_tick(self, capsys):
        """A paid agent run is not thrown away over a convenience.

        This sits between a finished agent and a twenty-minute verification.
        Whatever goes wrong -- a worktree that is not there, a git that
        refuses -- the tree is left as the agent left it and the gate says
        what it always said.
        """
        contract = {"verification": [f"/x/python /y/{repair.RATCHET}"]}
        assert repair.sort_imports(Path("/nonexistent"), contract, "HEAD",
                                   print) == []
        assert "import sort: GitError" in capsys.readouterr().out

    def test_the_sort_happens_before_the_commit(self):
        """Order, asserted, because it is the whole of why it works.

        After `commit_agent_work` the commit is what gets pushed and what
        `boundary.derive` measures, so a sort applied later either never
        reaches the branch or needs every recorded sha re-derived. Before it,
        the sorted line is part of the agent's commit -- counted against the
        diff budget, judged by the boundary, verified, merged.
        """
        src = (ROOT / "runner" / "cycle.py").read_text()
        sort = src.index("repair.sort_imports(")
        commit = src.index("boundary.commit_agent_work(\n"
                           "            wt_path, f\"fleet task {task['id']}")
        assert sort < commit, (
            "the import sort must run before the agent's work is committed, "
            "or it never reaches the branch")


@pytest.mark.skipif(
    not RUFF.exists() or not (PLATFORM / "api" / "ruff.toml").exists(),
    reason="the platform checkout or its ruff is not on this host")
class TestItAgreesWithTheProjectsOwnRuff:
    def test_the_two_roots_still_disagree(self, tmp_path):
        """The 11 Sep measurement, re-taken, and it still holds.

        This is not a test of our code. It is the fact the whole design rests
        on: a misrooted ruff wants an ordering the project rejects. If ruff
        ever makes the two agree this test fails, and whoever sees it should
        know that the root guard has stopped being load-bearing rather than
        assume it never was.
        """
        repo, _ = _repo(tmp_path, {}, {CREATED: UNSORTED})
        f = CREATED
        discovery = subprocess.run([str(RUFF), "check", "--select", "I001", "--fix", f],
                                   cwd=repo, capture_output=True, text=True)
        assert discovery.returncode == 0, discovery.stdout
        wanted_by_the_project = (repo / f).read_text()

        (repo / f).write_text(UNSORTED)
        subprocess.run([str(RUFF), "check", "--select", "I001", "--fix",
                        "--config", "api/ruff.toml", f],
                       cwd=repo, capture_output=True, text=True)
        assert (repo / f).read_text() != wanted_by_the_project, (
            "the misrooted fixer and the project now agree; the root guard in "
            "ruff_no_new_findings.py is no longer load-bearing and the "
            "argument in its docstring needs rewriting, not deleting")

    def test_an_introduced_sort_is_fixed_and_the_gate_then_passes(self, tmp_path):
        """Task 136, in miniature."""
        repo, base = _repo(tmp_path, {}, {CREATED: UNSORTED})
        changed = [CREATED]

        before = _run(repo, base, changed)
        assert before.returncode == 1, before.stdout
        assert "1 new I001" in before.stdout

        fix = _run(repo, base, changed, "--fix")
        assert fix.returncode == 0, fix.stdout
        assert f"sorted the imports in {CREATED}" in fix.stdout

        after = _run(repo, base, changed)
        assert after.returncode == 0, after.stdout

    def test_what_it_wrote_is_what_the_project_wants(self, tmp_path):
        """A fixpoint, not one end of an oscillation.

        The project's own unmodified `ruff check` -- every rule, no --select --
        must be satisfied by the file the repair produced.
        """
        repo, base = _repo(tmp_path, {}, {CREATED: UNSORTED})
        _run(repo, base, [CREATED], "--fix")
        assert (repo / CREATED).read_text() == SORTED
        verdict = subprocess.run([str(RUFF), "check", CREATED],
                                 cwd=repo, capture_output=True, text=True)
        assert verdict.returncode == 0, verdict.stdout

    def test_running_it_twice_changes_nothing(self, tmp_path):
        repo, base = _repo(tmp_path, {}, {CREATED: UNSORTED})
        _run(repo, base, [CREATED], "--fix")
        once = (repo / CREATED).read_text()
        second = _run(repo, base, [CREATED], "--fix")
        assert second.returncode == 0
        assert "nothing to sort" in second.stdout
        assert (repo / CREATED).read_text() == once


@pytest.mark.skipif(
    not RUFF.exists() or not (PLATFORM / "api" / "ruff.toml").exists(),
    reason="the platform checkout or its ruff is not on this host")
class TestItDoesNotWidenAndItDoesNotLowerTheBar:
    def test_a_pre_existing_finding_is_left_where_it_is(self, tmp_path):
        """The ratchet's own argument, applied to the repair.

        `revenue.py` and `sync_engine.py` both carry a pre-existing I001, and
        both are writable under the api contract. Sorting one of those on the
        way past puts an unrelated import-sort into a diff being judged for
        staying narrow -- the widening the gate's docstring refuses, paid for
        out of the task's line budget.
        """
        repo, base = _repo(tmp_path,
                           {CREATED: UNSORTED},
                           {CREATED: UNSORTED + "\nVALUE = 1\n"})
        out = _run(repo, base, [CREATED], "--fix")
        assert out.returncode == 0, out.stdout
        assert "nothing to sort" in out.stdout
        assert (repo / CREATED).read_text() == UNSORTED + "\nVALUE = 1\n"

    def test_it_fixes_import_order_and_nothing_else(self, tmp_path):
        """A real fault in the change is still the change's problem.

        `--select I001` is the whole licence. A repair pass that quietly
        rewrote the other rules the project enables would hide work the gate
        exists to show.
        """
        bad = "import logging\n\nVALUE = 1\nlogging.info(VALUE == None)\n"   # E711
        repo, base = _repo(tmp_path, {}, {CREATED: bad})
        fix = _run(repo, base, [CREATED], "--fix")
        assert fix.returncode == 0, fix.stdout
        assert (repo / CREATED).read_text() == bad
        assert _run(repo, base, [CREATED]).returncode == 1

    def test_a_genuinely_unsorted_file_is_still_sorted_not_excused(self, tmp_path):
        repo, base = _repo(tmp_path, {}, {
            CREATED: "import sys\nimport os\nimport logging\n"})
        _run(repo, base, [CREATED], "--fix")
        assert (repo / CREATED).read_text() == (
            "import logging\nimport os\nimport sys\n")

    def test_a_deleted_file_is_not_opened(self, tmp_path):
        repo, base = _repo(tmp_path, {CREATED: UNSORTED}, {})
        (repo / CREATED).unlink()
        out = _run(repo, base, [CREATED], "--fix")
        assert out.returncode == 0, out.stdout


@pytest.mark.skipif(
    not RUFF.exists() or not (PLATFORM / "api" / "ruff.toml").exists(),
    reason="the platform checkout or its ruff is not on this host")
class TestAWrongRootWritesNothing:
    """The guard that matters more in this mode than in the other one.

    A misrooted JUDGE refuses correct files: expensive, visible, recoverable.
    A misrooted FIXER replaces correct imports with ones the project rejects,
    commits them, and merges them. Same guard, higher stakes, so it is asserted
    of the writing path and not only of the reading one.
    """

    def _load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ruff_ratchet_fix", CHECK)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_it_refuses_to_sort_when_the_root_is_wrong(self, tmp_path, monkeypatch):
        repo, base = _repo(tmp_path, {}, {CREATED: UNSORTED})
        (repo / "ruff.toml").write_text((PLATFORM / "api" / "ruff.toml").read_text())
        mod = self._load()
        monkeypatch.chdir(repo)
        monkeypatch.setenv("FLEET_BASE_SHA", base)
        monkeypatch.setenv("FLEET_CHANGED_FILES", CREATED)
        # CONFIG at the repo root while ruff's discovery resolves .../api
        monkeypatch.setattr(mod, "CONFIG", "ruff.toml")
        with pytest.raises(SystemExit) as e:
            mod.main(["--fix"])
        assert e.value.code == 2
        assert (repo / CREATED).read_text() == UNSORTED, (
            "a repair that cannot establish the project's root must write "
            "nothing at all")

    def test_a_missing_config_writes_nothing(self, tmp_path):
        repo, base = _repo(tmp_path, {}, {CREATED: UNSORTED})
        (repo / "api" / "ruff.toml").unlink()
        out = _run(repo, base, [CREATED], "--fix")
        assert out.returncode == 2, out.stdout
        assert (repo / CREATED).read_text() == UNSORTED

    def test_an_unknown_argument_is_refused_rather_than_guessed(self, tmp_path):
        repo, base = _repo(tmp_path, {}, {CREATED: UNSORTED})
        out = _run(repo, base, [CREATED], "--repair")
        assert out.returncode == 2, out.stdout
        assert (repo / CREATED).read_text() == UNSORTED
