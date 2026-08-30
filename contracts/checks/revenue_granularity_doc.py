#!/usr/bin/env python3
"""Acceptance check for the revenue granularity documentation task.

Run from the root of the worktree. Reads the file with `ast` rather than
importing it, so it needs no database, no settings and no FastAPI, and cannot
be affected by anything the module does at import time.

This file lives in the fleet repository, not in the platform one. The agent
works inside a worktree of the platform repo and cannot write here, so the
check it is judged by is outside its reach by construction rather than by
being on a protected-path list.

Exit 0 if the documentation now states every granularity the code accepts,
and the accepted set itself is untouched. Exit 1 otherwise, saying which.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

TARGET = Path("api/analytics/routes/revenue.py")
EXPECTED = {"hour", "day", "week", "month"}


def fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if not TARGET.exists():
        return fail(f"{TARGET} does not exist")
    tree = ast.parse(TARGET.read_text())

    # 1. The behaviour must not have moved. The task was to correct the
    #    documentation, and widening or narrowing the accepted set instead
    #    would be a different change wearing the same diff.
    accepted: set[str] | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_VALID_GRANULARITIES"
                for t in node.targets):
            try:
                accepted = set(ast.literal_eval(node.value))
            except ValueError:
                return fail("_VALID_GRANULARITIES is no longer a literal set")
    if accepted is None:
        return fail("_VALID_GRANULARITIES is gone")
    if accepted != EXPECTED:
        return fail(f"_VALID_GRANULARITIES changed to {sorted(accepted)}; "
                    f"the task was to fix the documentation, not the behaviour")

    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "get_revenue"), None)
    if fn is None:
        return fail("get_revenue is gone")

    # 2. The docstring must name every accepted value.
    doc = (ast.get_docstring(fn) or "").lower()
    missing = sorted(g for g in EXPECTED if g not in doc)
    if missing:
        return fail(f"get_revenue's docstring does not mention {missing}")

    # 3. So must the query parameter's own description, which is what a
    #    caller reads in the generated API docs.
    description = None
    for arg, default in zip(fn.args.args[-len(fn.args.defaults):] if fn.args.defaults else [],
                            fn.args.defaults):
        if arg.arg != "granularity":
            continue
        if isinstance(default, ast.Call):
            for kw in default.keywords:
                if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                    description = str(kw.value.value)
    if description is None:
        return fail("could not find the granularity parameter's description")
    missing = sorted(g for g in EXPECTED if g not in description.lower())
    if missing:
        return fail(f"the granularity description does not mention {missing}: "
                    f"{description!r}")

    print(f"ok: docstring and description both state {sorted(EXPECTED)}, "
          f"and _VALID_GRANULARITIES is unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
