"""Merging without a person, and the rules for what may.

specs/unattended-operation.md §6.1.

THE DEFAULT IS ELIGIBLE, AND THAT IS SCOPED TO THE PARITY PUSH
--------------------------------------------------------------
A code task is eligible unless something says otherwise. That is the opposite
of what this module was first designed with, and the inversion is deliberate
and TEMPORARY.

The argument for opt-in was that only a person reading a spec can judge whether
the work is worth doing, and that argument is correct in general. It is wrong
for the next three weeks: the work is Metorik parity, the rows are already
agreed, Deadly Digital has no customers, HIB is not using it, and reading every
spec puts a person back in the loop twice per feature -- which is the thing
being removed. A bad spec here costs a revert, and every change is reversible
through git.

**THIS DEFAULT SHOULD BE REVERSED ONCE THERE ARE CUSTOMERS.** It is listed in
specs/unattended-operation.md §7 with the rest of what goes back, and it is
written here as well because a default is inherited by whoever reads the code
next, and they will not necessarily read the spec. `auto_merge: true` in a
contract is not a statement that unattended merging is safe in general. It is a
statement that for THIS body of work, on a product with no users, a revert is
cheaper than a review.

WHAT IS NEVER ELIGIBLE, WHATEVER A CONTRACT SAYS
-------------------------------------------------
`draft_spec` and `research` produce artefacts that exist to be READ. Merging
one without a person defeats the only step where intent, rather than the diff,
is judged -- and under this posture that step is the single remaining human
gate. It is a hard rule keyed on work_type, not a default a contract can turn
off.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

#: Work types whose whole purpose is to be read by a person. No contract flag
#: makes these eligible.
NEVER_UNATTENDED = ("draft_spec", "research", "candidate_producer",
                    # A script that swaps production containers is read
                    # by a person before it lands, whatever its checks
                    # said. The shape check proves it is shaped like a
                    # deploy; nothing proves it deploys.
                    "dd_infra")

#: The check whose passing is the only evidence that the NEW behaviour works
#: rather than that nothing broke. See contracts/checks/new_test_bites.sh.
BITE_CHECK = "new_test_bites.sh"


@dataclass
class Eligibility:
    ok: bool
    reason: str = ""
    #: Everything the decision rested on, for the record a person reads later.
    gates: dict[str, Any] = field(default_factory=dict)


def _check(reverification: Any, needle: str) -> Optional[dict]:
    for c in getattr(reverification, "checks", None) or []:
        if needle in (c.get("command") or ""):
            return c
    return None


def eligible(task: dict, reverification: Any) -> Eligibility:
    """May this task merge with nobody watching?

    Every branch below refuses. There is no path that returns ok=True by
    falling off the end, because the failure mode of an eligibility rule is
    to be accidentally permissive.
    """
    contract = task.get("acceptance_contract") or {}
    work_type = contract.get("work_type")

    # 1. The hard rule. Not a default; not overridable.
    if work_type in NEVER_UNATTENDED:
        return Eligibility(False, (
            f"{work_type} exists to be read by a person, so it never merges "
            f"unattended. This is not the contract's flag -- no flag makes it "
            f"eligible."))

    # 2. The opt-OUT. Absent means eligible: see the module docstring for why
    #    that default is what it is and when it should stop being it.
    if contract.get("auto_merge") is False:
        return Eligibility(False, (
            "the spec set auto_merge: false, so this one is for a person to "
            "look at. It is waiting in the console."))

    # 3. There must be evidence the NEW behaviour works, not merely that
    #    nothing broke. Everything from here down is about that.
    if reverification is None:
        return Eligibility(False, (
            "nothing re-verified this merge, so nothing is known about the "
            "tree it would produce"))
    if getattr(reverification, "skipped_reason", ""):
        return Eligibility(False, (
            f"re-verification did not run ({reverification.skipped_reason}), "
            f"so a green here would mean nothing was checked"))
    if getattr(reverification, "could_not_run", False):
        return Eligibility(False, (
            "re-verification could not run, which is not the same as passing"))
    if not getattr(reverification, "ok", False):
        return Eligibility(False, (
            f"re-verification did not pass, so this is not merging: "
            f"{getattr(reverification, 'reason', '') or 'no reason recorded'}"))

    if not contract.get("creatable_paths"):
        return Eligibility(False, (
            "the contract permits no new test file, so the agent could not "
            "have added one -- a green suite here proves the change broke "
            "nothing and cannot show the new behaviour works"))

    bite = _check(reverification, BITE_CHECK)
    if bite is None:
        return Eligibility(False, (
            f"{BITE_CHECK} did not run, so it is not established that the "
            f"added test fails without the change. Without that a passing "
            f"suite is not evidence about this change at all"))
    if bite.get("exit_code") != 0:
        return Eligibility(False, (
            f"the added test did not bite: {BITE_CHECK} exited "
            f"{bite.get('exit_code')}. It passes against the tree BEFORE the "
            f"change, so it is not testing the change"))

    checks = [{"command": c.get("command"), "exit_code": c.get("exit_code"),
               "duration_ms": c.get("duration_ms")}
              for c in (reverification.checks or [])]
    return Eligibility(True, "", gates={
        "work_type": work_type,
        "auto_merge": contract.get("auto_merge", "default (absent)"),
        "reverified": True,
        "test_bit": True,
        "merged_sha": getattr(reverification, "merged_sha", None),
        "base_sha": getattr(reverification, "base_sha", None),
        "checks": checks,
        # Named so a reader does not have to infer it from the absence of a
        # note. The brief prints this.
        "reviewed_by_a_person": False,
    })


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(msg, flush=True)


def sweep(*, dry_run: bool = False, log=_log) -> list[dict[str, Any]]:
    """Every READY_FOR_REVIEW task, considered once. Never raises.

    It goes through `merge.preflight`, `reverify.run` and `merge.merge_and_push`
    -- the same three the Accept route uses, in the same order, with the same
    refusals. This module adds ONE thing to that path and removes nothing: the
    eligibility question, asked after re-verification and before the merge.

    NOT the Accept route itself. That takes `rendered_at` from a form and
    checks the request's origin, both of which exist because a browser posted
    it; satisfying them from a timer would mean inventing a page render that
    did not happen.
    """
    from pathlib import Path

    from . import config, db, decide, merge, reverify
    from runner import worktree

    out: list[dict[str, Any]] = []
    with db.connect() as conn:
        waiting = conn.execute(
            "SELECT * FROM tasks WHERE status = 'READY_FOR_REVIEW'"
            " ORDER BY id").fetchall()

    for task in waiting:
        tid = task["id"]
        run = None
        with db.connect() as conn:
            r = conn.execute(
                "SELECT id FROM runs WHERE task_id = %s ORDER BY id DESC LIMIT 1",
                (tid,)).fetchone()
            run = r["id"] if r else None
            patch = conn.execute(
                "SELECT s.payload FROM run_steps s JOIN runs r ON r.id = s.run_id"
                " WHERE r.task_id = %s AND s.step_type = 'PATCH_PROPOSED'"
                " ORDER BY s.id DESC LIMIT 1", (tid,)).fetchone()
        patch = (patch or {}).get("payload") or {}
        repo = config.repo_root() / task["repo"]
        branch = task["branch_name"]
        contract = task["acceptance_contract"] or {}

        # Cheap refusals first, so an ineligible task never builds a clone.
        early = eligible(task, None) if contract.get("work_type") in NEVER_UNATTENDED \
            or contract.get("auto_merge") is False else None
        if early is not None and not early.ok:
            log(f"task {tid}: left for review — {early.reason}")
            out.append({"task_id": tid, "merged": False, "reason": early.reason})
            continue

        check = merge.preflight(repo, task, branch,
                                patch.get("base_commit_sha", ""),
                                patch.get("patch_commit_sha", ""),
                                patch.get("branch_point_sha", ""))
        if not check.ok:
            log(f"task {tid}: left for review — {check.reason}")
            out.append({"task_id": tid, "merged": False, "reason": check.reason})
            continue
        if check.already_merged:
            log(f"task {tid}: already merged; a person records that one")
            out.append({"task_id": tid, "merged": False,
                        "reason": "already merged"})
            continue

        again = None
        try:
            again = reverify.run(
                repo, config.trial_root(), task, contract, branch,
                recorded_base=patch.get("base_commit_sha", ""),
                changed_files=[p for p in (patch.get("files_changed") or [])
                               if (patch.get("file_status") or {}).get(p) != "D"],
                keep_on_success=True)

            verdict = eligible(task, again)
            if not verdict.ok:
                log(f"task {tid}: left for review — {verdict.reason}")
                out.append({"task_id": tid, "merged": False,
                            "reason": verdict.reason})
                continue

            if dry_run:
                log(f"task {tid}: WOULD merge unattended ({again.merged_sha[:12]})")
                out.append({"task_id": tid, "merged": False, "dry_run": True,
                            "would_merge": again.merged_sha})
                continue

            result = merge.merge_and_push(
                repo, task, branch,
                recorded_base=patch.get("base_commit_sha", ""),
                recorded_patch=patch.get("patch_commit_sha", ""),
                branch_point=patch.get("branch_point_sha", ""),
                reverification=again)
            if not result.ok:
                log(f"task {tid}: NOT merged — {result.reason}")
                out.append({"task_id": tid, "merged": False,
                            "reason": result.reason})
                continue

            gates = dict(verdict.gates)
            gates["merge_commit"] = result.base_sha_after
            gates["pushed"] = result.pushed
            gates["push_verified"] = result.push_verified
            decide.record(
                task=task, run_id=run, verdict="MERGED",
                decision=decide.ACCEPT_DECISION, note=None, rendered_at=None,
                decided_via="unattended", gates=gates,
                merge={"reverified": again.as_record(),
                       "already_merged": False,
                       "merge_commit": result.base_sha_after,
                       "base_before": result.base_sha_before,
                       "branch_tip": result.branch_tip,
                       "pushed": result.pushed,
                       "push_verified": result.push_verified,
                       "remote_sha": result.remote_sha})
            log(f"task {tid}: MERGED unattended as {result.base_sha_after[:12]}")
            out.append({"task_id": tid, "merged": True,
                        "sha": result.base_sha_after})
        except Exception as exc:                                  # noqa: BLE001
            # A sweep that dies on one task must not skip the rest, and must
            # not leave a task looking considered when it was not.
            log(f"task {tid}: sweep error, left for review — {exc}")
            out.append({"task_id": tid, "merged": False, "reason": str(exc)})
        finally:
            if again is not None and again.trial_path:
                worktree.discard_trial_clone(Path(again.trial_path))
    return out
