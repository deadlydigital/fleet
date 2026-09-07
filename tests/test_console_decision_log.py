"""The decisions page. Read-only, and the outcomes on it are derived.

Two things are worth testing here and the HTML is neither of them:

1. **The page adds no write route.** The console has exactly two POSTs, both
   about merging a task. A decision log with a form on it would be a third,
   and the reason it must not exist is in `decisions()`'s docstring.
2. **What it renders moves when the world moves.** Every outcome cell comes
   from a view. The test changes the task after the page has been loaded once
   and reloads it, which no amount of reading the template can establish.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_decision_log import (PRODUCT, add_issue, add_run, add_task, decide,
                               merge_task, reopen_issue, resolve_issue)


@pytest.fixture
def client(dsns, monkeypatch):
    from console import app as app_module
    monkeypatch.setattr(app_module.config, "repo_root", lambda: Path("/nonexistent"))
    with TestClient(app_module.app) as c:
        yield c


def test_the_decisions_page_adds_no_write_route(client):
    """`/decisions` is read-only and stays so.

    The exhaustive list grew on 7 Sep 2026 when `/candidates/approve` was added
    deliberately (`specs/approval-surface.md`). What this test is actually about
    is unchanged and is the second assertion: NO ROUTE UNDER `/decisions`.
    Recording a decision stays a shell command, because the log's value is the
    reason field and a textarea on a web page is where a reason becomes "yes".

    The candidates page types its reason for the same argument: one sentence
    about the selection, written last, against a visible list — not a box beside
    each row.
    """
    posts = {r.path for r in client.app.routes
             if "POST" in getattr(r, "methods", set())}
    assert posts == {"/tasks/{task_id}/accept", "/tasks/{task_id}/reject",
                     "/candidates/approve"}
    assert not any(p.startswith("/decisions") for p in posts)


def test_an_empty_log_says_so(client):
    body = client.get("/decisions").text
    assert "Nothing recorded yet" in body


def test_a_rejection_and_its_reason_are_on_the_page(client, console):
    decide(console, decision="REJECTED",
           reason="right diagnosis, wrong quarter",
           subject="Rework the AOV card")
    body = client.get("/decisions").text
    assert "REJECTED" in body
    assert "right diagnosis, wrong quarter" in body
    assert "Rework the AOV card" in body


def test_the_outcome_is_recomputed_between_two_loads(client, console, admin):
    """The property the page claims about itself, exercised rather than read."""
    task = add_task(console, title="Refund reporting")
    decide(console, task_id=task, subject=None)

    assert "IN_FLIGHT" in client.get("/decisions").text

    add_run(admin, task, "3.75", status="AWAITING_HUMAN")
    merge_task(console, admin, task)
    admin.execute("COMMIT")

    body = client.get("/decisions").text
    assert "DELIVERED" in body
    assert "£3.75" in body


def test_a_reopened_issue_is_not_shown_as_a_decision_that_held(
        client, console, admin):
    issue = add_issue(admin)
    decide(console, issue_id=issue, subject="close the reconciliation gap")
    resolve_issue(admin, issue)
    reopen_issue(admin, issue)
    resolve_issue(admin, issue)
    admin.execute("COMMIT")

    body = client.get("/decisions").text
    assert "REOPENED" in body
    assert "RESOLVED_HELD" not in body
    assert "came back after this decision" in body


def test_a_backfilled_row_is_marked_and_its_reason_is_not_dressed_up(
        client, console):
    decide(console, subject="an old task", origin="BACKFILLED",
           confidence="INFERRED", reason="UNRECORDED", decided_by="UNRECORDED")
    body = client.get("/decisions").text
    assert "reconstructed" in body
    assert "not recorded at the time, and not invented" in body


def test_a_decision_citing_nothing_renders_absent_not_failed(client, console):
    decide(console, subject="a judgement call with nothing to point at")
    body = client.get("/decisions").text
    assert "NOT_DELIVERED" not in body
    assert "STILL_OPEN" not in body


def test_the_product_filter_is_a_filter_not_a_partition(client, console):
    decide(console, product="deadly_digital", subject="one product")
    decide(console, product="fleet", subject="another product")

    both = client.get("/decisions").text
    assert "one product" in both and "another product" in both

    one = client.get("/decisions?product=fleet").text
    assert "another product" in one and "one product" not in one
