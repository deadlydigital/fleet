"""Two things the runner puts in front of the agent before it starts.

THE PATHS PACK
--------------
Three draft specs failed on paths, and every failing one had a real sibling:
`routes/orders.py` next to a genuine `api/analytics/routes/orders.py`,
`routes/categories.py` next to a directory full of real routes. That is
recall, not knowledge -- the agent knew the shape of the tree and not its
prefix -- and recall is fixed by putting the tree in front of it rather than
by asking it to try harder.

So the RUNNER lists the paths, exactly as it runs the evidence queries: the
agent reads a file. Committed before the agent runs, for the reason the
evidence pack is -- an uncommitted runner artifact lands in the derived diff,
where the boundary correctly refuses it for being outside writable_paths.

THE SELF-CHECK STATE
--------------------
Lives OUTSIDE the worktree. Inside it, every invocation would write a file the
boundary then refuses, so the act of checking would fail the branch. Outside,
the agent cannot reach it at all: it has no shell but the one scoped command,
and that command's script is under `contracts/**`, which is protected.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

#: How many times an agent may run the gate before it has to think instead.
#: One to discover, one to confirm the fix, one spare for a second distinct
#: problem. Past that a changing set of unresolved paths is search, not
#: correction, and search that ends green has satisfied the check without
#: establishing anything.
DEFAULT_SELFCHECK_MAX = 3

MAX_PATHS_LISTED = 4000


def write_paths_pack(worktree: Path, contract: dict[str, Any]) -> tuple[Path | None, int]:
    """Materialise the real tree under the contract's declared roots."""
    spec = contract.get("paths_pack")
    if not spec:
        return None, 0
    rel = spec.get("file") or "reference/PATHS.md"
    roots = list(spec.get("roots") or [])
    base = Path(spec.get("base") or ".")

    lines = [
        "# Real paths in this tree",
        "",
        "Listed by the runner before the agent started, from the checkout "
        "itself. **These are the paths. Anything you write that is not one of "
        "them, and is not a new file in one of these directories, is wrong.**",
        "",
        "Cite paths IN FULL from the repository root. `routes/orders.py` is "
        "not a path; `api/analytics/routes/orders.py` is.",
        "",
    ]
    total = 0
    for root in roots:
        start = (worktree / base / root).resolve()
        lines.append(f"## {root}")
        lines.append("")
        if not start.exists():
            lines.append(f"_(nothing at `{root}`)_")
            lines.append("")
            continue
        found = []
        for p in sorted(start.rglob("*")):
            if not p.is_file() or "/." in str(p):
                continue
            try:
                found.append(p.relative_to((worktree / base).resolve()).as_posix())
            except ValueError:
                continue
            if len(found) >= MAX_PATHS_LISTED:
                break
        total += len(found)
        lines.append("```")
        lines.extend(found)
        lines.append("```")
        lines.append("")

    out = worktree / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines))
    return out, total


def selfcheck_env(contract: dict[str, Any]) -> dict[str, str]:
    """Environment for the scoped self-check, or nothing.

    The command is the contract's FIRST verification command, not a second
    copy of it. A self-check that could drift from the gate would be a preview
    of a different program -- and the point is that the agent sees what the
    runner will say.
    """
    if not contract.get("self_check"):
        return {}
    commands = list(contract.get("verification") or [])
    if not commands:
        return {}
    fd, path = tempfile.mkstemp(prefix="fleet-selfcheck-", suffix=".log")
    os.close(fd)
    cap = int(contract.get("self_check_max", DEFAULT_SELFCHECK_MAX))
    return {"FLEET_SELFCHECK_STATE": path,
            "FLEET_SELFCHECK_COMMAND": commands[0],
            "FLEET_SELFCHECK_MAX": str(cap)}


def read_selfcheck(state_path: str | None) -> list[dict[str, Any]]:
    """The invocations and their verdicts, for the PATCH_PROPOSED step.

    A sequence whose unresolved set CHANGES COMPOSITION rather than shrinking
    is the signature of an agent mutating paths until the gate goes green.
    Recorded rather than judged: no check can tell a correction from a lucky
    guess, and a reviewer reading three different failing path sets can.
    """
    if not state_path or not Path(state_path).exists():
        return []
    runs: list[dict[str, Any]] = []
    for block in Path(state_path).read_text().split("\nrun "):
        block = block.strip()
        if not block:
            continue
        head = block.split("\n", 1)[0].replace("run ", "", 1)
        try:
            n, _, code = head.partition(" exit=")
            runs.append({"n": int(n.strip()),
                         "exit_code": int(code.strip()),
                         "output": block.split("\n", 1)[1].strip()[:1200]
                                   if "\n" in block else ""})
        except ValueError:
            continue
    return runs
