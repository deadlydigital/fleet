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

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import subprocess

from runner import boundary, verify, worktree

TRIAL_PREFIX = "fleet-accept-trial"
DEADLINE_SECONDS = 900


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


def run(repo: Path, trial_root: Path, task: dict[str, Any],
        contract: dict[str, Any], branch: str, *,
        recorded_base: str, changed_files: list[str]) -> Reverification:
    """Trial-merge into a scratch clone, verify there, throw it away."""
    started = time.monotonic()
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

        result = verify.run(
            trial, commands, DEADLINE_SECONDS,
            changed=changed_files,
            facts={"FLEET_BASE_SHA": base_sha, "FLEET_HEAD_SHA": head,
                   "FLEET_TASK_ID": str(task["id"])})

        checks = [{"command": c.command, "expanded": c.expanded,
                   "exit_code": c.exit_code, "duration_ms": c.duration_ms,
                   "timed_out": c.timed_out, "skipped_reason": c.skipped_reason,
                   "unresolved_reason": c.unresolved_reason,
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

        if not result.passed:
            failed = [c for c in result.checks if not c.passed]
            named = failed[0].command if failed else "a check"
            return Reverification(
                ok=False, base_sha=base_sha, merged_sha=head,
                verification=result, checks=checks,
                reason=(f"the branch verifies on its own and FAILS when merged "
                        f"into {base} as it stands now: {named}. The base moved "
                        f"under it. Nothing was recorded."),
                duration_s=time.monotonic() - started)

        return Reverification(ok=True, base_sha=base_sha, merged_sha=head,
                              verification=result, checks=checks,
                              duration_s=time.monotonic() - started)
    finally:
        worktree.discard_trial_clone(trial)
