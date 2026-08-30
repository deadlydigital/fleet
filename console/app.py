"""The fleet console. Three pages, read-only, no writes of any kind.

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

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from console import config, db, gitdiff, queries

RUNNING_AS: str = ""


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Refuse to serve as a credential that can write."""
    global RUNNING_AS
    RUNNING_AS = db.assert_read_only()
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
        {"running_as": RUNNING_AS, "diff_css": gitdiff.diff_css(), **extra},
        status_code=status_code)


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
                  counts=queries.status_counts(), active=status)


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
