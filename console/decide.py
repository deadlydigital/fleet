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


#: How the decision was arrived at. Not a status and not a verdict: the task
#: is MERGED either way, because it IS merged. This says who performed it.
#:
#: `by_hand` exists because a merge outside the console is a real event the
#: record must be able to express. Task 26 was merged by hand on 8 Sep after
#: the console refused a push into a stale base, and until this parameter
#: existed the only supported writer asserted `console` -- so recording the
#: truth meant either lying in this field or writing rows around the one
#: function that keeps the step and the status transition in a transaction.
#: "unattended" and not "auto": the word that matters is that NOBODY WAS
#: WATCHING, not that a machine did it. A reader who sees "auto" asks which
#: automation; a reader who sees "unattended" knows what to check.
DECIDED_VIA = ("console", "by_hand", "unattended")


def record(*, task: dict, run_id: int, verdict: str, decision: str,
           note: str | None, rendered_at: float | None,
           merge: dict[str, Any] | None = None,
           decided_via: str = "console",
           gates: dict[str, Any] | None = None) -> dict[str, Any]:
    """Move the task and write the step, in one transaction.

    `verdict` is the task status -- MERGED or REJECTED. `decision` is the
    run_steps vocabulary -- APPROVED or one of the REJECTED_* codes. They are
    separate because they answer different questions: what happened to the
    task, and why the person decided it.

    `decided_via` is a third question again: WHO PERFORMED IT. A merge made
    outside the console is still a merge, and the status should say so; the
    provenance belongs here rather than in a new status that fourteen readers
    would have to learn.

    AN UNATTENDED MERGE RECORDS TWO FIELDS DIFFERENTLY, AND BOTH MATTER
    --------------------------------------------------------------------
    `decision_seconds` is `now - rendered_at`, which is how long a REVIEW took.
    An unattended merge had no review, so `rendered_at` is None and the field
    is NULL. Writing 0.0 would read as "decided instantly", which is a claim
    about a person who does not exist -- the same defect as `sent_at` on a row
    nothing sent.

    `note` is where a person types why, so it stays NULL too. `gates` carries
    the machine record instead: which checks ran, what they exited, whether the
    added test bit, and the sha that landed. "Why" stays answerable without
    fabricating prose that nobody wrote.

    `decision` is still APPROVED. It is 001's vocabulary and fourteen readers
    know it; provenance belongs in `decided_via`, which is the argument this
    module already makes for `by_hand`. A fourth status would be the
    MERGED_OUTSIDE mistake again.
    """
    if decided_via not in DECIDED_VIA:
        raise VerdictNotRecorded(
            f"{decided_via!r} is not a way a decision can be arrived at; "
            f"known: {', '.join(DECIDED_VIA)}")
    if verdict not in ("MERGED", "REJECTED"):
        raise VerdictNotRecorded(f"{verdict} is not a task verdict")
    if decision != ACCEPT_DECISION and decision not in REJECT_REASONS:
        raise VerdictNotRecorded(f"{decision} is not a reason the database accepts")

    if decided_via == "unattended":
        if rendered_at is not None:
            raise VerdictNotRecorded(
                "an unattended decision cannot carry a rendered_at: there was "
                "no page and no review, and a duration derived from one would "
                "be a measurement of nobody")
        if (note or "").strip():
            raise VerdictNotRecorded(
                "an unattended decision cannot carry a note. `note` is where a "
                "person says why; use `gates` for what the checks reported")
        if not gates:
            raise VerdictNotRecorded(
                "an unattended decision must carry its gates. A merge nobody "
                "watched, with no record of what was checked, is unreviewable "
                "afterwards -- which is the whole thing the brief has to be "
                "able to show")
    elif rendered_at is None:
        raise VerdictNotRecorded(
            f"a {decided_via!r} decision needs a rendered_at; only an "
            f"unattended one has no review to measure")

    decision_seconds = (None if rendered_at is None
                        else round(max(0.0, time.time() - rendered_at), 1))
    payload: dict[str, Any] = {
        "decision": decision,
        "verdict": verdict,
        "note": (note or "").strip() or None,
        "decided_via": decided_via,
        "decision_seconds": decision_seconds,
        "task_id": task["id"],
    }
    if merge:
        payload["merge"] = merge
    if gates:
        payload["gates"] = gates

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
