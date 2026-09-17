#!/usr/bin/env python3
"""Entrypoint: run the chain until there is nothing left or something needs you.

    python run_chain.py [--dry-run] [--config PATH]

specs/one-entry-point.md. One command in place of five: autoapprove, run_task,
automerge, run_task, automerge. `accept` and `deploy` stay yours.

`--dry-run` decides everything and writes nothing, and goes through the same
`chain.run()` the real path does -- so what it prints is what a real run would
have done, rather than a second implementation that agrees with it for a while.
The four stage entry points are unchanged and still work by hand; this schedules
them, and re-implements none of them.

EXIT CODES
    0  the loop ran out of work, or stopped on its own clock. An idle night is
       an ordinary night -- run_autoapprove.py's precedent.
    1  it stopped on a condition somebody should read: the credit ceiling, the
       same task failing twice, or the pass ceiling that should be unreachable.
    3  ANOTHER CHAIN IS ALREADY RUNNING, so this one did nothing at all. Not 1:
       that means the loop ran and stopped on something it found, and this
       means it never started. Not 0 either -- a unit that always refuses looks
       exactly like a unit with nothing to do, which is how fleet-autodeploy
       went seven runs without deploying. Refusing rather than queueing is
       deliberate; `runner/exclusive.py` carries the argument and the 27
       seconds on task 125 that paid for it.
"""
from __future__ import annotations

import logging
import sys

import chain

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

if __name__ == "__main__":
    sys.exit(chain.main())
