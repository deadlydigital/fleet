"""Sort the imports the agent un-sorted, before the gate that would refuse it.

THE CLASS THIS CLOSES. A correct change arrives with one import block ruff
would group differently, `contracts/checks/ruff_no_new_findings.py` reports it
as a new I001, and the run ends FAILED. The work was right; the ordering of
three lines was not. Task 58 died that way on 11 Sep 2026 (£1.90, terminal),
task 87 came within one check of it on 13 Sep, and task 136 died that way on
18 Sep -- every other check on its branch passed. The re-roll costs another
agent run and does not produce the same diff twice, so the sorting is not even
reliably fixed by paying again.

WHY THIS IS SAFE NOW AND WAS NOT ON 11 SEP. The argument against auto-fixing
was measured, not assumed: applying what the checker wanted produced a file
the project's own ruff then reported as I001, because the checker passed
`--config api/ruff.toml` and that sets ruff's project root to the worktree
root rather than to `api/`. The two roots disagree permanently, so a fixer
built on the wrong one oscillates. 62b7fc9 removed `--config` the same day and
added `_assert_project_root`; re-measured on 19 Sep, a discovery-rooted
`--fix` is a fixpoint -- the file it produces passes the project's own
unmodified `ruff check`, and running it twice changes nothing. The two roots
still disagree, which is why the sorting is done by the gate's own program and
under the gate's own root assertion, and not by a second invocation here.

WHAT IT DOES NOT DO. It does not lower the bar. `--fix` is limited to I001, it
touches only files whose I001 count the change itself raised, and the
unchanged gate judges the result afterwards -- including any finding the sort
introduced. A branch that is wrong is still refused; a branch that was only
un-sorted now gets to be judged on its work.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from runner import boundary, verify

#: The gate that can repair what it is about to judge. Matched against the
#: contract's OWN verification command rather than configured separately, and
#: deliberately so. The repair has to run the same binary, from the same root,
#: as the judgement -- a second configuration is exactly how the two come to
#: disagree, and a fixer that disagrees with the gate writes the wrong imports
#: into the tree instead of merely refusing the right ones. Reading the command
#: off the contract also means every task already queued under a contract that
#: runs the ratchet gets this, with no new contract key and no version bump.
RATCHET = "contracts/checks/ruff_no_new_findings.py"

#: Bounded separately from the verification phase's budget, because this runs
#: before it and must not eat it. Ruff on a handful of files is tens of
#: milliseconds; the number is a hang-stop, not an allowance.
REPAIR_DEADLINE_SECONDS = 120.0


def ratchet_command(contract: dict) -> str | None:
    """The contract's lint-ratchet command, if it runs one."""
    for command in contract.get("verification") or []:
        if RATCHET in command:
            return command
    return None


def sort_imports(worktree: Path, contract: dict, base_sha: str,
                 log: Callable[[str], None]) -> list[str]:
    """Run the ratchet in repair mode. Returns the lines it printed.

    CALLED BEFORE `boundary.commit_agent_work`, which is the only place the
    fix can land coherently. Afterwards the commit is what gets pushed and
    what `boundary.derive` measures, so a repair applied later would either
    sit in the worktree and never reach the branch, or need the commit amended
    and every sha already recorded against the run re-derived. Before it, the
    sorted line is part of the agent's commit: counted against the diff budget
    like any other line, judged by the boundary, verified, and merged.

    COUNTING IT AGAINST THE BUDGET CANNOT COST A BRANCH, which is worth the
    sentence because "the runner grew the diff" reads like it might. The only
    files touched are ones whose I001 count this change raised -- every one of
    them was going to fail the lint gate as it stood. So a branch the sort
    pushes over `max_diff_lines` trades one refusal for another, and no branch
    that would have passed can be refused because of it.

    NOT FATAL, AND THE `except` IS THE POINT RATHER THAN AN OVERSIGHT. This
    now runs on every task with a lint gate, between a finished agent and a
    verification that is about to spend twenty minutes. A repair that cannot
    run leaves the tree exactly as the agent left it and the gate then says
    what it always said -- whereas an exception here would throw away a paid
    agent run over a convenience. Losing the sort is worth strictly less than
    losing the tick, so nothing this function can do is allowed to end one.
    """
    try:
        return _sort_imports(worktree, contract, base_sha, log)
    except Exception as exc:                       # noqa: BLE001 -- see above
        log(f"  import sort: {type(exc).__name__}: {exc}. The tree is "
            f"unchanged and the lint gate will judge it as it stands")
        return []


def _sort_imports(worktree: Path, contract: dict, base_sha: str,
                  log: Callable[[str], None]) -> list[str]:
    command = ratchet_command(contract)
    if not command:
        return []

    # The same set the commit is about to take, derived the same way: `add -A`
    # picks up untracked files and deletions alike, so nothing the agent wrote
    # sits outside it. HEAD is still `base_sha` here -- the evidence commit, if
    # there was one, moved it before the agent started -- and naming the sha
    # rather than relying on that keeps the comparison true if it ever stops
    # being.
    boundary.git(worktree, "add", "-A")
    changed = [p for p in boundary.git(
        worktree, "diff", "--cached", "--name-only", base_sha).splitlines()
        if p.strip()]
    if not any(p.endswith(".py") for p in changed):
        return []

    result = verify.run(worktree, [f"{command} --fix"], REPAIR_DEADLINE_SECONDS,
                        changed=changed,
                        facts={"FLEET_BASE_SHA": base_sha})
    check = result.checks[0] if result.checks else None
    if check is None or not check.ran:
        log("  import sort: could not run; the tree is unchanged and the "
            "lint gate will judge it as it stands")
        return []

    lines = [ln for ln in check.output_tail.splitlines() if ln.strip()]
    for line in lines:
        log(f"  import sort: {line}")
    if check.exit_code != 0:
        log("  import sort: refused to sort anything, which is not a failure "
            "of this run; the lint gate below is unaffected")
    return lines

