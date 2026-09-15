"""Taking a branch the gate refused, when the gate was what was wrong.

A FAILED task whose branch verified GREEN can be moved to READY_FOR_REVIEW
instead of being rebuilt. 038 adds the edge and the database enforces the half
of the precondition that lives in the database; this module enforces the half
that lives in git, and refuses first, because a refusal that costs a
subprocess is better than one that costs a transaction.

WHAT IT COST TO FIND OUT THIS WAS MISSING. Task 69 ran four times, 12 Sep 2026.
Run 44 produced a branch that passed all six of its contract's checks and was
refused by max_test_diff_lines at a value retired the same day. There was no
way to reach that branch: FAILED leads only to QUEUED, and QUEUED means the
agent writes the change again from the spec. It does not write the same thing
-- four runs off one spec and one base gave tests of 377, 606, 439 and 385
lines -- and the rebuild failed ruff on a single new I001. £15.06, four
branches, nothing merged, and the correct one had been on disk since the third.

THE TWO QUESTIONS THIS ASKS THE TREE

  IS THIS THE COMMIT THAT WAS VERIFIED? The branch tip must equal the
  patch_commit_sha of the run being adopted. A branch that has moved since --
  amended, rebased, pushed over -- is not the artefact the checks looked at,
  and the run's greenness says nothing about it.

  HAS THE BASE MOVED? The run's base_commit_sha must still be the tip of the
  task's base branch. Green against 871f165d is not green against whatever main
  becomes: the merge that ships is `branch + base-as-it-is`, and git can merge
  a verified branch into a moved base cleanly and produce something broken.
  console/reverify.py exists because of exactly that, and this refuses rather
  than leaning on it.

THE SECOND ONE IS A FAST REFUSAL AND NOT THE ONLY DEFENCE. accept() re-runs the
contract's verification against the merged tree before merging, for every
branch, adopted or not. So a stale adoption cannot ship a broken merge; it can
only waste the human who clicked Accept. Refusing here turns that into a
sentence naming the two shas instead.

WHEN THE CHECK WAS WHAT WAS WRONG (042, 14 Sep 2026)

Everything above is about a branch refused by a GATE. Task 100 was refused by a
CHECK -- `tests/analytics/test_migrations.py` asserting a hand-maintained step
tally that a migration on the base had moved by one -- and the branch touched
no migration and no test. The recorded FAIL was true about the tree and false
about the branch, and nothing here could tell those apart.

So: A CHECK THAT FAILS IDENTICALLY ON THE BASE IS NOT EVIDENCE ABOUT THE
BRANCH. `corroborate()` re-runs the failing commands in a throwaway clone at
the base the run recorded, writes a BASE_CHECK_RUN step against that same run,
and `plan()` then excuses exactly the checks that failed the same way. 042
enforces the same rule in the database, because 038's trigger requires green
independently of anything Python decides.

IT IS NARROW, AND THE NARROWNESS IS THE POINT. Only a check that RAN and
exited non-zero can be excused. Unresolved, undecided and timed-out checks
establish nothing at either end and stay failures. Matching exit codes are not
matching causes -- pytest exits 1 for any failure at all -- so both output
tails are recorded side by side for the human, and the real defence is the one
named above: accept() re-runs the whole contract against the merged tree and
requires green outright, consulting no corroboration at all.

AND IT WAS NOT NARROW ENOUGH (15 Sep 2026)

A CHECK WHOSE SUBJECT IS THE CHANGE FAILS AT THE BASE FOR A REASON THAT IS NOT
ABOUT THE TREE, AND MUST NOT CORROBORATE ANYTHING.

contracts/checks/spec_requirements_cited.py reads `git diff BASE..HEAD` and
refuses a change that cites no requirement. At a corroboration run BASE and
HEAD are the same commit, so the diff is empty, so NOTHING is cited, so it
exits 1 -- every time, for every branch, whatever the branch did. Matched on
command and exit code, that excused the check FOR EVERY BRANCH. 042 enforces
the same rule in SQL and has the same blind spot. Measured, not reasoned: run
at the base it prints `FAIL: 8 of 8 numbered requirement(s) are cited nowhere`
and exits 1.

That is exactly the gate that caught task 102 -- five checks green over 530
lines, including a 15-minute analytics suite, and this the only one that
noticed the branch had not proved its central claim. The rule written to rescue
task 100 punched a hole in it two days later.

WHY NOT COMPARE THE OUTPUT, which is the obvious fix and is wrong. Task 100's
excused check printed `FAIL: 1 of 43 files in tests/analytics failed` on the
branch and `1 of 42` at the base -- the branch had added a test file. The tails
differ in length by a factor of three. Requiring them to match would refuse the
one case this feature exists for.

SO THE CHECK SAYS SO ITSELF, and the vocabulary already existed: exit 2, COULD
NOT RUN. A check that cannot speak about a tree with no branch applied reports
2 there, and _excusable() and 042 both already refuse a base check that is
undecided. No new state, no output matching, and the knowledge lives in the
check that has it rather than in a list here that would drift from it.

IF YOU ARE WRITING A CHECK THAT READS THE DIFF -- `git diff`, FLEET_CHANGED_FILES,
or `{changed_files}` -- make it exit 2 when the change is empty. A 1 there is
not a verdict about the base; it is your check answering a question nobody
asked, and the answer excuses you.

The two structural halves of that rule are enforced here rather than trusted:
the base run is handed only the changed files that EXIST at the base (see
corroborate()), so a `{changed_files}` command over files the branch added
expands to nothing and is recorded as skipped -- and a skipped base check
excuses nothing.

WHAT THIS DOES NOT DO. It does not merge, it does not push, and it does not
record a verdict. It moves a row to READY_FOR_REVIEW, which is where a person
decides -- the same place the runner's own branches arrive, reached by a
different edge.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from psycopg.types.json import Jsonb

from console import config, db
# The deadline is IMPORTED rather than recomputed. _deadline_for's own
# docstring is about what it cost to have two numbers for one question, and a
# base run that timed out where the branch run did not is a corroboration that
# silently is not one.
from console.reverify import _deadline_for
from runner import verify, worktree

BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
TRIAL_PREFIX = "corroborate"


class NotAdoptable(RuntimeError):
    """The branch, the base or the record does not support adoption."""


@dataclass
class Adoption:
    task_id: int
    branch: str
    run_id: int
    base_sha: str
    head_sha: str
    checks: list[str] = field(default_factory=list)
    corroborated: list[str] = field(default_factory=list)


@dataclass
class Corroboration:
    task_id: int
    run_id: int
    base_sha: str
    excused: list[str] = field(default_factory=list)
    still_failing: list[str] = field(default_factory=list)


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise NotAdoptable(
            f"git {' '.join(args)} failed in {repo.name}: "
            f"{(r.stderr or r.stdout).strip()[:200]}")
    return r.stdout.strip()


def _check_is_green(c: dict) -> bool:
    """runner/verify.py's Check.passed, read back off the payload.

    Deliberately the same order as the original, including why: unresolved and
    undecided are failures BEFORE the skip branch is reached, so a checker that
    went missing or a check the kernel killed cannot fall through into "there
    was nothing for it to do".
    """
    if c.get("unresolved_reason") is not None:
        return False
    if c.get("undecided_reason") is not None:
        return False
    # AN UNMET OBLIGATION IS NOT GREEN, ahead of the skip branch for the same
    # reason the two above are. It is handled as its own case by the caller;
    # what must never happen is it falling through into "nothing to do".
    if c.get("obligation_reason") is not None:
        return False
    if c.get("skipped_reason") is not None:
        return True
    return c.get("exit_code") == 0 and not c.get("timed_out")


def _excusable(c: dict) -> str:
    """Why this check could not be excused by a base run, or "" if it can.

    A check is excusable only if it RAN and exited non-zero. Everything else
    is a check that did not judge the tree, and re-running it somewhere else
    judges nothing either. 042 refuses the same four cases in SQL.

    AN UNMET OBLIGATION JOINS THAT LIST, 15 Sep 2026, and it is the case that
    made the list too short. An obligation is owed BY THE BRANCH. The base has
    no branch and therefore owes nothing, so re-running such a check there
    answers a question nobody asked -- and answers it the same way every time,
    for every branch, which is an excuse rather than evidence. That is exactly
    the hole spec_requirements_cited.py fell into: it returned 1 at the base
    and corroborated itself.

    The check now returns 2 there, which this function already refuses. This
    branch closes the same door from the other side, so that a check which
    forgets the base-run rule is still not excusable on an obligation.
    """
    if c.get("skipped_reason") is not None:
        return "it was skipped, so it is not a failure to excuse"
    if c.get("unresolved_reason") is not None:
        return "unresolved: " + str(c["unresolved_reason"])
    if c.get("undecided_reason") is not None:
        return "undecided: " + str(c["undecided_reason"])
    if c.get("obligation_reason") is not None:
        return ("it is an obligation the BRANCH owes, and the base owes "
                "nothing -- a base run would refuse it identically for every "
                "branch, which is an excuse rather than evidence. The remedy "
                "is to clear it on the branch: cite the requirement, or change "
                "the spec that asked for something the branch cannot give")
    if c.get("timed_out"):
        return ("it timed out, and a timeout corroborated by a timeout is how "
                "a busy box adopts a branch nobody judged")
    if c.get("exit_code") in (0, None):
        return "it recorded no non-zero exit code"
    return ""


def _corroboration_for(check: dict, base_payloads: list[dict],
                       recorded_base: str) -> dict | None:
    """The BASE_CHECK_RUN entry that excuses `check`, or None.

    THE SAME RULE AS 042, IN THE SAME ORDER, for the same reason
    _check_is_green mirrors Check.passed: two places decide this and they must
    decide it the same way. The database is the one that binds -- this can
    only ever be the more conservative of the two.

    Matched on the COMMAND as recorded, not on position: a contract whose
    verification list changed between the run and now would otherwise excuse
    one check with another check's evidence.
    """
    if _excusable(check):
        return None
    for payload in base_payloads:
        if (payload.get("base_commit_sha") or "") != recorded_base:
            continue
        for bc in payload.get("checks") or []:
            if bc.get("command") != check.get("command"):
                continue
            if bc.get("exit_code") != check.get("exit_code"):
                continue
            if bc.get("timed_out"):
                continue
            if (bc.get("skipped_reason") is not None
                    or bc.get("unresolved_reason") is not None
                    or bc.get("undecided_reason") is not None
                    # 046: AND A BASE CHECK THAT REPORTS AN OBLIGATION EXCUSES
                    # NOTHING. _excusable() above closes the branch side; this
                    # is the base side, and they are two separate doors. A base
                    # run reporting an obligation is a check answering a
                    # question about a branch that is not applied -- whatever
                    # it says, it is not about this branch.
                    or bc.get("obligation_reason") is not None):
                continue
            return bc
    return None


def _verification_is_green(payload: dict,
                           base_payloads: list[dict] | None = None) -> bool:
    """Verification.passed, likewise, including the half people forget.

    Every check passed AND at least one of them actually ran. A payload of
    skips establishes nothing, and nothing is not a pass.

    042: a check that failed here and fails the same way at the base it was
    verified against is not counted against the branch. The ran-at-all test
    above is unchanged and deliberately so -- it asks whether anything looked
    at the tree, and a corroborated failure DID look at the tree.
    """
    if payload.get("verification_skipped") is not None:
        return False
    checks = payload.get("checks") or []
    if not checks:
        return False
    if not any(c.get("skipped_reason") is None
               and c.get("unresolved_reason") is None
               and c.get("undecided_reason") is None for c in checks):
        return False
    base = base_payloads or []
    recorded_base = payload.get("base_commit_sha") or ""
    return all(_check_is_green(c)
               or _corroboration_for(c, base, recorded_base) is not None
               for c in checks)


def _boundary_was_size_only(payload: dict) -> bool:
    """Nothing protected, nothing outside the contract. Size, or nothing.

    A run that touched a protected path cannot have its checks believed --
    api/tests/** is on that list, and a suite the change rewrote cannot judge
    the change. Today such a run never reaches verification, so this is
    belt-and-braces; it is here so that this module states the property it
    depends on rather than inheriting it from an ordering somewhere else.
    """
    v = payload.get("boundary_violations") or {}
    return not (v.get("protected") or {}) and not (v.get("outside_writable") or [])


def plan(task_id: int, branch: str) -> Adoption:
    """Everything that must be true, asked before anything is written."""
    if not BRANCH_RE.match(branch or ""):
        raise NotAdoptable(f"{branch!r} is not a branch name this will pass to git")

    with db.connect() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=%s",
                            (task_id,)).fetchone()
        if task is None:
            raise NotAdoptable(f"there is no task {task_id}")
        if task["status"] != "FAILED":
            raise NotAdoptable(
                f"task {task_id} is {task['status']}, not FAILED. Adoption is "
                f"for a task that ran, produced a branch, and was refused.")
        steps = conn.execute(
            "SELECT s.run_id, s.payload FROM run_steps s"
            " JOIN runs r ON r.id = s.run_id"
            " WHERE r.task_id = %s AND s.step_type = 'VERIFICATION_RUN'"
            " ORDER BY s.run_id DESC", (task_id,)).fetchall()
        # 042's evidence, read in the same breath as the thing it excuses.
        base_steps = conn.execute(
            "SELECT s.run_id, s.payload FROM run_steps s"
            " JOIN runs r ON r.id = s.run_id"
            " WHERE r.task_id = %s AND s.step_type = 'BASE_CHECK_RUN'"
            " ORDER BY s.run_id DESC", (task_id,)).fetchall()

    repo = config.repo_root() / task["repo"]
    head = _git(repo, "rev-parse", f"{branch}^{{commit}}")
    base_now = _git(repo, "rev-parse", f"{task['base_branch']}^{{commit}}")

    # THE RUN IS IDENTIFIED BY THE TREE, NOT BY RECENCY. Picking "the last
    # green run" and hoping it matches the branch is the class of inference
    # this whole exercise has been about. The branch tip names its run.
    for step in steps:
        payload = step["payload"] or {}
        if payload.get("patch_commit_sha") != head:
            continue
        mine = [b["payload"] or {} for b in base_steps
                if b["run_id"] == step["run_id"]]
        recorded_base = payload.get("base_commit_sha") or ""
        if not _verification_is_green(payload, mine):
            raise NotAdoptable(
                f"run {step['run_id']} is the run that produced {branch}, and "
                f"its checks are not green: "
                f"{payload.get('verification_skipped') or _why_not_green(payload, mine)}")
        if not _boundary_was_size_only(payload):
            raise NotAdoptable(
                f"run {step['run_id']} broke the boundary on something other "
                f"than size, so its checks cannot be believed")
        if recorded_base != base_now:
            raise NotAdoptable(
                f"the base has moved. {branch} was verified against "
                f"{recorded_base[:12]} and {task['base_branch']} is now at "
                f"{base_now[:12]}. Green against one base is not green against "
                f"another: re-run the task, or re-verify against this base.")
        return Adoption(
            task_id=task_id, branch=branch, run_id=step["run_id"],
            base_sha=recorded_base, head_sha=head,
            checks=[c.get("command", "") for c in (payload.get("checks") or [])],
            corroborated=[c.get("command", "")
                          for c in (payload.get("checks") or [])
                          if not _check_is_green(c)])

    raise NotAdoptable(
        f"no run of task {task_id} verified {branch} at {head[:12]}. The "
        f"branch has moved since it was checked, or it was never this task's.")


def _why_not_green(payload: dict, base_payloads: list[dict] | None = None) -> str:
    checks = payload.get("checks") or []
    if not checks:
        return "the run recorded no checks at all"
    base = base_payloads or []
    recorded_base = payload.get("base_commit_sha") or ""
    bad = [c for c in checks if not _check_is_green(c)
           and _corroboration_for(c, base, recorded_base) is None]
    if not bad:
        return "no check actually ran, so nothing was established"
    parts = []
    for c in bad:
        why = _excusable(c)
        parts.append(c.get("command", "?") + (f" ({why})" if why else ""))
    out = "failed: " + "; ".join(parts)
    if any(not _excusable(c) for c in bad):
        out += (". If these fail on the base too, they are not evidence about "
                "the branch -- corroborate them with --corroborate-base")
    return out


def adopt(task_id: int, branch: str) -> Adoption:
    """Move the task to READY_FOR_REVIEW behind the branch it already built.

    The UPDATE is narrow on purpose: status and branch_name, guarded on the
    status this read it at. 038's trigger independently re-establishes the
    recorded-green precondition, so a caller that skipped `plan` still cannot
    promote a run that proved nothing.
    """
    decided = plan(task_id, branch)
    with db.writer() as conn:
        rows = conn.execute(
            "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name=%s,"
            " completed_at=now() WHERE id=%s AND status='FAILED'",
            (branch, task_id)).rowcount
        if rows != 1:
            conn.rollback()
            raise NotAdoptable(
                f"task {task_id} was not FAILED when the write landed; "
                f"nothing was changed")
        conn.commit()
    return decided


def _has_commit(repo: Path, sha: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
                          capture_output=True, timeout=30).returncode == 0


def corroborate(task_id: int, branch: str) -> Corroboration:
    """Re-run this run's failing checks AT THE BASE IT RECORDED, and write it down.

    THE BASE THE RUN RECORDED, not the base as it is now. Those are different
    questions and the second one is asked in git, by plan(), a few lines up.
    Corroborating against a moved base would answer "does this fail today"
    when what was asked is "did the branch cause the failure that was
    recorded".

    THE COMMAND AS RECORDED, not as the contract now lists it. The recorded
    string is the one that failed; re-deriving it from a contract that may
    have been edited since would run something else and call it the same
    check. `changed` is the run's own file list for the same reason -- a
    command carrying the changed-files placeholder must expand identically or
    it is not the same command, and at the base those paths may not exist, in
    which case verify.run reports it unresolved and 042 refuses it as
    evidence. Failing closed there is the intended behaviour.

    IN A THROWAWAY CLONE, never the checkout. The checkout IS the deployment
    and a build may be in flight; this module has no business moving it, and
    the reasons are reverify.py's, which learned them the expensive way.

    WRITES ONE STEP AND DECIDES NOTHING. The task's status is untouched. What
    this produces is evidence, which plan() and 042 then judge separately --
    so a corroboration that excuses nothing costs a suite run and changes no
    row, which is the right price for being wrong.
    """
    if not BRANCH_RE.match(branch or ""):
        raise NotAdoptable(f"{branch!r} is not a branch name this will pass to git")

    with db.connect() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=%s",
                            (task_id,)).fetchone()
        if task is None:
            raise NotAdoptable(f"there is no task {task_id}")
        if task["status"] != "FAILED":
            raise NotAdoptable(
                f"task {task_id} is {task['status']}, not FAILED. There is "
                f"nothing here to corroborate.")
        rows = conn.execute(
            "SELECT s.run_id, s.step_type, s.payload FROM run_steps s"
            " JOIN runs r ON r.id = s.run_id"
            " WHERE r.task_id = %s"
            "   AND s.step_type IN ('VERIFICATION_RUN', 'PATCH_PROPOSED')"
            " ORDER BY s.run_id DESC", (task_id,)).fetchall()

    repo = config.repo_root() / task["repo"]
    head = _git(repo, "rev-parse", f"{branch}^{{commit}}")

    run_id, payload = None, None
    for r in rows:
        if r["step_type"] != "VERIFICATION_RUN":
            continue
        candidate = r["payload"] or {}
        if candidate.get("patch_commit_sha") == head:
            run_id, payload = r["run_id"], candidate
            break
    if payload is None:
        raise NotAdoptable(
            f"no run of task {task_id} verified {branch} at {head[:12]}. The "
            f"branch has moved since it was checked, or it was never this "
            f"task's.")

    failing = [c for c in (payload.get("checks") or []) if not _check_is_green(c)]
    if not failing:
        raise NotAdoptable(
            f"run {run_id}'s checks are already green; there is nothing to "
            f"corroborate. Adopt it.")
    blocked = [(c.get("command", "?"), _excusable(c)) for c in failing
               if _excusable(c)]
    if blocked:
        raise NotAdoptable(
            "these checks cannot be excused by any base run, so running one "
            "would prove nothing: "
            + "; ".join(f"{cmd} -- {why}" for cmd, why in blocked))

    recorded_base = payload.get("base_commit_sha") or ""
    if not recorded_base:
        raise NotAdoptable(f"run {run_id} recorded no base commit to stand on")
    if not _has_commit(repo, recorded_base):
        raise NotAdoptable(
            f"{repo.name} does not have {recorded_base[:12]}, the base run "
            f"{run_id} was verified against, so it cannot be checked out")

    patch = next((r["payload"] or {} for r in rows
                  if r["step_type"] == "PATCH_PROPOSED" and r["run_id"] == run_id),
                 {})
    changed = [f for f in (patch.get("files_changed") or [])
               if (patch.get("file_status") or {}).get(f) != "D"]
    contract = task["acceptance_contract"] or {}
    commands = [c.get("command", "") for c in failing]

    trial_root = config.trial_root()
    trial_root.mkdir(parents=True, exist_ok=True)
    trial = None
    try:
        trial, at = worktree.create_trial_clone(
            repo, trial_root, f"{TRIAL_PREFIX}-{task_id}", recorded_base)
        # The dependency tree, for the reason reverify.run gives: a clone has
        # no node_modules and no venv, and a check that cannot start reports
        # could-not-run -- which 042 refuses as evidence, so this would fail
        # closed rather than wrongly. Linked anyway, because "the base fails
        # this too" is only worth asking when the base can run it.
        worktree.link_dependencies(trial, contract.get("worktree_links", {}))
        # ONLY THE FILES THAT EXIST AT THE BASE, since 15 Sep 2026. `changed`
        # is the BRANCH's list, and a `{changed_files}` command expanded with
        # it at the base names paths that are not there -- a file the branch
        # ADDED cannot be checked on a tree that does not have it, and the
        # error that produces is about the missing file rather than about the
        # tree. Matching exit codes would then excuse the branch check with
        # evidence that is not about the base at all.
        #
        # The filter is the same sentence as the exit-2 rule below: at the base
        # there is no branch diff, so a check whose subject is the CHANGE has
        # no input here. A command whose placeholder now expands to nothing is
        # recorded by verify.run as skipped -- "no changed file matched this
        # check's filter" -- and a skipped base check excuses nothing, in this
        # module and in 042 alike.
        #
        # Files the branch MODIFIED are kept, and that is the whole point of
        # keeping the filter rather than passing []: those exist at the base,
        # a check over them asks a real question there, and task 100's kind of
        # excuse survives.
        at_base = [f for f in changed if (trial / f).exists()]
        result = verify.run(
            trial, commands, _deadline_for(task),
            changed=at_base,
            links=worktree.writable_links(trial, contract),
            # HEAD IS THE BASE HERE, and saying so is the point: the tree
            # under test is the base with nothing applied to it.
            facts={"FLEET_BASE_SHA": at, "FLEET_HEAD_SHA": at,
                   "FLEET_TASK_ID": str(task_id),
                   "FLEET_CONTRACT": json.dumps(contract),
                   "FLEET_SPEC_MD": task.get("spec_md") or ""})
    finally:
        if trial is not None:
            worktree.discard_trial_clone(trial)

    branch_side = {c.get("command"): c for c in failing}
    base_checks = []
    for c in result.checks:
        was = branch_side.get(c.command, {})
        base_checks.append({
            "command": c.command, "expanded": c.expanded,
            "exit_code": c.exit_code, "duration_ms": c.duration_ms,
            "timed_out": c.timed_out, "skipped_reason": c.skipped_reason,
            "unresolved_reason": c.unresolved_reason,
            "undecided_reason": c.undecided_reason,
            "obligation_reason": c.obligation_reason,
            "output_tail": c.output_tail[-800:],
            # BOTH TAILS, SIDE BY SIDE. Equal exit codes are not equal causes
            # and nothing here can tell them apart; the person who accepts
            # can, and this is the only place they would ever see both.
            "branch_exit_code": was.get("exit_code"),
            "branch_output_tail": (was.get("output_tail") or "")[-800:]})

    step_payload = {"base_commit_sha": recorded_base, "patch_commit_sha": head,
                    "checks": base_checks}

    with db.writer() as conn:
        seq = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS seq FROM run_steps"
            " WHERE run_id = %s", (run_id,)).fetchone()["seq"]
        conn.execute(
            "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
            " VALUES (%s, %s, 'BASE_CHECK_RUN', %s, %s)",
            (run_id, seq, "fleet-console/adopt", Jsonb(step_payload)))
        conn.commit()

    excused, still = [], []
    for c in failing:
        target = (excused if _corroboration_for(c, [step_payload], recorded_base)
                  else still)
        target.append(c.get("command", "?"))
    return Corroboration(task_id=task_id, run_id=run_id, base_sha=recorded_base,
                         excused=excused, still_failing=still)


def main(argv: list[str] | None = None) -> int:
    """    python -m console.adopt --task 69 --branch fleet/task-69.3
    python -m console.adopt --task 100 --branch fleet/task-100 --corroborate-base

    --dry-run asks every question and writes nothing, which is the way to find
    out whether a branch is adoptable without deciding that it is.
    """
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m console.adopt", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task", type=int, required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--dry-run", action="store_true",
                   help="check everything and change nothing")
    p.add_argument("--corroborate-base", action="store_true",
                   help="re-run this run's FAILING checks at the base it was "
                        "verified against, and record what happened. Adopts "
                        "nothing: a check that fails the same way on the base "
                        "is then excused by plan() and by 042.")
    args = p.parse_args(argv)

    if args.corroborate_base:
        try:
            found = corroborate(args.task, args.branch)
        except NotAdoptable as exc:
            print(f"REFUSED: {exc}")
            return 1
        print(f"ran task {found.task_id}'s failing checks at "
              f"{found.base_sha[:12]}, the base run {found.run_id} recorded")
        for c in found.excused:
            print(f"  base fails too  {c}")
        for c in found.still_failing:
            print(f"  base is fine    {c}")
        if found.still_failing:
            print("  -> not adoptable. The base does not fail these, so the "
                  "branch is what does.")
            return 1
        print("  -> recorded. `--dry-run` will now say whether it adopts.")
        return 0

    try:
        decided = (plan if args.dry_run else adopt)(args.task, args.branch)
    except NotAdoptable as exc:
        print(f"REFUSED: {exc}")
        return 1
    verb = "would adopt" if args.dry_run else "adopted"
    print(f"{verb} {decided.branch} for task {decided.task_id}")
    print(f"  run {decided.run_id}, {decided.head_sha[:12]} on "
          f"{decided.base_sha[:12]}")
    for c in decided.checks:
        print(f"  {'base' if c in decided.corroborated else '  ok'}  {c}")
    if decided.corroborated:
        print("  'base' means the check fails identically without this branch "
              "applied, so it is not evidence about it. Both output tails are "
              "on the run's BASE_CHECK_RUN step.")
    if not args.dry_run:
        print("  -> READY_FOR_REVIEW. Nothing merged: accept() re-verifies "
              "against the base before it does.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
