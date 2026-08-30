"""Invoking the coding agent, and stopping it.

The timeout is enforced here, by the runner, and never by asking the agent to
mind the clock. A stuck agent burning budget in a loop is the failure mode
this guards, and an agent that is stuck is by definition not going to notice
that it is.

The kill is against the process group, not the child: the CLI spawns its own
children, and terminating only the process the runner can see leaves them
running with the budget already spent.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TOOLS = ("Read", "Edit", "Write", "Grep", "Glob")

# Overridable so the timeout can be tested against a process that is
# guaranteed to hang, and so production can pin an absolute path rather than
# whatever `claude` resolves to on PATH.
CLAUDE_BIN = os.environ.get("FLEET_CLAUDE_BIN", "claude")

REPORT_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


@dataclass
class AgentResult:
    exit_code: int
    timed_out: bool
    duration_ms: int
    text: str = ""
    cost_usd: float | None = None
    num_turns: int | None = None
    session_id: str | None = None
    reported_paths: list[str] | None = None
    stderr: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def build_prompt(task: dict, contract: dict) -> str:
    """The spec, plus the boundary stated plainly.

    The contract is in the prompt so the agent can succeed, not so the runner
    can rely on it having read it. Everything here is re-derived from git
    afterwards; this text buys a better first attempt, nothing more.
    """
    writable = "\n".join(f"  - {p}" for p in contract["writable_paths"])
    protected = "\n".join(f"  - {p}" for p in contract["protected_paths"])
    return f"""{task['spec_md']}

---

## The boundary for this task

You may edit only these paths:

{writable}

You must not edit these paths under any circumstances:

{protected}

The test suite and the migrations are on that second list. Do not edit tests
to make them pass, and do not change any migration. If the task appears to
require editing a protected path, stop and say so instead: a branch that
explains why it could not be done is useful, and one that quietly widened its
own boundary is not.

Keep the whole change under {contract['max_diff_lines']} changed lines.
Do not commit anything. Do not create branches. Do not run git.

When you are finished, end your reply with a JSON block listing every file
you changed, relative to the repository root:

```json
{{"changed_files": ["path/one.py", "path/two.tsx"]}}
```

That list is recorded but is not what decides whether the branch is accepted.
The runner derives the real diff from git and judges that.
"""


def parse_report(text: str) -> list[str] | None:
    """The agent's account of what it changed, if it gave one."""
    for match in reversed(list(REPORT_RE.finditer(text or ""))):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        files = payload.get("changed_files")
        if isinstance(files, list) and all(isinstance(f, str) for f in files):
            return files
    return None


def invoke(worktree: Path, prompt: str, timeout_seconds: int,
           model: str | None = None,
           allowed_tools: tuple[str, ...] = DEFAULT_TOOLS) -> AgentResult:
    """Run the agent in the worktree under a hard wall clock."""
    cmd = [
        os.environ.get("FLEET_CLAUDE_BIN", CLAUDE_BIN), "-p", prompt,
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--add-dir", str(worktree),
        "--allowedTools", *allowed_tools,
    ]
    if model:
        cmd += ["--model", model]

    started = time.monotonic()
    proc = subprocess.Popen(
        cmd, cwd=str(worktree),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True)

    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        out, err = proc.communicate()

    duration_ms = int((time.monotonic() - started) * 1000)
    result = AgentResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        timed_out=timed_out,
        duration_ms=duration_ms,
        stderr=(err or "")[-4000:],
    )

    try:
        payload = json.loads(out) if out else {}
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict):
        result.raw = payload
        result.text = payload.get("result") or ""
        result.cost_usd = payload.get("total_cost_usd")
        result.num_turns = payload.get("num_turns")
        result.session_id = payload.get("session_id")
    if not result.text:
        result.text = (out or "")[-8000:]
    result.reported_paths = parse_report(result.text)
    return result


def _kill_group(proc: subprocess.Popen) -> None:
    """TERM the group, then KILL what is left.

    A plain proc.kill() would leave the CLI's children running: they were
    started in the same new session, which is why the runner asked for one.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    for sig, grace in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 0.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        if grace:
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    return
                time.sleep(0.1)
