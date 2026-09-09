"""Invoking the coding agent, and stopping it.

Two caps are enforced here, by the runner, and neither by asking the agent to
mind them. A stuck agent burning budget in a loop is the failure mode this
guards, and an agent that is stuck is by definition not going to notice that
it is.

  the wall clock   the runner's own deadline, against communicate().
  the spend cap    --max-budget-usd, which is the CLI's cap, not ours.

The spend cap is delegated deliberately. The CLI reports cost ONLY in its
terminal result payload -- no cost figure streams, and the session transcript
carries none either -- so the runner cannot observe money mid-run at any
price. It could observe tokens under --output-format stream-json and price
them itself, but that would mean a second rate table (per model, cache-write
premium, cache reads, and the sub-agent models a single turn also bills) whose
answer would drift away from the figure settle_model_budget records. One
source of truth for money is worth more than a check the runner owns.

What the CLI's cap is NOT is exact. It gates between turns, so the turn that
crosses the cap completes: overshoot is bounded by one model request, not by
zero. Settling at the reservation and recording the true figure stays
necessary.

The kill is against the process group, not the child: the CLI spawns its own
children, and terminating only the process the runner can see leaves them
running with the budget already spent. That applies to an agent that exited on
its own as much as to one the runner killed, so the group is reaped either
way.
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
    budget_exhausted: bool = False
    text: str = ""
    cost_usd: float | None = None
    num_turns: int | None = None
    session_id: str | None = None
    reported_paths: list[str] | None = None
    stderr: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (self.exit_code == 0 and not self.timed_out
                and not self.budget_exhausted)



def _creatable_note(contract: dict) -> str:
    """The one exception to the protected list, stated where it is read.

    ADD, never modify. The exception is granted by runner.boundary on the diff
    STATUS git reports, so an agent that edits an existing file under one of
    these globs is refused exactly as before.
    """
    globs = list(contract.get("creatable_paths") or [])
    if not globs:
        return ""
    listed = "\n".join(f"  - {g}" for g in globs)
    return f"""
## One exception, and it is an obligation rather than a permission

You MUST ADD exactly one new file matching one of these:

{listed}

That is a test, and it is the only thing in this run that can show the new
behaviour WORKS rather than that nothing broke. The suite passing proves the
second; only a test that fails without your change proves the first, and the
gate runs your test against the tree as it was before you touched it and
refuses the branch if it passes there.

So it must assert the behaviour the spec asked for, specifically enough to
fail if that behaviour is absent. A test that would pass against either tree
fails this run.

ADD, never modify. Creating a file here is permitted; editing any file that
already exists under these paths is refused exactly as the protected list
says. Add ONE file, not several -- each extra is another thing that has to be
shown to bite, and the gate refuses a change that adds more than one.
"""


def _paired_note(contract: dict) -> str:
    """Files that must land together, with the contract's own reason.

    The `why` is printed rather than summarised: it is the sentence somebody
    wrote about this specific pair, and an agent deciding what "together"
    means needs the reason, not the rule.
    """
    groups = list(contract.get("paired_paths") or [])
    if not groups:
        return ""
    blocks = []
    for group in groups:
        paths = "\n".join(f"  - {p}" for p in (group.get("paths") or []))
        why = (group.get("why") or "").strip()
        blocks.append(f"{paths}\n\n  Why: {why}")
    body = "\n\n".join(blocks)
    return f"""
## These change together, or not at all

{body}

A run that changes some of a group and not the rest is REFUSED, however good
the part it did. This is not a style rule: half of such a change is usually
worse than none of it, which is what the reason above says.

If you conclude the whole group cannot be changed, change none of it and say
why. That is a real answer. Landing the easy half is not.
"""


def build_prompt(task: dict, contract: dict, *, paths_file=None) -> str:
    """The spec, plus the boundary stated plainly.

    The contract is in the prompt so the agent can succeed, not so the runner
    can rely on it having read it. Everything here is re-derived from git
    afterwards; this text buys a better first attempt, nothing more.

    `paths_file` is named here rather than in the spec text because it is
    generated per run and its location is not knowable when the task is
    written. The spec used to hardcode `reference/PATHS.md`, which was a
    guess about a file the runner had not yet decided where to put.

    CREATABLE AND PAIRED PATHS ARE STATED BECAUSE OMITTING THEM MADE THE
    PROMPT WRONG, not merely incomplete.

    The protected list is introduced with "must not edit under any
    circumstances", and `platform/__tests__/**` and `api/tests/**` are on it.
    A contract with `creatable_paths` and `new_test_bites.sh` in its
    verification requires the agent to ADD a file inside exactly that tree --
    so an agent that believed the sentence above could not pass the gate, and
    one that passed it did so by disregarding the only line in the prompt
    written in absolute terms. Neither is a thing to build a fleet on.

    `paired_paths` is the same argument with a worse failure: an agent that
    does not know two files must move together will land one of them, and the
    check will refuse a branch that is otherwise good. Telling it after the
    fact costs a whole run.

    No decision rests on this text. Everything is re-derived from git and
    judged by runner.boundary and the contract's own checks.
    """
    writable = "\n".join(f"  - {p}" for p in contract["writable_paths"])
    protected = "\n".join(f"  - {p}" for p in contract["protected_paths"])
    creatable_note = _creatable_note(contract)
    paired_note = _paired_note(contract)
    paths_note = ""
    if paths_file:
        paths_note = f"""

## The real paths, listed for this run

`{paths_file}` lists every file in the read-only trees this task may see,
generated by the runner before you started. It is current for this run and
exists nowhere else.

**Cite paths IN FULL from the repository root.** `routes/orders.py` is not a
path; `api/analytics/routes/orders.py` is.
"""
    return f"""{task['spec_md']}{paths_note}

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
{creatable_note}{paired_note}
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
           allowed_tools: tuple[str, ...] = DEFAULT_TOOLS,
           readable: tuple[Path, ...] = (),
           max_cost_usd: float | None = None) -> AgentResult:
    """Run the agent in the worktree under a hard wall clock and a spend cap.

    `max_cost_usd` becomes --max-budget-usd. It is the reservation, converted
    at the same rate settlement uses, so the cap the agent is given and the
    figure the ledger records are the same number in two currencies rather
    than two independent estimates.

    `readable` adds directories the agent may look at -- a research task reads
    the platform checkout. --add-dir grants READ, but it does not make the
    directory read-only, so the runner snapshots every one of them before and
    after: a write there would land outside the worktree's git index entirely
    and the derived diff would show nothing.
    """
    cmd = [
        os.environ.get("FLEET_CLAUDE_BIN", CLAUDE_BIN), "-p", prompt,
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--add-dir", str(worktree),
        *[a for d in readable for a in ("--add-dir", str(d))],
        "--allowedTools", *allowed_tools,
    ]
    if model:
        cmd += ["--model", model]
    if max_cost_usd is not None:
        # Print mode only, which is what -p gives us. The CLI stops issuing
        # new work once its own accounting reaches this, and reports
        # subtype=error_max_budget_usd with exit 1.
        cmd += ["--max-budget-usd", f"{max_cost_usd:.6f}"]

    started = time.monotonic()
    proc = subprocess.Popen(
        cmd, cwd=str(worktree),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True)

    # start_new_session put the child in a new group it leads, so the group
    # id is its pid. Captured now rather than derived later: after the child
    # is reaped there is no pid left to ask.
    pgid = proc.pid

    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(pgid, proc)
        out, err = proc.communicate()
    finally:
        # Whichever way the agent ended. A CLI that stops itself on its
        # budget, or exits cleanly, can still leave a tool child behind, and
        # a surviving child is spend the reservation no longer bounds.
        _reap_group(pgid)

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
        # Two fields say the same thing; either alone is enough. Read both so
        # a rename on one side does not silently turn the cap back off.
        result.budget_exhausted = (
            payload.get("subtype") == "error_max_budget_usd"
            or payload.get("terminal_reason") == "budget_exhausted")
    if not result.text:
        result.text = (out or "")[-8000:]
    result.reported_paths = parse_report(result.text)
    return result


def _own_group(pgid: int) -> bool:
    """Guard: never signal the runner's own group.

    start_new_session should make this impossible. It is checked anyway
    because the failure mode is the runner killing itself and every other
    task in the tick, and the check costs one syscall.
    """
    try:
        return pgid == os.getpgid(0)
    except OSError:
        return True


def _kill_group(pgid: int, proc: subprocess.Popen) -> None:
    """TERM the group, then KILL what is left.

    A plain proc.kill() would leave the CLI's children running: they were
    started in the same new session, which is why the runner asked for one.
    """
    if _own_group(pgid):
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


def _reap_group(pgid: int) -> None:
    """Clear out whatever the agent left in its group.

    Called after every run, not only after a timeout. The leader is already
    gone by this point, so there is no process to poll and no reason to wait
    five seconds: anything still in the group outlived its parent and is not
    going to be talked down. ProcessLookupError is the normal case -- it
    means the group emptied itself, which is what should happen.
    """
    if _own_group(pgid):
        return
    for sig, grace in ((signal.SIGTERM, 0.5), (signal.SIGKILL, 0.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        if grace:
            time.sleep(grace)
