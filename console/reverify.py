"""Re-verifying a branch against the base it will actually merge into.

WHY THIS EXISTS

Both branch guards -- the merge base matching, and the tip being the commit
that was verified -- are claims about the BRANCH. Neither says anything about
the merge RESULT.

Verification ran against base B1. The merge lands on B2. What was tested is
`branch + B1`; what ships is `branch + B2`. Git can merge those cleanly and
produce something broken: a task adds a caller to a function while the base
changes that function's signature, different lines, no conflict, broken code.
That risk is untouched by any check on the branch, and it grows the longer a
branch waits -- which is to say it becomes routine the moment tasks run
overnight.

So the contract's own verification is run again, against the merged tree.

IT RUNS AGAINST THE MERGED TREE, NOT THE BRANCH. Running it against the branch
would re-establish exactly what the original run already established and prove
nothing new. The merge is made in a throwaway worktree first, verified there,
and only then made for real.

A FAILURE RECORDS NOTHING AND LEAVES NOTHING. The trial merge happens where it
can be deleted; on conflict or on a failing check the trial is removed, the
real checkout is never touched, and no verdict is written -- the same rule a
conflicting merge already follows, because a merge that could not be verified
is not a decision either.

THE TRIAL IS A CLONE, AND THAT IS WHAT MAKES THE PARAGRAPH ABOVE TRUE. It was
a linked worktree until 2026-09-09, and for as long as it was, the paragraph
above was false: a worktree's merge writes its objects into the SOURCE
repository's shared object store, and `git worktree remove` does not take them
back. Every Accept that reached re-verification left an unreferenced merge
commit and tree in the real repository. Nothing downstream read them and no
verdict depended on them, so the damage was litter rather than corruption --
but "leaves nothing" was a claim this module did not keep, and it was not
noticed until the same write failed loudly for a different reason. See
runner.worktree.create_trial_clone.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import subprocess

from runner import boundary, verify, worktree

TRIAL_PREFIX = "fleet-accept-trial"

#: Fallback only, for a task row that carries no timeout. The deadline itself
#: comes from the TASK, which is where the runner's comes from -- see
#: _deadline_for.
DEFAULT_DEADLINE_SECONDS = 900


@dataclass
class Reverification:
    ok: bool
    reason: str = ""
    merged_sha: str = ""
    base_sha: str = ""
    conflicted: bool = False
    verification: verify.Verification | None = None
    boundary_clean: bool = True
    violations: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0
    checks: list[dict[str, Any]] = field(default_factory=list)
    skipped_reason: str = ""
    # Set only when the caller asked for the trial to be KEPT and it passed.
    # The clone that verified is the clone that ships -- see merge.publish.
    # Deliberately absent from as_record(): it is a path on a temporary
    # filesystem that will not exist by the time anyone reads the record.
    trial_path: str = ""
    # "could not re-verify" is not "re-verification failed". The first means
    # the trial never ran and nothing is known about the merged tree; the
    # second means it ran and said no. Both refuse the merge -- not knowing is
    # not permission -- but they send the reader to different places, and a
    # setup failure reported as a verification failure would have them reading
    # a diff that is fine.
    could_not_run: bool = False

    def as_record(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "merged_sha": self.merged_sha,
                "base_sha": self.base_sha, "conflicted": self.conflicted,
                "boundary_clean": self.boundary_clean,
                "violations": self.violations, "duration_s": round(self.duration_s, 1),
                "checks": self.checks, "skipped_reason": self.skipped_reason,
                "could_not_run": self.could_not_run}


def _deadline_for(task: dict[str, Any]) -> float:
    """How long the contract's verification may take here.

    FROM THE TASK, BECAUSE THAT IS WHERE THE RUNNER'S COMES FROM. This was a
    hardcoded 900 until 11 Sep 2026, while runner/cycle.py gives verification
    the task's own `timeout_seconds` less whatever the agent spent. Two numbers
    for one question, and they were 900 and ~3460 for the same task.

    Measured that day on task 58's contract: `pytest_unit_per_file.sh api
    tests/analytics` alone takes 695s and the whole block about 956s. It passed
    in the runner and could not pass here, so a dd_api branch was
    unmergeable by construction -- and before the timeout joined the
    could-not-run class that would have read as "the branch FAILS when merged".

    THE RESIDUAL DIVERGENCE IS NAMED RATHER THAN HIDDEN. The runner splits one
    budget between the agent and the verification; this path has no agent and
    gives the whole of it. So the accept path is at least as permissive as the
    runner for the same task, which is the safe direction -- a branch the
    runner passed cannot fail here for want of time -- but the two are still
    not the same number when the agent ran long. The fix for that is a
    verification budget on the CONTRACT, separate from the task's wall clock,
    and it is not built here.
    """
    seconds = task.get("timeout_seconds")
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return float(DEFAULT_DEADLINE_SECONDS)
    return seconds if seconds > 0 else float(DEFAULT_DEADLINE_SECONDS)


def run(repo: Path, trial_root: Path, task: dict[str, Any],
        contract: dict[str, Any], branch: str, *,
        recorded_base: str, changed_files: list[str],
        keep_on_success: bool = False) -> Reverification:
    """Trial-merge into a scratch clone, verify there, throw it away.

    `keep_on_success` leaves the clone in place and names it in
    `trial_path`, so the caller can PUBLISH THE COMMIT THAT WAS TESTED
    rather than construct an equal-looking one somewhere else. The clone is
    then the caller's to delete -- see the accept route, which does it in a
    finally. Nothing is kept on any failing path: an unverified trial is
    still thrown away as it always was.
    """
    started = time.monotonic()
    keep = False                      # see the finally at the end of this function
    base = task["base_branch"]
    commands = list(contract.get("verification") or [])
    if not commands:
        return Reverification(
            ok=True, skipped_reason="the contract declares no verification",
            duration_s=time.monotonic() - started)

    name = f"{TRIAL_PREFIX}-{task['id']}"
    # Inside a handler, because everything this line touches is environmental
    # -- a root the sandbox will not let the console write to, a stale
    # worktree registration, a full disk. Uncaught, those became a 500 on
    # Accept: the same shape as any other rarely-taken path with no handler,
    # and indistinguishable to the reviewer from the app being broken.
    try:
        trial_root.mkdir(parents=True, exist_ok=True)
        trial, base_sha = worktree.create_trial_clone(repo, trial_root, name, base)
    except (boundary.GitError, OSError) as exc:
        return Reverification(
            ok=False, could_not_run=True,
            reason=(f"the trial clone could not be created under "
                    f"{trial_root}, so the merge into {base} was NOT "
                    f"re-verified and has not been made. This is not a failing "
                    f"check and not a conflict -- the trial never ran: {exc}"),
            duration_s=time.monotonic() - started)

    try:
        # The exit code, not a search for "CONFLICT" in the output: git's
        # wording is not an API, and a merge can fail for reasons that never
        # print that word -- a read-only filesystem said "cannot lock ref
        # 'ORIG_HEAD'" once and was reported as a conflict for exactly that
        # mistake.
        # `origin/<branch>`, not `<branch>`: in a clone the source's branches
        # arrive as remote-tracking refs and only the source's HEAD branch
        # exists locally, so the bare name would resolve to nothing -- or, in
        # the one case where it did resolve, to the wrong commit.
        merged = subprocess.run(
            ["git", "-C", str(trial), "-c", "user.name=fleet-console",
             "-c", "user.email=console@fleet.local",
             "merge", "--no-ff", "--no-edit", f"origin/{branch}"],
            capture_output=True, text=True, timeout=120)
        if merged.returncode != 0:
            output = (merged.stdout or "") + (merged.stderr or "")
            conflicted = ("CONFLICT" in output
                          or (trial / ".git" / "MERGE_HEAD").exists()
                          or "Automatic merge failed" in output)
            return Reverification(
                ok=False, conflicted=conflicted, base_sha=base_sha,
                reason=((f"{branch} does not merge cleanly into {base} as it "
                         f"stands now.")
                        if conflicted else
                        (f"the trial merge of {branch} into {base} could not be "
                         f"attempted -- this is not a conflict, it is git "
                         f"failing outright: {output.strip()[-300:]}")),
                duration_s=time.monotonic() - started)
        head = boundary.git(trial, "rev-parse", "HEAD").strip()

        # The merge's own contribution, judged against the contract again.
        # diff(base, merged) is what this merge adds to the base, and it must
        # still land only where the contract allows.
        change = boundary.derive(trial, base_sha)
        verdict = boundary.enforce(change, contract)

        # THE DEPENDENCY TREE, LINKED IN AS THE RUNNER LINKS IT.
        #
        # Without this, re-verification could not run ANY task whose checks
        # need an installed tree, and it failed the same way every time:
        #
        #     cd platform && ./node_modules/.bin/tsc --noEmit exited 127
        #
        # node_modules is gitignored, so a CLONE has none -- the same fact
        # runner/cycle.py links them for, and the same fact vitest_one_file.sh
        # links them for inside the bite check's `git archive` tree. This was
        # the third place that needed it and the only one that did not have it,
        # which stayed invisible because task 53 is the first frontend task to
        # reach accept: every earlier accept was a draft_spec or an api task,
        # whose checks are python and need nothing installed.
        #
        # AFTER the boundary is judged, for the reason link_dependencies gives:
        # the links must not be able to influence what the diff contains. Here
        # that is belt and braces -- nothing writes to this clone between the
        # merge and the checks -- but the ordering is the property, not the
        # circumstance.
        #
        # Nothing is unlinked afterwards: the clone is thrown away whole, and
        # on the keep_on_success path it is the caller's to delete. What must
        # NOT happen is the link outliving the clone, and discard_trial_clone
        # removes the directory rather than following into it.
        links = worktree.link_dependencies(trial, contract.get("worktree_links", {}))

        # The SAME facts the original run was given, including the frozen
        # contract. A check that can read its contract on the first run and not
        # on the re-verification is a check that reports could-not-run at
        # exactly the moment auto-merge consults it.
        result = verify.run(
            trial, commands, _deadline_for(task),
            changed=changed_files,
            # THE LINKS ARE HANDED OVER so the precondition can test them.
            # The trial tree itself is writable by construction -- it is a
            # clone this function just made -- and the LINK is the boundary
            # where that stops being true. That is the one that bit.
            links=links,
            facts={"FLEET_BASE_SHA": base_sha, "FLEET_HEAD_SHA": head,
                   "FLEET_TASK_ID": str(task["id"]),
                   "FLEET_CONTRACT": json.dumps(contract),
                   # THE SPEC ITSELF, for contracts/checks/
                   # spec_requirements_cited.py. specs/auto-approval.md
                   # §9.12 step 2: a check cannot reach the database and
                   # should not start, so the one thing that knows what the
                   # spec asked for has to hand it over. Never truncated --
                   # a requirement clipped off the end is a requirement the
                   # gate stops asking about.
                   "FLEET_SPEC_MD": task.get("spec_md") or ""})

        checks = [{"command": c.command, "expanded": c.expanded,
                   "exit_code": c.exit_code, "duration_ms": c.duration_ms,
                   "timed_out": c.timed_out, "skipped_reason": c.skipped_reason,
                   "unresolved_reason": c.unresolved_reason,
                   "undecided_reason": c.undecided_reason,
                   "output_tail": c.output_tail[-800:]} for c in result.checks]

        if not verdict.clean:
            return Reverification(
                ok=False, base_sha=base_sha, merged_sha=head,
                boundary_clean=False, checks=checks,
                violations={"protected": verdict.protected_hits,
                            "outside_writable": verdict.outside_writable,
                            "over_diff_limit": verdict.over_diff_limit},
                reason=("merged into the current base, this change lands "
                        "outside its contract: " + "; ".join(verdict.reasons())),
                duration_s=time.monotonic() - started)

        # BEFORE the failure branch below, because it is the branch that would
        # otherwise tell the wrong story. A contract naming a checker that is
        # not on disk produces exactly the shape of a failing check, and the
        # sentence below -- "the branch verifies on its own and FAILS when
        # merged" -- would send the reviewer to read a diff that is fine.
        # Nothing about the change is known here; that is `could_not_run`.
        if result.unresolved:
            return Reverification(
                ok=False, could_not_run=True, base_sha=base_sha, merged_sha=head,
                checks=checks,
                reason=(f"the merge into {base} was NOT re-verified and has "
                        f"not been made: {result.unresolved_summary()}. This "
                        f"is not a failing check and says nothing about "
                        f"{branch} -- the contract names a checker that is not "
                        f"there. Nothing was recorded."),
                duration_s=time.monotonic() - started)

        # A CHECK THAT WAS KILLED IS IN THE SAME CLASS, and it reached this
        # function as an ordinary non-zero exit until 11 Sep 2026.
        #
        # Measured that day, re-verifying task 53 under fleet-automerge's own
        # 512M: tsc exited 134 (SIGABRT, V8 out of memory) and the branch was
        # reported as "verifies on its own and FAILS when merged into main as
        # it stands now. The base moved under it." Every clause of that
        # sentence was false, and it was produced by the failure branch below
        # because a signalled process and a failing one look identical from an
        # exit code alone.
        #
        # BEFORE the failure branch for the same reason the unresolved check
        # is: the branch below is the one that would otherwise tell the wrong
        # story, and it would send a reviewer to read a diff that is fine.
        if result.undecided:
            return Reverification(
                ok=False, could_not_run=True, base_sha=base_sha, merged_sha=head,
                checks=checks,
                reason=(f"the merge into {base} was NOT re-verified and has "
                        f"not been made: {result.undecided_summary()}. This is "
                        f"not a failing check and says nothing about {branch} "
                        f"-- the check did not finish, so there is no verdict "
                        f"to read. Look at the unit's limits and the "
                        f"filesystem it ran on, not at the diff. Nothing was "
                        f"recorded."),
                duration_s=time.monotonic() - started)

        if not result.passed:
            failed = [c for c in result.checks if not c.passed]
            named = failed[0].command if failed else "a check"
            # WHAT HAPPENED TO THE BASE, NOT A CAUSE ASSERTED ABOUT IT.
            #
            # "The base moved under it" was unconditional here until 11 Sep
            # 2026 -- printed whether or not the base had moved, as a flat
            # statement of cause. The comment above already records it being
            # false for task 53; it was false again for task 67 the same
            # night, where the recorded base WAS the tip of main and the
            # merged tree was byte-for-byte the branch that had just passed.
            # A reader given a cause goes looking for it, and both times the
            # cause did not exist.
            #
            # So this says which of the two situations it is and stops there.
            # When the base has not moved, the merged tree IS the branch tree,
            # and a check that passed in the run and fails here cannot be
            # about the diff -- which is the fact worth handing the reader.
            if base_sha == recorded_base:
                moved = (f"{base} has NOT moved since the branch was cut -- it "
                         f"is still {base_sha[:12]} -- so the merged tree is "
                         f"the branch tree. This check passed when the runner "
                         f"ran it against the same tree, so look at what "
                         f"differs about where it ran, not at the diff")
            else:
                moved = (f"{base} moved from {recorded_base[:12]} to "
                         f"{base_sha[:12]} since the branch was cut, so this "
                         f"is a verdict about the merged tree and not about "
                         f"the branch on its own")
            return Reverification(
                ok=False, base_sha=base_sha, merged_sha=head,
                verification=result, checks=checks,
                reason=(f"the branch verifies on its own and FAILS when merged "
                        f"into {base} as it stands now: {named}. {moved}. "
                        f"Nothing was recorded."),
                duration_s=time.monotonic() - started)

        keep = keep_on_success
        return Reverification(ok=True, base_sha=base_sha, merged_sha=head,
                              verification=result, checks=checks,
                              trial_path=str(trial) if keep else "",
                              duration_s=time.monotonic() - started)
    finally:
        # Only the passing path can set `keep`, and it sets it immediately
        # before returning. Every `return` above it -- conflict, boundary
        # violation, unresolved checker, failing check -- and every exception
        # leaves it False, so a trial that did not verify is deleted here
        # exactly as it always was.
        if not keep:
            worktree.discard_trial_clone(trial)
