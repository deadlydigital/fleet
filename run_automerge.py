#!/usr/bin/env python
"""Entrypoint: merge what may be merged with nobody watching.

    python run_automerge.py [--dry-run]

specs/unattended-operation.md §6.1. A SEPARATE unit from fleet-runner, so it
can be stopped on its own -- which is what you want at 3am on a bad night, and
not something you want to have to think about.

`--dry-run` considers every waiting task and merges none, printing what it
would have done. It is the honest way to watch this for a few nights before
letting it write, and it is what the first nights should use.

EXIT 3 MEANS ANOTHER CHAIN OR SWEEP HOLDS THE MERGE LOCK, so this one did
nothing. It shares `runner.exclusive.only_one("chain", ...)` with run_chain.py
because both build a trial clone at the same task-id-derived path, and two of
them delete each other's -- task 125, 17 Sep 2026. Refusing rather than
queueing, and loudly, on the argument in run_chain.py's EXIT CODES.
"""
from __future__ import annotations

import argparse
import logging
import sys

from console import automerge

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="consider everything, merge nothing, say what it would do")
    # `argv` is a parameter, like chain.main's, so a test can call this without
    # argparse reading pytest's own command line and exiting 2 underneath it.
    args = ap.parse_args(argv)

    # THE SAME LOCK THE CHAIN TAKES, AND THE NAME IS THE RESOURCE.
    #
    # "chain" reads like an entry point, but what is excluded is the ONE merge
    # path and the trial clones it builds at
    # `<trial root>/fleet-accept-trial-<id>`. This module reaches that path
    # through exactly the same `reverify.run` the chain's merge stage does, so
    # a by-hand `run_automerge.py` during a chain run reproduces task 125
    # precisely: `create_trial_clone` rmtree's the live trial, and the gate
    # already running reports "the branch FAILS when merged" about a tree that
    # is fine.
    #
    # So it SHARES the lock rather than taking a second one. Two locks would be
    # two answers to one question, which is the shape
    # `tests/test_unit_ceilings.py` exists to stop.
    from runner import config as runner_config, exclusive

    try:
        with exclusive.only_one("chain", runner_config.task_runner_dsn()):
            results = automerge.sweep(dry_run=args.dry_run)
    except exclusive.AlreadyRunning as exc:
        # Loud and non-zero, on run_chain.py's argument: a sweep that always
        # refuses is indistinguishable from a sweep with nothing to merge.
        logging.getLogger("fleet.automerge").error("%s", exc)
        print(f"--- refused: {exc}")
        return 3

    merged = [r for r in results if r.get("merged")]
    print(f"--- {len(results)} considered, {len(merged)} merged"
          f"{' (dry run)' if args.dry_run else ''}")
    # Exit 0 even when nothing merged: nothing to merge is the ordinary night,
    # and a non-zero there would page somebody for silence.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
