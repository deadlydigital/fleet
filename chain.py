"""The chain as a loop: approve, build, merge, until there is nothing left.

specs/one-entry-point.md.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
It is a scheduler around the four stages that already exist. It imports
`autoapprove.sweep`, `cycle.tick` and `automerge.sweep` and calls them exactly
as their own entry points do. There is no second implementation of any stage
here, and there must never be one: a loop that reimplemented a gate would
disagree with the unit that still runs it by hand, and the disagreement would
surface at 3am.

It is NOT a merger and NOT a deployer. `accept` and `deploy` stay the
operator's. The loop reaches `automerge`, which has its own gates and refuses
by default for everything except contracts that opt in, and it never calls
`autodeploy` at all.

DRAIN BEFORE YOU ADD
--------------------
Build and merge are tried before approve, so the loop finishes what is started
rather than widening the front. The timers this replaces did the opposite --
approve 01:30, build 02:00-04:00, merge once at 03:30 -- which is why a task
finishing at 03:40 waited a day for a decision that takes seconds.

A FIXPOINT, NOT A SEQUENCE
--------------------------
The chain's length is not fixed. A merged draft queues its code task, and since
037 a candidate may split into several links. So the loop runs until a pass
changes nothing, rather than executing a known number of steps.
"""
from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import psycopg
import yaml
from psycopg.rows import dict_row

log = logging.getLogger("fleet.chain")

CONFIG_PATH = Path(__file__).resolve().parent / "chain.yaml"

#: Stops the loop can report. The reason is a value rather than a log line
#: because the morning question is "why did it stop", and a sentence in the
#: journal is not an answer anything can read back.
IDLE = "nothing left to do"
WALL_CLOCK = "the loop's own deadline"
CREDIT = "the next task costs more than the month's autonomous credit"
REPEAT_FAILURE = "the same task failed twice in one pass"
MAX_PASSES = "the pass ceiling, which should be unreachable"
DRY_RUN_ONE_PASS = "a dry run is one pass -- nothing changed, so nothing new could be decided"

#: A backstop, not a policy. Every real stop above is a stated condition; this
#: exists so that a bug in one of them cannot spin forever. If the loop ever
#: stops for this reason, something above it is broken.
PASS_CEILING = 50


@dataclass
class Step:
    """One stage doing something, or declining to."""
    stage: str
    acted: bool
    detail: str = ""
    task_id: int | None = None
    cost_gbp: float = 0.0


@dataclass
class ChainResult:
    passes: int = 0
    steps: list[Step] = field(default_factory=list)
    stopped_by: str = IDLE
    #: READY_FOR_REVIEW at the end, with automerge's reason where it gave one.
    waiting: list[dict[str, Any]] = field(default_factory=list)
    failed_task_ids: list[int] = field(default_factory=list)
    duration_s: float = 0.0
    dry_run: bool = False

    @property
    def acted(self) -> bool:
        return any(s.acted for s in self.steps)

    @property
    def spent_gbp(self) -> float:
        return round(sum(s.cost_gbp for s in self.steps), 4)


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Stage switches and the wall clock, from a file rather than a table.

    A FILE, AND THAT IS THE POINT. runner.yaml holds thresholds for the stated
    reason that "retuning one must not be a redeploy"; the same argument covers
    turning a stage off at 3am. A table would have been the other candidate and
    needs fleet_owner, which three other pieces of work are already queued
    behind.
    """
    p = path or CONFIG_PATH
    data = yaml.safe_load(p.read_text()) or {}
    stages = data.get("stages") or {}
    return {
        "stages": {name: bool(stages.get(name, True))
                   for name in ("build", "merge", "approve")},
        "wall_clock_seconds": int(data.get("wall_clock_seconds", 7200)),
        "queue": data.get("queue") or None,
    }


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True)


def next_claimable(conn, queue: str | None) -> dict[str, Any] | None:
    """The task `claim_task` would take next, without taking it.

    THE PREDICATE IS COPIED FROM claim_task DELIBERATELY, and the copy is the
    risk worth naming: status QUEUED, the queue filter, attempts < max_attempts,
    ORDER BY priority, id. If the two ever disagree the loop checks affordability
    and repeat-failure against one task and then builds a different one, which
    is a safety control aimed at the wrong row. There is no way to ask the
    database "what would you claim" without claiming it, so the copy stands and
    a test asserts the two agree on a seeded queue.
    """
    return conn.execute(
        "SELECT id, title, max_cost_gbp, attempts, max_attempts"
        "  FROM tasks"
        " WHERE status = 'QUEUED'"
        # Cast, because a bare NULL parameter compared against nothing leaves
        # the planner unable to type it. claim_task declares p_queue text and
        # gets the type from the signature; a client-side parameter has to say.
        "   AND (%(q)s::text IS NULL OR queue = %(q)s::text)"
        "   AND attempts < max_attempts"
        " ORDER BY priority, id LIMIT 1",
        {"q": queue}).fetchone()


def autonomous_credit(conn) -> tuple[float | None, str]:
    """What the month has left for work nobody watched, and its status.

    (None, status) when the pool is UNCOMPUTED -- which is not zero and must
    not be rounded to it. An unknown ceiling is a stop, not a budget of nought:
    the two produce the same behaviour here and completely different sentences,
    and the sentence is what gets read in the morning.
    """
    row = conn.execute("SELECT * FROM fleet_month_credit()").fetchone()
    if row["status"] != "COMPUTED":
        return None, str(row["status"])
    return float(row["autonomous_remaining_gbp"]), "COMPUTED"


def waiting_for_a_person(conn) -> list[dict[str, Any]]:
    """Everything sitting at READY_FOR_REVIEW when the loop gives up.

    This is the loop's actual output. The seven commands became one; what the
    one command owes back is the list of things it could not finish, which is
    the operator's accept queue.
    """
    return [dict(r) for r in conn.execute(
        "SELECT t.id, t.title, t.repo, t.branch_name,"
        "       t.acceptance_contract->>'work_type' AS work_type,"
        "       t.completed_at"
        "  FROM tasks t WHERE t.status = 'READY_FOR_REVIEW'"
        " ORDER BY t.id").fetchall()]


# ---------------------------------------------------------------------------
# The stages. Each returns a Step and never raises for an ordinary refusal.
# ---------------------------------------------------------------------------

def _build(cfg, conn, *, dry_run, failed: set[int], emit) -> tuple[Step, str | None]:
    """Claim and run one task, if there is one and it can be afforded.

    Returns (step, stop_reason). A stop_reason is a decision to end the loop,
    not an error: the credit ceiling and the repeat-failure stop both land here.
    """
    from runner import cycle

    nxt = next_claimable(conn, cfg["queue"])
    if nxt is None:
        return Step("build", False, "no task is queued"), None

    # THE REPEAT-FAILURE STOP, BEFORE THE CLAIM AND NOT AFTER IT.
    #
    # cycle.tick re-queues a failed task while attempts < max_attempts. Under
    # timers that is safe by accident -- the next fire is twenty minutes away.
    # Here QUEUED is claimed on the next pass, so max_attempts: 3 would be three
    # rebuilds in minutes with nobody between them.
    #
    # And a rebuild is a re-roll: task 69 ran four times off one spec and one
    # base and produced tests of 377, 606, 439 and 385 lines. The fourth cleared
    # the gate the third failed and then failed ruff on one new I001 -- GBP 3.32
    # to replace a verified branch with a broken one.
    if nxt["id"] in failed:
        return (Step("build", False,
                     f"task {nxt['id']} already failed this pass"),
                REPEAT_FAILURE)

    room, status = autonomous_credit(conn)
    cost = float(nxt["max_cost_gbp"])
    if room is None:
        return (Step("build", False,
                     f"the month's credit is {status}, so the next task's "
                     f"GBP {cost:.2f} cannot be checked against it"),
                CREDIT)
    if room < cost:
        return (Step("build", False,
                     f"task {nxt['id']} may cost GBP {cost:.2f} and the month "
                     f"has GBP {room:.2f} of autonomous credit left"),
                CREDIT)

    if dry_run:
        return Step("build", True,
                    f"WOULD build task {nxt['id']} ({nxt['title'][:60]}), "
                    f"GBP {cost:.2f} against GBP {room:.2f} remaining",
                    task_id=nxt["id"]), None

    result = cycle.tick(queue=cfg["queue"], log=emit)
    if result.outcome == "IDLE":
        # Raced: something claimed it between the peek and the tick. Not an
        # error and not a stop -- the next pass re-reads the queue.
        return Step("build", False, "nothing was claimable by the time it ran"), None

    step = Step("build", True,
                f"task {result.task_id}: {result.outcome} -- {result.reason}",
                task_id=result.task_id, cost_gbp=result.cost_gbp)
    if result.outcome == "FAILED" and result.task_id is not None:
        if result.task_id in failed:
            return step, REPEAT_FAILURE
        failed.add(result.task_id)
    return step, None


def _merge(cfg, conn, *, dry_run, emit) -> tuple[Step, str | None]:
    """Offer everything waiting to automerge, which refuses by default."""
    from console import automerge

    results = automerge.sweep(dry_run=dry_run, log=emit)
    if not results:
        return Step("merge", False, "nothing is waiting for review"), None

    # A DRY RUN REPORTS `would_merge` AND NO `reason`, so reading `merged`
    # alone prints "left for review -- 71:" with an empty explanation for a
    # task it would in fact have merged. The two keys mean the same thing on
    # the two paths and both are read here.
    merged = [r for r in results if r.get("merged") or r.get("would_merge")]
    if not merged:
        left = "; ".join(f"{r['task_id']}: {r.get('reason') or 'no reason given'}"
                         for r in results)
        return Step("merge", False, f"left for review -- {left}"), None
    verb = "would merge" if dry_run else "merged"
    return Step("merge", True,
                f"{verb} {', '.join(str(r['task_id']) for r in merged)}"), None


def _approve(cfg, conn, *, dry_run, emit) -> tuple[Step, str | None]:
    """Tick the top of the candidate list, if any ceiling leaves room.

    Every gate, the pace, the queue ceiling and the credit cut stay inside
    autoapprove. The loop does not re-implement or second-guess one of them; it
    only decides WHEN to ask.
    """
    from console import autoapprove

    plan = autoapprove.sweep(dry_run=dry_run)
    ids = plan.get("approve_ids") or []
    if not ids:
        return Step("approve", False,
                    plan.get("reason") or "nothing was eligible"), None
    return Step("approve", True,
                f"approved {len(ids)} candidate(s): "
                f"{', '.join(str(i) for i in ids)}"), None


# ---------------------------------------------------------------------------

def run(*, dry_run: bool = False, config_path: Path | None = None,
        emit: Callable[[str], None] = print,
        clock: Callable[[], float] = time.monotonic) -> ChainResult:
    """Run the chain to a fixpoint, or to the first stop.

    THE LOOP OWNS ITS CLOCK, and does not inherit fleet-runner.service's
    TimeoutStartSec=4200 -- which is sized for one task. Being killed by systemd
    mid-merge is the hardest failure to read in the morning: the merge either
    happened or did not, the decision row either exists or does not, and the
    journal stops mid-sentence. So the deadline is checked BETWEEN stages, never
    inside one, and the unit's timeout sits well above it as a backstop.
    """
    from console import config as console_config

    cfg = load_config(config_path)
    started = clock()
    deadline = started + cfg["wall_clock_seconds"]
    result = ChainResult(dry_run=dry_run)
    failed: set[int] = set()

    conn = _connect(console_config.console_reader_dsn())
    try:
        for _ in range(PASS_CEILING):
            if clock() >= deadline:
                result.stopped_by = WALL_CLOCK
                break

            acted_this_pass = False
            stop: str | None = None

            for name, fn in (("build", _build), ("merge", _merge),
                             ("approve", _approve)):
                if not cfg["stages"][name]:
                    continue
                # BETWEEN STAGES, NEVER INSIDE ONE. A stage that has started is
                # allowed to finish: a merge interrupted halfway is the state
                # this deadline exists to avoid producing.
                if clock() >= deadline:
                    stop = WALL_CLOCK
                    break

                if name == "build":
                    step, stop = fn(cfg, conn, dry_run=dry_run,
                                    failed=failed, emit=emit)
                else:
                    step, stop = fn(cfg, conn, dry_run=dry_run, emit=emit)

                result.steps.append(step)
                emit(f"  {step.stage}: {step.detail}")
                if stop:
                    break
                if step.acted:
                    acted_this_pass = True
                    # Back to the top: a build may have produced something to
                    # merge, and a merge may have queued something to build.
                    break

            result.passes += 1
            if stop:
                result.stopped_by = stop
                break
            if not acted_this_pass:
                result.stopped_by = IDLE
                break

            # A DRY RUN IS ONE PASS, AND HAS TO BE.
            #
            # The fixpoint is reached by the world changing: a built task stops
            # being QUEUED, a merged one stops being READY_FOR_REVIEW. A dry run
            # changes nothing, so every pass sees the state the last one saw and
            # decides the same thing again -- the loop would spin to the pass
            # ceiling and report a stop that means nothing.
            #
            # One pass is also the honest dry run. "What would this do next"
            # cannot be answered past the first step without executing it, and a
            # second pass would be the loop guessing at its own consequences.
            if dry_run:
                result.stopped_by = DRY_RUN_ONE_PASS
                break
        else:
            result.stopped_by = MAX_PASSES

        result.waiting = waiting_for_a_person(conn)
    finally:
        conn.close()

    result.failed_task_ids = sorted(failed)
    result.duration_s = round(clock() - started, 1)
    return result


def describe(result: ChainResult) -> list[str]:
    """The morning report, which is what the one command owes back."""
    out = [
        f"{result.passes} pass(es) in {result.duration_s}s, "
        f"GBP {result.spent_gbp:.2f} spent -- stopped: {result.stopped_by}",
    ]
    if result.dry_run:
        out.insert(0, "DRY RUN: nothing was written")
    if result.failed_task_ids:
        out.append(f"failed this run: {result.failed_task_ids}")
    if not result.waiting:
        out.append("nothing is waiting for you")
        return out
    out.append(f"{len(result.waiting)} waiting for your accept:")
    for t in result.waiting:
        out.append(f"  task {t['id']}  {t['work_type'] or '?'}  "
                   f"{t['branch_name'] or '(no branch)'}  {t['title'][:70]}")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="run_chain.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true",
                   help="decide everything, write nothing")
    p.add_argument("--config", type=Path, default=None)
    args = p.parse_args(argv)

    result = run(dry_run=args.dry_run, config_path=args.config,
                 emit=lambda m: log.info("%s", m))
    for line in describe(result):
        print(line)
    # EXIT 0 FOR AN IDLE NIGHT, on run_autoapprove.py's precedent: approving
    # nothing is an ordinary night and often the designed answer. A non-zero
    # exit is reserved for the loop stopping on a condition somebody should
    # read, which is the two safety stops.
    return 1 if result.stopped_by in (CREDIT, REPEAT_FAILURE, MAX_PASSES) else 0
