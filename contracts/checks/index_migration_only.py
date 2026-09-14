#!/usr/bin/env python3
"""Acceptance check: this migration adds an index and can do nothing else.

Run from the root of the worktree. Reads FLEET_CHANGED_FILES and
FLEET_BASE_SHA, which the runner derives from git.

Exit 0 if the change is one new index migration, 1 naming what is wrong, 2 if
the check could not run.

WHY THIS EXISTS, AND WHY IT IS NARROWER THAN "A MIGRATION CONTRACT"
-------------------------------------------------------------------
`api/alembic/**` and `api/analytics/migrations/**` are on the protected floor of
every contract for this repository -- seven of them, checked -- and none makes
them writable. That floor is correct: a task that can alter the schema can drop
a column. Its consequence, measured on 14 Sep 2026, is that **nothing the fleet
builds can ever be made fast**. The dashboard endpoint takes 21.3s; 85% of its
SQL is one query whose plan sequentially scans 2,887,010 orders to remove 2,063
of them and sorts 1,724,169 rows on disk to produce 21,280. The index that
would serve it cannot be written by any task this system has ever run, and
candidates 27 and 35 -- both schema work -- have been sitting in the pool
refused as `protected_path` while that was true.

So the floor opens by exactly one crack, and this check is the shape of it.

WHAT MAKES THIS SAFE IS THAT THE WHITELIST IS STRUCTURAL, NOT TEXTUAL
---------------------------------------------------------------------
`api/analytics/migrations/migration.py` offers three step types: `SQLStep`
(arbitrary SQL), `DataStep` (row manipulation) and `CreateIndexStep`. This
check requires **every step to be a CreateIndexStep** and refuses the other two
outright. It is not a regex over SQL hoping to have thought of every dangerous
statement -- `DROP TABLE`, `ALTER`, `UPDATE`, a `DO $$` block, a function call
that writes -- because a blacklist is a list of the things somebody remembered.
There is no SQL here for a blacklist to miss: the step class is the whole
vocabulary, and two thirds of it is refused.

`CreateIndexStep` then supplies, by construction rather than by the agent
remembering:

  * CONCURRENTLY when the schema is live, so the build does not hold ACCESS
    EXCLUSIVE on a 2.9M-row table for minutes, which would be an outage;
  * IF NOT EXISTS, plus a drop of an invalid leftover from a failed
    concurrent build, which is the failure `v0003` documents;
  * a per-step predicate requiring `indisvalid`, which is what lets the same
    migration be applied to tenant schemas that are at different states --
    `analytics_1` has 679,917 orders and `analytics_2` has 2,887,844, and the
    header of migration.py records `analytics_12` being half through a change.

None of those is something this check has to verify in the file, because none
of them is something the file can get wrong.

WHAT IS STILL REFUSED, AND WHY EACH ONE
----------------------------------------
  * `unique=True`. A unique index is a CONSTRAINT: it can fail on existing data
    and it can reject future inserts. That is a change to what the system
    accepts, not to how fast it answers, and it does not belong in a contract
    whose entire justification is performance.
  * Editing an existing migration file. Applied migrations are history; a task
    that rewrites one changes what a schema already at version N means.
  * More than one file, or any file outside `versions/`.
  * Any module-level statement other than the docstring, imports, and the single
    `migration = Migration(...)` assignment. A migration file that can run code
    at import time is a migration file that can do anything, and the runner
    imports it.
  * `transactional` anything but False. CREATE INDEX CONCURRENTLY cannot run
    inside a transaction block, and migration.py's own header says a migration
    is transactional or not and never mixed.

WHAT THIS CHECK CANNOT ESTABLISH, so nobody reads more into a green
-------------------------------------------------------------------
That the index is the right index, that it will be used, or that it is worth
112 MB per tenant schema. The planner decides whether an index is used and it
frequently declines: measured the same day, the composite index proposed for
that dashboard query is NOT chosen by the planner for the query as written --
it is chosen only once the query is also rewritten to ask per customer. A green
here means the change is an index and nothing else. Whether it helps is a
question for a plan, and the plan belongs in the spec.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

VERSIONS_DIR = "api/analytics/migrations/versions/"

#: The one step type this contract admits. `SQLStep` and `DataStep` are the
#: other two migration.py defines, and both are refused -- see the header.
ALLOWED_STEP = "CreateIndexStep"

#: What a migration module may contain at the top level, and nothing else.
ALLOWED_IMPORTS = {"CreateIndexStep", "Migration"}


def fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def could_not_run(msg: str) -> int:
    # 2, which runner/verify.py reads as COULD NOT RUN rather than as a verdict
    # about the branch. "The check could not look" and "the change is wrong"
    # send a reader to different places.
    print(f"COULD NOT RUN: {msg}")
    return 2


def changed_files() -> list[str]:
    raw = os.environ.get("FLEET_CHANGED_FILES", "")
    return [p.strip() for p in raw.splitlines() if p.strip()]


def existed_before(path: str, base: str) -> bool:
    r = subprocess.run(["git", "cat-file", "-e", f"{base}:{path}"],
                       capture_output=True)
    return r.returncode == 0


def check_module(tree: ast.Module, path: str) -> list[str]:
    """Every top-level statement, and the Migration call in detail."""
    problems: list[str] = []
    migration_call = None

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            continue                                   # the docstring
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = {a.asname or a.name for a in node.names}
            extra = names - ALLOWED_IMPORTS
            if extra:
                problems.append(
                    f"imports {sorted(extra)}; an index migration needs only "
                    f"{sorted(ALLOWED_IMPORTS)}, and anything else is code this "
                    f"contract cannot vouch for")
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id == "migration":
            migration_call = node.value
            continue
        problems.append(
            f"line {node.lineno}: a migration module under this contract is a "
            f"docstring, imports, and `migration = Migration(...)`. Nothing "
            f"else, because the runner imports this file and anything else "
            f"here runs")

    if migration_call is None:
        problems.append("defines no `migration = Migration(...)`")
        return problems
    if not (isinstance(migration_call, ast.Call)
            and isinstance(migration_call.func, ast.Name)
            and migration_call.func.id == "Migration"):
        problems.append("`migration` is not a Migration(...) call")
        return problems

    kwargs = {k.arg: k.value for k in migration_call.keywords}

    transactional = kwargs.get("transactional")
    if transactional is None or not isinstance(transactional, ast.Constant) \
            or transactional.value is not False:
        problems.append(
            "must set transactional=False. CREATE INDEX CONCURRENTLY cannot "
            "run inside a transaction block, and migration.py is explicit that "
            "a migration is transactional or not and never mixed")

    steps = kwargs.get("steps")
    if steps is None or not isinstance(steps, ast.List):
        problems.append("carries no `steps=[...]` list")
        return problems
    if not steps.elts:
        problems.append("carries an empty `steps` list, which migrates nothing")

    for el in steps.elts:
        if not (isinstance(el, ast.Call) and isinstance(el.func, ast.Name)):
            problems.append(f"line {el.lineno}: a step that is not a call")
            continue
        kind = el.func.id
        if kind != ALLOWED_STEP:
            problems.append(
                f"line {el.lineno}: step type {kind!r}. This contract admits "
                f"{ALLOWED_STEP} and nothing else -- {kind} can express changes "
                f"an index migration must not make")
            continue
        for kw in el.keywords:
            if kw.arg == "unique" and isinstance(kw.value, ast.Constant) \
                    and kw.value.value is True:
                problems.append(
                    f"line {el.lineno}: unique=True. A unique index is a "
                    f"constraint -- it can fail on existing data and reject "
                    f"future inserts -- which is a change to what the system "
                    f"accepts rather than to how fast it answers")
    return problems


def main() -> int:
    files = changed_files()
    base = os.environ.get("FLEET_BASE_SHA", "")
    if not files:
        return could_not_run("FLEET_CHANGED_FILES is empty, so there is "
                             "nothing to check and nothing was established")
    if len(files) > 1:
        return fail(f"{len(files)} files changed: {files}. One index "
                    f"migration is one new file")

    path = files[0]
    if not path.startswith(VERSIONS_DIR) or not path.endswith(".py"):
        return fail(f"{path} is not a migration under {VERSIONS_DIR}")
    if base and existed_before(path, base):
        return fail(f"{path} already exists at {base[:12]}. Applied migrations "
                    f"are history: editing one changes what a schema already "
                    f"at that version means. Add a new version instead")

    src = Path(path)
    if not src.exists():
        return could_not_run(f"{path} is named as changed and is not on disk")
    try:
        tree = ast.parse(src.read_text())
    except SyntaxError as exc:
        return fail(f"{path} does not parse: {exc}")

    problems = check_module(tree, path)
    if problems:
        print(f"FAIL: {path} -- {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1

    steps = sum(1 for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == ALLOWED_STEP)
    print(f"ok: {path} -- {steps} {ALLOWED_STEP}(s), transactional=False, "
          f"no other step type, no other top-level statement. Whether the "
          f"index is the right one is a question for its plan, not for this.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
