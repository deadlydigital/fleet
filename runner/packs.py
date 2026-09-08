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
agent reads a file.

GENERATED PER RUN, OUTSIDE THE WORKTREE, AND NEVER COMMITTED

A committed listing is the wrong shape for the same reason the gap list was:
it goes stale, nothing re-derives it, and it is believed while it is wrong.
Generated at run start it is current by construction and it disappears with
the worktree.

It also must not be committed FOR A SECOND AND HARDER REASON. A file in the
repository is readable by every later task, including ones whose contract
makes that repository writable. A committed listing of both trees is a
standing index of a tree a given task was never granted -- exactly the leak
the research contract's readable_repos boundary exists to prevent, arriving as
a convenience rather than as a grant. Whoever finds this generating a file
every run and thinks to check it in: that is what it costs.

Outside the worktree, because inside it the file lands in the derived diff and
the boundary correctly refuses it for being outside writable_paths -- the same
trap the evidence pack solved by committing, which is the option ruled out
above.

GATED ON THE CAPABILITY, NOT ON THE WORK TYPE

A contract that already exposes a read-only tree gets a listing of it, because
a listing of a tree the agent may read grants nothing it could not already
enumerate. Derived from `readable_repos` and from `worktree_links` targets
that are repositories, so a future contract that adds a read-only worktree
gets this automatically rather than when somebody remembers to add its name to
a list.

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


def read_only_trees(contract: dict[str, Any], repo_root: Path) -> dict[str, Path]:
    """Every tree this contract lets the agent READ but not write.

    THE CAPABILITY, DERIVED -- not a flag somebody sets. Two mechanisms grant
    it today and both are found here, so a contract that acquires one later is
    covered without an edit:

      readable_repos   --add-dir, granting read for the whole run
      worktree_links   a symlink to a checkout

    `worktree_links` is included with a caveat that matters: the runner
    creates those links AFTER the diff is derived, so for a draft-spec task
    the linked checkout DOES NOT EXIST while the agent runs. Task 25's own
    spec says so -- "the reference/deadly-digital-platform checkout named in
    the task was not present in this worktree ... no path or line number below
    was read from the tree for this spec". The listing is therefore not a
    convenience for that contract; it is the only view of the tree it has.
    """
    trees: dict[str, Path] = {}
    for name in contract.get("readable_repos") or []:
        p = repo_root / name
        if p.is_dir():
            trees[name] = p
    for target in (contract.get("worktree_links") or {}).values():
        p = Path(target)
        if (p / ".git").exists():
            trees[p.name] = p
    return trees


def write_paths_pack(out_dir: Path, contract: dict[str, Any],
                     repo_root: Path) -> tuple[Path | None, int]:
    """List every read-only tree, into a directory OUTSIDE the worktree.

    Returns (file, count). No contract key is required: the listing follows
    the capability. `paths_pack.roots` narrows it when a contract says so, and
    a contract that says nothing gets the whole of each tree it may read --
    which is no more than it may already enumerate.
    """
    trees = read_only_trees(contract, repo_root)
    if not trees:
        return None, 0
    spec = contract.get("paths_pack") or {}
    roots = list(spec.get("roots") or [])

    lines = [
        "# Real paths in the read-only trees for this run",
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
    for name, tree in sorted(trees.items()):
        starts = [tree / r for r in roots] if roots else [tree]
        found: list[str] = []
        for start in starts:
            if not start.exists():
                continue
            for p in sorted(start.rglob("*")):
                if not p.is_file() or "/." in str(p):
                    continue
                try:
                    found.append(p.relative_to(tree).as_posix())
                except ValueError:
                    continue
                if len(found) >= MAX_PATHS_LISTED:
                    break
        total += len(found)
        lines.append(f"## {name}")
        lines.append("")
        lines.append("```")
        lines.extend(found or ["(nothing listed)"])
        lines.append("```")
        lines.append("")

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "PATHS.md"
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
            n, _, rest = head.partition(" exit=")
            code, _, shape = rest.partition(" shape_changed=")
            body = block.split("\n", 1)[1].strip()[:1200] if "\n" in block else ""
            runs.append({"n": int(n.strip()),
                         "exit_code": int(code.strip()),
                         # True when this run named a path the previous did
                         # not. The check reports every unresolved path at
                         # once, so a new one was introduced rather than
                         # uncovered -- the mutation signature.
                         "shape_changed": shape.strip() == "yes",
                         "output": body})
        except ValueError:
            continue
    return runs
