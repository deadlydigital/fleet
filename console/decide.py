"""Recording a task verdict.

The verdict is two writes and they must not be able to disagree, so they are
one transaction: the task's status transition, and a HUMAN_DECISION step on
its run.

WHY HUMAN_DECISION AND NOT `decisions`
    `decisions.proposal_id` is NOT NULL and references `proposals`. A task
    verdict structurally cannot live there. 001 already built the right home:
    `step_authority` gates HUMAN_DECISION to fleet_console, and the reason
    vocabulary in run_steps' CHECK is branch-shaped -- wrong fix, excessive
    scope, insufficient evidence -- which is what you reject a diff for.

TIMING
    Both numbers the design is measured on, and neither is invented.
    `waited_seconds` is how long the task sat in READY_FOR_REVIEW, from the
    completed_at the runner stamped. `decision_seconds` is how long the review
    took, measured from when the page rendered to when the verdict arrived --
    the same clock `review.py` runs on a proposal. A review whose page was
    opened yesterday reports the honest large number rather than a tidy one.
"""
from __future__ import annotations

import re
import time
from typing import Any

from psycopg.types.json import Jsonb

from console import db

ACCEPT_DECISION = "APPROVED"

# The vocabulary 001 put in run_steps' CHECK constraint, restated here so the
# page can render it without a database round trip on every request.
#
# Restating it is a duplication, and duplication of a constraint is how a page
# comes to offer a value the database refuses. So it is not trusted:
# `reasons_in_database()` reads the constraint back, and a test asserts the two
# agree. If 001's list ever changes, that test fails rather than a reviewer
# discovering it at the moment they press Reject.
REJECT_REASONS = (
    "REJECTED_WRONG_DIAGNOSIS",
    "REJECTED_WRONG_FIX",
    "REJECTED_EXCESSIVE_SCOPE",
    "REJECTED_INSUFFICIENT_EVIDENCE",
    "REJECTED_RISK",
    "REJECTED_PRODUCT_DECISION",
    "REJECTED_DUPLICATE",
)

REASON_HELP = {
    "REJECTED_WRONG_DIAGNOSIS": "it solved a problem the task did not have",
    "REJECTED_WRONG_FIX": "right problem, wrong change",
    "REJECTED_EXCESSIVE_SCOPE": "it did more than the spec asked for",
    "REJECTED_INSUFFICIENT_EVIDENCE": "it may be right; nothing here shows that it is",
    "REJECTED_RISK": "plausible, and not worth the blast radius",
    "REJECTED_PRODUCT_DECISION": "a judgement call that went the other way",
    "REJECTED_DUPLICATE": "already done, or already in flight elsewhere",
}


def reasons_in_database() -> set[str]:
    """The REJECTED_* codes run_steps' CHECK constraint actually permits."""
    row = db.one(
        """
        SELECT pg_get_constraintdef(con.oid) AS def
          FROM pg_constraint con
          JOIN pg_class c ON c.oid = con.conrelid
         WHERE c.relname = 'run_steps' AND con.contype = 'c'
           AND pg_get_constraintdef(con.oid) LIKE %(pat)s
        """, {"pat": "%HUMAN_DECISION%"})
    if not row:
        return set()
    return set(re.findall(r"'(REJECTED_[A-Z_]+)'", row["def"]))


class VerdictNotRecorded(RuntimeError):
    """The merge may have happened. The verdict did not. Say so loudly."""


def _next_sequence(conn, run_id: int) -> int:
    row = conn.execute(
        "SELECT coalesce(max(sequence), 0) + 1 AS n FROM run_steps WHERE run_id = %s",
        (run_id,)).fetchone()
    return row["n"]


def record(*, task: dict, run_id: int, verdict: str, decision: str,
           note: str | None, rendered_at: float,
           merge: dict[str, Any] | None = None) -> dict[str, Any]:
    """Move the task and write the step, in one transaction.

    `verdict` is the task status -- MERGED or REJECTED. `decision` is the
    run_steps vocabulary -- APPROVED or one of the REJECTED_* codes. They are
    separate because they answer different questions: what happened to the
    task, and why the person decided it.
    """
    if verdict not in ("MERGED", "REJECTED"):
        raise VerdictNotRecorded(f"{verdict} is not a task verdict")
    if decision != ACCEPT_DECISION and decision not in REJECT_REASONS:
        raise VerdictNotRecorded(f"{decision} is not a reason the database accepts")

    decision_seconds = max(0.0, time.time() - rendered_at)
    payload: dict[str, Any] = {
        "decision": decision,
        "verdict": verdict,
        "note": (note or "").strip() or None,
        "decided_via": "console",
        "decision_seconds": round(decision_seconds, 1),
        "task_id": task["id"],
    }
    if merge:
        payload["merge"] = merge

    try:
        with db.writer() as conn:
            with conn.transaction():
                waited = conn.execute(
                    "SELECT extract(epoch FROM (now() - completed_at)) AS s,"
                    "       status FROM tasks WHERE id = %s FOR UPDATE",
                    (task["id"],)).fetchone()
                if waited is None:
                    raise VerdictNotRecorded(f"task {task['id']} is gone")
                if waited["status"] != "READY_FOR_REVIEW":
                    raise VerdictNotRecorded(
                        f"task {task['id']} is {waited['status']}, not "
                        f"READY_FOR_REVIEW -- it was decided by something else "
                        f"while this page was open")
                payload["waited_seconds"] = (
                    round(float(waited["s"]), 1) if waited["s"] is not None else None)

                conn.execute(
                    "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
                    " VALUES (%s, %s, 'HUMAN_DECISION', %s, %s)",
                    (run_id, _next_sequence(conn, run_id), "console", Jsonb(payload)))
                conn.execute("UPDATE tasks SET status = %s WHERE id = %s",
                             (verdict, task["id"]))
    except VerdictNotRecorded:
        raise
    except Exception as exc:                                     # noqa: BLE001
        raise VerdictNotRecorded(str(exc)) from exc

    return payload
