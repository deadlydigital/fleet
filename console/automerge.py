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
`research`, `candidate_producer` and `dd_infra` produce artefacts that exist to
be READ, or that swap production containers. It is a hard rule keyed on
work_type, not a default a contract can turn off.

`draft_spec` WAS ON THIS TUPLE AND CAME OFF IT ON 10 SEP 2026
--------------------------------------------------------------
It was the single remaining human gate, and removing it was asked for three
times and granted deliberately. What it cost is recorded here rather than only
in the spec, because the cost is inherited by whoever reads this code next.

**Nothing reads a spec at any point now.** specs/auto-approval.md §9.9 is the
measured account: task 53 shipped §2.5 of its own spec unbuilt with `tsc`,
`vitest`, `new_test_bites.sh` and `paired_paths.py` all green, because none of
them can read a spec. That was caught by `auto_merge: false` on the frontend
contract, which became `true` earlier the same day -- so the spec-against-diff
comparison was already gone. This removes the other reading: the person who
read the DRAFT, before the work existed, and judged whether it was the right
work at all.

**The failure it admits has no revert trigger.** A partially-built feature is
not a bad merge. Nothing fails, nothing reverts, nothing pages. §9.9.1 records
the mirror case on task 55, which built MORE than its spec on a premise about
the tree that was false. Two of the last three tasks did one or the other.

**What still catches part of it.** Gate 6 (030_candidate_premise.sql) re-runs
what a candidate rests on at approval time, which is the task-55 class. Nothing
catches the task-53 class -- a true premise, a right spec, a requirement
quietly dropped -- because at approval time there is nothing wrong yet.
specs/auto-approval.md §9.12 costs the cheapest thing that would notice, at
about eighty lines, and its one stated objection ("on the frontend contract,
where a person already reads the spec, it adds annotation cost for a check
weaker than the reader it sits beside") expired with this change. There is no
reader on any path to be weaker than.

**What carries it after the fact.** `brief/pass_.py` lists the numbered
requirements of anything merged unattended, and the morning page's "Needs you"
now carries the same list as an ask against the merge. Neither notices
anything; both put the comparison in front of the one person who will make it,
after the feature has shipped. That is the trade this change makes explicit:
a shipped feature you can see was partially built, instead of a gate you sit
at.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

#: Work types whose whole purpose is to be read by a person. No contract flag
#: makes these eligible.
NEVER_UNATTENDED = ("research", "candidate_producer",
                    # A script that swaps production containers is read
                    # by a person before it lands, whatever its checks
                    # said. The shape check proves it is shaped like a
                    # deploy; nothing proves it deploys.
                    "dd_infra")

#: The check whose passing is the only evidence that the NEW behaviour works
#: rather than that nothing broke. See contracts/checks/new_test_bites.sh.
BITE_CHECK = "new_test_bites.sh"

#: Work types that produce a DOCUMENT, for which the added-test gate below is
#: not a weaker check -- it is not a check at all.
#:
#: TAKING `draft_spec` OFF NEVER_UNATTENDED DID NOT MAKE IT MERGE, and finding
#: that out is why this exists. It fell through to gate 3 and was refused for
#: "the contract permits no new test file", which is true of
#: contracts/draft-spec.yaml and always will be: a draft spec writes one
#: markdown file under `drafts/**`, the contract refuses a diff containing
#: anything else, and there is no behaviour for a test to bite on. The bite
#: check is not in its verification list either, so the next clause would have
#: refused it too.
#:
#: A rule that cannot be satisfied is not a strict rule, it is a disabled
#: feature with a misleading message -- and the first version of this change
#: shipped a test that passed while the real contract could never have got
#: past this point, because the fixture contract carried `creatable_paths`
#: that the real one does not.
#:
#: WHAT A DOCUMENT MUST STILL SATISFY, which is everything above gate 3:
#: re-verification ran, was not skipped, did not fail to run, and passed. For
#: a draft spec that means `draft_spec_shape.py` passed against the merged
#: tree -- the declared block parses, its work_type names a contract that
#: exists, every declared path resolves, none is on the floor, and the paths
#: cited in prose resolve. That is the evidence a document can offer.
#:
#: WHAT IT DOES NOT ESTABLISH, and this is the cost the whole change accepts:
#: whether the spec describes work worth doing, whether its approach is right,
#: or whether the paths it names are the RELEVANT ones. draft_spec_shape.py's
#: own docstring says so. Nothing reads a spec now. See the module docstring.
DOCUMENT_WORK_TYPES = ("draft_spec",)


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


#: A link is ready when it has verified and is waiting to merge, or has
#: already merged. Anything else -- still queued, running, failed, rejected --
#: means the chain is not complete.
CHAIN_READY = ("READY_FOR_REVIEW", "MERGED")


HALF_FAILED = ("FAILED", "REJECTED", "ABANDONED")


def half_failed_chains(conn) -> list[dict]:
    """Chains where one link is over and another is still holding.

    A link that failed after a sibling passed says something about the SPLIT
    was wrong. specs/auto-approval.md §12: retrying the failed link against a
    held sibling compounds a bad split rather than recovering from it, so
    nothing here resumes anything.
    """
    rows = conn.execute(
        "SELECT c.candidate_id, c.position, c.task_id, t.status, t.title,"
        "       t.branch_name, c.contract_file"
        "  FROM task_chain c LEFT JOIN tasks t ON t.id = c.task_id"
        " ORDER BY c.candidate_id, c.position").fetchall()
    by_cand: dict = {}
    for r in rows:
        by_cand.setdefault(r["candidate_id"], []).append(r)
    out = []
    for cid, links in by_cand.items():
        dead = [l for l in links if l["status"] in HALF_FAILED]
        if not dead:
            continue
        if all(l["status"] in HALF_FAILED for l in links):
            # EVERY link is over. Nothing is held and nothing half-shipped;
            # this is an ordinary failed candidate and not this finding.
            continue
        out.append({"candidate_id": cid, "links": links, "dead": dead,
                    "held": [l for l in links
                             if l["status"] not in HALF_FAILED]})
    return out


def release_half_failed(conn, log=print) -> list[int]:
    """Return the candidate to PENDING and leave every branch where it is.

    THE BRANCHES STAY. Unmerged, unreferenced, and cheap -- and they are the
    evidence of what the split produced, which is the thing a person needs in
    order to decide whether the split was the problem. Deleting them would
    tidy away the only artefact of a failure whose lesson is in it.

    NOTHING IS RESUMED. The candidate is PENDING, so a later night may pick it
    up again and a new draft may split it differently. That is a fresh
    decision by the ranker, not a retry of a chain that half-failed.
    """
    released = []
    for chain in half_failed_chains(conn):
        cid = chain["candidate_id"]
        row = conn.execute(
            "SELECT disposition FROM candidates WHERE id=%s", (cid,)).fetchone()
        if row is None or row["disposition"] == "PENDING":
            continue                      # already released
        dead = ", ".join(f"task {l['task_id']} ({l['status']})"
                         for l in chain["dead"])
        held = ", ".join(f"task {l['task_id']} ({l['status']})"
                         for l in chain["held"])
        conn.execute(
            "UPDATE candidates SET disposition='PENDING', work_task_id=NULL,"
            " approval_decision_id=NULL, decided_at=NULL WHERE id=%s", (cid,))
        log(f"candidate {cid}: chain half-failed — {dead}; {held} held and "
            f"not merged. Returned to PENDING; branches kept.")
        released.append(cid)
    return released


def chain_state(conn, task_id: int) -> Optional[dict]:
    """This task's chain, or None if it is not a link.

    Read as one query for the task rather than per link, and returned as data
    so `eligible` stays pure -- the same argument console/rank.gate makes for
    taking `writables` and `floor` as arguments.
    """
    row = conn.execute(
        "SELECT candidate_id, position FROM task_chain WHERE task_id = %s",
        (task_id,)).fetchone()
    if row is None:
        return None
    links = conn.execute(
        "SELECT c.position, c.task_id, t.status"
        "  FROM task_chain c LEFT JOIN tasks t ON t.id = c.task_id"
        " WHERE c.candidate_id = %s ORDER BY c.position",
        (row["candidate_id"],)).fetchall()
    waiting = [f"task {l['task_id']} ({l['status'] or 'not queued'})"
               for l in links
               if l["task_id"] != task_id and l["status"] not in CHAIN_READY]
    return {"candidate_id": row["candidate_id"], "position": row["position"],
            "length": len(links), "waiting": waiting,
            "complete": not waiting,
            "failed": [f"task {l['task_id']}" for l in links
                       if l["status"] in ("FAILED", "REJECTED", "ABANDONED")]}


def eligible(task: dict, reverification: Any,
             chain: Optional[dict] = None) -> Eligibility:
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

    # 2b. A LINK MAY NOT MERGE WHILE ITS CHAIN IS INCOMPLETE.
    #
    #     specs/auto-approval.md §12. A candidate whose paths no single
    #     contract covers is split into an ordered chain, and the whole point
    #     is that the halves merge together or not at all. Task 28 is what
    #     happens otherwise: the comparison-window backend merged on 9 Sep,
    #     the half that would have made it reachable was queued by hand six
    #     hours later and failed, and candidates 22 and 30 are still PENDING.
    #
    #     AHEAD OF THE RE-VERIFICATION because it is free and that is not, and
    #     behind the hard rules so a row they hold keeps reporting them.
    #
    #     IT FAILS CLOSED. `chain` is passed IN; a caller that does not supply
    #     it gets no hold, which is right for every existing caller -- a task
    #     with no chain is not a link -- and console/automerge.sweep reads it
    #     for every task it considers.
    if chain and not chain.get("complete"):
        waiting = chain.get("waiting") or []
        return Eligibility(False, (
            f"this is link {chain.get('position')} of {chain.get('length')} "
            f"for candidate {chain.get('candidate_id')}, and "
            f"{len(waiting)} of its links {'is' if len(waiting) == 1 else 'are'} "
            f"not ready: {waiting}. No link merges until every link has "
            f"verified, so a failure in one leaves none of them shipped."))

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

    # 4. Evidence that the NEW behaviour works. Skipped for a document,
    #    which has no behaviour -- see DOCUMENT_WORK_TYPES above for what it
    #    is held to instead and what that leaves uncovered.
    if work_type in DOCUMENT_WORK_TYPES:
        return Eligibility(True, "", gates={
            "work_type": work_type,
            "auto_merge": contract.get("auto_merge", "default (absent)"),
            "reverified": True,
            # NOT True, and not omitted. False here is a fact about this
            # merge that a later reader needs: no test bit, because there was
            # nothing for one to bite on.
            "test_bit": False,
            "document": True,
            "merged_sha": getattr(reverification, "merged_sha", None),
            "base_sha": getattr(reverification, "base_sha", None),
            "checks": [{"command": c.get("command"),
                        "exit_code": c.get("exit_code"),
                        "duration_ms": c.get("duration_ms")}
                       for c in (reverification.checks or [])]})

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

    from . import autoqueue, config, db, decide, merge, reverify
    from runner import worktree

    out: list[dict[str, Any]] = []
    with db.connect() as conn:
        waiting = conn.execute(
            "SELECT * FROM tasks WHERE status = 'READY_FOR_REVIEW'"
            " ORDER BY id").fetchall()

    # BEFORE ANYTHING IS CONSIDERED. A chain that half-failed is holding a
    # sibling that will never merge, and leaving it held means the ranker sees
    # a candidate it cannot re-approve and the queue carries a task nothing
    # will ever take. §12: released, never resumed.
    if not dry_run:
        with db.writer() as conn, conn.transaction():
            release_half_failed(conn, log)

    for task in waiting:
        tid = task["id"]
        repo = config.repo_root() / task["repo"]
        branch = task["branch_name"]
        contract = task["acceptance_contract"] or {}

        # THE RUN IS THE ONE THAT PRODUCED THIS BRANCH, not the newest one.
        #
        # This took the newest patch step, which was the same row right up
        # until 038 made it possible for branch_name to point at an earlier
        # run's branch. On task 69 -- adopted at fleet/task-69.3 from run 44 --
        # the newest step belonged to run 45 and fleet/task-69.4, so this swept
        # one branch and checked another. It refused, which is the right
        # failure and not a reason to leave it: a sweep whose refusal names the
        # wrong two shas sends somebody to look for tampering that never
        # happened. See console.queries.PATCH_FOR_TIP.
        tip = merge.branch_tip(repo, branch or "")
        with db.connect() as conn:
            row = conn.execute(
                "SELECT s.run_id, s.payload FROM run_steps s"
                " JOIN runs r ON r.id = s.run_id"
                " WHERE r.task_id = %s AND s.step_type = 'PATCH_PROPOSED'"
                "   AND s.payload->>'patch_commit_sha' = %s"
                " ORDER BY s.run_id DESC LIMIT 1", (tid, tip)).fetchone() if tip else None
        if row is None:
            reason = (f"no run of this task recorded {branch} at the commit it "
                      f"is on, so nothing says what would merge")
            log(f"task {tid}: left for review — {reason}")
            out.append({"task_id": tid, "merged": False, "reason": reason})
            continue
        patch = row["payload"] or {}
        # The run whose verdict this merge would be standing on, which is now
        # the run that built the branch rather than whichever ran last.
        run = row["run_id"]

        with db.connect() as conn:
            chain = chain_state(conn, tid)

        # Cheap refusals first, so an ineligible task never builds a clone.
        # The chain hold is among them: a link whose sibling is still running
        # must not spend a trial clone and a full verification to be told so.
        if chain and not chain.get("complete"):
            held = eligible(task, None, chain)
            log(f"task {tid}: left for review — {held.reason}")
            out.append({"task_id": tid, "merged": False, "reason": held.reason})
            continue

        early = eligible(task, None, chain) if contract.get("work_type") in NEVER_UNATTENDED \
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

            verdict = eligible(task, again, chain)
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

            # THE CHAIN CONTINUES ITSELF, AND SINCE 10 SEP 2026 IT RUNS.
            #
            # This branch was written while `draft_spec` was still on
            # NEVER_UNATTENDED, against the day it came off. That day is now:
            # the sweep merges a draft at 03:30 and queues the code task it
            # describes in the same pass, so the night does not end with a
            # spec merged and nothing built.
            #
            # console/app.py makes the same call on the accept route, which is
            # still a real path -- a person may accept a draft before 03:30.
            # Both callers are `autoqueue.from_accepted_draft`, so there is one
            # implementation and the two paths cannot drift.
            #
            # A refusal is logged and does NOT fail the sweep: the draft is
            # merged and pushed either way, and the other tasks in this sweep
            # have nothing to do with it. It is the one place in the loop where
            # a failure leaves work stranded rather than refused, so it says so
            # loudly and the morning brief carries the merge without a task.
            queued = None
            if (contract.get("work_type") == "draft_spec"
                    and not result.already_merged):
                try:
                    queued = autoqueue.from_accepted_draft(
                        task, patch, result.base_sha_after)
                    log(f"task {tid}: queued task {queued.task_id} from its "
                        f"spec, under {queued.contract_file}")
                except Exception as exc:                          # noqa: BLE001
                    log(f"task {tid}: MERGED but the code task was NOT queued "
                        f"-- {exc}")

            out.append({"task_id": tid, "merged": True,
                        "sha": result.base_sha_after,
                        "queued_task_id": queued.task_id if queued else None})
        except Exception as exc:                                  # noqa: BLE001
            # A sweep that dies on one task must not skip the rest, and must
            # not leave a task looking considered when it was not.
            log(f"task {tid}: sweep error, left for review — {exc}")
            out.append({"task_id": tid, "merged": False, "reason": str(exc)})
        finally:
            if again is not None and again.trial_path:
                worktree.discard_trial_clone(Path(again.trial_path))
    return out
