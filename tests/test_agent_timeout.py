"""The wall clock, against a process that will not stop on its own.

The agent binary is replaced with a script that spawns a child and then
sleeps far longer than the timeout. That shape is the point: killing only the
process the runner can see would leave the child running with the budget
already spent, which is why the runner starts a new session and signals the
group.
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from runner import agent


@pytest.fixture
def hanging_binary(tmp_path, monkeypatch) -> Path:
    """A fake `claude` that forks a child and sleeps for an hour."""
    marker = tmp_path / "child.pid"
    script = tmp_path / "fake-claude"
    script.write_text(f"""#!/bin/bash
sleep 3600 &
echo $! > {marker}
sleep 3600
""")
    script.chmod(0o755)
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))
    return marker


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def test_a_hanging_agent_is_killed_at_the_deadline(tmp_path, hanging_binary):
    started = time.monotonic()
    result = agent.invoke(tmp_path, "prompt", timeout_seconds=2)
    elapsed = time.monotonic() - started

    assert result.timed_out
    assert not result.ok
    assert elapsed < 20, "the runner waited far past its own deadline"


def test_the_agents_children_are_killed_too(tmp_path, hanging_binary):
    """A kill that leaves grandchildren running has not stopped the spend."""
    agent.invoke(tmp_path, "prompt", timeout_seconds=2)
    time.sleep(0.5)
    assert hanging_binary.exists(), "the fake agent never started its child"
    child_pid = int(hanging_binary.read_text().strip())
    assert not alive(child_pid), f"child {child_pid} survived the timeout"


def test_a_prompt_that_finishes_in_time_is_not_a_timeout(tmp_path, monkeypatch):
    script = tmp_path / "fast-claude"
    script.write_text('#!/bin/bash\necho \'{"result":"done","total_cost_usd":0.01}\'\n')
    script.chmod(0o755)
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))
    result = agent.invoke(tmp_path, "prompt", timeout_seconds=30)
    assert not result.timed_out
    assert result.ok
    assert result.cost_usd == 0.01
    assert result.text == "done"


def test_a_nonzero_exit_is_not_ok(tmp_path, monkeypatch):
    script = tmp_path / "failing-claude"
    script.write_text("#!/bin/bash\nexit 3\n")
    script.chmod(0o755)
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))
    result = agent.invoke(tmp_path, "prompt", timeout_seconds=30)
    assert result.exit_code == 3
    assert not result.ok


# ---- the agent's report ---------------------------------------------------

def test_report_is_parsed_when_given():
    text = 'I changed things.\n```json\n{"changed_files": ["a.py", "b.py"]}\n```'
    assert agent.parse_report(text) == ["a.py", "b.py"]


def test_the_last_report_wins():
    text = ('```json\n{"changed_files": ["old.py"]}\n```\n'
            'actually\n```json\n{"changed_files": ["new.py"]}\n```')
    assert agent.parse_report(text) == ["new.py"]


def test_a_missing_or_malformed_report_is_none():
    assert agent.parse_report("no json here") is None
    assert agent.parse_report("```json\nnot json\n```") is None
    assert agent.parse_report('```json\n{"other": 1}\n```') is None
    assert agent.parse_report("") is None
    assert agent.parse_report(None) is None


def test_the_prompt_states_the_boundary():
    task = {"spec_md": "# do it"}
    contract = {"writable_paths": ["api/analytics/services/analytics_engine.py"],
                "protected_paths": ["api/tests/**"],
                "max_diff_lines": 800}
    prompt = agent.build_prompt(task, contract)
    assert "# do it" in prompt
    assert "api/tests/**" in prompt
    assert "Do not commit anything" in prompt
    # The prompt says plainly that it is not what decides.
    assert "derives the real diff from git" in prompt


def test_the_prompt_states_the_one_file_the_agent_must_add():
    """Without this the prompt CONTRADICTED the gate.

    `platform/__tests__/**` and `api/tests/**` are introduced as paths not to
    edit "under any circumstances", and a contract with creatable_paths runs
    new_test_bites.sh, which refuses a change that adds no test there. An agent
    that believed the absolute sentence could not pass; one that passed had
    disregarded the only line in the prompt written in absolute terms.
    """
    task = {"spec_md": "# do it"}
    contract = {
        "writable_paths": ["platform/app/(dashboard)/analytics/page.tsx"],
        "protected_paths": ["platform/__tests__/**"],
        "creatable_paths": ["platform/__tests__/unit/analytics/test_fleet_*.test.tsx"],
        "max_diff_lines": 600}
    prompt = agent.build_prompt(task, contract)
    assert "platform/__tests__/unit/analytics/test_fleet_*.test.tsx" in prompt
    assert "MUST ADD exactly one new file" in prompt
    # The two properties the gate actually checks, said in the prompt.
    assert "ADD, never modify" in prompt
    assert "Add ONE file, not several" in prompt
    # And why, so an agent knows what makes the test acceptable rather than
    # merely present.
    assert "fails without your change" in prompt


def test_a_contract_with_no_creatable_paths_says_nothing_about_adding_a_test():
    """Every other contract in contracts/ is one of these, and telling those
    agents to add a test would send them at a protected tree for no reason."""
    prompt = agent.build_prompt(
        {"spec_md": "# do it"},
        {"writable_paths": ["api/analytics/routes/orders.py"],
         "protected_paths": ["api/tests/**"], "max_diff_lines": 400})
    assert "MUST ADD" not in prompt


def test_the_prompt_states_paired_paths_with_the_contracts_own_reason():
    """An agent that does not know two files move together lands one of them,
    and paired_paths.py refuses a branch that is otherwise good. That costs a
    whole run to say something the prompt could have said first.

    The `why` is printed rather than summarised: it is the sentence somebody
    wrote about this specific pair, and an agent deciding what "together" means
    needs the reason and not the rule.
    """
    task = {"spec_md": "# do it"}
    contract = {
        "writable_paths": ["platform/app/api/analytics/dashboard/**",
                           "platform/app/(dashboard)/analytics/page.tsx"],
        "protected_paths": ["platform/__tests__/**"],
        "paired_paths": [{
            "why": "widening the proxy alone renders vs previous 366 days over "
                   "a year-on-year comparison",
            "paths": ["platform/app/api/analytics/dashboard/route.ts",
                      "platform/app/(dashboard)/analytics/page.tsx"]}],
        "max_diff_lines": 600}
    prompt = agent.build_prompt(task, contract)
    assert "change together, or not at all" in prompt
    assert "platform/app/api/analytics/dashboard/route.ts" in prompt
    assert "vs previous 366 days" in prompt
    # The instruction for the case where it cannot do both, which is the one an
    # agent would otherwise resolve by landing the easy half.
    assert "Landing the easy half is not" in prompt


def test_a_contract_with_no_paired_paths_says_nothing_about_pairs():
    prompt = agent.build_prompt(
        {"spec_md": "# do it"},
        {"writable_paths": ["api/analytics/routes/orders.py"],
         "protected_paths": ["api/tests/**"], "max_diff_lines": 400})
    assert "change together" not in prompt


def test_the_shipped_frontend_contract_produces_a_prompt_that_agrees_with_itself():
    """The whole point, against the real file rather than a fixture: the
    contract that runs the bite check must tell the agent to write the test,
    and the contract that pairs two files must name them."""
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    contract = yaml.safe_load(
        (root / "contracts" / "dd-analytics-frontend.yaml").read_text())
    prompt = agent.build_prompt({"spec_md": "# do it"}, contract)

    assert any("new_test_bites.sh" in v for v in contract["verification"])
    assert "MUST ADD exactly one new file" in prompt

    assert any("paired_paths.py" in v for v in contract["verification"])
    assert "change together, or not at all" in prompt
    for p in contract["paired_paths"][0]["paths"]:
        assert p in prompt


# ---- the spend cap --------------------------------------------------------
#
# The cap is the CLI's, not the runner's: the CLI reports cost only in its
# terminal payload, so the runner cannot see money mid-run and does not
# pretend to. What is tested here is the runner's half of the contract --
# that it asks for the cap, reads the answer, and leaves nothing running.

BUDGET_EXHAUSTED_PAYLOAD = (
    '{"type":"result","subtype":"error_max_budget_usd","is_error":true,'
    '"terminal_reason":"budget_exhausted","total_cost_usd":0.0779,'
    '"errors":["Reached maximum budget ($0.02)"],'
    '"usage":{"input_tokens":0,"output_tokens":0,"iterations":[]},'
    '"modelUsage":{"claude-opus-5[1m]":{"inputTokens":2,"outputTokens":964,'
    '"cacheReadInputTokens":18774,"cacheCreationInputTokens":4380}}}'
)


def _fake_claude(tmp_path, name, body) -> Path:
    script = tmp_path / name
    script.write_text(f"#!/bin/bash\n{body}\n")
    script.chmod(0o755)
    return script


def test_the_cap_is_passed_to_the_cli(tmp_path, monkeypatch):
    """The runner must actually ask for it; an unset cap caps nothing."""
    seen = tmp_path / "argv"
    script = _fake_claude(
        tmp_path, "echo-claude",
        f'printf "%s\\n" "$@" > {seen}\necho \'{{"result":"ok"}}\'')
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    agent.invoke(tmp_path, "prompt", timeout_seconds=30, max_cost_usd=3.7975)

    argv = seen.read_text().splitlines()
    assert "--max-budget-usd" in argv, argv
    assert argv[argv.index("--max-budget-usd") + 1] == "3.797500"


def test_no_cap_is_passed_when_none_is_given(tmp_path, monkeypatch):
    seen = tmp_path / "argv"
    script = _fake_claude(
        tmp_path, "echo-claude",
        f'printf "%s\\n" "$@" > {seen}\necho \'{{"result":"ok"}}\'')
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    agent.invoke(tmp_path, "prompt", timeout_seconds=30)

    assert "--max-budget-usd" not in seen.read_text().splitlines()


def test_budget_exhaustion_is_read_from_the_payload(tmp_path, monkeypatch):
    script = _fake_claude(tmp_path, "broke-claude",
                          f"echo '{BUDGET_EXHAUSTED_PAYLOAD}'\nexit 1")
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    result = agent.invoke(tmp_path, "prompt", timeout_seconds=30,
                          max_cost_usd=0.02)

    assert result.budget_exhausted
    assert not result.ok, "a run stopped for spending its budget is not ok"
    assert not result.timed_out, "the wall clock is a different failure"
    assert result.cost_usd == 0.0779, "the true figure must survive"


def test_a_clean_run_is_not_budget_exhausted(tmp_path, monkeypatch):
    script = _fake_claude(
        tmp_path, "fine-claude",
        'echo \'{"result":"done","total_cost_usd":0.01,"subtype":"success",'
        '"terminal_reason":"completed"}\'')
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    result = agent.invoke(tmp_path, "prompt", timeout_seconds=30,
                          max_cost_usd=5.0)

    assert not result.budget_exhausted
    assert result.ok


def test_children_are_reaped_when_the_agent_exits_on_its_own(tmp_path,
                                                             monkeypatch):
    """Exiting is not stopping if a tool child is still spending.

    The wall-clock path already guaranteed this. Budget exhaustion is the CLI
    ending its own run, which never goes near that path, so the group is
    reaped after every run rather than only after a kill.
    """
    marker = tmp_path / "child.pid"
    script = _fake_claude(
        tmp_path, "leaky-claude",
        f"sleep 3600 &\necho $! > {marker}\n"
        f"echo '{BUDGET_EXHAUSTED_PAYLOAD}'\nexit 1")
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    result = agent.invoke(tmp_path, "prompt", timeout_seconds=30,
                          max_cost_usd=0.02)

    assert result.budget_exhausted
    assert marker.exists(), "the fake agent never started its child"
    child_pid = int(marker.read_text().strip())
    assert not alive(child_pid), (
        f"child {child_pid} outlived the agent with the budget spent")


def test_the_runner_does_not_signal_its_own_group():
    """The guard that stops a bad pgid taking the whole tick down."""
    assert agent._own_group(os.getpgid(0))
    agent._reap_group(os.getpgid(0))   # must be a no-op, not suicide
