"""Undoing one night's approval, before anything has been spent on it.

specs/auto-approval.md §5, correction 4. The brief prints this command beside
every unattended approval, and it prints it as copy-paste for the reason the
revert line is copy-paste: "the command to do that should be copy-paste rather
than a lookup at the moment somebody is annoyed."

WHAT IT DOES, AND THE BOUNDARY IS THE CLAIM

    the spec task, if still QUEUED   -> ABANDONED
    the candidate                    -> back to PENDING, as though never ticked
    the decision_log row             -> LEFT WHERE IT IS
    a second decision_log row        -> written, saying it was undone and why

THE ORIGINAL ROW IS NOT DELETED AND NOT EDITED. specs/auto-approval.md §0 says
the `decided_via='unattended'` rows stay as the record of the period when this
was on, and a log that can be tidied afterwards is not a record. So the undo is
a NEW decision citing the old one -- the same shape `decision_outcomes` already
expects, and the same reason 010 refuses to let a decision be rewritten.

IT IS ONLY COMPLETE BEFORE THE TASK IS CLAIMED. Once the runner has it, the £2
is committed and a branch exists; this abandons what it can and says plainly
what it could not, rather than reporting a clean undo over a task that is
already running.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from . import db


class UndoRefused(Exception):
    """Nothing was changed. The message says what stopped it."""


#: A spec task in one of these has not started, so abandoning it costs nothing
#: and returns the candidate cleanly. 003's task_transitions is what actually
#: decides; this list is what the message is written against.
UNSTARTED = ("QUEUED",)


def undo_approval(decision_id: int, *, reason: str | None = None,
                  dry_run: bool = False) -> Dict[str, Any]:
    """Return one batch's candidates to PENDING and abandon their spec tasks."""
    with db.writer() as conn, conn.transaction():
        decision = conn.execute(
            "SELECT id, decision, decided_via, decided_at, reason"
            " FROM decision_log WHERE id=%s", (decision_id,)).fetchone()
        if decision is None:
            raise UndoRefused(f"there is no decision {decision_id}")
        if decision["decision"] != "APPROVED":
            raise UndoRefused(
                f"decision {decision_id} is {decision['decision']}, not an "
                f"approval; there is nothing here to undo")

        rows = conn.execute(
            "SELECT c.id, c.title, c.spec_task_id, t.status AS task_status"
            "  FROM candidates c LEFT JOIN tasks t ON t.id = c.spec_task_id"
            " WHERE c.approval_decision_id = %s ORDER BY c.id",
            (decision_id,)).fetchall()
        if not rows:
            raise UndoRefused(
                f"decision {decision_id} has no candidates citing it. It may "
                f"already have been undone -- decision_log keeps both rows, so "
                f"look for a later decision citing this one.")

        undone: List[Dict[str, Any]] = []
        kept: List[Dict[str, Any]] = []
        for r in rows:
            if r["spec_task_id"] is not None and r["task_status"] not in UNSTARTED:
                # Deliberately NOT forced. A RUNNING task can be abandoned by
                # this role, but doing it here would kill an agent mid-write and
                # leave a worktree behind, which is a different operation from
                # "this was never approved" and should be typed deliberately.
                kept.append({"candidate_id": r["id"], "task_id": r["spec_task_id"],
                             "task_status": r["task_status"],
                             "why": f"task {r['spec_task_id']} is "
                                    f"{r['task_status']}, not {'/'.join(UNSTARTED)}"})
                continue
            undone.append({"candidate_id": r["id"], "task_id": r["spec_task_id"],
                           "title": r["title"]})

        if dry_run:
            return {"decision_id": decision_id, "undone": undone, "kept": kept,
                    "follow_up_decision_id": None, "dry_run": True}

        if not undone:
            raise UndoRefused(
                f"none of decision {decision_id}'s {len(rows)} candidate(s) can "
                f"be returned: " + "; ".join(k["why"] for k in kept) +
                ". Past the claim the £2 is committed and a branch exists, so "
                "this is a rejection at review rather than an undo.")

        for u in undone:
            if u["task_id"] is not None:
                conn.execute(
                    "UPDATE tasks SET status='ABANDONED', completed_at=now()"
                    " WHERE id=%s AND status = ANY(%s)",
                    (u["task_id"], list(UNSTARTED)))
            # decided_at goes back to NULL with the disposition: 013's
            # candidates_decided_is_stamped_ck ties the two together, so a row
            # that is PENDING and still stamped cannot exist.
            conn.execute(
                "UPDATE candidates SET disposition='PENDING', decided_at=NULL,"
                " approval_decision_id=NULL, spec_task_id=NULL WHERE id=%s",
                (u["candidate_id"],))

        note = (reason or "").strip() or (
            "undone from the morning brief; no reason typed. The candidates are "
            "PENDING again and will be re-ranked tonight, so an undo with no "
            "reason is a delay rather than a decision.")
        conn.execute(
            "INSERT INTO decision_log (product, subject, decision, reason,"
            " decided_by, evidence) VALUES (%s,%s,'REJECTED',%s,"
            " coalesce(%s, current_user), %s)",
            ("fleet",
             f"Undo decision {decision_id}: {len(undone)} candidate(s) "
             f"returned to PENDING",
             f"Undoing decision {decision_id}. {note}", None,
             json.dumps(
                 [{"kind": "decision", "id": decision_id}] +
                 [{"kind": "candidate", "id": u["candidate_id"]} for u in undone] +
                 [{"kind": "task", "id": u["task_id"]}
                  for u in undone if u["task_id"] is not None])))
        follow_up = conn.execute(
            "SELECT currval('decision_log_id_seq') AS id").fetchone()["id"]

    return {"decision_id": decision_id, "undone": undone, "kept": kept,
            "follow_up_decision_id": follow_up, "dry_run": False}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Undo one approval: abandon its unclaimed spec tasks and "
                    "return its candidates to PENDING.")
    ap.add_argument("decision_id", type=int)
    ap.add_argument("--reason", help="why it is being undone; recorded on the "
                                     "follow-up decision")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    try:
        out = undo_approval(args.decision_id, reason=args.reason,
                            dry_run=args.dry_run)
    except UndoRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    what = "would return" if out["dry_run"] else "returned"
    print(f"{what} {len(out['undone'])} candidate(s) to PENDING: "
          f"{[u['candidate_id'] for u in out['undone']]}")
    for u in out["undone"]:
        if u["task_id"] is not None:
            print(f"  task {u['task_id']} "
                  f"{'would be' if out['dry_run'] else ''} abandoned")
    for k in out["kept"]:
        print(f"  KEPT c{k['candidate_id']}: {k['why']}")
    if out["follow_up_decision_id"]:
        print(f"  decision {out['decision_id']} is unchanged; decision "
              f"{out['follow_up_decision_id']} records the undo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
