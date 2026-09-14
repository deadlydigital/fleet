"""Retiring a candidate the tree has already answered.

THE POOL ONLY EVER GREW. On 14 Sep 2026 the sweep considered 24 candidates and
approved none; eight of the twenty held were not blocked work but FINISHED
work. c23 asks for a CSV export of the order list and its own probe says
`platform/app/api/analytics/orders/export/route.ts` must not exist -- it was
created that morning. c21 asks to show net revenue on the dashboard and its
probe says the page must not mention `net_revenue`; the page mentions it
eighteen times.

The gate reads those correctly. `probes_failed` is true, and it is also the
word it uses for a claim that was never right, so nothing distinguishes "the
ground moved under this" from "somebody did it". The rows are re-ranked and
re-refused every night, and the number a person reads as a backlog is a third
history.

THE DIRECTION OF THE FAILURE IS THE WHOLE SIGNAL

A probe that asserted ABSENCE and now finds PRESENCE says the thing exists:

    path_absent: X                  and X is there
    grep_count {..., expected: 0}   and the pattern is found

That is the producer's own statement of why the work was needed, answered by
the tree. Anything else is not this. `expected 1, found 0` means what the work
RESTS ON has gone -- c20 and c46 tonight -- and that is a different fact with a
different remedy, so those stay held for a person. Retiring on it would be
reading "my premise is broken" as "my job is done".

EVERY FAILING PROBE, NOT ANY. A row with one shipped-shaped failure and one
ground-moved failure is not settled, and taking the first as decisive is the
inference this module exists to avoid making.

AND NOT A ROW WHOSE PROBES ALL HOLD. That is live work with its ground intact;
it is held by some other gate, or it is eligible.

WHAT IT WRITES, AND WHAT THAT COSTS. `disposition = 'SHIPPED'` with the probe
that answered it as the reason -- 043 refuses the disposition without one. It
is a write, it is reversible by hand, and gate 1 considers PENDING only, so a
retired row leaves the pool without any gate changing. What it gives up is the
`candidate that reappears is a signal` property of specs/approval-surface.md
§7: a retired row will be produced again by the next producer run, and arrive
PENDING, and be retired again. That is the correct behaviour and it is also a
small nightly cost nobody is paying attention to yet.
"""
from __future__ import annotations

import argparse
from typing import Any, Dict, List

from . import db, rank


def _asserts_absence(kind: str, arg: Any) -> bool:
    """Did this probe claim the thing is NOT there?

    The two shapes the vocabulary can express it in. `path_exists` and a
    `grep_count` with a positive `expected` are the opposite claim and are not
    this; a `grep_count` whose `expected` is missing or not an integer is
    neither, and is treated as not-absence because guessing is how a row gets
    retired on a probe nobody can read.
    """
    if kind == "path_absent":
        return True
    if kind == "grep_count" and isinstance(arg, dict):
        return arg.get("expected") == 0
    return False


def classify(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Re-execute this row's probes and say whether the tree has answered it.

    Pure of the database and of any decision: it reads the tree and returns a
    verdict, on console/rank.gate's argument. The caller writes.
    """
    mod = rank._shape_check()
    probes = candidate.get("probes") or []
    repo_path = mod.REPOS.get(candidate.get("repo"))

    if repo_path is None:
        return {"retire": False, "why": f"repo {candidate.get('repo')!r} is "
                                        f"not one this host has"}
    if not probes:
        # The same refusal gate 5 makes, and for the same reason: a row with
        # nothing to re-execute cannot have been answered by anything.
        return {"retire": False, "why": "carries no probes, so nothing can "
                                        "have answered it"}

    failed: List[str] = []
    shipped: List[str] = []
    for probe in probes:
        held, desc = mod.run_probe(repo_path, probe)
        if held:
            continue
        failed.append(desc)
        if isinstance(probe, dict) and len(probe) == 1:
            kind, arg = next(iter(probe.items()))
            if _asserts_absence(kind, arg):
                shipped.append(desc)

    if not failed:
        return {"retire": False, "why": "every probe still holds, so the work "
                                        "it describes has not been done"}
    if len(shipped) != len(failed):
        stuck = [d for d in failed if d not in shipped]
        return {"retire": False,
                "why": (f"{len(stuck)} of {len(failed)} failing probe(s) failed "
                        f"because the ground moved rather than because the work "
                        f"landed, so this is not settled: {stuck[0]}")}

    return {"retire": True,
            "why": ("every probe that asserted this work was still needed now "
                    "finds it present: " + "; ".join(shipped))}


def plan() -> List[Dict[str, Any]]:
    """Every PENDING candidate, classified. Writes nothing."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, title, repo, probes FROM candidates"
            " WHERE disposition = 'PENDING' ORDER BY id").fetchall()
    return [{**dict(r), "verdict": classify(dict(r))} for r in rows]


def retire(dry_run: bool = False) -> Dict[str, Any]:
    """Write SHIPPED for the rows the tree has answered.

    GUARDED ON `disposition='PENDING'` IN THE UPDATE, not on what plan() read.
    The sweep takes minutes; a person ticking a row in the console during it
    must win, and an UPDATE that does not say so is a race nobody will ever
    reproduce.
    """
    decided = plan()
    take = [r for r in decided if r["verdict"]["retire"]]
    if dry_run or not take:
        return {"considered": len(decided), "retired": 0,
                "would_retire": [r["id"] for r in take], "rows": decided}

    done = []
    with db.writer() as conn:
        for r in take:
            n = conn.execute(
                "UPDATE candidates SET disposition='SHIPPED',"
                " disposition_reason=%s, decided_at=now()"
                " WHERE id=%s AND disposition='PENDING'",
                (r["verdict"]["why"], r["id"])).rowcount
            if n == 1:
                done.append(r["id"])
        conn.commit()
    return {"considered": len(decided), "retired": len(done),
            "would_retire": [r["id"] for r in take], "retired_ids": done,
            "rows": decided}


def main(argv: List[str] | None = None) -> int:
    """    python -m console.retire [--dry-run] [--verbose]

    Exit 0 whether or not anything was retired: a night with nothing to retire
    is the ordinary case and is not a failure, on run_autoapprove.py's
    argument about nothing-approved.
    """
    ap = argparse.ArgumentParser(
        prog="python -m console.retire", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="classify everything and write nothing")
    ap.add_argument("--verbose", action="store_true",
                    help="print the verdict for every row, not only the "
                         "rows that would be retired")
    args = ap.parse_args(argv)

    out = retire(dry_run=args.dry_run)
    for r in out["rows"]:
        v = r["verdict"]
        if v["retire"]:
            print(f"  c{r['id']}  {'would retire' if args.dry_run else 'RETIRED'}"
                  f"  {r['title'][:52]}")
            print(f"        {v['why'][:200]}")
        elif args.verbose:
            print(f"  c{r['id']}  kept  {r['title'][:52]}")
            print(f"        {v['why'][:160]}")
    verb = "would retire" if args.dry_run else "retired"
    print(f"--- {out['considered']} considered, "
          f"{len(out['would_retire'])} {verb}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
