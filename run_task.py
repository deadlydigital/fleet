#!/usr/bin/env python3
"""One tick of the task runner.

    python run_task.py                 claim the next queued task and run it
    python run_task.py --task 7        run that task, if it is QUEUED
    python run_task.py --no-push       leave the branch local
    python run_task.py --queue nightly restrict to one queue

Invoked by hand. There is no timer, and systemd/ carries no unit for this:
the spec's build order puts the timer after three tasks have gone through by
hand, and that has not happened yet.

One task per tick. Serial. To run two tasks, invoke it twice -- there is no
loop here, so the cost and the blast radius of an invocation stay one task
wide.

Exit codes: 0 if a branch is ready or nothing was queued, 1 if the task
failed, 2 on a configuration problem.
"""
from __future__ import annotations

import argparse
import sys

from runner import cycle


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="run_task.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task", type=int, help="run this task rather than claiming")
    p.add_argument("--queue", help="claim only from this queue")
    p.add_argument("--no-push", action="store_true",
                   help="leave the finished branch local")
    args = p.parse_args(argv)

    try:
        result = cycle.tick(queue=args.queue, only_task=args.task,
                            push=not args.no_push)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if result.outcome == "IDLE":
        return 0

    print()
    print(f"task {result.task_id}  {result.outcome}  "
          f"£{result.cost_gbp:.4f}  {result.duration_s:.1f}s")
    if result.reason:
        print(f"  {result.reason}")
    for note in result.notes:
        print(f"  note: {note}")
    if result.verdict and not result.verdict.clean:
        for line in result.verdict.reasons():
            print(f"  violation: {line}")
    if result.outcome == "READY_FOR_REVIEW":
        print(f"  branch {result.branch}"
              + ("" if result.pushed else " (local only)"))
        print(f"  review with: ./fleet task status {result.task_id}")
        print("  the runner does not merge. That decision is yours.")
    return 0 if result.outcome == "READY_FOR_REVIEW" else 1


if __name__ == "__main__":
    sys.exit(main())
