#!/usr/bin/env python
"""Entrypoint: merge what may be merged with nobody watching.

    python run_automerge.py [--dry-run]

specs/unattended-operation.md §6.1. A SEPARATE unit from fleet-runner, so it
can be stopped on its own -- which is what you want at 3am on a bad night, and
not something you want to have to think about.

`--dry-run` considers every waiting task and merges none, printing what it
would have done. It is the honest way to watch this for a few nights before
letting it write, and it is what the first nights should use.
"""
from __future__ import annotations

import argparse
import logging
import sys

from console import automerge

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="consider everything, merge nothing, say what it would do")
    args = ap.parse_args()

    results = automerge.sweep(dry_run=args.dry_run)
    merged = [r for r in results if r.get("merged")]
    print(f"--- {len(results)} considered, {len(merged)} merged"
          f"{' (dry run)' if args.dry_run else ''}")
    # Exit 0 even when nothing merged: nothing to merge is the ordinary night,
    # and a non-zero there would page somebody for silence.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
