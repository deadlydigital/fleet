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
    "platform/app/page.tsx": "export default () => null\n",
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
                           "platform/app/**"],
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
               cost_usd: float = 0.10, deletes: list[str] | None = None):
    """An agent that writes exactly what it is told to, and says what it likes."""
    def invoke(worktree: Path, prompt, timeout_seconds, model=None,
               allowed_tools=(), readable=(), max_cost_usd=None):
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
            reported_paths=agent_mod.parse_report(text), raw={"model": "fake"})
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
               readable=(), max_cost_usd=None):
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


# ---- the spend cap --------------------------------------------------------
#
# The runner cannot see money mid-run -- the CLI reports cost only in its
# terminal payload -- so enforcement is delegated to the CLI's own
# --max-budget-usd. These cover the runner's half: deriving the cap from the
# reservation, and telling apart a cap that fired from one that did not.

def test_the_reservation_becomes_the_cli_spend_cap(dsns, settings, console,
                                                   monkeypatch):
    """A reservation the agent is never told about caps nothing."""
    tid = queue_task(console, max_cost_gbp=3.00)
    seen: dict[str, float | None] = {}
    inner = fake_agent({"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"})

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_cost_usd=None):
        seen["cap"] = max_cost_usd
        return inner(worktree, prompt, timeout_seconds, model=model,
                     allowed_tools=allowed_tools, readable=readable)

    result = run_tick(monkeypatch, invoke)

    assert result.task_id == tid
    assert seen["cap"] is not None, "the agent ran with no spend cap at all"
    # £3.00 at the settings' stated rate, in the currency the CLI caps in.
    assert seen["cap"] == pytest.approx(3.00 / float(settings["usd_to_gbp"]))


def test_reaching_the_cap_fails_the_task_and_says_why(dsns, settings, console,
                                                      monkeypatch):
    queue_task(console, max_cost_gbp=3.00)

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_cost_usd=None):
        (worktree / "api/analytics/services/analytics_engine.py").write_text("half a change\n")
        return agent_mod.AgentResult(
            exit_code=1, timed_out=False, duration_ms=900,
            budget_exhausted=True, text="", cost_usd=4.20,
            raw={"model": "fake", "subtype": "error_max_budget_usd"})

    result = run_tick(monkeypatch, invoke)

    assert result.outcome == "FAILED"
    assert "spend cap" in result.reason, result.reason
    # Distinguishable from the wall clock, which is a different failure.
    assert "wall clock" not in result.reason


def test_an_overshoot_with_the_cap_fired_is_reported_as_expected(
        dsns, settings, console, monkeypatch):
    """The cap gates between turns, so one turn of overshoot is normal."""
    queue_task(console, max_cost_gbp=3.00)
    over_usd = 3.20 / float(settings["usd_to_gbp"])

    def invoke(worktree, prompt, timeout_seconds, model=None, allowed_tools=(),
               readable=(), max_cost_usd=None):
        (worktree / "api/analytics/services/analytics_engine.py").write_text("x\n")
        return agent_mod.AgentResult(
            exit_code=1, timed_out=False, duration_ms=900,
            budget_exhausted=True, text="", cost_usd=over_usd,
            raw={"model": "fake"})

    result = run_tick(monkeypatch, invoke)

    notes = " ".join(result.notes)
    assert "the cap fired and stopped it" in notes, notes
    assert "BREAKER DID NOT FIRE" not in notes
    assert result.cost_gbp == pytest.approx(3.00), "settled above the cap"


def test_an_overshoot_with_no_exhaustion_is_named_as_a_dead_breaker(
        dsns, settings, console, monkeypatch):
    """This is the £8.75-on-£3.00 shape, and it must not read as routine."""
    queue_task(console, max_cost_gbp=3.00)
    runaway_usd = 8.75 / float(settings["usd_to_gbp"])

    result = run_tick(monkeypatch, fake_agent(
        {"api/analytics/services/analytics_engine.py": "def app():\n    '''new'''\n    return 1\n"},
        cost_usd=runaway_usd))

    notes = " ".join(result.notes)
    assert "BREAKER DID NOT FIRE" in notes, notes
    assert "--max-budget-usd" in notes, "the note must say what to check"
    assert "£8.75" in notes, "the true figure must still be reported"
    assert result.cost_gbp == pytest.approx(3.00)


def test_model_usage_is_the_token_source_when_usage_is_zeroed():
    """A budget-exhausted payload zeroes `usage` but keeps `modelUsage`."""
    raw = {"usage": {"input_tokens": 0, "output_tokens": 0, "iterations": []},
           "modelUsage": {
               "claude-opus-5[1m]": {"inputTokens": 2, "outputTokens": 964,
                                     "cacheReadInputTokens": 18774,
                                     "cacheCreationInputTokens": 4380},
               "claude-haiku-4-5": {"inputTokens": 537, "outputTokens": 19,
                                    "cacheReadInputTokens": 0,
                                    "cacheCreationInputTokens": 0}}}

    prompt, completion = cycle._model_usage_totals(raw)

    # Every model the run billed, not just the one the contract named.
    assert prompt == 2 + 18774 + 4380 + 537
    assert completion == 964 + 19
    assert cycle._model_usage_totals({}) == (0, 0)
