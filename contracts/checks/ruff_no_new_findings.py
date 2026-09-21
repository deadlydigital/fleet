#!/usr/bin/env python3
"""Lint gate: the change may not add a finding. With --fix, sort first.

Run from the root of the worktree. Reads FLEET_CHANGED_FILES and
FLEET_BASE_SHA, both derived by the runner from git, and compares ruff's
findings on each changed file against the same file at the base commit.

TWO MODES, ONE PROGRAM, AND THAT IS THE POINT

    (no argument)   judge. Unchanged, and still the authority.
    --fix           repair the import order the change itself un-sorted,
                    before the judge runs. Writes to the worktree.

They live in one file because the defect this file exists to prevent was two
invocations of ruff DISAGREEING -- see _assert_project_root. A repair mode
configured separately, with its own path to the binary and its own idea of
the root, is that defect with a write attached: it would not refuse correct
imports, it would replace them with wrong ones. Here, `RUFF`, `CONFIG`,
`findings()` and the root guard have exactly one definition, so the thing
that sorts and the thing that judges cannot drift apart.

The repair is NOT trusted. It runs before verification and the unchanged gate
then judges the tree it produced, so a fix that introduces a finding of its
own fails exactly as it would have if an agent had written it by hand.

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

Judging: exit 0 if the change introduced no new finding, 1 naming each one.
Repairing: exit 0 whether or not anything needed sorting, 2 if ruff could not
be trusted to sort correctly -- never 1, because a repair pass has no verdict
to deliver and the gate that does runs afterwards regardless.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

RUFF = "/home/ubuntu/deadly-digital-platform/api/.venv/bin/ruff"

#: The project's config. ASSERTED TO EXIST AND ASSERTED TO BE THE ONE RUFF
#: PICKS, and deliberately NOT passed with `--config`. See _assert_project_root.
CONFIG = "api/ruff.toml"


def findings(source: str, filename: str) -> Counter:
    """Ruff's findings for one file's content, counted by rule code.

    Counted by code rather than by line, because a change that shifts a line
    would otherwise read as removing one finding and adding another.
    """
    # NO `--config`, AND THAT IS THE WHOLE POINT OF _assert_project_root.
    #
    # `--config api/ruff.toml` does not mean "use this config as the project
    # would". It also sets ruff's PROJECT ROOT to the current directory, and
    # the project root is what isort resolves first-party imports against.
    # Run from the worktree root, `--config api/ruff.toml` gave
    #
    #     linter.project_root = /home/ubuntu/deadly-digital-platform
    #
    # where the correct root -- the one a developer gets, and the one ruff
    # finds by discovery -- is `.../api`. Under the wrong root `analytics` is
    # not a first-party package, so `from analytics...` is sorted into the
    # third-party block, and a correctly-sorted file reports I001.
    #
    # Letting ruff discover the config from the filename gives the developer's
    # answer. `--stdin-filename` is what makes discovery work on stdin.
    proc = subprocess.run(
        [RUFF, "check", "--output-format", "json",
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


def _assert_project_root(sample: str) -> None:
    """Refuse to judge anything unless ruff resolved the root we expect.

    THIS IS THE CHECK THAT WOULD HAVE CAUGHT ITS OWN BUG, which is why it is
    here rather than a comment saying "do not pass --config".

    The defect it replaces was invisible for EXISTING files and fatal for
    CREATED ones. A wrongly-rooted I001 appears in the base content and the
    head content alike, so the ratchet cancels it and nobody sees it. A file
    the change creates has no base content, so the same spurious finding
    counts as new. Task 58 -- a correct one-line upsert fix -- died that way,
    on the test file the contract's own bite check obliged it to create.

    Asked of ruff rather than assumed: a future version that changes discovery
    must fail here, loudly, rather than start rejecting correct files again.
    """
    proc = subprocess.run(
        [RUFF, "check", "--show-settings", sample],
        capture_output=True, text=True)
    want = str(Path(CONFIG).resolve().parent)
    for line in proc.stdout.splitlines():
        if line.strip().startswith("linter.project_root"):
            got = line.split("=", 1)[1].strip().strip('"')
            if got != want:
                print(f"ruff resolved its project root to {got}, and this "
                      f"check only means what it says when the root is {want} "
                      f"-- the root decides which imports are first-party, so "
                      f"a wrong one rejects correctly-sorted files. Not run.")
                sys.exit(2)
            return
    print(f"could not read ruff's resolved project root from --show-settings; "
          f"this check cannot establish that it is judging by the project's "
          f"own rules. Not run.")
    sys.exit(2)


def at_base(base_sha: str, path: str) -> str | None:
    """The file's content at the base commit, or None if it is new."""
    proc = subprocess.run(["git", "show", f"{base_sha}:{path}"],
                          capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else None


def _counts(base_sha: str, path: str) -> tuple[Counter, Counter]:
    """(what the base had, what the worktree has) for one file, by rule code."""
    after = findings(Path(path).read_text(), path)
    before_source = at_base(base_sha, path)
    before = Counter() if before_source is None else findings(before_source, path)
    return before, after


def _live(changed: list[str]) -> list[str]:
    """The changed python files still on disk. A deletion has nothing to lint."""
    return [p for p in changed if Path(p).exists()]


def repair(base_sha: str, changed: list[str]) -> int:
    """Sort the import blocks THIS CHANGE un-sorted, and no others.

    WHY ONLY THOSE, when `ruff --fix` on every changed file is one line
    shorter. The files worth changing here are often already dirty --
    `api/analytics/routes/revenue.py` and `sync_engine.py` both carry a
    pre-existing I001 -- and sorting one of those on the way past puts an
    unrelated import-sort into a diff that is being judged for staying
    narrow. That is the widening the module docstring above refuses, and it
    spends the contract's diff budget on history the task did not create.
    So the repair is aimed exactly where the ratchet bites: a file is sorted
    only where its I001 count is HIGHER than it was at the base.

    WHY NO FILTER ON THE CONTRACT'S WRITABLE PATHS, which was the obvious
    guard and is the wrong one. Deciding writability here means re-deriving
    the boundary's precedence between `protected_paths` and `creatable_paths`
    in a second place -- and under this contract `api/tests/**` is protected
    while `api/tests/analytics/test_fleet_*.py` is creatable, so a filter that
    got that precedence backwards would skip precisely the created test file
    task 58 died on. The cheaper truth: every file here is one the agent
    already wrote to, in a worktree that is thrown away, and the boundary
    judges the result afterwards either way -- a modified file is still
    modified when its imports are sorted, so no verdict changes.
    """
    sorted_paths, stubborn = [], []
    for path in _live(changed):
        before, after = _counts(base_sha, path)
        if after["I001"] - before["I001"] <= 0:
            continue
        # THE SAME RUFF, WITH THE SAME DISCOVERY, as `findings` above: no
        # `--config`, so the root is the one `_assert_project_root` just
        # confirmed. `--select I001` keeps this to import order -- every other
        # rule the project enables is the agent's to answer for, and a repair
        # pass silently rewriting them would hide work the gate should show.
        proc = subprocess.run([RUFF, "check", "--fix", "--select", "I001", path],
                              capture_output=True, text=True)
        if proc.returncode not in (0, 1):
            print(f"ruff could not sort {path}: {proc.stderr.strip()}")
            return 2
        still = findings(Path(path).read_text(), path)["I001"] - before["I001"]
        (stubborn if still > 0 else sorted_paths).append(path)

    for path in sorted_paths:
        print(f"sorted the imports in {path}")
    for path in stubborn:
        # Said out loud rather than swallowed. Ruff declined its own fix, so
        # the judge below will refuse the branch and the run report should
        # already say that this pass saw it coming.
        print(f"{path}: ruff still reports I001 after --fix, so this is not "
              f"the ordering it wanted; the gate will refuse it")
    if not sorted_paths and not stubborn:
        print("nothing to sort: no changed file introduces an I001")
    return 0


def judge(base_sha: str, changed: list[str]) -> int:
    """The gate. Unchanged by the repair mode, and run after it."""
    introduced: list[str] = []
    for path in _live(changed):
        before, after = _counts(base_sha, path)
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


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    fixing = argv == ["--fix"]
    if argv and not fixing:
        print(f"unknown argument(s) {' '.join(argv)}; this script takes "
              f"--fix or nothing at all")
        return 2

    base_sha = os.environ.get("FLEET_BASE_SHA")
    if not base_sha:
        print("FLEET_BASE_SHA is not set; this check must be run by the runner")
        return 2

    changed = [p for p in os.environ.get("FLEET_CHANGED_FILES", "").splitlines()
               if p.endswith(".py")]
    if not changed:
        print("nothing to sort: no python file changed" if fixing
              else "ok: no python file changed")
        return 0

    # THE SAMPLE HAS TO BE A FILE THAT EXISTS, and `changed[0]` is not
    # necessarily one. `--show-settings` on a deleted path prints nothing, and
    # the root guard reads that as "cannot establish the root" and exits 2 --
    # so a change whose alphabetically-first python file is a DELETION was
    # refused as unjudgeable, whatever the rest of it did. Found by the
    # repair-mode tests on 19 Sep 2026; it was always true of the judge.
    live = _live(changed)
    if not live:
        print("nothing to sort: every changed python file was deleted" if fixing
              else "ok: every changed python file was deleted, so there is "
                   "nothing left to lint")
        return 0

    if not Path(CONFIG).exists():
        print(f"{CONFIG} is not in this worktree, so ruff would lint with its "
              f"own defaults and this check would be a different, laxer gate "
              f"than the one it claims to be. Not run.")
        return 2
    # BEFORE THE REPAIR AS WELL AS BEFORE THE JUDGEMENT, and it matters more
    # here. A wrong root makes the judge refuse correct files, which is
    # expensive; it makes the repair WRITE the wrong ordering into the tree,
    # which is expensive and then wrong for every developer who pulls it.
    _assert_project_root(live[0])

    return repair(base_sha, changed) if fixing else judge(base_sha, changed)


if __name__ == "__main__":
    sys.exit(main())
