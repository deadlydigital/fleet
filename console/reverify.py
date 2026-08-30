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
can be deleted; on conflict or on a failing check the worktree is removed, the
real checkout is never touched, and no verdict is written -- the same rule a
conflicting merge already follows, because a merge that could not be verified
is not a decision either.
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

    def as_record(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "merged_sha": self.merged_sha,
                "base_sha": self.base_sha, "conflicted": self.conflicted,
                "boundary_clean": self.boundary_clean,
                "violations": self.violations, "duration_s": round(self.duration_s, 1),
                "checks": self.checks, "skipped_reason": self.skipped_reason}


def run(repo: Path, worktree_root: Path, task: dict[str, Any],
        contract: dict[str, Any], branch: str, *,
        recorded_base: str, changed_files: list[str]) -> Reverification:
    """Trial-merge into a scratch worktree, verify there, throw it away."""
    started = time.monotonic()
    base = task["base_branch"]
    commands = list(contract.get("verification") or [])
    if not commands:
        return Reverification(
            ok=True, skipped_reason="the contract declares no verification",
            duration_s=time.monotonic() - started)

    name = f"{TRIAL_PREFIX}-{task['id']}"
    trial, base_sha = worktree.create_detached(repo, worktree_root, name, base)
    try:
        # The exit code, not a search for "CONFLICT" in the output: git's
        # wording is not an API, and a merge can fail for reasons that never
        # print that word -- a read-only filesystem said "cannot lock ref
        # 'ORIG_HEAD'" once and was reported as a conflict for exactly that
        # mistake.
        merged = subprocess.run(
            ["git", "-C", str(trial), "-c", "user.name=fleet-console",
             "-c", "user.email=console@fleet.local",
             "merge", "--no-ff", "--no-edit", branch],
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
        worktree.remove(repo, trial)
