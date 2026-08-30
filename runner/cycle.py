"""One task, start to finish.

The order here departs from the spec's numbered list in one place, and it
matters. The spec runs verification (step 5) before deriving the diff (step
6). This runs the diff first and refuses to verify a tree whose boundary is
dirty, because a suite executed after the agent may have edited that suite
returns a result about the agent's tests rather than the project's. A PASS
obtained that way is worse than no result: it is a false one with provenance
attached.

Four database identities, on four connections:

    fleet_task_runner    claims the task, opens the run, records the branch
    fleet_model_gateway  reserves and settles budget
    fleet_agent          writes PATCH_PROPOSED
    fleet_verifier       writes VERIFICATION_RUN

They are separate because 001's step_authority says the thing that proposes a
patch is not the thing that certifies it. One connection holding all four
would satisfy every trigger while proving nothing.

Nothing in this module merges and nothing deploys. `runs.status` is never set
to DEPLOYED, there is no call to `git merge`, and the only push names an
explicit task-branch refspec.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from runner import agent as agent_mod
from runner import boundary, config, evidence, reclaim as reclaim_mod
from runner import verify, worktree

FORBIDDEN_RUN_STATUS = {"DEPLOYED"}


@dataclass
class TickResult:
    task_id: int | None = None
    run_id: int | None = None
    outcome: str = "IDLE"          # IDLE | READY_FOR_REVIEW | FAILED
    reason: str = ""
    branch: str | None = None
    pushed: bool = False
    requeued: bool = False
    change: boundary.Change | None = None
    verdict: boundary.Boundary | None = None
    verification: verify.Verification | None = None
    cost_gbp: float = 0.0
    duration_s: float = 0.0
    notes: list[str] = field(default_factory=list)
    reclaimed: list[tuple[int, str]] = field(default_factory=list)


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True)


def tick(*, queue: str | None = None, only_task: int | None = None,
         push: bool = True, reclaim_first: bool = True,
         log: Callable[[str], None] = print) -> TickResult:
    """Claim at most one task and carry it to a branch or to a failure.

    One task per tick, serial. There is no parallel path here and no loop: a
    second task is a second invocation, so cost and blast radius stay one
    task wide.
    """
    settings = config.load_runner_config()
    started = time.monotonic()
    result = TickResult()

    # Before claiming anything: recover ticks that died. A task left RUNNING
    # holds its run ACTIVE, and runs_one_active_per_task then blocks its own
    # retry, so a stuck task stays stuck until somebody notices. Running it
    # first means a reclaimed task is claimable in this tick.
    #
    # Every reclaim writes a task_reclaims row, which is what makes an
    # automatic repair readable afterwards rather than inferable from the
    # attempt count.
    if reclaim_first:
        recovered = reclaim_mod.before_claiming(log=log)
        result.reclaimed = [(r.task_id, r.outcome) for r in recovered]

    runner = _connect(config.task_runner_dsn())
    try:
        task = _claim(runner, queue, only_task, log)
        if task is None:
            log("nothing queued")
            return result

        result.task_id = task["id"]
        deadline = started + task["timeout_seconds"]
        log(f"task {task['id']}  {task['title']}")
        log(f"  budget £{task['max_cost_gbp']}   "
            f"wall clock {task['timeout_seconds']}s   "
            f"attempt {task['attempts']}/{task['max_attempts']}")

        try:
            _execute(runner, task, settings, deadline, push, result, log)
        except Exception as exc:                      # noqa: BLE001
            result.outcome = "FAILED"
            result.reason = f"{type(exc).__name__}: {exc}"
            log(f"  ! {result.reason}")

        _settle_task(runner, task, result, log)
        return result
    finally:
        result.duration_s = time.monotonic() - started
        runner.close()


# ---- claiming -------------------------------------------------------------

def _claim(runner, queue, only_task, log) -> dict | None:
    if only_task is not None:
        # A named task still goes through the state machine: the transition
        # trigger is what makes "claimed" mean claimed, and skipping it here
        # would make --task a way around the thing being tested.
        row = runner.execute(
            "SELECT id, status FROM tasks WHERE id = %s", (only_task,)).fetchone()
        if row is None:
            log(f"no task {only_task}")
            return None
        if row["status"] != "QUEUED":
            log(f"task {only_task} is {row['status']}, not QUEUED")
            return None
        runner.execute(
            "UPDATE tasks SET status='RUNNING', claimed_at=now(),"
            " attempts = attempts + 1 WHERE id=%s AND status='QUEUED'",
            (only_task,))
        task_id = only_task
    else:
        task_id = runner.execute(
            "SELECT claim_task(%s) AS id", (queue,)).fetchone()["id"]
        if task_id is None:
            return None
    return runner.execute("SELECT * FROM tasks WHERE id=%s", (task_id,)).fetchone()


# ---- the body of a tick ---------------------------------------------------

def _execute(runner, task, settings, deadline, push, result, log) -> None:
    contract = task["acceptance_contract"]
    repo = Path(settings["repo_root"]) / task["repo"]
    if not (repo / ".git").exists():
        raise RuntimeError(f"no git repository at {repo}")

    # "The working tree is never touched" is asserted, not assumed. The
    # snapshot covers every file, not only tracked ones -- see
    # worktree.Untouched.
    #
    # `readable_repos` are checkouts the agent may READ. --add-dir grants read
    # access and nothing makes them read-only, so a write there would land
    # outside the worktree's git index and the derived diff would show
    # nothing. They are snapshotted for exactly that reason.
    watched: dict[str, worktree.Untouched] = {}
    watch_paths: dict[str, Path] = {task["repo"]: repo}
    fleet_repo = config.PROJECT_ROOT
    if fleet_repo.resolve() != repo.resolve():
        watch_paths["fleet"] = fleet_repo
    readable: list[Path] = []
    for name in contract.get("readable_repos", []) or []:
        other = Path(settings["repo_root"]) / name
        if not other.exists():
            raise RuntimeError(f"readable repo {name} is not at {other}")
        readable.append(other)
        watch_paths.setdefault(name, other)
    for name, path in watch_paths.items():
        watched[name] = worktree.Untouched.of(path)

    branch = worktree.branch_name(task["id"], task["attempts"])
    result.branch = branch
    wt_root = Path(settings["worktree_root"])
    wt_root.mkdir(parents=True, exist_ok=True)

    wt_path, base_sha = worktree.create(
        repo, wt_root, branch, task["base_branch"])
    # The point the branch was cut from, kept separately from the sha the
    # agent's diff is measured against. They start equal and stop being equal
    # the moment anything is committed before the agent runs -- the evidence
    # pack does exactly that -- and they answer different questions:
    #
    #   branch_point_sha  where the branch left the base. The only thing a
    #                     merge base can ever equal.
    #   base_commit_sha   what the agent's work is diffed against.
    #
    # Conflating them made task 5 unacceptable: its recorded base was the
    # evidence commit, which sits ON the branch, so no merge base could match
    # it and the guard refused a branch nothing was wrong with.
    branch_point_sha = base_sha
    log(f"  worktree {wt_path}  off {task['base_branch']} @ {base_sha[:12]}")

    keep_branch = False
    try:
        run_id = _open_run(runner, task, contract)
        result.run_id = run_id
        log(f"  run {run_id}")

        # ---- the agent, under the runner's clock ----
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("wall clock exhausted before the agent started")

        # The evidence pack: the RUNNER reads the databases, as roles holding
        # SELECT and nothing else, and the agent reads a file. It never holds a
        # credential and has no shell to use one with.
        pack_path = contract.get("evidence_pack")
        if contract.get("evidence_queries"):
            results = evidence.run_queries(contract["evidence_queries"])
            written = evidence.write_pack(
                wt_path, pack_path or "EVIDENCE.md", results, task)
            failed = [r.key for r in results if not r.ok]
            log(f"  evidence pack {written.relative_to(wt_path)}: "
                f"{len(results)} quer{'y' if len(results) == 1 else 'ies'}"
                + (f", {len(failed)} FAILED: {', '.join(failed)}" if failed else ""))
            result.notes.extend(
                f"evidence query {k} failed and produced no reading" for k in failed)

            # COMMITTED BEFORE THE AGENT RUNS, and the base moves to that
            # commit. The pack is the runner's file, not the agent's: leaving
            # it uncommitted put it in the derived diff, where the boundary
            # correctly refused it for being outside writable_paths -- the
            # runner's own artifact failing the runner's own check.
            #
            # Committing it also keeps it: the readings a document rests on
            # travel with the document, on the same branch, so a reviewer can
            # see what the numbers came from.
            boundary.commit_agent_work(
                wt_path, f"evidence pack for task {task['id']}: "
                         f"{len(results)} readings taken before the agent ran")
            base_sha = boundary.git(wt_path, "rev-parse", "HEAD").strip()
            log(f"  evidence committed; the agent's diff is measured from "
                f"{base_sha[:12]}")

        token, reserved = _reserve(task, run_id, log)
        prompt = agent_mod.build_prompt(task, contract)
        outcome = agent_mod.invoke(
            wt_path, prompt, int(remaining),
            allowed_tools=tuple(contract.get("agent_tools",
                                             settings["agent_tools"])),
            readable=tuple(readable))
        result.cost_gbp = _settle(token, reserved, outcome, run_id, settings,
                                  result, log)
        log(f"  agent exit {outcome.exit_code} in {outcome.duration_ms}ms"
            + ("  TIMED OUT" if outcome.timed_out else ""))

        if outcome.timed_out:
            result.outcome = "FAILED"
            result.reason = (f"agent exceeded the {task['timeout_seconds']}s "
                             f"wall clock and was killed")
            _record_patch(task, run_id, base_sha, None, outcome, log,
                          branch_point_sha=branch_point_sha)
            return

        # ---- what it actually did ----
        boundary.commit_agent_work(
            wt_path, f"fleet task {task['id']}: {task['title']}")
        change = boundary.derive(wt_path, base_sha)
        change.reported = outcome.reported_paths
        result.change = change
        _record_patch(task, run_id, base_sha, change, outcome, log,
                      branch_point_sha=branch_point_sha)

        if change.empty:
            result.outcome = "FAILED"
            result.reason = "the agent changed nothing"
            return

        log(f"  derived {len(change.paths)} changed files, "
            f"{change.diff_lines} lines")
        if change.reported is None:
            log("  the agent reported no file list")
        else:
            div = change.divergence
            if div["touched_but_unclaimed"] or div["claimed_but_untouched"]:
                log(f"  the agent's account differs from git: "
                    f"+{div['touched_but_unclaimed']} "
                    f"-{div['claimed_but_untouched']}")

        # ---- the boundary, before anything is run ----
        verdict = boundary.enforce(change, contract)
        result.verdict = verdict
        keep_branch = True
        if not verdict.clean:
            result.outcome = "FAILED"
            result.reason = "boundary violation"
            # Carried on the result, not only written to the database: a
            # caller that cannot tell "verification failed" from "verification
            # was never run" cannot report the difference either.
            result.verification = verify.Verification(
                skipped_reason="boundary violation")
            for line in verdict.reasons():
                log(f"  REFUSED  {line}")
            _record_verification(
                task, run_id, base_sha, change, wt_path, contract,
                result.verification, verdict, log)
            return

        log("  boundary clean")

        # ---- verification, on a tree whose suite is known unmoved ----
        #
        # Dependencies are linked in HERE, after the diff is derived and
        # judged, and never before: the agent has finished and cannot write
        # through them. See worktree.link_dependencies.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("wall clock exhausted before verification")
        links = worktree.link_dependencies(wt_path, contract.get("worktree_links", {}))
        if links:
            log(f"  linked {len(links)} dependency tree(s) for verification")
        try:
            verification = verify.run(
                wt_path, contract["verification"], remaining,
                changed=[p for p in change.paths
                         if change.status.get(p) != "D"],
                facts={"FLEET_BASE_SHA": base_sha,
                       "FLEET_HEAD_SHA": change.head_sha,
                       "FLEET_TASK_ID": str(task["id"])})
        finally:
            worktree.unlink_dependencies(links)
        result.verification = verification
        for check in verification.checks:
            mark = "skip" if not check.ran else "ok  " if check.passed else "FAIL"
            log(f"  {mark} {check.command} ({check.duration_ms}ms)"
                + (f"  -- {check.skipped_reason}" if not check.ran else ""))
            if not check.passed:
                log("        " + check.output_tail.strip().splitlines()[-1][:150]
                    if check.output_tail.strip() else "")

        _record_verification(task, run_id, base_sha, change, wt_path, contract,
                             verification, verdict, log)

        if not verification.passed:
            result.outcome = "FAILED"
            result.reason = "verification failed"
            return

        # ---- the branch, and nothing beyond it ----
        if push and worktree.has_remote(repo, settings["remote"]):
            worktree.push(repo, branch, task["base_branch"], settings["remote"])
            result.pushed = True
            log(f"  pushed {branch}")
        elif push:
            # ~/fleet has no remote. The document on the local branch IS the
            # artifact; calling that a failed push would report a good run as
            # a broken one.
            result.notes.append(
                f"{task['repo']} has no remote, so the branch is local. The "
                f"document is the artifact.")
            log(f"  branch {branch} left local ({task['repo']} has no remote)")
        else:
            result.notes.append("not pushed (--no-push); the branch is local")
            log(f"  branch {branch} left local")

        result.outcome = "READY_FOR_REVIEW"
        result.reason = "verified, branch ready"
    finally:
        worktree.remove(repo, wt_path)
        if not keep_branch:
            worktree.delete_branch(repo, branch)
        for name, snap in watched.items():
            snap.assert_unchanged(watch_paths[name], f"the {name} checkout")


# ---- the database side ----------------------------------------------------

def _open_run(runner, task, contract) -> int:
    return runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s, %s, %s, %s) RETURNING id",
        (task["id"], contract.get("work_type", "dd_feature"),
         int(contract.get("contract_version", 1)), task["max_cost_gbp"]),
    ).fetchone()["id"]


def _reserve(task, run_id, log) -> tuple[str | None, float]:
    """Reserve the whole task budget up front.

    The reservation is an upper bound, and settle_model_budget refuses an
    actual above it, so reserving the cap is what makes the cap enforceable
    at settlement rather than merely recorded.
    """
    reserved = float(task["max_cost_gbp"])
    with _connect(config.model_gateway_dsn()) as gw:
        token = gw.execute("SELECT reserve_model_budget(%s::bigint, %s::numeric) AS t",
                           (run_id, reserved)).fetchone()["t"]
    if token is None:
        raise RuntimeError("budget breaker tripped: no reservation granted")
    return token, reserved


def _settle(token, reserved, outcome, run_id, settings, result, log) -> float:
    """Close the reservation with what the call actually cost.

    If the agent spent more than the task authorised, the reservation is
    closed at its upper bound -- the function refuses anything higher -- and
    the true figure goes in the payload rather than being lost. The wall
    clock, not this, is what stops a runaway.
    """
    usd = outcome.cost_usd or 0.0
    gbp = round(usd * float(settings["usd_to_gbp"]), 6)
    settled = min(gbp, reserved)
    if gbp > reserved:
        note = (f"agent cost £{gbp:.4f} exceeded the reserved £{reserved:.4f}; "
                f"settled at the cap and recorded the true figure")
        result.notes.append(note)
        log(f"  ! {note}")

    now = datetime.now(timezone.utc).isoformat()
    call = {
        "provider": "anthropic", "model": outcome.raw.get("model") or "claude-cli",
        "purpose": "task_runner_patch",
        "started_at": now, "completed_at": now,
        "total_duration_ms": outcome.duration_ms,
        "ok": outcome.ok,
    }
    usage = outcome.raw.get("usage") or {}
    if isinstance(usage, dict):
        call["prompt_tokens"] = usage.get("input_tokens")
        call["completion_tokens"] = usage.get("output_tokens")

    with _connect(config.model_gateway_dsn()) as gw:
        gw.execute("SELECT settle_model_budget(%s::uuid, %s::numeric, %s::jsonb)",
                   (token, settled, Jsonb(call)))
    return settled


def _record_patch(task, run_id, base_sha, change, outcome, log,
                  *, branch_point_sha: str = "") -> None:
    """PATCH_PROPOSED, written as fleet_agent.

    The derived facts and the agent's own account both go in, labelled, so
    the record shows what was claimed next to what was done. Only the derived
    side is ever read by a decision.
    """
    payload: dict[str, Any] = {
        "base_commit_sha": base_sha,
        "branch_point_sha": branch_point_sha or base_sha,
        "agent_exit_code": outcome.exit_code,
        "agent_timed_out": outcome.timed_out,
        "agent_duration_ms": outcome.duration_ms,
        "agent_session_id": outcome.session_id,
        "derived_by": "runner",
    }
    if change is not None:
        payload.update({
            "patch_commit_sha": change.head_sha,
            "files_changed": change.paths,
            "file_status": change.status,
            "diff_lines": change.diff_lines,
            "ignored_writes": change.ignored_writes,
            "agent_reported_files": change.reported,
            "divergence": change.divergence,
        })
    with _connect(config.agent_dsn()) as conn:
        conn.execute(
            "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
            " VALUES (%s, 1, 'PATCH_PROPOSED', %s, %s)",
            (run_id, "fleet-runner/agent", Jsonb(payload)))


def _record_verification(task, run_id, base_sha, change, wt_path, contract,
                         verification, verdict, log) -> None:
    """VERIFICATION_RUN, written as fleet_verifier.

    001 refuses a PASS without a verifier-derived `boundary_clean` and full
    diff provenance, and refuses one whose patch sha is not the latest
    proposal. Both are the database restating this module's whole point, and
    both are left to it rather than being duplicated here.
    """
    passed = verdict.clean and verification.passed
    payload: dict[str, Any] = {
        "result": "PASS" if passed else "FAIL",
        "boundary_clean": verdict.clean,
        "base_commit_sha": base_sha,
        "patch_commit_sha": change.head_sha,
        "suite_commit_sha": boundary.suite_digest(
            wt_path, "HEAD", contract["protected_paths"]),
        "suite_commit_sha_at_base": boundary.suite_digest(
            wt_path, base_sha, contract["protected_paths"]),
        "contract_version": int(contract.get("contract_version", 1)),
        "checks": [{"command": c.command, "expanded": c.expanded,
                    "exit_code": c.exit_code, "duration_ms": c.duration_ms,
                    "timed_out": c.timed_out, "skipped_reason": c.skipped_reason,
                    "output_tail": c.output_tail} for c in verification.checks],
        "verification_skipped": verification.skipped_reason,
        "boundary_violations": {
            "protected": verdict.protected_hits,
            "outside_writable": verdict.outside_writable,
            "over_diff_limit": verdict.over_diff_limit,
            "diff_lines": verdict.diff_lines,
        },
    }
    with _connect(config.verifier_dsn()) as conn:
        conn.execute(
            "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
            " VALUES (%s, 2, 'VERIFICATION_RUN', %s, %s)",
            (run_id, "fleet-runner/verifier", Jsonb(payload)))


def _settle_task(runner, task, result, log) -> None:
    """Move the task and close the run. Never to a deploying state."""
    if result.run_id is not None:
        status = "AWAITING_HUMAN" if result.outcome == "READY_FOR_REVIEW" else "FAILED"
        assert status not in FORBIDDEN_RUN_STATUS
        runner.execute(
            "UPDATE runs SET status=%s, completed_at=now() WHERE id=%s",
            (status, result.run_id))

    if result.outcome == "READY_FOR_REVIEW":
        runner.execute(
            "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name=%s,"
            " completed_at=now() WHERE id=%s", (result.branch, task["id"]))
        log(f"  -> READY_FOR_REVIEW  {result.branch}")
        return

    if task["attempts"] < task["max_attempts"]:
        runner.execute(
            "UPDATE tasks SET status='QUEUED', claimed_at=NULL WHERE id=%s",
            (task["id"],))
        result.requeued = True
        log(f"  -> QUEUED again ({task['attempts']}/{task['max_attempts']} used)")
    else:
        runner.execute(
            "UPDATE tasks SET status='FAILED', completed_at=now() WHERE id=%s",
            (task["id"],))
        log(f"  -> FAILED  {result.reason}")
