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


class TestThePromptCarriesATargetNotTheBound:
    """12 Sep 2026. The figure in the prompt is an anchor the output lands on.

    Task 69, same spec and same base, three times: told 300 it wrote 377, told
    600 it wrote 606, told 300 again it wrote 439 -- and that last one passed
    every check including new_test_bites.sh. Task 67 landed at 298 of 300. The
    told figure shapes the test and cannot bound it, so `test_diff_target` is
    the number the prompt carries and `max_test_diff_lines` became a runaway
    bound the agent is never shown.
    """

    #: The real shape: a target three times under the bound. max_diff_lines is
    #: deliberately neither, so any 1200 in the prompt could only be the bound.
    CONTRACT = {
        "writable_paths": ["api/analytics/routes/orders.py"],
        "protected_paths": ["api/tests/**"],
        "creatable_paths": ["api/tests/analytics/test_fleet_*.py"],
        "max_diff_lines": 500,
        "test_diff_target": 300,
        "max_test_diff_lines": 1200,
    }

    def test_the_target_is_named_and_the_bound_is_not(self):
        prompt = agent.build_prompt({"spec_md": "# do it"}, self.CONTRACT)
        assert "own budget of about 300 lines" in prompt
        # NAMING BOTH WOULD PUT THE ANCHOR BACK ON THE LARGER NUMBER, which is
        # the finding the whole arrangement rests on -- and the larger number
        # is now four times the target, so it would be a disaster rather than
        # a drift.
        assert "1200" not in prompt

    def test_it_says_the_target_is_not_a_hard_edge(self):
        """An agent that reads a target as a gate rations the test, which is
        the failure the split budget was built to end."""
        prompt = agent.build_prompt({"spec_md": "# do it"}, self.CONTRACT)
        assert "target rather than a hard edge" in prompt
        assert "padding" in prompt

    def test_the_target_is_the_contracts_and_not_a_fraction_of_the_bound(self):
        """The bound is chosen NOT to bind, so a fraction of it means nothing.
        0.75 * 1200 would anchor the agent at 900."""
        assert agent.test_target(self.CONTRACT) == 300

    def test_a_row_frozen_before_the_field_existed_still_gets_a_figure(self):
        """Task 69's own task row is one of these, so the fallback is a live
        path rather than a courtesy."""
        legacy = {k: v for k, v in self.CONTRACT.items()
                  if k != "test_diff_target"} | {"max_test_diff_lines": 400}
        assert agent.test_target(legacy) == 300
        prompt = agent.build_prompt({"spec_md": "# do it"}, legacy)
        assert "own budget of about 300 lines" in prompt

    def test_a_contract_with_neither_says_nothing_about_a_test_budget(self):
        assert agent.test_target({"max_diff_lines": 400}) == 0

    def test_a_contract_without_a_test_budget_is_untouched(self):
        prompt = agent.build_prompt(
            {"spec_md": "# do it"},
            {"writable_paths": ["api/analytics/routes/orders.py"],
             "protected_paths": ["api/tests/**"], "max_diff_lines": 400})
        assert "Keep the whole change under 400 changed lines" in prompt


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

    # AND IT AGREES IN THE OTHER DIRECTION TOO, which is the half that was
    # never tested: the contract declared two paired groups until 10 Sep 2026
    # and this asserted the prompt named their files. Both groups are gone --
    # contracts/checks/proxy_passthrough.py replaced them -- so what must hold
    # now is that the prompt does NOT tell the agent two files move together
    # when nothing refuses it for landing one. A prompt carrying a rule the
    # contract no longer holds is how an agent spends a run on a constraint
    # that does not exist.
    if contract.get("paired_paths"):
        assert "change together, or not at all" in prompt
        for group in contract["paired_paths"]:
            for path in group["paths"]:
                assert path in prompt
    else:
        assert "change together" not in prompt
        assert not any("paired_paths.py" in v for v in contract["verification"])
        assert any("proxy_passthrough.py" in v for v in contract["verification"])


# ---- the output ceiling ---------------------------------------------------
#
# THE CAP USED TO BE THE CLI'S AND USED TO BE MONEY. It is neither now: there
# is no flag that bounds output tokens, and the money figure that was passed
# described an account nobody holds -- so the runner counts the transcript
# itself and kills the group. What is tested here is that it does, that it
# says so, and that it no longer hands the CLI a price.

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


def _transcript_for(worktree: Path) -> Path:
    """Where the CLI would write this worktree's session, under a fake HOME."""
    d = agent.transcript_dir(worktree)
    d.mkdir(parents=True, exist_ok=True)
    return d / "sess.jsonl"


def _turn(mid: str, out_tokens: int) -> str:
    import json as _json
    return _json.dumps({"type": "assistant", "message": {
        "id": mid, "usage": {"output_tokens": out_tokens}}}) + "\n"


def test_no_money_figure_is_passed_to_the_cli(tmp_path, monkeypatch):
    """THE REGRESSION THIS EXISTS TO STOP.

    --max-budget-usd was derived from `max_cost_gbp` and it stopped task 140
    at 35,441 output tokens over GBP 2.50 of money nobody was charged. The
    flag going away is the fix; this is what keeps it away, because the next
    person to want a per-task backstop will find a flag named for one.
    """
    seen = tmp_path / "argv"
    script = _fake_claude(
        tmp_path, "echo-claude",
        f'printf "%s\\n" "$@" > {seen}\necho \'{{"result":"ok"}}\'')
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    agent.invoke(tmp_path, "prompt", timeout_seconds=30,
                 max_output_tokens=100_000)

    argv = seen.read_text()
    assert "--max-budget-usd" not in argv, argv
    assert "usd" not in argv.lower(), f"a currency reached the agent: {argv}"


def test_crossing_the_ceiling_stops_the_run_and_says_so(tmp_path, monkeypatch):
    """The whole mechanism, against a CLI that would otherwise never stop."""
    monkeypatch.setattr(agent.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(agent, "WATCH_INTERVAL_SECONDS", 0.2)
    worktree = tmp_path / "wt"
    worktree.mkdir()
    transcript = _transcript_for(worktree)
    # A CLI that writes two turns and then runs forever. The wall clock is far
    # away, so if the ceiling does not fire, nothing stops this.
    script = _fake_claude(
        tmp_path, "runaway-claude",
        f"cat > {transcript} <<'EOF'\n{_turn('msg_a', 600)}{_turn('msg_b', 600)}EOF\n"
        f"sleep 600")
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    result = agent.invoke(worktree, "prompt", timeout_seconds=120,
                          max_output_tokens=1000)

    assert result.output_capped, "the ceiling did not fire"
    assert result.output_tokens == 1200, result.output_tokens
    assert not result.ok, "a run stopped for running away is not ok"
    assert not result.timed_out, "the wall clock is a different failure"
    assert result.duration_ms < 60_000, "it ran to the wall clock instead"


def test_a_run_inside_the_ceiling_is_not_capped_and_is_still_counted(
        tmp_path, monkeypatch):
    monkeypatch.setattr(agent.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(agent, "WATCH_INTERVAL_SECONDS", 0.2)
    worktree = tmp_path / "wt"
    worktree.mkdir()
    transcript = _transcript_for(worktree)
    script = _fake_claude(
        tmp_path, "fine-claude",
        f"cat > {transcript} <<'EOF'\n{_turn('msg_a', 500)}EOF\n"
        f"sleep 1\necho '{{\"result\":\"done\",\"total_cost_usd\":0.01}}'")
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    result = agent.invoke(worktree, "prompt", timeout_seconds=60,
                          max_output_tokens=100_000)

    assert not result.output_capped
    assert result.ok
    assert result.output_tokens == 500, "the count is kept either way"


def test_a_ceiling_that_could_not_be_enforced_is_reported_as_such(
        tmp_path, monkeypatch):
    """A dead watcher is an uncapped run, and must not look like a quiet one."""
    monkeypatch.setattr(agent.Path, "home", staticmethod(
        lambda: (_ for _ in ()).throw(OSError("no home"))))
    monkeypatch.setattr(agent, "WATCH_INTERVAL_SECONDS", 0.2)
    script = _fake_claude(tmp_path, "fine-claude",
                          "sleep 1\necho '{\"result\":\"done\"}'")
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    result = agent.invoke(tmp_path, "prompt", timeout_seconds=60,
                          max_output_tokens=1000)

    assert result.watcher_failed, "the watcher died in silence"
    assert "OSError" in result.watcher_failed
    assert not result.output_capped, "nothing was observed, so nothing fired"


def test_a_cli_budget_payload_no_longer_means_anything(tmp_path, monkeypatch):
    """Belt and braces on the removal.

    Nothing passes --max-budget-usd any more, so the CLI cannot report it
    firing. If a payload saying so ever turns up, it is the CLI's own business
    and not a verdict about the task -- it must not silently become one.
    """
    script = _fake_claude(tmp_path, "broke-claude",
                          f"echo '{BUDGET_EXHAUSTED_PAYLOAD}'\nexit 1")
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    result = agent.invoke(tmp_path, "prompt", timeout_seconds=30,
                          max_output_tokens=100_000)

    assert not result.output_capped
    assert result.cost_usd == 0.0779, "the notional figure is still recorded"


def test_children_are_reaped_when_the_agent_exits_on_its_own(tmp_path,
                                                             monkeypatch):
    """Exiting is not stopping if a tool child is still spending.

    The wall-clock path already guaranteed this. A CLI that ends its own run
    never goes near that path, so the group is reaped after every run rather
    than only after a kill.
    """
    marker = tmp_path / "child.pid"
    script = _fake_claude(
        tmp_path, "leaky-claude",
        f"sleep 3600 &\necho $! > {marker}\n"
        f"echo '{BUDGET_EXHAUSTED_PAYLOAD}'\nexit 1")
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    result = agent.invoke(tmp_path, "prompt", timeout_seconds=30,
                          max_output_tokens=100_000)

    assert not result.ok, "the fake agent exited 1"
    assert marker.exists(), "the fake agent never started its child"
    child_pid = int(marker.read_text().strip())
    assert not alive(child_pid), (
        f"child {child_pid} outlived the agent and kept producing")


def test_the_runner_does_not_signal_its_own_group():
    """The guard that stops a bad pgid taking the whole tick down."""
    assert agent._own_group(os.getpgid(0))
    agent._reap_group(os.getpgid(0))   # must be a no-op, not suicide


def test_a_watcher_that_read_nothing_is_reported_too(tmp_path, monkeypatch):
    """The quieter half of an unenforced ceiling: no crash, no reading, no cap.

    This is what the CLI moving where it writes its transcript would look like
    from inside the runner, and it must not look like a well-behaved run.
    """
    monkeypatch.setattr(agent.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(agent, "WATCH_INTERVAL_SECONDS", 0.2)
    worktree = tmp_path / "wt"
    worktree.mkdir()
    # No transcript is ever written, so the watcher reads an empty directory
    # for the whole run without erroring.
    script = _fake_claude(tmp_path, "silent-claude",
                          "sleep 1\necho '{\"result\":\"done\"}'")
    monkeypatch.setenv("FLEET_CLAUDE_BIN", str(script))

    result = agent.invoke(worktree, "prompt", timeout_seconds=60,
                          max_output_tokens=1000)

    assert not result.output_tokens
    assert result.watcher_failed, "an uncapped run reported nothing wrong"
    assert "nothing was counted" in result.watcher_failed
