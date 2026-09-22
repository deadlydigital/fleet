"""A whole tick, with a fake agent.

The agent is faked because the property under test is what the runner does
with whatever the agent leaves behind, and a real model would make that
non-deterministic and expensive. Everything else is real: a real git
repository, real worktrees, the real database with the real four identities,
and the real boundary derivation.

The fake agent is deliberately hostile in several of these. An agent that
edits the suite and reports that it did not is the case the runner exists
for, and it is easier to arrange here than to wait for.
"""
from __future__ import annotations

import json
import subprocess

import psycopg
from pathlib import Path

import pytest

from runner import agent as agent_mod
from runner import cycle

REPO = "deadly-digital-platform"

from tests.support import PLATFORM_FLOOR

FLOOR = PLATFORM_FLOOR

FILES = {
    "api/analytics/services/analytics_engine.py": "def app():\n    '''old docstring'''\n    return 1\n",
    "api/services/thing.py": "value = 1\n",
    "api/tests/test_thing.py": "def test_v():\n    assert True\n",
    "api/pytest.ini": "[pytest]\n",
    "api/ruff.toml": "line-length = 100\n",
    "api/alembic/env.py": "# migrations\n",
    "api/analytics/migrations/001.sql": "-- migration\n",
    "platform/app/(dashboard)/analytics/orders/page.tsx":
        "export default () => null\n",
    "platform/__tests__/a.test.ts": "test('x', () => {})\n",
    "platform/vitest.config.ts": "export default {}\n",
    "platform/playwright.config.ts": "export default {}\n",
    "README.md": "# platform\n",
}


def sh(cwd: Path, *args: str) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"{' '.join(args)}: {r.stderr}"
    return r.stdout


@pytest.fixture
def platform_repo(tmp_path) -> Path:
    """A stand-in for the platform, with the floor's paths actually present."""
    root = tmp_path / "repos"
    root.mkdir()
    repo = root / REPO
    repo.mkdir()
    sh(repo, "git", "init", "-q", "-b", "main")
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "t")
    for path, body in FILES.items():
        f = repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    (repo / ".gitignore").write_text("*.log\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "base")
    return repo


@pytest.fixture
def settings(tmp_path, platform_repo, monkeypatch):
    """Runner configuration pointed entirely inside tmp_path."""
    cfg = {
        "worktree_root": str(tmp_path / "worktrees"),
        "repo_root": str(platform_repo.parent),
        "remote": "origin",
        "agent_tools": ["Read", "Edit", "Write"],
        "usd_to_gbp": 0.79,
    }
    monkeypatch.setattr(cycle.config, "load_runner_config", lambda path=None: cfg)
    # The fleet repository check is real in production; here the suite itself
    # is mutating the checkout, so it is pointed at the throwaway repo.
    monkeypatch.setattr(cycle.config, "PROJECT_ROOT", platform_repo)
    return cfg


def contract(**over) -> dict:
    c = {
        "work_type": "dd_feature",
        "repo": REPO,
        "base_branch": "main",
        "contract_version": 1,
        "writable_paths": ["api/analytics/services/analytics_engine.py",
                           "platform/app/(dashboard)/analytics/orders/**"],
        "protected_paths": list(FLOOR),
        "verification": ["true"],
        "max_diff_lines": 200,
        "max_cost_gbp": 3.00,
    }
    c.update(over)
    return c


def queue_task(console, **over) -> int:
    fields = {"title": "docstring fix", "spec_md": "# fix the docstring",
              "repo": REPO, "base_branch": "main",
              "acceptance_contract": json.dumps(over.pop("contract", contract())),
              "max_cost_gbp": "3.00", "max_attempts": 1}
    fields.update(over)
    cols = ", ".join(fields)
    marks = ", ".join(f"%({k})s" for k in fields)
    row = console.execute(
        f"INSERT INTO tasks ({cols}) VALUES ({marks}) RETURNING id", fields
    ).fetchone()
    console.commit()
    return row["id"]


def fake_agent(edits: dict[str, str] | None = None, *,
               reported: list[str] | None = None,
               timed_out: bool = False, exit_code: int = 0,
               cost_usd: float = 0.10, deletes: list[str] | None = None,
               raw: dict | None = None, output_tokens: int | None = None):
    """An agent that writes exactly what it is told to, and says what it likes."""
    def invoke(worktree: Path, prompt, timeout_seconds, model=None,
               allowed_tools=(), readable=(), max_output_tokens=None):
        for path, body in (edits or {}).items():
            f = worktree / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body)
        for path in (deletes or []):
            (worktree / path).unlink()
        text = "done"
        if reported is not None:
            text += "\n```json\n" + json.dumps({"changed_files": reported}) + "\n```"
        return agent_mod.AgentResult(
            exit_code=exit_code, timed_out=timed_out, duration_ms=1200,
            text=text, cost_usd=cost_usd, num_turns=3, session_id="fake",
            reported_paths=agent_mod.parse_report(text),
            output_tokens=output_tokens,
            raw={"model": "fake", **(raw or {})})
    return invoke


def run_tick(monkeypatch, invoke, **kw):
    monkeypatch.setattr(cycle.agent_mod, "invoke", invoke)
    return cycle.tick(push=False, log=lambda *_: None, **kw)


# ---- the happy path -------------------------------------------------------

def test_a_clean_task_reaches_ready_for_review(dsns, settings, console,
                                               monkeypatch):
    tid = queue_task(console)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new docstring'''\n    return 1\n"},
        reported=["api/analytics/services/analytics_engine.py"]))

    assert result.outcome == "READY_FOR_REVIEW", result.reason
    assert result.task_id == tid
    assert result.verdict.clean
    assert result.verification.passed

    row = console.execute("SELECT status, branch_name FROM tasks WHERE id=%s",
                          (tid,)).fetchone()
    assert row["status"] == "READY_FOR_REVIEW"
    assert row["branch_name"] == f"fleet/task-{tid}"


def test_the_run_and_its_steps_are_recorded(dsns, settings, console, monkeypatch):
    tid = queue_task(console)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))

    steps = console.execute(
        "SELECT sequence, step_type, actor, payload FROM run_steps"
        " WHERE run_id=%s ORDER BY sequence", (result.run_id,)).fetchall()
    assert [s["step_type"] for s in steps] == ["PATCH_PROPOSED", "VERIFICATION_RUN"]

    patch, verification = steps
    assert patch["payload"]["files_changed"] == ["api/analytics/services/analytics_engine.py"]
    assert patch["payload"]["derived_by"] == "runner"
    assert verification["payload"]["result"] == "PASS"
    assert verification["payload"]["boundary_clean"] is True
    # 001 refuses a PASS whose patch sha is not the latest proposal.
    assert (verification["payload"]["patch_commit_sha"]
            == patch["payload"]["patch_commit_sha"])
    # The suite did not move, and the record says so in a recomputable way.
    assert (verification["payload"]["suite_commit_sha"]
            == verification["payload"]["suite_commit_sha_at_base"])


def test_the_run_ends_awaiting_a_human_and_never_deployed(dsns, settings,
                                                          console, monkeypatch):
    queue_task(console)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))
    row = console.execute("SELECT status FROM runs WHERE id=%s",
                          (result.run_id,)).fetchone()
    assert row["status"] == "AWAITING_HUMAN"
    assert row["status"] not in cycle.FORBIDDEN_RUN_STATUS


# ---- the agent's account is not the input ---------------------------------

def test_an_agent_that_edits_the_suite_and_denies_it_is_refused(
        dsns, settings, console, monkeypatch):
    """The case the runner exists for."""
    tid = queue_task(console)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n",
         "api/tests/test_thing.py": "def test_v():\n    pass  # relaxed\n"},
        reported=["api/analytics/services/analytics_engine.py"]))          # the agent's story

    assert result.outcome == "FAILED"
    assert result.reason == "boundary violation"
    assert "api/tests/test_thing.py" in result.verdict.protected_hits
    assert result.verification.skipped_reason == "boundary violation"

    assert console.execute("SELECT status FROM tasks WHERE id=%s",
                           (tid,)).fetchone()["status"] == "FAILED"


def test_the_divergence_is_on_the_record(dsns, settings, console, monkeypatch):
    queue_task(console)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n",
         "api/tests/test_thing.py": "def test_v():\n    pass\n"},
        reported=["api/analytics/services/analytics_engine.py"]))
    payload = console.execute(
        "SELECT payload FROM run_steps WHERE run_id=%s AND sequence=1",
        (result.run_id,)).fetchone()["payload"]
    assert payload["agent_reported_files"] == ["api/analytics/services/analytics_engine.py"]
    assert payload["divergence"]["touched_but_unclaimed"] == \
        ["api/tests/test_thing.py"]


def test_verification_never_runs_on_a_dirty_boundary(dsns, settings, console,
                                                     monkeypatch):
    """A suite executed after the agent may have edited it says nothing.

    The contract's verification here would pass trivially; the point is that
    it is not run at all, so no PASS can be built on it."""
    queue_task(console, contract=contract(verification=["true"]))
    result = run_tick(monkeypatch, fake_agent(
        {"api/pytest.ini": "[pytest]\naddopts = --ignore=api/tests\n"}))
    assert result.outcome == "FAILED"
    assert result.verification.checks == []
    assert not result.verification.ran

    payload = console.execute(
        "SELECT payload FROM run_steps WHERE run_id=%s AND sequence=2",
        (result.run_id,)).fetchone()["payload"]
    assert payload["result"] == "FAIL"
    assert payload["boundary_clean"] is False
    assert payload["checks"] == []


class TestASizeRefusalStillCollectsTheEvidence:
    """12 Sep 2026, and task 69 is the whole of the argument.

    Verification is skipped on a boundary violation because a diff that
    touched a PROTECTED path may have touched the suite, and a suite the
    change rewrote cannot judge the change. That reason does not reach a diff
    whose only fault is length: every path in it was admitted by the contract.

    Task 69 paid for the distinction. Two runs, £7.97, refused at 377 test
    lines of 300 and then at 606 of 600 -- and because a size refusal returns
    before the checks, neither test was ever executed. The number those runs
    were re-measuring needed to know whether a long test passes and whether it
    BITES, and that is exactly what was thrown away twice.
    """

    #: One file, over the line, and nothing else wrong with it.
    OVERSIZED = {"api/analytics/services/analytics_engine.py":
                 "def app():\n" + "".join(f"    x{n} = {n}\n" for n in range(260))
                 + "    return 1\n"}

    def test_the_checks_run_and_the_branch_is_still_refused(
            self, dsns, settings, console, monkeypatch):
        tid = queue_task(console, contract=contract(verification=["true"]))
        result = run_tick(monkeypatch, fake_agent(self.OVERSIZED))

        assert result.outcome == "FAILED"
        assert result.reason == "boundary violation"
        assert result.verdict.over_diff_limit and result.verdict.size_only
        # The evidence the old path destroyed.
        assert result.verification.ran
        assert result.verification.skipped_reason is None
        assert [c.command for c in result.verification.checks] == ["true"]
        assert not result.pushed

        payload = console.execute(
            "SELECT payload FROM run_steps WHERE run_id=%s AND sequence=2",
            (result.run_id,)).fetchone()["payload"]
        # FAIL, with the checks beside it. A green suite on an oversized
        # branch is evidence, never an acceptance.
        assert payload["result"] == "FAIL"
        assert payload["boundary_clean"] is False
        assert payload["verification_skipped"] is None
        assert len(payload["checks"]) == 1
        assert payload["checks"][0]["exit_code"] == 0

        assert console.execute("SELECT status FROM tasks WHERE id=%s",
                               (tid,)).fetchone()["status"] == "FAILED"

    def test_a_green_suite_cannot_turn_a_refusal_into_a_pass(
            self, dsns, settings, console, monkeypatch):
        """The one thing this must never do."""
        queue_task(console, contract=contract(verification=["true"]))
        result = run_tick(monkeypatch, fake_agent(self.OVERSIZED))
        assert result.verification.passed          # the checks were happy
        assert result.outcome != "READY_FOR_REVIEW"
        assert result.outcome == "FAILED"

    def test_the_boundary_is_the_reason_even_when_the_checks_also_fail(
            self, dsns, settings, console, monkeypatch):
        """Two faults, one sentence, and it names the one that decided."""
        queue_task(console, contract=contract(verification=["false"]))
        result = run_tick(monkeypatch, fake_agent(self.OVERSIZED))
        assert result.outcome == "FAILED"
        assert result.reason == "boundary violation"
        assert not result.verification.passed
        assert result.verification.ran

    def test_the_test_allowance_collects_evidence_the_same_way(
            self, dsns, settings, console, monkeypatch):
        """The refusal task 69 actually hit, not the production one."""
        queue_task(console, contract=contract(
            creatable_paths=["api/tests/test_fleet_*.py"],
            max_test_diff_lines=50, verification=["true"]))
        result = run_tick(monkeypatch, fake_agent(
            {"api/analytics/services/analytics_engine.py":
                "def app():\n    '''new'''\n    return 1\n",
             "api/tests/test_fleet_thing.py":
                "".join(f"def test_{n}():\n    assert {n} == {n}\n"
                        for n in range(40))}))
        assert result.outcome == "FAILED"
        assert result.verdict.over_test_limit and result.verdict.size_only
        assert result.verification.ran

    def test_a_protected_path_still_skips_them(
            self, dsns, settings, console, monkeypatch):
        """The original reason, unchanged: too big AND into the suite is not
        size-only, and a suite the change may have rewritten cannot be run."""
        queue_task(console, contract=contract(verification=["true"]))
        edits = dict(self.OVERSIZED)
        edits["api/pytest.ini"] = "[pytest]\naddopts = --ignore=api/tests\n"
        result = run_tick(monkeypatch, fake_agent(edits))
        assert result.outcome == "FAILED"
        assert not result.verdict.size_only
        assert result.verification.skipped_reason == "boundary violation"
        assert result.verification.checks == []


def test_deleting_a_test_is_refused(dsns, settings, console, monkeypatch):
    queue_task(console)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"},
        deletes=["api/tests/test_thing.py"]))
    assert result.outcome == "FAILED"
    assert "api/tests/test_thing.py" in result.verdict.protected_hits


def test_a_file_outside_the_contract_is_refused(dsns, settings, console,
                                                monkeypatch):
    queue_task(console)
    result = run_tick(monkeypatch, fake_agent({"README.md": "# rewritten\n"}))
    assert result.outcome == "FAILED"
    assert result.verdict.outside_writable == ["README.md"]


# ---- failure paths --------------------------------------------------------

def test_an_unmet_obligation_gets_its_own_sentence(dsns, settings, console,
                                                   monkeypatch):
    """15 Sep 2026. `tasks.status` still has no third terminal value -- adding
    one is a schema change and does not belong riding along here -- so the
    task is FAILED either way and the SENTENCE is doing the work.

    Task 102 read "verification failed" with five checks green beside it,
    including a 15.4-minute analytics suite. That sentence is what the brief
    and the console print, and it sent a reader to a diff that was fine.
    """
    tid = queue_task(console, contract=contract(verification=["true", "exit 3"]))
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))
    assert result.outcome == "FAILED"
    assert result.reason.startswith("the branch owes:")
    assert "verification failed" not in result.reason
    assert not result.verification.passed, "it still refuses"
    assert result.verification.unmet_obligation
    assert not result.verification.failed_outright


def test_a_failure_beside_an_obligation_still_says_verification_failed(
        dsns, settings, console, monkeypatch):
    """The verdict that was reached is kept, on failed_outright's own
    argument. A branch that is broken and also owes a citation is broken."""
    tid = queue_task(console, contract=contract(verification=["exit 3", "false"]))
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))
    assert result.outcome == "FAILED"
    assert result.reason == "verification failed"


def test_failing_verification_fails_the_task(dsns, settings, console,
                                             monkeypatch):
    tid = queue_task(console, contract=contract(verification=["false"]))
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))
    assert result.outcome == "FAILED"
    assert result.reason == "verification failed"
    assert result.verdict.clean            # the boundary was fine
    assert not result.verification.passed
    assert console.execute("SELECT status FROM tasks WHERE id=%s",
                           (tid,)).fetchone()["status"] == "FAILED"


def test_an_agent_that_changes_nothing_fails(dsns, settings, console,
                                             monkeypatch):
    queue_task(console)
    result = run_tick(monkeypatch, fake_agent({}))
    assert result.outcome == "FAILED"
    assert result.reason == "the agent changed nothing"


def test_a_timeout_is_a_failure_and_is_recorded(dsns, settings, console,
                                                monkeypatch):
    tid = queue_task(console)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "x\n"}, timed_out=True))
    assert result.outcome == "FAILED"
    assert "wall clock" in result.reason
    payload = console.execute(
        "SELECT payload FROM run_steps WHERE run_id=%s AND sequence=1",
        (result.run_id,)).fetchone()["payload"]
    assert payload["agent_timed_out"] is True


def test_a_task_below_max_attempts_is_requeued(dsns, settings, console,
                                               monkeypatch):
    tid = queue_task(console, max_attempts=2)
    result = run_tick(monkeypatch, fake_agent({}))
    assert result.requeued
    row = console.execute("SELECT status, attempts FROM tasks WHERE id=%s",
                          (tid,)).fetchone()
    assert row["status"] == "QUEUED"
    assert row["attempts"] == 1


def test_a_second_attempt_gets_its_own_branch(dsns, settings, console,
                                              monkeypatch, platform_repo):
    tid = queue_task(console, max_attempts=2)
    run_tick(monkeypatch, fake_agent({}))
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))
    assert result.outcome == "READY_FOR_REVIEW", result.reason
    assert result.branch == f"fleet/task-{tid}.2"


# ---- one task per tick, and the tree is left alone ------------------------

def test_one_task_per_tick(dsns, settings, console, monkeypatch):
    a = queue_task(console, title="first", priority=10)
    b = queue_task(console, title="second", priority=20)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))
    assert result.task_id == a
    assert console.execute("SELECT status FROM tasks WHERE id=%s",
                           (b,)).fetchone()["status"] == "QUEUED"


def test_an_empty_queue_is_not_a_failure(dsns, settings, monkeypatch):
    result = run_tick(monkeypatch, fake_agent({}))
    assert result.outcome == "IDLE"
    assert result.task_id is None


def test_the_checkout_is_never_touched(dsns, settings, console, monkeypatch,
                                       platform_repo):
    before_head = sh(platform_repo, "git", "rev-parse", "HEAD").strip()
    before_status = sh(platform_repo, "git", "status", "--porcelain").strip()
    queue_task(console)
    run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))
    assert sh(platform_repo, "git", "rev-parse", "HEAD").strip() == before_head
    assert sh(platform_repo, "git", "status", "--porcelain").strip() == before_status


def test_the_worktree_is_removed_afterwards(dsns, settings, console,
                                            monkeypatch, tmp_path):
    queue_task(console)
    run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))
    leftovers = list((tmp_path / "worktrees").glob("*")) \
        if (tmp_path / "worktrees").exists() else []
    assert leftovers == []


# ---- budget ---------------------------------------------------------------

def test_cost_is_settled_against_the_reservation(dsns, settings, console,
                                                 admin, monkeypatch):
    queue_task(console)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"},
        cost_usd=1.00))
    assert result.cost_gbp == pytest.approx(0.79)
    row = console.execute(
        "SELECT committed_gbp FROM runs WHERE id=%s", (result.run_id,)).fetchone()
    assert float(row["committed_gbp"]) == pytest.approx(0.79)
    reservations = admin.execute(
        "SELECT status FROM budget_reservations WHERE run_id=%s",
        (result.run_id,)).fetchall()
    assert [r["status"] for r in reservations] == ["SETTLED"]


def test_an_overspend_is_capped_and_recorded(dsns, settings, console,
                                             monkeypatch):
    """settle_model_budget refuses an actual above the reservation, so the
    reservation closes at its bound and the true figure is not lost."""
    queue_task(console, max_cost_gbp="0.10")
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"},
        cost_usd=5.00))
    assert result.cost_gbp == pytest.approx(0.10)
    # The true figure is not lost. Which of the two overspend notes is
    # written -- cap fired, or cap dead -- is the spend-cap tests' subject,
    # not this one's; this asserts only that the real number is reported.
    true_gbp = round(5.00 * float(settings["usd_to_gbp"]), 4)
    assert any(f"£{true_gbp:.4f}" in n for n in result.notes), result.notes


# ---- push refusals --------------------------------------------------------

def test_pushing_the_base_branch_is_refused(platform_repo):
    from runner import worktree
    with pytest.raises(worktree.PushRefused, match="never merges"):
        worktree.push(platform_repo, "main", "main")


def test_pushing_a_name_that_is_not_a_task_branch_is_refused(platform_repo):
    from runner import worktree
    with pytest.raises(worktree.PushRefused):
        worktree.push(platform_repo, "main-ish", "main")


# ---- dependency links are created after the agent, not before -------------

def test_the_agent_never_sees_the_linked_dependencies(dsns, settings, console,
                                                      monkeypatch, tmp_path):
    """The timing IS the safety property.

    A write through the link would land outside the worktree's git index --
    not merely in an ignored path -- so the derived diff would show nothing.
    The only thing preventing that is that the link does not exist yet.
    """
    deps = tmp_path / "fake_node_modules"
    (deps / "pkg").mkdir(parents=True)
    c = contract(worktree_links={"platform/node_modules": str(deps)})
    queue_task(console, contract=c)

    seen: dict[str, bool] = {}

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_output_tokens=None):
        seen["linked_during_agent"] = (worktree / "platform/node_modules").exists()
        (worktree / "api/analytics/services/analytics_engine.py").write_text(
            "def app():\n    '''new'''\n    return 1\n")
        return agent_mod.AgentResult(exit_code=0, timed_out=False,
                                     duration_ms=10, text="done", cost_usd=0.01)

    result = run_tick(monkeypatch, invoke)
    assert seen["linked_during_agent"] is False
    assert result.outcome == "READY_FOR_REVIEW", result.reason


def test_the_link_exists_for_verification_and_is_gone_afterwards(
        dsns, settings, console, monkeypatch, tmp_path, platform_repo):
    deps = tmp_path / "fake_node_modules"
    (deps / "pkg").mkdir(parents=True)
    c = contract(
        worktree_links={"platform/node_modules": str(deps)},
        verification=["test -e platform/node_modules/pkg"])
    queue_task(console, contract=c)

    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))
    assert result.outcome == "READY_FOR_REVIEW", result.reason
    assert result.verification.passed          # the check saw the link
    assert (deps / "pkg").exists()             # and the real tree survived


# ---- verification aimed at the change ------------------------------------

def test_a_check_filtered_to_untouched_file_types_is_skipped(
        dsns, settings, console, monkeypatch):
    c = contract(verification=["true", "false # {changed_files:.tsx}"])
    queue_task(console, contract=c)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))
    assert result.outcome == "READY_FOR_REVIEW", result.reason
    assert [ch.ran for ch in result.verification.checks] == [True, False]


def test_a_run_where_every_check_was_skipped_fails(dsns, settings, console,
                                                   monkeypatch):
    """Nothing looked at this change, so it is not verified."""
    c = contract(verification=["true # {changed_files:.tsx}"])
    queue_task(console, contract=c)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"}))
    assert result.outcome == "FAILED"
    assert result.reason == "verification failed"


def test_checks_are_given_the_derived_change_not_the_agents_account(
        dsns, settings, console, monkeypatch):
    """$FLEET_CHANGED_FILES comes from git, so a lying agent cannot narrow
    what the lint gate looks at."""
    c = contract(verification=[
        'test "$FLEET_CHANGED_FILES" = "api/analytics/services/analytics_engine.py" && test -n "$FLEET_BASE_SHA"'])
    queue_task(console, contract=c)
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"},
        reported=[]))                      # the agent claims it changed nothing
    assert result.outcome == "READY_FOR_REVIEW", result.reason


def test_checks_are_given_the_frozen_contract(dsns, settings, console,
                                              monkeypatch):
    """$FLEET_CONTRACT is the contract from the ROW, not contracts/*.yaml.

    contracts/checks/paired_paths.py reads its groups from it. Reading the yaml
    on disk instead would judge this task against whatever that file says at the
    moment the check runs, which is the drift guard_task_immutability exists to
    remove -- the contract is frozen once the task leaves QUEUED precisely so
    that what judges the work cannot move under it.
    """
    read_it = (
        'test "$(printf %s "$FLEET_CONTRACT" | python3 -c '
        "\"import json,sys; print(json.load(sys.stdin)['max_diff_lines'])\")\" = 200")
    queue_task(console, contract=contract(verification=[read_it]))
    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py":
         "def app():\n    '''new'''\n    return 1\n"}))
    assert result.outcome == "READY_FOR_REVIEW", result.reason


# ---- the output ceiling ---------------------------------------------------
#
# The cap the runner hands the agent used to be `max_cost_gbp` converted to
# dollars. It described no account -- these runs are subscription usage, not
# billed calls -- and on 21 Sep it deleted task 140 at 35,441 output tokens,
# a run of ordinary size. The backstop is `max_output_tokens` now, which is
# the unit 049's window ledger already counts in. These cover the runner's
# half: handing the ceiling over, and reading back what it did.

NEW_FILE = {"api/analytics/services/analytics_engine.py":
            "def app():\n    '''new'''\n    return 1\n"}


def test_the_tasks_own_ceiling_is_what_the_agent_runs_under(
        dsns, settings, console, monkeypatch):
    """A ceiling the agent is never told about caps nothing."""
    tid = queue_task(console, max_cost_gbp=3.00)
    seen: dict[str, int | None] = {}
    inner = fake_agent(NEW_FILE)

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_output_tokens=None):
        seen["ceiling"] = max_output_tokens
        return inner(worktree, prompt, timeout_seconds, model=model,
                     allowed_tools=allowed_tools, readable=readable)

    result = run_tick(monkeypatch, invoke)

    assert result.task_id == tid
    assert seen["ceiling"] is not None, "the agent ran with no ceiling at all"
    # The task's own column, not a figure derived from its money cap.
    row = console.execute("SELECT max_output_tokens FROM tasks WHERE id=%s",
                          (tid,)).fetchone()
    assert seen["ceiling"] == row["max_output_tokens"]


def test_no_money_figure_reaches_the_agent(dsns, settings, console,
                                           monkeypatch):
    """The point of the change, asserted at the runner's boundary.

    `max_cost_gbp` is still on the task and still settles the notional ledger.
    What it must not do any more is cross into the run.
    """
    queue_task(console, max_cost_gbp=3.00)
    seen: dict[str, object] = {}
    inner = fake_agent(NEW_FILE)

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_output_tokens=None, **kw):
        seen["kw"] = kw
        seen["prompt"] = prompt
        return inner(worktree, prompt, timeout_seconds, model=model,
                     allowed_tools=allowed_tools, readable=readable)

    run_tick(monkeypatch, invoke)

    assert seen["kw"] == {}, f"an unexpected argument reached invoke: {seen['kw']}"
    for token in ("£", "max_cost", "usd", "GBP"):
        assert token not in str(seen["prompt"]), (
            f"the prompt names {token!r}: a money figure reached the agent")


def test_reaching_the_ceiling_fails_the_task_and_says_why(
        dsns, settings, console, monkeypatch):
    queue_task(console, max_cost_gbp=3.00)

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_output_tokens=None):
        (worktree / "api/analytics/services/analytics_engine.py").write_text(
            "half a change\n")
        return agent_mod.AgentResult(
            exit_code=-15, timed_out=False, duration_ms=900,
            output_capped=True, output_tokens=max_output_tokens,
            text="", cost_usd=None, raw={})

    result = run_tick(monkeypatch, invoke)

    assert result.outcome == "FAILED"
    assert "output ceiling" in result.reason, result.reason
    assert "£" not in result.reason, "the reason still talks money"
    # Distinguishable from the wall clock, which is a different failure.
    assert "wall clock" not in result.reason


def test_a_capped_run_still_counts_against_the_window(
        dsns, settings, console, monkeypatch):
    """049's ledger sums model_calls.completion_tokens.

    A run the runner killed prints no result payload, so without the fallback
    the runs that produced the MOST output would be the ones the window
    counted as zero.
    """
    queue_task(console, max_cost_gbp=3.00)

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_output_tokens=None):
        (worktree / "api/analytics/services/analytics_engine.py").write_text("x\n")
        return agent_mod.AgentResult(
            exit_code=-15, timed_out=False, duration_ms=900,
            output_capped=True, output_tokens=101_337, text="",
            cost_usd=None, raw={})

    run_tick(monkeypatch, invoke)

    from tests import conftest as ct
    with psycopg.connect(ct.FLEET_TEST_DSN) as conn:
        completion, source = conn.execute(
            "SELECT completion_tokens, token_source FROM model_calls"
            " ORDER BY id DESC LIMIT 1").fetchone()
    assert completion == 101_337, completion
    assert source == "transcript", (
        "a figure read from the session JSONL is 048's 'transcript'")


def test_the_cli_figures_still_win_when_the_run_ended_normally(
        dsns, settings, console, monkeypatch):
    """The fallback is for killed runs only; it must not overwrite a real
    reading with the watcher's floor."""
    queue_task(console, max_cost_gbp=3.00)
    run_tick(monkeypatch, fake_agent(NEW_FILE, raw=REAL_SHAPED_RAW,
                                     output_tokens=7))

    from tests import conftest as ct
    with psycopg.connect(ct.FLEET_TEST_DSN) as conn:
        completion, source = conn.execute(
            "SELECT completion_tokens, token_source FROM model_calls"
            " ORDER BY id DESC LIMIT 1").fetchone()
    assert source == "modelUsage"
    assert completion == 964 + 19, "the watcher's floor overwrote the total"


def test_an_unenforceable_ceiling_is_named_in_the_notes(
        dsns, settings, console, monkeypatch):
    """A watcher that died left the run with only the wall clock, and the
    record must say so: an uncapped run and a quiet one look identical."""
    queue_task(console, max_cost_gbp=3.00)

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_output_tokens=None):
        for path, body in NEW_FILE.items():
            (worktree / path).write_text(body)
        return agent_mod.AgentResult(
            exit_code=0, timed_out=False, duration_ms=900,
            watcher_failed="OSError: boom", text="done", cost_usd=0.5,
            raw={"model": "fake"})

    result = run_tick(monkeypatch, invoke)

    notes = " ".join(result.notes)
    assert "THE OUTPUT CEILING WAS NOT ENFORCED" in notes, notes
    assert "OSError: boom" in notes


def test_a_notional_overshoot_is_recorded_and_not_alarmed_about(
        dsns, settings, console, monkeypatch):
    """This is the GBP 8.75-on-GBP 3.00 shape, and it is no longer a breach.

    Nothing was supposed to stop it at GBP 3.00, because GBP 3.00 never
    bounded anything. The reservation is the ledger's upper bound; the true
    figure is still reported.
    """
    queue_task(console, max_cost_gbp=3.00)
    runaway_usd = 8.75 / float(settings["usd_to_gbp"])

    result = run_tick(monkeypatch, fake_agent(NEW_FILE, cost_usd=runaway_usd))

    notes = " ".join(result.notes)
    assert "BREAKER DID NOT FIRE" not in notes, (
        "nothing was breached: no money figure bounds a run")
    assert "£8.75" in notes, "the true figure must still be reported"
    assert result.cost_gbp == pytest.approx(3.00)


#: A payload shaped like the real thing: the top-level block carries the
#: UNCACHED REMAINDER of the input, and `modelUsage` carries the classes.
#: These are the proportions of an actual run -- the cache read is three
#: orders of magnitude larger than the uncached input, which is why reading
#: only the top-level block understated September by 54,000x.
REAL_SHAPED_RAW = {
    "model": "fake",
    "usage": {"input_tokens": 2, "output_tokens": 964,
              "cache_read_input_tokens": 18774,
              "cache_creation_input_tokens": 4380},
    "modelUsage": {
        "claude-opus-5[1m]": {"inputTokens": 2, "outputTokens": 964,
                              "cacheReadInputTokens": 18774,
                              "cacheCreationInputTokens": 4380},
        "claude-haiku-4-5": {"inputTokens": 537, "outputTokens": 19,
                             "cacheReadInputTokens": 0,
                             "cacheCreationInputTokens": 0}},
}


def test_the_classes_are_kept_apart_and_summed_across_every_model():
    c = cycle._model_usage_classes(REAL_SHAPED_RAW)

    # Every model the run billed, not just the one the contract named.
    assert c["input_tokens"] == 2 + 537
    assert c["cache_read_tokens"] == 18774
    assert c["cache_creation_tokens"] == 4380
    assert c["completion_tokens"] == 964 + 19
    # The sum is what `prompt_tokens` has always claimed to be.
    assert c["prompt_tokens"] == 2 + 537 + 18774 + 4380


def test_no_model_usage_is_none_rather_than_zero():
    """None means 'ask something else'; zeros would mean 'the run used none'."""
    assert cycle._model_usage_classes({}) is None
    assert cycle._model_usage_classes({"modelUsage": "not a map"}) is None


def test_an_ordinary_run_records_the_classes_not_the_uncached_remainder(
        dsns, settings, console, monkeypatch):
    """The regression. `usage` is POPULATED here, as it is on every run that
    did not exhaust its budget -- and it must still lose to `modelUsage`.

    Until 17 Sep 2026 the top-level block won whenever it was non-empty, so
    this row would have stored prompt_tokens=2: the uncached remainder, with
    the 18,774 cache reads and 4,380 cache writes discarded.
    """
    import psycopg
    from tests import conftest as ct

    queue_task(console, max_cost_gbp=3.00)

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_output_tokens=None):
        (worktree / "api/analytics/services/analytics_engine.py").write_text(
            "def app():\n    '''new'''\n    return 1\n")
        return agent_mod.AgentResult(
            exit_code=0, timed_out=False, duration_ms=900,
            text="done", cost_usd=0.10, raw=REAL_SHAPED_RAW)

    run_tick(monkeypatch, invoke)

    with psycopg.connect(ct.FLEET_TEST_DSN) as conn:
        row = conn.execute(
            "SELECT input_tokens, cache_read_tokens, cache_creation_tokens,"
            "       prompt_tokens, completion_tokens, token_source"
            "  FROM model_calls ORDER BY id DESC LIMIT 1").fetchone()

    assert row is not None, "the tick recorded no model call"
    inp, cread, cwrite, prompt, completion, source = row
    assert source == "modelUsage", "the weak path won"
    assert (inp, cread, cwrite) == (2 + 537, 18774, 4380)
    assert completion == 964 + 19
    assert prompt == inp + cread + cwrite, "048's CHECK is the same sum"
    assert prompt != 2, "this is the defect: the uncached remainder alone"


# ---------------------------------------------------------------------------
# The provider refusing to run is not the task failing.
#
# Usage credits are off on the account these runs authenticate as and the
# balance is zero, so there is no spend path past the plan's weekly window:
# the request is refused and the run stops where it stands. A task must not
# spend an attempt on that -- task 120 ran at 1/1, and one refusal would have
# exhausted it over work nobody judged.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload,text,expect", [
    ({"api_error_status": 429}, "", "HTTP 429"),
    ({"subtype": "usage_limit_reached"}, "", "usage_limit_reached"),
    ({"terminal_reason": "rate_limit_error"}, "", "rate_limit_error"),
    ({}, "You've hit your weekly limit. Resets Sunday.", "weekly limit"),
    ({}, "you've hit your session limit", "session limit"),
])
def test_a_usage_window_refusal_is_recognised(payload, text, expect):
    reason = agent_mod.classify_could_not_run(payload, text)
    assert reason is not None, "the refusal was not recognised"
    assert expect in reason, reason


@pytest.mark.parametrize("payload,text", [
    ({}, ""),
    ({"api_error_status": 500}, "internal server error"),
    ({"api_error_status": 400}, "bad request"),
    ({"subtype": "error_max_budget_usd"}, "budget exhausted"),
    ({"is_error": True}, "the tests failed and I could not fix them"),
    ({"stop_reason": "end_turn"}, "I hit a wall on the weekly report feature"),
])
def test_an_ordinary_failure_is_not_mistaken_for_one(payload, text):
    """A false positive requeues a genuinely failing task forever, so this
    direction matters more than recall."""
    assert agent_mod.classify_could_not_run(payload, text) is None


def test_the_output_ceiling_outranks_it():
    """fleet's own ceiling is a verdict about the run. The provider declining
    to run is not. If both look true, the ceiling wins."""
    result = agent_mod.AgentResult(
        exit_code=-15, timed_out=False, duration_ms=1,
        output_capped=True, could_not_run=None)
    assert not result.ok


def test_a_refused_run_requeues_and_refunds_the_attempt(
        dsns, settings, console, monkeypatch):
    tid = queue_task(console, max_attempts=1)

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_output_tokens=None):
        return agent_mod.AgentResult(
            exit_code=1, timed_out=False, duration_ms=400, cost_usd=0.02,
            text="You've hit your weekly limit.",
            could_not_run="the provider said 'hit your weekly limit'",
            raw={"model": "fake"})

    result = run_tick(monkeypatch, invoke)

    row = console.execute(
        "SELECT status, attempts FROM tasks WHERE id=%s", (tid,)).fetchone()
    # QUEUED, not FAILED: max_attempts is 1 and the attempt was handed back,
    # so the task is claimable again rather than exhausted.
    assert row["status"] == "QUEUED", row
    assert row["attempts"] == 0, "the attempt was not refunded"
    assert result.requeued is True
    assert "could not run" in (result.reason or ""), result.reason
    assert "weekly limit" in (result.reason or ""), result.reason


# ---------------------------------------------------------------------------
# Observed, not enforced. A ceiling at p90 would have cut 9 failures and 5
# verified runs out of 95, so the size signal reports and does not fire.
# ---------------------------------------------------------------------------

def test_the_transcript_directory_is_derived_from_the_worktree():
    d = agent_mod.transcript_dir(Path("/home/ubuntu/.fleet-worktrees/fleet-task-120"))
    assert d.name == "-home-ubuntu--fleet-worktrees-fleet-task-120"


def test_every_separator_the_cli_collapses_is_collapsed_here_too():
    """A path this gets wrong is a run with NO CEILING.

    The underscore was missing until 22 Sep 2026 and cost nothing, because
    this only reported and no fleet worktree path carries one. It is the
    backstop now: the watcher reads an empty directory, counts nothing, and
    the run is bounded only by its wall clock. Found by running the real CLI
    in a `mkdtemp` directory named `real-stopped-h9d6_4yk`.
    """
    d = agent_mod.transcript_dir(Path("/tmp/a_b/c.d/e-f"))
    assert d.name == "-tmp-a-b-c-d-e-f"
    assert "_" not in d.name and "." not in d.name


def _write_turn(fh, mid, out_tokens, blocks=1):
    """One turn, written as `blocks` records that repeat the same usage --
    which is how the CLI writes a multi-block message."""
    import json as _json
    for _ in range(blocks):
        fh.write(_json.dumps({
            "type": "assistant",
            "message": {"id": mid, "model": "claude-opus-5",
                        "usage": {"output_tokens": out_tokens,
                                  "input_tokens": 1,
                                  "cache_read_input_tokens": 10}}}) + "\n")
    fh.flush()


def _transcript_dir_for(worktree):
    """ASK THE FUNCTION WHERE IT WILL LOOK; never restate the rule.

    These tests spelled the mangling out by hand until 22 Sep 2026, and when
    `transcript_dir` gained the underscore the CLI had always collapsed, they
    wrote the transcript to one directory while the watcher read another. With
    no ceiling and a `stop` the test never sets, the watcher then span at one
    poll per 15s and the run hung rather than failed.
    """
    d = agent_mod.transcript_dir(worktree)
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_a_run_past_p90_is_reported_once_and_counts_turns_not_records(
        tmp_path, monkeypatch):
    import threading as _th
    worktree = tmp_path / "wt"
    worktree.mkdir()
    monkeypatch.setattr(agent_mod.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(agent_mod, "WATCH_INTERVAL_SECONDS", 0.05)
    target = _transcript_dir_for(worktree)

    per_turn = agent_mod.NOTABLE_OUTPUT_TOKENS // 2 + 1
    with (target / "sess.jsonl").open("w") as fh:
        # Each turn written three times over, as a three-block message is.
        _write_turn(fh, "msg_a", per_turn, blocks=3)
        _write_turn(fh, "msg_b", per_turn, blocks=3)

    seen = []
    stop = _th.Event()
    agent_mod._watch_output_tokens(
        worktree, 0.0, stop, lambda tok, turns: seen.append((tok, turns)))

    assert len(seen) == 1, "reported more than once"
    tokens, turns = seen[0]
    assert turns == 2, "records were counted instead of messages"
    assert tokens == per_turn * 2


def test_a_run_below_the_threshold_reports_nothing(tmp_path, monkeypatch):
    import threading as _th
    worktree = tmp_path / "wt"
    worktree.mkdir()
    monkeypatch.setattr(agent_mod.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(agent_mod, "WATCH_INTERVAL_SECONDS", 0.05)
    target = _transcript_dir_for(worktree)
    with (target / "sess.jsonl").open("w") as fh:
        _write_turn(fh, "msg_a", 100)

    seen = []
    stop = _th.Event()
    stop.set()          # one pass, then stop
    agent_mod._watch_output_tokens(
        worktree, 0.0, stop, lambda tok, turns: seen.append(tok))
    assert seen == []


def test_a_broken_transcript_never_breaks_the_run(tmp_path, monkeypatch):
    """The watcher observes a run; it must not be able to end one."""
    import threading as _th
    monkeypatch.setattr(agent_mod.Path, "home",
                        staticmethod(lambda: (_ for _ in ()).throw(OSError("boom"))))
    stop = _th.Event()
    agent_mod._watch_output_tokens(  # must not raise
        tmp_path, 0.0, stop, lambda *a: None)


def test_a_window_refusal_is_an_idle_with_a_reason_and_not_a_crash(
        dsns, settings, console, admin, monkeypatch):
    """049's ceiling is a trigger, so a declined claim arrives as an exception
    from the UPDATE. `_claim` runs in a try whose only clause is `finally`, so
    before this it escaped tick() entirely -- and chain.py would have spent its
    pass ceiling re-raising once per pass.

    There is work and it may not start yet. That is an idle with a reason, not
    a fault.
    """
    queue_task(console, max_cost_gbp=3.00)
    admin.execute(
        "INSERT INTO model_window_target (output_tokens_per_week, set_by,"
        " effective_from, rationale) VALUES (1, 'test', now(), 'test')")
    admin.commit()

    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "x\n"}))

    assert result.outcome == "IDLE"
    assert "usage window" in result.reason, result.reason
    assert result.task_id is None, "a refused claim must not name a task"


def test_a_contract_refusal_still_surfaces_rather_than_idling(
        dsns, settings, console, admin, monkeypatch):
    """THE NARROWNESS OF THE CATCH, which is the part worth guarding.

    The contract floor, the transition rules and the queue depth all raise the
    same exception type from the same table, and each of those IS a fault in
    the caller. A catch that swallowed them would turn a bug into a quiet idle
    night -- a check that cannot fail, which is the defect this codebase keeps
    naming.
    """
    from runner import cycle as cycle_mod

    class Boom(psycopg.errors.RaiseException):
        pass

    def exploding_claim(runner, queue, only_task, log):
        raise Boom("contract for x does not protect y")

    monkeypatch.setattr(cycle_mod, "_claim", exploding_claim)
    queue_task(console)

    with pytest.raises(psycopg.errors.RaiseException, match="does not protect"):
        run_tick(monkeypatch, fake_agent())


# ---------------------------------------------------------------------------
# 052: the third instance. A run that judged nothing is not the task failing,
# and the discriminator is the DECLARED refusal rather than the empty diff.
# ---------------------------------------------------------------------------

REFUSAL_REPLY = (
    "I am stopping rather than editing the protected suite.\n\n"
    '```json\n{"refused": "the signature assertion still forbids a columns '
    'parameter and api/tests/** is protected"}\n```\n')


def test_a_declared_refusal_is_read_out_of_the_reply_block():
    """The same fenced block `changed_files` uses -- not a second protocol."""
    assert agent_mod.parse_refusal(REFUSAL_REPLY).startswith(
        "the signature assertion")
    assert agent_mod.parse_refusal("I gave up, sorry") is None
    assert agent_mod.parse_refusal('```json\n{"changed_files": []}\n```') is None


def test_an_empty_diff_without_a_declared_refusal_is_still_a_failure(
        dsns, settings, console, monkeypatch):
    """THE NARROWNESS. An agent that tried and produced nothing HAS judged the
    work. Only a declared refusal is forgiven, never the empty diff itself."""
    tid = queue_task(console, max_attempts=1)

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_output_tokens=None):
        return agent_mod.AgentResult(
            exit_code=0, timed_out=False, duration_ms=900, cost_usd=0.02,
            text="I could not work out how to do this.", raw={"model": "fake"})

    result = run_tick(monkeypatch, invoke)

    assert result.outcome == "FAILED"
    assert "changed nothing" in (result.reason or "")
    row = console.execute("SELECT status, attempts FROM tasks WHERE id=%s",
                          (tid,)).fetchone()
    assert row["status"] == "FAILED" and row["attempts"] == 1


def test_a_refusal_on_instruction_requeues_and_refunds(
        dsns, settings, console, monkeypatch):
    """TASK 125'S SHAPE. Its spec told the agent to stop and explain rather
    than edit the suite that judges it; doing so produced an empty diff and
    scored identically to giving up."""
    tid = queue_task(console, max_attempts=1)

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_output_tokens=None):
        return agent_mod.AgentResult(
            exit_code=0, timed_out=False, duration_ms=64_000, cost_usd=0.02,
            text=REFUSAL_REPLY, refused="the signature assertion still forbids it",
            raw={"model": "fake"})

    result = run_tick(monkeypatch, invoke)

    assert result.outcome == "COULD_NOT_RUN", result.reason
    assert "declined and said why" in (result.reason or "")
    row = console.execute("SELECT status, attempts FROM tasks WHERE id=%s",
                          (tid,)).fetchone()
    assert row["status"] == "QUEUED", "a refusal on instruction exhausted the task"
    assert row["attempts"] == 0
    # and the run says so in a column, not in the wording of a sentence
    assert console.execute(
        "SELECT unjudged_reason FROM runs WHERE task_id=%s ORDER BY id DESC"
        " LIMIT 1", (tid,)).fetchone()["unjudged_reason"]


def test_the_refund_stops_at_the_ceiling(dsns, settings, console, monkeypatch):
    """An agent refusing on a precondition nobody satisfies would otherwise be
    requeued forever, and each refusal costs a run and a worktree."""
    ceiling = console.execute(
        "SELECT fleet_unjudged_refund_ceiling() AS n").fetchone()["n"]
    tid = queue_task(console, max_attempts=1)

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_output_tokens=None):
        return agent_mod.AgentResult(
            exit_code=0, timed_out=False, duration_ms=900, cost_usd=0.02,
            text=REFUSAL_REPLY, refused="the precondition is still unmet",
            raw={"model": "fake"})

    for _ in range(ceiling):
        assert run_tick(monkeypatch, invoke).outcome == "COULD_NOT_RUN"
        assert console.execute("SELECT status FROM tasks WHERE id=%s",
                               (tid,)).fetchone()["status"] == "QUEUED"

    run_tick(monkeypatch, invoke)          # one past the ceiling

    assert console.execute("SELECT status FROM tasks WHERE id=%s",
                           (tid,)).fetchone()["status"] == "FAILED", (
        "the refund never stopped; a task that always refuses would loop")


def test_the_two_live_detectors_share_one_answer():
    """052's consolidation: the provider refusing and the agent refusing are
    the same question, asked in one place."""
    provider = agent_mod.AgentResult(
        exit_code=1, timed_out=False, duration_ms=1,
        could_not_run="the provider rate-limited the request (HTTP 429)")
    assert cycle._judged_the_work(provider, None)

    class _Empty:
        empty = True

    declined = agent_mod.AgentResult(
        exit_code=0, timed_out=False, duration_ms=1, refused="a precondition")
    assert cycle._judged_the_work(declined, _Empty())

    # An empty diff on its own is not an answer to the question.
    silent = agent_mod.AgentResult(exit_code=0, timed_out=False, duration_ms=1)
    assert cycle._judged_the_work(silent, _Empty()) is None


# ---------------------------------------------------------------------------
# §9.6: the FAILED path used to discard everything the run knew.
#
# specs/auto-approval.md §9.6, named 10 Sep 2026 and unscheduled every time.
# The failure branch wrote `status` and `completed_at` while the runner held
# `result.reason` and `result.branch`. Five readings were misled by the
# silence -- tasks 21, 34, 49, 50 and 51 -- including "the platform has no
# deploy script" (it had been on main since that morning) and "the candidate
# producer is failing" (both runs produced the documents that became batches
# 9 and 10).
# ---------------------------------------------------------------------------


class _FakeRunner:
    """Captures the SQL a settle would run. Enough to assert on columns."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), tuple(params)))

    def sql_for(self, table: str) -> tuple[str, tuple] | None:
        for sql, params in self.calls:
            if sql.startswith(f"UPDATE {table}"):
                return sql, params
        return None


def _settle(tmp_path, outcome, reason, branch, *, make_branch, attempts=1,
            max_attempts=1):
    """Run _settle_task against a real git repo, so the branch test is real."""
    import subprocess
    from runner import cycle

    repo_root = tmp_path / "repos"
    repo = repo_root / "fleet"
    repo.mkdir(parents=True)
    for args in (("init", "-q", "."), ("config", "user.email", "t@t"),
                 ("config", "user.name", "t")):
        subprocess.run(("git", "-C", str(repo)) + args, check=True,
                       capture_output=True)
    (repo / "a.txt").write_text("x")
    subprocess.run(("git", "-C", str(repo), "add", "-A"), check=True,
                   capture_output=True)
    subprocess.run(("git", "-C", str(repo), "commit", "-qm", "base"),
                   check=True, capture_output=True)
    if make_branch:
        subprocess.run(("git", "-C", str(repo), "branch", branch), check=True,
                       capture_output=True)

    result = cycle.TickResult(task_id=1, run_id=7, outcome=outcome,
                              reason=reason, branch=branch)
    runner = _FakeRunner()
    cycle._settle_task(
        runner, {"id": 1, "repo": "fleet", "attempts": attempts,
                 "max_attempts": max_attempts},
        {"repo_root": str(repo_root)}, result, lambda *_a, **_k: None)
    return runner, result


class TestAFailedRunKeepsWhatItKnew:
    def test_the_reason_is_written_on_failure(self, tmp_path):
        runner, _ = _settle(tmp_path, "FAILED", "verification failed",
                            "fleet/task-1", make_branch=True)
        sql, params = runner.sql_for("runs")
        assert "reason=%s" in sql
        assert "verification failed" in params

    def test_the_reason_is_written_on_success_too(self, tmp_path):
        """A column that is NULL for success is a second encoding of status,
        and the first reader to treat NULL as "fine" would be right until a
        failure forgot to write it."""
        runner, _ = _settle(tmp_path, "READY_FOR_REVIEW", "verified, branch "
                            "ready", "fleet/task-1", make_branch=True)
        sql, params = runner.sql_for("runs")
        assert "reason=%s" in sql
        assert "verified, branch ready" in params

    def test_the_branch_is_recorded_on_the_failed_path(self, tmp_path):
        """Task 49 pushed its branch and died at the next step, so origin
        held verified work that nothing in the system pointed at."""
        runner, _ = _settle(tmp_path, "FAILED", "boom", "fleet/task-1",
                            make_branch=True)
        sql, params = runner.sql_for("tasks")
        assert "status='FAILED'" in sql and "branch_name=%s" in sql
        assert "fleet/task-1" in params

    def test_a_branch_that_was_never_cut_is_not_recorded(self, tmp_path):
        """`result.branch` is assigned BEFORE worktree.create runs, so it is
        a name and not evidence. Recording it would be a new false statement
        of exactly the kind §9.6 exists to end."""
        runner, result = _settle(tmp_path, "FAILED", "died early",
                                 "fleet/task-1", make_branch=False)
        sql, params = runner.sql_for("tasks")
        assert "branch_name=%s" in sql
        assert params[0] is None
        assert any("never cut" in n for n in result.notes)

    def test_a_requeued_attempt_records_the_branch_it_left(self, tmp_path):
        runner, _ = _settle(tmp_path, "FAILED", "retrying", "fleet/task-1",
                            make_branch=True, attempts=1, max_attempts=3)
        sql, params = runner.sql_for("tasks")
        assert "status='QUEUED'" in sql and "branch_name=%s" in sql
        assert "fleet/task-1" in params

    def test_the_branch_check_asks_git_and_not_the_result(self, tmp_path):
        """§9.6's own rule: ask the tree, not the row."""
        from runner import cycle
        repo = tmp_path / "r"
        repo.mkdir()
        assert cycle._branch_exists(repo, "fleet/task-1") is False
        assert cycle._branch_exists(repo, None) is False
        assert cycle._branch_exists(repo, "") is False
