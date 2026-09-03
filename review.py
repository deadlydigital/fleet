#!/usr/bin/env python3
"""Review the proposal layer's output.

    python review.py                     list undecided proposals with evidence
    python review.py review              decide each in turn, timing each one
    python review.py decide --proposal 7 --verdict REJECT --reason ALREADY_KNOWN \
                            --why "the fix is a product call, not a bug"
                                         one decision, non-interactively

Connects as fleet_console. It is the only role the database will accept a
decision from -- the trigger on decisions is the same rule as the one on
observation_verdicts, and for the same reason: a layer that can record its
own approval is an agent marking its own work as passing.

EVERY VERDICT ALSO OPENS A DECISION LOG ENTRY, IN THE SAME TRANSACTION
---------------------------------------------------------------------
`decisions` is this layer's grade on itself: an enum reason code, countable,
sized for finding out what the proposer is bad at. `decision_log` is the
record across everything -- proposals, issues, tasks -- with a free-text
reason, which is where the sentence goes that no enum was ever going to hold.
Both, not either: the code is what you count, the sentence is what you read
in six months.

One transaction. A verdict recorded without its log entry is precisely the
split the log was built to close, and two statements that can half-succeed
would reintroduce it on the first connection drop.

EVERY verdict, not only the ones that lead to action. Logging accepts and
dropping rejects would rebuild the asymmetry the log exists to remove -- a
rejected proposal with a reason is worth more than an approved one, because
approval leaves a branch behind and rejection leaves nothing.

SKIP logs nothing. Skipping is not deciding.

Every decision carries the seconds it took. The number is not decoration:
this layer costs human attention, and the only way to find out whether it
earns that is to measure it. In `review` the clock runs from the moment a
proposal finishes printing to the moment the verdict is entered. In `decide`
there is nothing to measure, so --seconds must be supplied and defaults to
zero, which is an honest zero rather than an invented duration.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row

from proposer import config

VERDICTS = ("ACCEPT", "REJECT", "DEFER_30D")
REASON_CODES = ("ALREADY_KNOWN", "WRONG_PRIORITY", "TOO_EXPENSIVE",
                "BAD_REASONING", "MISSING_CONTEXT", "NOT_MY_CALL",
                "DISAGREE_WITH_PREMISE")
VERDICT_KEYS = {"a": "ACCEPT", "r": "REJECT", "d": "DEFER_30D"}

#: The proposal verdict vocabulary, mapped onto the decision log's. They are
#: deliberately different vocabularies -- this layer defers for a fixed 30
#: days, and the log has no opinion about how long -- so the mapping is stated
#: rather than assumed to be the identity.
LOG_DECISION = {"ACCEPT": "APPROVED", "REJECT": "REJECTED",
                "DEFER_30D": "DEFERRED"}

UNDECIDED_SQL = """
SELECT p.id, p.cycle_id, p.kind, p.product, p.area, p.finding_key, p.title, p.body,
       p.objective_ref, p.est_effort, p.est_impact, p.reversibility,
       p.confidence, p.created_at
  FROM proposals p
  LEFT JOIN decisions d ON d.proposal_id = p.id
 WHERE d.id IS NULL
   AND (%(only)s::bigint IS NULL OR p.id = %(only)s)
 ORDER BY p.created_at, p.id
"""

EVIDENCE_SQL = """
SELECT adapter, query_key, value, fetched_at, freshness_bound, stale
  FROM proposal_evidence
 WHERE proposal_id = %(pid)s
 ORDER BY id
"""


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or config.console_dsn(), row_factory=dict_row)


def undecided(conn: psycopg.Connection, only: int | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(UNDECIDED_SQL, {"only": only}).fetchall()
    for row in rows:
        row["evidence"] = conn.execute(EVIDENCE_SQL, {"pid": row["id"]}).fetchall()
    return rows


def render(proposal: dict[str, Any]) -> str:
    lines = [
        "",
        "=" * 78,
        f"proposal {proposal['id']}  [{proposal['kind']}]  "
        f"{proposal['objective_ref'] or 'no objective (risk)'}",
        f"{proposal['title']}",
        "-" * 78,
    ]
    lines += proposal["body"].splitlines()
    lines += [
        "-" * 78,
        f"product {proposal['product']}   area {proposal['area']}   "
        f"confidence {proposal['confidence']}   "
        f"reversibility {proposal['reversibility']}",
        f"effort {proposal['est_effort'] or '-'}   "
        f"impact {proposal['est_impact'] or '-'}   "
        f"raised {proposal['created_at']:%Y-%m-%d %H:%M}",
        f"finding key {proposal['finding_key']}",
        "",
        "evidence:",
    ]
    for row in proposal["evidence"]:
        flag = "  ** STALE WHEN READ **" if row["stale"] else ""
        lines.append(f"  {row['adapter']}.{row['query_key']} fetched "
                     f"{row['fetched_at']:%Y-%m-%d %H:%M:%S} "
                     f"(bound {row['freshness_bound']}){flag}")
        for key, value in row["value"].items():
            lines.append(f"      {key}: {value}")
    if not proposal["evidence"]:
        # The database makes this unreachable. Printed rather than assumed,
        # because a review tool that silently shows nothing is worse than one
        # that says the row is wrong.
        lines.append("  NONE -- this should be impossible; check the constraint trigger")
    return "\n".join(lines)


def record(conn: psycopg.Connection, proposal_id: int, verdict: str,
           reason_code: str | None, seconds: float,
           why: str | None = None) -> tuple[int, int]:
    """Record the verdict and open the decision log entry. Returns both ids.

    `why` is the free-text reason the log requires on every row. It is not
    optional in the database and it is not optional here: falling back to the
    enum code would put ALREADY_KNOWN in a field whose whole purpose is to hold
    what the code could not.
    """
    if verdict not in VERDICTS:
        raise ValueError(f"{verdict} is not one of {', '.join(VERDICTS)}")
    if verdict != "ACCEPT" and reason_code is None:
        raise ValueError(f"{verdict} needs a reason code")
    if reason_code is not None and reason_code not in REASON_CODES:
        raise ValueError(f"{reason_code} is not one of {', '.join(REASON_CODES)}")
    if not (why or "").strip():
        raise ValueError("a decision needs a reason in words, not only a code")

    product = conn.execute(
        "SELECT product FROM proposals WHERE id = %s", (proposal_id,)
    ).fetchone()
    if product is None:
        raise ValueError(f"no proposal {proposal_id}")

    # BOTH OR NEITHER. `conn.transaction()` rolls back the verdict if the log
    # entry fails and vice versa; committing them separately is how a verdict
    # ends up with no record of why it was reached.
    #
    # The explicit commit afterwards is not redundant. psycopg opens an
    # implicit transaction on the first statement -- the SELECT above -- so
    # `conn.transaction()` here is a SAVEPOINT inside it rather than a
    # transaction of its own, and leaving the block releases the savepoint
    # without committing anything. Both rows were written and neither was
    # durable; the tests read back nothing and said so.
    with conn.transaction():
        decision = conn.execute(
            """
            INSERT INTO decisions (proposal_id, verdict, reason_code,
                                   decision_seconds)
            VALUES (%(pid)s, %(verdict)s, %(reason)s, %(seconds)s)
            RETURNING id
            """,
            {"pid": proposal_id, "verdict": verdict, "reason": reason_code,
             "seconds": round(seconds, 3)}).fetchone()

        # subject and evidence are left to the capture trigger, which takes
        # them from the proposal and its evidence rows. Nothing is retyped here
        # and nothing can drift from what was actually proposed.
        logged = conn.execute(
            """
            INSERT INTO decision_log (product, proposal_id, decision, reason)
            VALUES (%(product)s, %(pid)s, %(decision)s, %(why)s)
            RETURNING id
            """,
            {"product": product["product"], "pid": proposal_id,
             "decision": LOG_DECISION[verdict], "why": why.strip()}).fetchone()

    conn.commit()
    return decision["id"], logged["id"]


# ---- interactive ----------------------------------------------------------

def prompt_verdict() -> tuple[str, str | None] | None:
    """Returns (verdict, reason_code), or None to stop reviewing."""
    while True:
        answer = input("[a]ccept  [r]eject  [d]efer 30d  [s]kip  [q]uit > ").strip().lower()
        if answer in ("q", "quit"):
            return None
        if answer in ("s", "skip"):
            return ("SKIP", None)
        verdict = VERDICT_KEYS.get(answer) or (
            answer.upper() if answer.upper() in VERDICTS else None)
        if verdict is None:
            print("  not one of those.")
            continue
        if verdict == "ACCEPT":
            return (verdict, None)
        return (verdict, prompt_reason())


def prompt_why() -> str | None:
    """The sentence. Required, and the loop will not move on without one.

    Deliberately after the verdict rather than before: the reason is easier to
    write once the choice is made, and asking first turns a decision into an
    essay prompt. Empty input re-asks rather than defaulting -- a log whose
    reason field can be skipped is the log this replaced.
    """
    while True:
        try:
            answer = input("why? (a sentence, for the decision log) > ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if answer:
            return answer
        print("  the log needs a reason. It is the part worth keeping.")


def prompt_reason() -> str:
    for n, code in enumerate(REASON_CODES, start=1):
        print(f"  {n}. {code}")
    while True:
        answer = input("reason > ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(REASON_CODES):
            return REASON_CODES[int(answer) - 1]
        if answer.upper() in REASON_CODES:
            return answer.upper()
        print("  not one of those.")


def review(conn: psycopg.Connection, only: int | None = None) -> int:
    proposals = undecided(conn, only)
    if not proposals:
        print("nothing undecided.")
        return 0

    decided = 0
    for proposal in proposals:
        print(render(proposal))
        # The clock starts once there is something to read, and stops when the
        # verdict is entered. Everything before that is the tool's time, not
        # the reviewer's.
        started = time.monotonic()
        answer = prompt_verdict()
        seconds = time.monotonic() - started
        if answer is None:
            print(f"stopped. {decided} decided, "
                  f"{len(proposals) - decided} left.")
            return decided
        verdict, reason = answer
        if verdict == "SKIP":
            # Nothing is logged. Skipping is not deciding.
            continue

        # The clock has already stopped. The sentence is written after the
        # verdict, so the seconds measure the judgement rather than the typing.
        why = prompt_why()
        if why is None:
            print(f"stopped without recording proposal {proposal['id']}. "
                  f"{decided} decided, {len(proposals) - decided} left.")
            return decided

        decision_id, log_id = record(conn, proposal["id"], verdict, reason,
                                     seconds, why)
        decided += 1
        print(f"  decision {decision_id}: {verdict}"
              f"{' / ' + reason if reason else ''} in {seconds:.1f}s"
              f"  (decision log {log_id})")

    print(f"\n{decided} decided.")
    return decided


# ---- commands -------------------------------------------------------------

def cmd_list(conn: psycopg.Connection, args: argparse.Namespace) -> int:
    proposals = undecided(conn, args.proposal)
    if not proposals:
        print("nothing undecided.")
        return 0
    for proposal in proposals:
        print(render(proposal))
    print(f"\n{len(proposals)} undecided.")
    return 0


def cmd_review(conn: psycopg.Connection, args: argparse.Namespace) -> int:
    review(conn, args.proposal)
    return 0


def cmd_decide(conn: psycopg.Connection, args: argparse.Namespace) -> int:
    decision_id, log_id = record(conn, args.proposal, args.verdict, args.reason,
                                 args.seconds, args.why)
    print(f"decision {decision_id}: proposal {args.proposal} {args.verdict}"
          f"{' / ' + args.reason if args.reason else ''} "
          f"in {args.seconds:.1f}s")
    print(f"decision log {log_id}: {LOG_DECISION[args.verdict]} — {args.why}")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command")

    lister = sub.add_parser("list", help="print undecided proposals and stop")
    lister.add_argument("--proposal", type=int, default=None)
    lister.set_defaults(func=cmd_list)

    reviewer = sub.add_parser("review", help="decide each undecided proposal")
    reviewer.add_argument("--proposal", type=int, default=None)
    reviewer.set_defaults(func=cmd_review)

    decider = sub.add_parser("decide", help="record one decision without prompting")
    decider.add_argument("--proposal", type=int, required=True)
    decider.add_argument("--verdict", required=True, choices=VERDICTS)
    decider.add_argument("--reason", default=None, choices=REASON_CODES)
    decider.add_argument("--why", required=True,
                         help="the reason in words, for the decision log. "
                              "Required on every verdict including rejections "
                              "and deferrals -- the enum is what gets counted, "
                              "this is what gets read")
    decider.add_argument("--seconds", type=float, default=0.0,
                         help="human seconds spent; nothing measures this for "
                              "you here, so an unsupplied value is recorded "
                              "as zero rather than guessed")
    decider.set_defaults(func=cmd_decide)

    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["list"])
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        with connect() as conn:
            return args.func(conn, args)
    except (KeyboardInterrupt, EOFError):
        print("\nstopped.")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
