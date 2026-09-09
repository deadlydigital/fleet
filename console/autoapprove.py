"""Ticking candidates with nobody watching, and refusing to when it cannot say why.

specs/auto-approval.md §2.3 and §2.5. Selects, gates, ranks, and calls
approve.approve_batch with the ranked ids. IT ADDS NO CEILING OF ITS OWN AND
BYPASSES NONE -- the repeat-failure stop, the batch cap, the queue-depth check,
the credit check and the one-transaction ordering are already in approve.py and
were put there on the grounds that auto-approval would have to meet them.

THE REFUSAL THAT MATTERS
------------------------
`decision_log.reason` is NOT NULL on every row, and 010 §4 is explicit that ten
paraphrases of "yes" satisfy the constraint while emptying the column. An
approval nobody made is exactly where that failure arrives by a new route.

So the reason is generated FROM THE DISCRIMINATOR that actually separated the
last approved row from the first row below the line -- and if there is no
discriminator, this approves NOTHING and says so. A night where the top two
differ only in candidate id produces no approval and a brief line explaining
that. "It was first" is not a reason, and a system that will not say why it
chose is the one thing 010 §4 was written to prevent.

WHAT THIS CAN COST, STATED
---------------------------
Draft-spec tasks and nothing else. `draft_spec` is on
automerge.NEVER_UNATTENDED, so the output is markdown on a local branch that no
auto-merge will touch. A wrong ranking every night for a week costs £14 at the
pace in force and lands nothing in either repository.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from . import approve, db, rank


class NothingToApprove(Exception):
    """Not an error. The night had no answer it could defend."""


def _open_candidates(conn) -> List[Dict[str, Any]]:
    return conn.execute(
        "SELECT id, batch_id, title, repo, band, hib_signal, probes,"
        " suggested_paths, disposition, objective_ref"
        " FROM candidates WHERE disposition IN ('PENDING','NOT_NOW')"
        " ORDER BY id").fetchall()


def _live_tasks(conn) -> List[Dict[str, Any]]:
    return conn.execute(
        "SELECT id, status, title, repo, spec_md, acceptance_contract"
        " FROM tasks WHERE status = ANY(%s) ORDER BY id",
        (list(rank.LIVE_TASK_STATES),)).fetchall()


def _ceilings(conn) -> Dict[str, Any]:
    caps = conn.execute(
        "SELECT fleet_autoapprove_per_night() AS per_night,"
        " fleet_max_approval_batch() AS max_batch,"
        " fleet_max_queued_tasks() AS max_queued,"
        " (SELECT count(*) FROM tasks WHERE status='QUEUED') AS queued_now"
    ).fetchone()
    credit = conn.execute("SELECT * FROM fleet_month_credit()").fetchone()
    return {"caps": caps, "credit": credit}


def _cut(ceilings: Dict[str, Any], task_max_cost: float) -> Dict[str, Any]:
    """How many may be ticked tonight, and WHICH ceiling decided it.

    The effective number is the smallest of four, and which one bound is worth
    recording: "1 tonight" reads the same whether the pace chose it or the pool
    did, and those want different responses in the morning.
    """
    caps, credit = ceilings["caps"], ceilings["credit"]
    limits = {
        "per_night": caps["per_night"],
        "max_approval_batch": caps["max_batch"],
        "queue_room": max(0, caps["max_queued"] - caps["queued_now"]),
    }
    if credit["status"] == "UNCOMPUTED":
        limits["autonomous_credit"] = 0
    else:
        room = credit["autonomous_remaining_gbp"]
        limits["autonomous_credit"] = max(0, int(float(room) // task_max_cost))
    n = min(limits.values())
    bound_by = sorted(k for k, v in limits.items() if v == n)
    return {"n": n, "limits": limits, "bound_by": bound_by}


def _reason(approved: List[Dict[str, Any]], below: List[Dict[str, Any]],
            considered: int) -> str:
    """The sentence, built from what actually separated the cut.

    Raises NothingToApprove when nothing did. This is the function that makes
    the refusal real rather than aspirational.
    """
    top = approved[0]
    last = approved[-1]
    keys_last = rank.key_values(last)

    head = (f"Approved {len(approved)} of {considered} open candidate(s) "
            f"(rank_v{rank.RANK_VERSION}). ")

    eligible_below = [b for b in below if b["gate"]["eligible"]]

    if not eligible_below:
        # Legitimate, and not the same thing as having no discriminator: there
        # was nothing to prefer this row OVER. Said explicitly, because "the
        # only one that passed the gates" is a much weaker claim than "the best
        # of nine" and the record should not let them read alike.
        held = len([b for b in below if not b["gate"]["eligible"]])
        return (head + f"Candidate {top['id']} ({top['title'][:70]}) is the only "
                f"candidate that passed the gates; the other {held} were each "
                f"held by a rule, listed in mechanics. It was not preferred over "
                f"an alternative, because there was none.")

    nxt = eligible_below[0]
    keys_next = rank.key_values(nxt)

    if keys_last["key1_class"] != keys_next["key1_class"]:
        why = (f"its probes make it a {keys_last['key1_class']} candidate and "
               f"the next eligible row ({nxt['id']}) is "
               f"{keys_next['key1_class']}")
        if keys_last["key1_class"] == "frontend-only":
            ap = keys_last["key1_why"]["api_presence"]
            pf = keys_last["key1_why"]["platform_feature_absent"]
            why += (f": {', '.join(ap[:2])} already returns the value and "
                    f"{', '.join(pf[:2])} does not carry it to a person")
    elif keys_last["key2_band"] != keys_next["key2_band"]:
        why = (f"both are {keys_last['key1_class']} work, and its band is "
               f"{keys_last['key2_band']} against {keys_next['key2_band']} for "
               f"the next eligible row ({nxt['id']})")
    else:
        # NO DISCRIMINATOR. Approve nothing.
        raise NothingToApprove(
            f"candidates {last['id']} and {nxt['id']} are indistinguishable on "
            f"every key that means anything: both {keys_last['key1_class']}, "
            f"both band {keys_last['key2_band']}, and only the candidate id "
            f"separates them. Approving on that is approving because it was "
            f"first, which is a decision nobody made and a reason nobody wrote. "
            f"Nothing was approved.")

    held_lines = "; ".join(
        f"{b['id']} held ({b['gate']['rule']})"
        for b in below if not b["gate"]["eligible"])
    tail = f" Held below the line: {held_lines}." if held_lines else ""
    return head + (f"Candidate {last['id']} ({last['title'][:70]}) was taken "
                   f"because {why}.") + tail


def plan(*, decided_by: str | None = None) -> Dict[str, Any]:
    """Everything tonight would do, computed and written nowhere.

    This IS the dry run. The same function produces the plan that sweep()
    executes, so what a dry run prints is what a real run would have done
    rather than a second implementation that agrees with it for a while.
    """
    _, task_max_cost, _, _ = approve._draft_spec_contract()

    with db.connect() as conn:
        candidates = _open_candidates(conn)
        tasks = _live_tasks(conn)
        ceilings = _ceilings(conn)
        newest = conn.execute(
            "SELECT max(batch_id) AS b FROM candidates").fetchone()["b"]

    head = rank.platform_head("deadly-digital-platform")

    scored = []
    for c in candidates:
        g = rank.gate(c, newest_batch=newest, live_tasks=tasks)
        scored.append({**dict(c), "gate": g, "keys": rank.key_values(c),
                       "sort": rank.rank(c)})

    # THE GATES ARE AHEAD OF THE SORT. An ineligible row is not ranked into
    # position and then skipped; it never enters the order. It is still listed,
    # with the rule that held it, because a ranking is wrong in what it passed
    # over and a list of what it took cannot show that.
    eligible = sorted([s for s in scored if s["gate"]["eligible"]],
                      key=lambda s: s["sort"])
    ineligible = sorted([s for s in scored if not s["gate"]["eligible"]],
                        key=lambda s: s["sort"])

    cut = _cut(ceilings, float(task_max_cost))
    take = eligible[:cut["n"]]
    below = eligible[cut["n"]:] + ineligible

    credit = ceilings["credit"]
    result: Dict[str, Any] = {
        "rank_version": rank.RANK_VERSION,
        "platform_sha": head,
        "considered": len(candidates),
        "newest_batch": newest,
        "eligible": [s["id"] for s in eligible],
        "cut": cut,
        "approve_ids": [s["id"] for s in take],
        "reserved_gbp": round(float(task_max_cost) * len(take), 2),
        # None means "whatever identity writes the row", which approve_batch
        # resolves to `current_user` in the INSERT. Deliberately not read here:
        # plan() holds the READ-ONLY connection, so `current_user` here is the
        # reader's login and recording it would name an identity that did not
        # and could not have written the decision.
        "decided_by": decided_by,
        "ranked": [
            {"candidate_id": s["id"], "title": s["title"],
             "keys": s["keys"], "eligible": s["gate"]["eligible"],
             "rule": s["gate"]["rule"], "detail": s["gate"]["detail"],
             # WHICH of the two path sources matched, per §2.2 gate 3. A
             # contract match is a much weaker statement than a spec match --
             # the contract paths are deliberately wide -- and flattening both
             # into "overlapped" is what would make §7.2 unanswerable.
             "matched_via": s["gate"].get("matched_via"),
             "overlap_task_id": s["gate"].get("task_id"),
             # EACH PROBE'S RESULT, not just the tally. §3 asks for this by
             # name: "32 of 32 held" cannot tell a later reader WHICH claim
             # was true, and the whole argument for storing predicates rather
             # than a verdict is that the individual answers are the evidence.
             "probes": (s["gate"].get("probes") or {}).get("results"),
             "hib_signal": s["hib_signal"]}
            for s in eligible + ineligible],
        "credit": {
            "status": credit["status"],
            "pool": float(credit["pool_gbp"]) if credit["pool_gbp"] is not None else None,
            "committed": float(credit["committed_gbp"]),
            "remaining": float(credit["remaining_gbp"]) if credit["remaining_gbp"] is not None else None,
            "autonomous_remaining": (
                float(credit["autonomous_remaining_gbp"])
                if credit["autonomous_remaining_gbp"] is not None else None),
            "read_at": credit["read_at"].isoformat() if credit["read_at"] else None,
            "source": credit["source"],
        },
        # THE GATES SHORT-CIRCUIT, so this counts the probes of the candidates
        # that REACHED gate 4 -- not the whole pool. A row held at gate 2 or 3
        # never has its probes re-executed, because there is nothing to spend on
        # it either way. `reached` is recorded beside the totals so "18 of 18
        # held" cannot be misread as "the whole pool was re-verified".
        "probes": {
            "run": sum(s["gate"].get("probes", {}).get("run", 0) for s in scored),
            "held": sum(s["gate"].get("probes", {}).get("held", 0) for s in scored),
            "reached_gate_4": sum(1 for s in scored if "probes" in s["gate"]),
            "of_candidates": len(scored),
        },
    }

    if not take:
        result["reason"] = None
        result["refused"] = (
            "no candidate passed the gates" if not eligible else
            f"the cut is {cut['n']}, bound by {' and '.join(cut['bound_by'])}")
        return result

    try:
        result["reason"] = _reason(take, below, len(candidates))
    except NothingToApprove as exc:
        result["approve_ids"] = []
        result["reserved_gbp"] = 0.0
        result["reason"] = None
        result["refused"] = str(exc)
    return result


def mechanics_of(p: Dict[str, Any]) -> Dict[str, Any]:
    """What the decision rested on, for decision_log.mechanics.

    §3's list, and every item is here because its absence would make a morning
    unanswerable: the rank version (so last week's order stays attributable),
    the sha the probes ran at (so "still true" has a referent), every key value
    (so the order can be recomputed), the cut line and what bound it, the rule
    that held each row below it, and the credit reading the spend was reserved
    against.
    """
    return {
        "rank_version": p["rank_version"],
        "platform_sha": p["platform_sha"],
        "probes": p["probes"],
        "cut": p["cut"],
        "ranked": p["ranked"],
        # The reading the spend was reserved against AND what was reserved, so
        # the morning can set one against the other without recomputing either.
        "credit": {**p["credit"], "reserved": p["reserved_gbp"]},
        "newest_batch": p["newest_batch"],
    }


def sweep(*, dry_run: bool = False) -> Dict[str, Any]:
    """Tonight's approval, or a recorded refusal to make one."""
    p = plan()

    if dry_run or not p["approve_ids"]:
        p["queued_task_ids"] = []
        p["decision_id"] = None
        return p

    out = approve.approve_batch(
        reason=p["reason"],
        approve_ids=p["approve_ids"],
        reject={}, not_now_ids=[],
        # THE LOGIN, NEVER A PERSON'S NAME. console/app.py defaults this to
        # "eamonn" on the console route; a row that reads as a person's decision
        # is the one thing this record exists to prevent. Read from
        # `current_user` rather than typed, so it cannot drift from the identity
        # that actually did it.
        decided_by=p["decided_by"],
        decided_via="unattended",
        mechanics=mechanics_of(p))
    p.update(out)
    return p


def _print(p: Dict[str, Any], *, dry_run: bool) -> None:
    what = "WOULD APPROVE" if dry_run else "APPROVED"
    print(f"rank_v{p['rank_version']} at platform "
          f"{(p['platform_sha'] or 'unknown')[:7]}; "
          f"{p['considered']} open candidate(s), newest batch {p['newest_batch']}")
    print(f"probes re-executed: {p['probes']['held']} of {p['probes']['run']} held"
          f"  (across the {p['probes']['reached_gate_4']} of "
          f"{p['probes']['of_candidates']} candidate(s) that reached gate 4)")
    c = p["credit"]
    if c["status"] == "COMPUTED":
        print(f"credit: GBP {c['remaining']:.2f} remains of GBP {c['pool']:.2f}; "
              f"the unattended 60% line leaves GBP {c['autonomous_remaining']:.2f}")
    else:
        print("credit: UNCOMPUTED -- nothing may be approved")
    print(f"cut: {p['cut']['n']}, bound by {', '.join(p['cut']['bound_by'])} "
          f"{p['cut']['limits']}")
    print()
    print("ranked, eligible first:")
    for r in p["ranked"]:
        mark = "  " if r["eligible"] else "x "
        k = r["keys"]
        line = (f"  {mark}c{r['candidate_id']:<3} {str(k['key1_class']):<14}"
                f" {str(k['key2_band'] or '-'):<8} {r['title'][:52]}")
        print(line)
        if not r["eligible"]:
            print(f"        HELD ({r['rule']}): {r['detail']}")
    print()
    if p["approve_ids"]:
        print(f"{what}: {p['approve_ids']}  reserving GBP {p['reserved_gbp']:.2f}")
        print(f"  as: {p['decided_by'] or 'the writing login (current_user)'}")
        print(f"  reason: {p['reason']}")
        if p.get("queued_task_ids"):
            print(f"  queued task(s): {p['queued_task_ids']}  "
                  f"decision {p['decision_id']}")
    else:
        print(f"APPROVED NOTHING: {p['refused']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Rank open candidates and tick the top of the list.")
    ap.add_argument("--dry-run", action="store_true",
                    help="rank everything, approve nothing, print the order "
                         "with every key value and every gate that fired")
    ap.add_argument("--json", action="store_true", help="emit the plan as JSON")
    args = ap.parse_args(argv)

    try:
        p = sweep(dry_run=args.dry_run)
    except approve.ApprovalRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(p, indent=2, default=str))
    else:
        _print(p, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
