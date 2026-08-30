#!/usr/bin/env python3
"""Lint gate: the change may not add a finding.

Run from the root of the worktree. Reads FLEET_CHANGED_FILES and
FLEET_BASE_SHA, both derived by the runner from git, and compares ruff's
findings on each changed file against the same file at the base commit.

WHY A RATCHET AND NOT "THE CHANGED FILES MUST BE CLEAN"

`ruff check api/` is unusable as a gate: 261 of its 402 findings sit in
protected paths and 65 more in files no contract makes writable, so 337 of
them can never be fixed by the work being gated. Aiming it at the changed
files fixes that, but not the underlying shape -- the files worth changing
are often already dirty. `api/analytics/routes/revenue.py` carries a
pre-existing I001, so a one-line docstring fix there would fail a
must-be-clean gate for history it did not create.

The alternative is worse than it looks. Forcing the fix means every task
arrives carrying an unrelated import-sort, which is exactly the widening
that specs/revenue-granularity-doc.md tells the agent not to do. A gate that
contradicts the spec it enforces will be satisfied by widening the diff.

So: findings present at base are tolerated, findings the change introduces
are not. The bar is not lowered -- ruff runs under the project's own
unmodified ruff.toml, with no rules disabled -- it is aimed at the change.
Fixing the backlog is a separate, tracked job; see docs/TODO.md in the
platform repository.

Exit 0 if the change introduced no new finding. Exit 1 naming each one.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

RUFF = "/home/ubuntu/deadly-digital-platform/api/.venv/bin/ruff"
CONFIG = "api/ruff.toml"


def findings(source: str, filename: str) -> Counter:
    """Ruff's findings for one file's content, counted by rule code.

    Counted by code rather than by line, because a change that shifts a line
    would otherwise read as removing one finding and adding another.
    """
    proc = subprocess.run(
        [RUFF, "check", "--config", CONFIG, "--output-format", "json",
         "--stdin-filename", filename, "-"],
        input=source, capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        print(f"ruff failed on {filename}: {proc.stderr.strip()}")
        sys.exit(2)
    try:
        return Counter(f["code"] for f in json.loads(proc.stdout or "[]"))
    except json.JSONDecodeError:
        print(f"could not read ruff output for {filename}: {proc.stdout[:400]}")
        sys.exit(2)


def at_base(base_sha: str, path: str) -> str | None:
    """The file's content at the base commit, or None if it is new."""
    proc = subprocess.run(["git", "show", f"{base_sha}:{path}"],
                          capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else None


def main() -> int:
    base_sha = os.environ.get("FLEET_BASE_SHA")
    if not base_sha:
        print("FLEET_BASE_SHA is not set; this check must be run by the runner")
        return 2

    changed = [p for p in os.environ.get("FLEET_CHANGED_FILES", "").splitlines()
               if p.endswith(".py")]
    if not changed:
        print("ok: no python file changed")
        return 0

    introduced: list[str] = []
    for path in changed:
        head = Path(path)
        if not head.exists():          # deleted; nothing to lint
            continue
        after = findings(head.read_text(), path)
        before_source = at_base(base_sha, path)
        before = Counter() if before_source is None else findings(before_source, path)

        for code, count in sorted(after.items()):
            added = count - before.get(code, 0)
            if added > 0:
                introduced.append(
                    f"{path}: {added} new {code}"
                    + (f" (was {before.get(code, 0)}, now {count})"
                       if before.get(code) else ""))

    if introduced:
        print("FAIL: the change introduces ruff findings that were not there before")
        for line in introduced:
            print(f"  {line}")
        print("\nPre-existing findings are tolerated. These are new.")
        return 1

    print(f"ok: {len(changed)} changed python file(s) introduce no new ruff finding")
    return 0


if __name__ == "__main__":
    sys.exit(main())
