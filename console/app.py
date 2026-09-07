"""The fleet console. Four pages, read-only, no writes of any kind.

There is no POST route in this file and no form in any template. That is the
V1 boundary and it is worth stating as code rather than as intent: the
credential cannot write, the session is read-only, and there is no handler
that would try.

No polling and no live updates. The data changes hourly at most, a refresh is
enough, and a websocket is a service that can break silently.
"""
from __future__ import annotations

import json
from typing import Any

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from console import approve, config, db, decide, gitdiff, merge, queries, reverify

RUNNING_AS: str = ""
WRITING_AS: str = ""


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Both credentials are checked, and in opposite directions.

    The reader must be provably unable to write -- that is what makes every
    page safe. The writer must be provably able to record a verdict, and must
    be a different principal. Two DSNs accidentally set to the same value
    would otherwise fail only at the moment somebody pressed Accept, after the
    merge had already happened.
    """
    global RUNNING_AS, WRITING_AS
    RUNNING_AS = db.assert_read_only()
    WRITING_AS = db.assert_can_write()
    yield


app = FastAPI(title="fleet console", docs_url=None, redoc_url=None,
              lifespan=lifespan)
templates = Jinja2Templates(directory=str(config.PROJECT_ROOT / "console" / "templates"))


def _pretty(value: Any) -> str:
    return json.dumps(value, indent=2, default=str, sort_keys=True)


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = float(seconds)
    if seconds < 90:
        return f"{seconds:.1f}s"
    return f"{seconds / 60:.1f}m"


def _age(delta) -> str:
    if delta is None:
        return "—"
    total = int(delta.total_seconds())
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        return f"{total // 3600}h"
    return f"{total // 86400}d"


templates.env.filters["pretty"] = _pretty
templates.env.filters["duration"] = _duration
templates.env.filters["age"] = _age


def render(request: Request, template: str, status_code: int = 200,
           **extra: Any):
    """Every page gets the running identity and the diff stylesheet."""
    return templates.TemplateResponse(
        request, template,
        {"running_as": RUNNING_AS, "writing_as": WRITING_AS,
         "diff_css": gitdiff.diff_css(), "now": time.time(), **extra},
        status_code=status_code)


def same_origin(request: Request) -> bool:
    """Refuse a decision that did not come from this page.

    Basic auth is sent by the browser on every request to this host, including
    ones a different site caused. Without an origin check, a page elsewhere
    could make a logged-in reviewer merge a branch by loading an image. The
    two decision routes are the only places in this app where that matters,
    and they are the only places that would ever matter.
    """
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return False
    host = request.headers.get("host", "")
    return bool(host) and (origin.split("://", 1)[-1].split("/", 1)[0] == host)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return tasks(request, status="READY_FOR_REVIEW")


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return f"ok as {RUNNING_AS}"


# ---------------------------------------------------------------- page 1

@app.get("/tasks", response_class=HTMLResponse)
def tasks(request: Request, status: str | None = "READY_FOR_REVIEW"):
    """Default filter is READY_FOR_REVIEW, because that is the morning question."""
    if status in ("", "all", "ALL"):
        status = None
    return render(request, "tasks.html",
                  tasks=queries.task_list(status),
                  counts=queries.status_counts(), active=status,
                  reclaims=queries.reclaim_counts())


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: int):
    task = queries.task_detail(task_id)
    if task is None:
        return render(request, "missing.html", status_code=404,
                      what=f"task {task_id}")

    steps = queries.run_steps(task["run_id"])
    patch = next((s for s in steps if s["step_type"] == "PATCH_PROPOSED"), None)
    verification = next((s for s in steps if s["step_type"] == "VERIFICATION_RUN"), None)

    return render(
        request, "task_detail.html",
        task=task,
        reject_reasons=decide.REJECT_REASONS,
        reason_help=decide.REASON_HELP,
        outcome=_take_outcome(task_id),
        reclaims=queries.task_reclaims(task_id),
        runs=queries.task_runs(task_id),
        contract=task["acceptance_contract"] or {},
        steps=steps,
        patch=(patch or {}).get("payload", {}),
        verification=(verification or {}).get("payload", {}),
        budget=queries.run_budget(task["run_id"]),
        diff=gitdiff.for_branch(config.repo_root(), task["repo"],
                                task["base_branch"], task["branch_name"]),
    )


# ---------------------------------------------------------------- page 2

@app.get("/detectors", response_class=HTMLResponse)
def detectors(request: Request):
    return render(
        request, "detectors.html",
        health=queries.detector_health(),
        issues=queries.open_issues(),
        untriaged=queries.untriaged(),
        rates=queries.false_positive_rate(),
        coverage=queries.coverage_summary(),
        covered=queries.covered(),
    )


# ---------------------------------------------------------------- page 3

@app.get("/proposals", response_class=HTMLResponse)
def proposals(request: Request):
    return render(
        request, "proposals.html",
        proposals=queries.proposals(),
        evidence=queries.proposal_evidence(),
        cycles=queries.cycles(),
    )


# ---------------------------------------------------------------- page 4

@app.get("/decisions", response_class=HTMLResponse)
def decisions(request: Request, product: str | None = None):
    """The decision log, read-only, and deliberately with no form on it.

    Recording a decision is a shell command. It stays there because the log's
    value is the reason field, and a textarea on a web page is where a reason
    becomes "yes" -- whereas `fleet decision record --reason` makes the
    sentence the thing you are typing.

    Every outcome rendered here comes from `decision_outcomes`. There is no
    column behind any of it.
    """
    if product in ("", "all", "ALL"):
        product = None
    return render(request, "decisions.html",
                  decisions=queries.decisions(product),
                  products=queries.decision_products(),
                  totals=queries.decision_totals(),
                  active=product)


# ---------------------------------------------------------------- decisions
#
# The only two routes in this application that write. Everything else, on
# every page, reads as fleet_console_reader.
#
# There is no rework here, no task creation, no deploy and no re-run. Those
# stay in the shell where they are deliberate.

# The result of the last decision, held until the redirected page collects it.
# In-process and single-user; the console is one person with a browser, and a
# durable store for a message that survives one redirect would be a schema
# change for a toast.
_OUTCOMES: dict[int, dict[str, Any]] = {}


def _take_outcome(task_id: int) -> dict[str, Any] | None:
    return _OUTCOMES.pop(task_id, None)


def _load(task_id: int):
    task = queries.task_detail(task_id)
    if task is None:
        return None, None, None
    steps = queries.run_steps(task["run_id"])
    patch = next((s["payload"] for s in steps
                  if s["step_type"] == "PATCH_PROPOSED"), {})
    return task, patch, task["run_id"]


@app.post("/tasks/{task_id}/accept")
def accept(request: Request, task_id: int,
           branch: str = Form(...), rendered_at: float = Form(...),
           note: str = Form("")):
    """Merge the branch into its base, push the base, then record the verdict.

    In that order, and never the other way round: a verdict recorded before
    the merge would be a claim about something that had not happened yet.
    """
    if not same_origin(request):
        return render(request, "decided.html", status_code=403, task_id=task_id,
                      outcome={"ok": False, "headline": "Refused",
                               "detail": ["This decision did not come from the "
                                          "console's own page."]})
    task, patch, run_id = _load(task_id)
    if task is None:
        return render(request, "missing.html", status_code=404,
                      what=f"task {task_id}")

    repo = config.repo_root() / task["repo"]
    contract = task["acceptance_contract"] or {}
    recorded_base = (patch or {}).get("base_commit_sha", "")
    recorded_patch = (patch or {}).get("patch_commit_sha", "")

    # BEFORE the merge, never after. The contract's own verification, run
    # against the tree this branch would actually produce in the base as it
    # stands now -- not against the branch, which would only re-establish what
    # the original run already established.
    #
    # It happens in a throwaway worktree, so a failure leaves the checkout
    # untouched and records nothing, exactly as a conflicting merge does.
    check = merge.preflight(repo, task, branch, recorded_base, recorded_patch,
                            (patch or {}).get("branch_point_sha", ""))
    again = None
    if check.ok and not check.already_merged:
        again = reverify.run(
            repo, config.trial_worktree_root(), task, contract, branch,
            recorded_base=recorded_base,
            changed_files=[p for p in (patch or {}).get("files_changed", [])
                           if (patch or {}).get("file_status", {}).get(p) != "D"])

    result = merge.merge_and_push(
        repo, task, branch,
        recorded_base=recorded_base, recorded_patch=recorded_patch,
        branch_point=(patch or {}).get("branch_point_sha", ""),
        reverification=again)

    if not result.ok:
        _OUTCOMES[task_id] = {
            "ok": False, "headline": "Not merged, and nothing recorded",
            "loud": result.merged or result.pushed,
            "detail": ([result.reason] + [d for d in result.detail if d]
                       + ([f"re-verification: {c['command']} exited "
                           f"{c['exit_code']}"
                           for c in (again.checks if again else [])
                           if c["exit_code"] != 0]))}
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)

    merge_record = {
        "reverified": again.as_record() if again is not None else None,
        "already_merged": result.already_merged,
        "merge_commit": result.base_sha_after,
        "base_before": result.base_sha_before,
        "branch_tip": result.branch_tip,
        "pushed": result.pushed,
        "push_verified": result.push_verified,
        "remote_sha": result.remote_sha,
    }
    try:
        decide.record(task=task, run_id=run_id, verdict="MERGED",
                      decision=decide.ACCEPT_DECISION, note=note,
                      rendered_at=rendered_at, merge=merge_record)
    except decide.VerdictNotRecorded as exc:
        # The loud case. The merge happened and is on the remote; the database
        # does not know. Never swallowed.
        _OUTCOMES[task_id] = {
            "ok": False, "loud": True,
            "headline": "MERGED AND PUSHED, BUT THE VERDICT WAS NOT RECORDED",
            "detail": [str(exc),
                       f"{task['base_branch']} is at {result.base_sha_after[:12]} "
                       f"locally and on origin.",
                       "The branch is merged. The task still reads "
                       "READY_FOR_REVIEW. Record it by hand:",
                       f"UPDATE tasks SET status='MERGED' WHERE id={task_id};"]}
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)

    _OUTCOMES[task_id] = {
        "ok": True,
        "headline": ("Recorded as MERGED; the branch was already in "
                     + task["base_branch"] + ", so no merge was performed"
                     if result.already_merged else
                     "Merged, pushed and recorded"),
        "detail": result.detail}
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.post("/tasks/{task_id}/reject")
def reject(request: Request, task_id: int,
           reason: str = Form(...), rendered_at: float = Form(...),
           note: str = Form("")):
    """Record the verdict. The branch is not touched."""
    if not same_origin(request):
        return render(request, "decided.html", status_code=403, task_id=task_id,
                      outcome={"ok": False, "headline": "Refused",
                               "detail": ["This decision did not come from the "
                                          "console's own page."]})
    task, _, run_id = _load(task_id)
    if task is None:
        return render(request, "missing.html", status_code=404,
                      what=f"task {task_id}")
    if reason not in decide.REJECT_REASONS:
        _OUTCOMES[task_id] = {"ok": False, "headline": "Not recorded",
                              "detail": [f"{reason!r} is not a reason code the "
                                         f"database accepts."]}
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)

    try:
        decide.record(task=task, run_id=run_id, verdict="REJECTED",
                      decision=reason, note=note, rendered_at=rendered_at)
    except decide.VerdictNotRecorded as exc:
        _OUTCOMES[task_id] = {"ok": False, "headline": "Not recorded",
                              "detail": [str(exc)]}
        return RedirectResponse(f"/tasks/{task_id}", status_code=303)

    _OUTCOMES[task_id] = {
        "ok": True, "headline": f"Recorded as REJECTED ({reason})",
        "detail": ["The branch was not touched. It is still in the checkout "
                   "and on the remote if it was pushed."]}
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@app.get("/briefs", response_class=HTMLResponse)
def briefs(request: Request):
    """The daily briefs, as a SERIES.

    A single brief is a file on disk (`briefs/YYYY-MM-DD.md`) and does not need
    a web page. This page exists for what a file cannot show: the same metric
    across days, and whether the number of things the pass could not compute is
    growing.

    Nothing here is stored as a trend. Every figure is a claim row a pass wrote
    at the time, with the source and the recency it recorded — the page joins
    them, it does not recompute them. A trend recomputed today from today's
    database would restate history the moment a source was backfilled.
    """
    return render(request, "briefs.html",
                  runs=queries.brief_runs(),
                  series=queries.brief_series(),
                  latest=queries.brief_latest())


@app.get("/candidates", response_class=HTMLResponse)
def candidates(request: Request):
    """The approval surface: tick what you want built.

    A tick produces a DRAFT SPEC task, not a code task. specs/approval-surface.md
    §3 — two hand-written specs contained factual errors about file paths, and
    the check on the draft-spec contract is what turns that class into something
    a task cannot pass with rather than something a reviewer must catch.
    """
    return render(request, "candidates.html",
                  batches=queries.candidate_batches_open(),
                  open_candidates=queries.candidates_open(),
                  decided=queries.candidates_decided(),
                  ceilings=queries.ceilings())


@app.post("/candidates/approve")
async def approve_candidates(request: Request):
    """Record one batch decision and queue its draft-spec tasks.

    One transaction, in approve.py. The ceilings are enforced there and in the
    database beneath it; a refusal is a designed answer and is rendered as one
    rather than as a 500.
    """
    if not same_origin(request):
        return render(request, "decided.html", status_code=403, task_id=0,
                      outcome={"ok": False, "headline": "Refused",
                               "detail": ["This decision did not come from the "
                                          "console's own page."]})
    form = await request.form()
    approve_ids = [int(v) for v in form.getlist("approve")]
    not_now_ids = [int(v) for v in form.getlist("not_now")]
    reject = {}
    for k in form.keys():
        if k.startswith("reject_reason_"):
            cid = int(k.rsplit("_", 1)[1])
            if str(form.get(k) or "").strip():
                reject[cid] = str(form.get(k))

    try:
        result = approve.approve_batch(
            reason=str(form.get("reason") or ""),
            approve_ids=approve_ids, reject=reject, not_now_ids=not_now_ids,
            decided_by=str(form.get("decided_by") or "eamonn"))
    except approve.ApprovalRefused as exc:
        return render(request, "decided.html", status_code=409, task_id=0,
                      outcome={"ok": False, "headline": "Not recorded",
                               "detail": [str(exc)]})

    return render(request, "decided.html", task_id=0, outcome={
        "ok": True, "headline": "Recorded",
        "detail": [
            f"{len(result['queued_task_ids'])} draft-spec task(s) queued: "
            f"{result['queued_task_ids']}",
            f"{result['rejected']} rejected, {result['not_now']} left for later.",
            "Nothing is built yet. Each draft spec is reviewed before a code "
            "task exists.",
        ]})
