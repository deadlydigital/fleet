#!/usr/bin/env python
"""Entrypoint: rank the open candidates and tick the top of the list.

    python run_autoapprove.py [--dry-run] [--json]

specs/auto-approval.md §2.6. A SEPARATE unit from fleet-runner and from
fleet-automerge, for the reason run_automerge.py gives: so it can be stopped on
its own, which is what you want at 3am on a bad night and not something you
want to have to think about.

At 01:30, before the runner window opens at 02:00, so the night's work is
queued when the first fire lands.

`--dry-run` ranks everything, approves nothing, and prints the order with every
key value and every gate that fired. It is the honest way to watch this for a
few nights before letting it write, and it is what the first nights should use.
Both paths go through the same `plan()`, so a dry run is not a second
implementation that agrees with the real one only until somebody edits it.

EXIT CODES, AND WHY NOTHING-APPROVED IS ZERO

Approving nothing is an ORDINARY NIGHT and often the designed answer: the pace
is one, the pool has a 60% line, and §2.3 refuses outright when no key
separates the top two candidates. A non-zero exit there would page somebody for
the system working. Only a refusal from approve_batch -- a ceiling that was hit
in a way the caller did not anticipate -- is an error.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from console import approve, autoapprove

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="rank everything, approve nothing, say what it would do")
    ap.add_argument("--json", action="store_true",
                    help="emit the whole plan as JSON, for a machine or a diff")
    args = ap.parse_args()

    try:
        p = autoapprove.sweep(dry_run=args.dry_run)
    except approve.ApprovalRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(p, indent=2, default=str))
    else:
        autoapprove._print(p, dry_run=args.dry_run)

    print(f"--- {p['considered']} considered, {len(p['approve_ids'])} approved"
          f"{' (dry run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
