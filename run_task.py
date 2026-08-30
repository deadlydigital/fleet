#!/usr/bin/env python3
"""One tick of the task runner.

    python run_task.py                 claim the next queued task and run it
    python run_task.py --task 7        run that task, if it is QUEUED
    python run_task.py --no-push       leave the branch local
    python run_task.py --queue nightly restrict to one queue
    python run_task.py --reclaim       recover ticks that died

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

from runner import cycle, reclaim as reclaim_mod


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="run_task.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--task", type=int, help="run this task rather than claiming")
    p.add_argument("--queue", help="claim only from this queue")
    p.add_argument("--no-push", action="store_true",
                   help="leave the finished branch local")
    p.add_argument("--reclaim", action="store_true",
                   help="recover tasks left RUNNING by a tick that died, and "
                        "sweep the worktrees they pinned")
    p.add_argument("--no-reclaim", action="store_true",
                   help="skip the reclaim that normally begins a tick")
    p.add_argument("--grace", type=int, default=reclaim_mod.DEFAULT_GRACE_SECONDS,
                   help="seconds past a task's own wall clock before it counts "
                        "as stale (minimum 300)")
    args = p.parse_args(argv)

    if args.reclaim:
        # This flag now means "reclaim and stop", because reclaiming also
        # happens at the start of every tick.
        #
        # It used to say a repair that happens automatically is one nobody
        # reads the output of. That objection was right and is answered, not
        # ignored: every reclaim writes a task_reclaims row and the console
        # shows it on the task, so an overnight retry is visible in the
        # morning rather than inferred from the attempt count. Automatic and
        # invisible was the bad combination; only one half of it was removed.
        try:
            results = reclaim_mod.reclaim(grace_seconds=args.grace,
                                          only_task=args.task)
            print()
            reclaim_mod.sweep_worktrees()
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except Exception as exc:                                  # noqa: BLE001
            print(f"reclaim failed: {exc}", file=sys.stderr)
            return 2
        for r in results:
            print(f"task {r.task_id}: {r.outcome}"
                  + (f", worktree removed" if r.worktree_removed else ""))
        return 0

    try:
        result = cycle.tick(queue=args.queue, only_task=args.task,
                            push=not args.no_push,
                            reclaim_first=not args.no_reclaim)
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
