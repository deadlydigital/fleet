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
    contract = {"writable_paths": ["api/app.py"],
                "protected_paths": ["api/tests/**"],
                "max_diff_lines": 800}
    prompt = agent.build_prompt(task, contract)
    assert "# do it" in prompt
    assert "api/tests/**" in prompt
    assert "Do not commit anything" in prompt
    # The prompt says plainly that it is not what decides.
    assert "derives the real diff from git" in prompt
