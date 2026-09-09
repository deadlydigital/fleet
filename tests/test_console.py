"""The console, against the real database and the real read-only role.

The console's entire safety argument is the credential it holds, so the first
tests here are about that rather than about HTML. The rest check that the
three pages surface the things the spec says are the reason they exist --
the divergence, the blocked-clear reason, the denominator, and the fact that
zero-output cycles cannot be shown.
"""
from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests import support_proposals as sp

REPO = "deadly-digital-platform"
from tests.support import PLATFORM_FLOOR

FLOOR = PLATFORM_FLOOR

def contract(**over) -> dict:
    c = {"work_type": "dd_feature", "repo": REPO, "base_branch": "main",
         "contract_version": 1,
         "writable_paths": ["api/analytics/services/analytics_engine.py"], "protected_paths": list(FLOOR),
         "verification": ["true"], "max_diff_lines": 200, "max_cost_gbp": 3.00}
    c.update(over)
    return c


@pytest.fixture
def client(dsns, monkeypatch):
    from console import app as app_module
    monkeypatch.setattr(app_module.config, "repo_root", lambda: Path("/nonexistent"))
    with TestClient(app_module.app) as c:
        yield c


@pytest.fixture
def a_task(console, admin, runner):
    """A task carried to READY_FOR_REVIEW the way the runner carries one.

    Each move is made by the identity the transition table names: the console
    writes the queue, the runner claims it and marks it ready. Driving the
    whole thing as one role would arrange a state the system cannot actually
    reach, and the page would then be tested against a fiction.
    """
    tid = console.execute(
        "INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,"
        " max_cost_gbp, objective_ref)"
        " VALUES ('a task','# the spec body',%s,'main',%s,3.00,'dd-feature-parity')"
        " RETURNING id", (REPO, json.dumps(contract()))).fetchone()["id"]
    console.commit()

    runner.execute("SELECT claim_task(NULL)")
    runner.commit()

    # admin, not console: fleet_console holds SELECT on runs and not INSERT,
    # which is 003's grant doing its job rather than something to work around.
    rid = admin.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp,"
        " committed_gbp, status) VALUES (%s,'dd_feature',1,3.00,0.75,'AWAITING_HUMAN')"
        " RETURNING id", (tid,)).fetchone()["id"]

    runner.execute(
        "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name='fleet/task-1',"
        " completed_at=now() WHERE id=%s", (tid,))
    runner.commit()
    return tid, rid


def add_steps(admin, run_id, *, reported, derived, divergence):
    admin.execute(
        "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
        " VALUES (%s,1,'PATCH_PROPOSED','fleet-runner/agent',%s)",
        (run_id, json.dumps({"base_commit_sha": "a" * 40, "patch_commit_sha": "b" * 40,
                             "files_changed": derived, "file_status": {p: "M" for p in derived},
                             "diff_lines": 3, "ignored_writes": [],
                             "agent_reported_files": reported,
                             "divergence": divergence, "derived_by": "runner"})))
    admin.execute(
        "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
        " VALUES (%s,2,'VERIFICATION_RUN','fleet-runner/verifier',%s)",
        (run_id, json.dumps({"result": "PASS", "boundary_clean": True,
                             "base_commit_sha": "a" * 40, "patch_commit_sha": "b" * 40,
                             "suite_commit_sha": "s" * 64,
                             "suite_commit_sha_at_base": "s" * 64,
                             "contract_version": 1,
                             "checks": [{"command": "pytest -q", "expanded": "pytest -q",
                                         "exit_code": 0, "duration_ms": 12,
                                         "timed_out": False, "skipped_reason": None,
                                         "output_tail": ""}],
                             "verification_skipped": None,
                             "boundary_violations": {"protected": {}, "outside_writable": [],
                                                     "over_diff_limit": False,
                                                     "diff_lines": 3}})))


# ---- the credential ------------------------------------------------------

def test_the_console_runs_as_a_role_that_cannot_write(dsns):
    from console import db
    assert db.assert_read_only() == "fleet_test_console_reader"


def test_it_refuses_to_start_as_a_credential_that_can_write(dsns, monkeypatch):
    """The whole safety argument, checked rather than documented."""
    from console import db
    monkeypatch.setenv("FLEET_CONSOLE_READER_DSN", dsns["console"])
    with pytest.raises(db.NotReadOnly, match="can write"):
        db.assert_read_only()


def test_the_reader_role_cannot_write_even_if_asked(dsns):
    """Belt and braces: the session flag is not what stops it, the role is."""
    with psycopg.connect(dsns["console_reader"], autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM tasks")


def test_the_proposal_layers_reader_still_cannot_see_decisions(dsns):
    """004 must not have widened the wrong role. 002's B7, from the outside."""
    with psycopg.connect(dsns["reader"], autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT 1 FROM decisions")


def test_the_only_write_routes_are_accept_reject_and_approve(client):
    """Three actions, no more. No rework, no re-run, no deploy.

    This is the assertion that stops the next feature becoming a button
    without somebody deciding it should be — and it worked: it failed when
    `/candidates/approve` was added, which is the point of it.

    TASK CREATION WAS ADDED DELIBERATELY on 7 Sep 2026, and this docstring
    used to say "no task creation". `specs/approval-surface.md` is the decision:
    a ticked candidate queues a DRAFT-SPEC task, never a code task, and a human
    reviews the spec through accept/reject before any code task exists. The
    ceilings that make it safe are in the database (013), not in this route.

    The list stays exhaustive. A fourth entry needs its own decision.
    """
    from console.app import app
    writes = {r.path for r in app.routes
              if hasattr(r, "methods") and r.methods & {"POST", "PUT", "PATCH", "DELETE"}}
    assert writes == {"/tasks/{task_id}/accept", "/tasks/{task_id}/reject",
                      "/candidates/approve"}
    assert not any("PUT" in r.methods or "DELETE" in r.methods
                   for r in app.routes if hasattr(r, "methods"))


def test_every_page_route_is_still_a_read(client):
    from console.app import app
    pages = {r.path for r in app.routes
             if hasattr(r, "methods") and r.methods == {"GET"}}
    assert {"/tasks", "/tasks/{task_id}", "/detectors", "/proposals"} <= pages


# ---- page 1 --------------------------------------------------------------

def test_tasks_defaults_to_ready_for_review(client, a_task, console):
    console.execute(
        "INSERT INTO tasks (title, spec_md, repo, acceptance_contract, max_cost_gbp)"
        " VALUES ('still queued','x',%s,%s,1.00)", (REPO, json.dumps(contract())))
    console.commit()
    body = client.get("/tasks").text
    assert "a task" in body
    assert "still queued" not in body, "the default filter is not READY_FOR_REVIEW"
    assert "still queued" in client.get("/tasks?status=all").text


def test_task_detail_shows_the_spec_and_the_contract(client, a_task):
    tid, _ = a_task
    body = client.get(f"/tasks/{tid}").text
    assert "# the spec body" in body
    assert "api/tests/**" in body          # a protected glob
    assert "api/analytics/services/analytics_engine.py" in body            # a writable glob


def test_divergence_is_surfaced(client, a_task, admin):
    """It is recorded so under-reporting is visible after the fact, and it is
    invisible unless something surfaces it."""
    tid, rid = a_task
    add_steps(admin, rid, reported=["api/analytics/services/analytics_engine.py"],
              derived=["api/analytics/services/analytics_engine.py", "api/tests/test_x.py"],
              divergence={"touched_but_unclaimed": ["api/tests/test_x.py"],
                          "claimed_but_untouched": []})
    body = client.get(f"/tasks/{tid}").text
    assert "disagree" in body
    assert "api/tests/test_x.py" in body


def test_an_honest_agent_is_reported_as_such(client, a_task, admin):
    tid, rid = a_task
    add_steps(admin, rid, reported=["api/analytics/services/analytics_engine.py"], derived=["api/analytics/services/analytics_engine.py"],
              divergence={"touched_but_unclaimed": [], "claimed_but_untouched": []})
    assert "matches git exactly" in client.get(f"/tasks/{tid}").text


def test_verification_checks_are_shown_with_exit_and_duration(client, a_task, admin):
    tid, rid = a_task
    add_steps(admin, rid, reported=[], derived=["api/analytics/services/analytics_engine.py"],
              divergence={"touched_but_unclaimed": ["api/analytics/services/analytics_engine.py"],
                          "claimed_but_untouched": []})
    body = client.get(f"/tasks/{tid}").text
    assert "pytest -q" in body and "12ms" in body


def test_a_missing_branch_says_so_rather_than_showing_nothing(client, a_task, admin):
    """repo_root is pointed at /nonexistent by the fixture."""
    tid, rid = a_task
    add_steps(admin, rid, reported=[], derived=["api/analytics/services/analytics_engine.py"], divergence={})
    assert "no git repository" in client.get(f"/tasks/{tid}").text


def test_an_unknown_task_is_404(client):
    assert client.get("/tasks/9999").status_code == 404


# ---- page 2 --------------------------------------------------------------

def test_detectors_renders_health_from_the_registry(client):
    body = client.get("/detectors").text
    assert "fleet_heartbeat" in body
    assert "cadence" in body


def test_the_false_positive_rate_always_shows_its_denominator(client, admin):
    """`2 of 3` refuses the decision that `67%` invites."""
    slot = sp.slot_ends(admin, sp.RECONCILIATION, count=1)[0]
    ids = sp.arrange_observations(admin, sp.RECONCILIATION, slot, count=3)
    for oid, verdict in zip(ids, ("FALSE_POSITIVE", "FALSE_POSITIVE", "VALID")):
        sp.record_verdict(admin, oid, verdict)
    body = client.get("/detectors").text
    assert "2 of 3" in body
    # The page's own explanation contains the characters "67%", so assert on the
    # rendered form -- the template emits a percentage as "(67%)" or not at all.
    assert "(67%)" not in body, "a percentage rendered on three data points"


def test_untriaged_is_prominent_when_it_is_not_zero(client, admin):
    slot = sp.slot_ends(admin, sp.RECONCILIATION, count=1)[0]
    sp.arrange_observations(admin, sp.RECONCILIATION, slot, count=2)
    body = client.get("/detectors").text
    assert "no effective verdict" in body
    assert "2" in body


def test_the_coverage_table_explains_why_something_is_not_queued(client, admin):
    """"Why is this not in my queue" must be answerable on the page."""
    slots = sp.slot_ends(admin, sp.RECONCILIATION, count=3)
    first = sp.arrange_observations(admin, sp.RECONCILIATION, slots[0],
                                    count=1, magnitude=500)[0]
    sp.record_verdict(admin, first, "VALID")
    for slot in slots[1:]:
        sp.arrange_observations(admin, sp.RECONCILIATION, slot, count=1,
                                magnitude=500)
    body = client.get("/detectors").text
    assert "one judgement, restated" in body
    assert "covered by the judgement of" in body or "restates the judgement of" in body


def test_untriaged_zero_is_stated_positively(client):
    """Zero is the answer this page most wants to give, so it says it."""
    assert "nothing awaiting a verdict" in client.get("/detectors").text


# ---- page 3 --------------------------------------------------------------

def test_proposals_states_that_empty_cycles_cannot_be_shown(client):
    """The spec asks for cycles that produced nothing. They are not recorded,
    and the page has to say so rather than render an empty table that reads
    as 'nothing happened'."""
    body = client.get("/proposals").text
    assert "not shown, because they are not recorded" in body
    assert "journalctl" in body


def test_proposals_renders_a_proposal_with_its_evidence(client, admin):
    """proposal_evidence is immutable by trigger, so the row the helper writes
    is the row the page must render."""
    sp.insert_proposal(admin, title="A finding", body="the body")
    body = client.get("/proposals").text
    assert "A finding" in body
    assert "open_issues" in body          # the adapter's query key
    assert "the body" in body


# ---- one row per task, not one per run -----------------------------------

def _task_with_runs(console, admin, runner, n_runs: int) -> int:
    """A task carried to READY_FOR_REVIEW after n_runs attempts."""
    tid = console.execute(
        "INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,"
        " max_cost_gbp, max_attempts) VALUES ('many runs','# s',%s,'main',%s,9.00,%s)"
        " RETURNING id", (REPO, json.dumps(contract()), n_runs)).fetchone()["id"]
    console.commit()
    for i in range(n_runs):
        runner.execute("SELECT claim_task(NULL)")
        runner.commit()
        rid = admin.execute(
            "INSERT INTO runs (task_id, work_type, contract_version,"
            " spend_limit_gbp, committed_gbp, status)"
            " VALUES (%s,'dd_feature',1,9.00,%s,'ACTIVE') RETURNING id",
            (tid, 1 + i)).fetchone()["id"]
        if i < n_runs - 1:
            admin.execute("UPDATE runs SET status='FAILED', completed_at=now()"
                          " WHERE id=%s", (rid,))
            runner.execute("UPDATE tasks SET status='QUEUED', claimed_at=NULL"
                           " WHERE id=%s", (tid,))
            runner.commit()
    runner.execute(
        "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name='fleet/task-x',"
        " completed_at=now() WHERE id=%s", (tid,))
    runner.commit()
    return tid


def test_a_task_with_several_runs_is_one_row(dsns, console, admin, runner):
    """Joining runs without aggregating rendered task 5 four times while the
    tab counts, which come from `tasks` alone, said two."""
    from console import queries
    tid = _task_with_runs(console, admin, runner, 4)
    rows = [r for r in queries.task_list(None) if r["id"] == tid]
    assert len(rows) == 1
    assert rows[0]["runs_total"] == 4


def test_the_row_count_and_the_tab_counts_agree(dsns, console, admin, runner):
    """The invariant that was broken: the list said nine, the tabs said six."""
    from console import queries
    _task_with_runs(console, admin, runner, 3)
    _task_with_runs(console, admin, runner, 1)
    assert len(queries.task_list(None)) == sum(queries.status_counts().values())


def test_the_row_shows_the_latest_run_not_an_arbitrary_one(dsns, console, admin,
                                                           runner):
    from console import queries
    tid = _task_with_runs(console, admin, runner, 3)
    row = [r for r in queries.task_list(None) if r["id"] == tid][0]
    latest = admin.execute("SELECT max(id) AS m FROM runs WHERE task_id=%s",
                           (tid,)).fetchone()["m"]
    assert row["run_id"] == latest


def test_the_detail_page_shows_the_latest_run(dsns, console, admin, runner):
    """The worse half of the same bug: task 5 showed the cost and steps of its
    first, killed run beside the branch its fourth run produced."""
    from console import queries
    tid = _task_with_runs(console, admin, runner, 4)
    latest = admin.execute("SELECT max(id) AS m FROM runs WHERE task_id=%s",
                           (tid,)).fetchone()["m"]
    assert queries.task_detail(tid)["run_id"] == latest


def test_the_page_reports_what_every_run_cost(dsns, console, admin, runner):
    """The last run's cost is not the task's cost. Four attempts at £1..£4 cost
    £10, and showing £4 would understate it by most of what it spent."""
    from console import queries
    tid = _task_with_runs(console, admin, runner, 4)
    d = queries.task_detail(tid)
    assert float(d["committed_gbp"]) == 4.0
    assert float(d["spent_all_runs"]) == 10.0
    assert len(queries.task_runs(tid)) == 4


def test_a_task_with_no_run_still_appears(dsns, console):
    from console import queries
    console.execute(
        "INSERT INTO tasks (title, spec_md, repo, acceptance_contract, max_cost_gbp)"
        " VALUES ('never claimed','# s',%s,%s,1.00)", (REPO, json.dumps(contract())))
    console.commit()
    rows = [r for r in queries.task_list(None) if r["title"] == "never claimed"]
    assert len(rows) == 1
    assert rows[0]["run_id"] is None and rows[0]["runs_total"] == 0


def test_the_list_renders_one_row_per_task(client, console, admin, runner):
    tid = _task_with_runs(console, admin, runner, 3)
    body = client.get("/tasks?status=all").text
    assert body.count(f'href="/tasks/{tid}"') == 2, "one link per cell, one row"
    assert "over 3 runs" in body


# ---------------------------------------------------------------------------
# The refusal, shown BEFORE the button rather than after it.
#
# Task 26 was accepted five times against a checkout on another branch. The
# merge refused correctly each time and the reason reached one browser tab and
# nowhere else. `preflight` reads git and writes nothing, so the page can ask
# it on the GET and turn a refusal from a result into a precondition.
# ---------------------------------------------------------------------------

class TestTheRefusalIsShownBeforeTheButton:

    def test_a_ready_task_whose_merge_would_refuse_says_so(self, client, a_task):
        """The client fixture points repo_root at /nonexistent, so preflight
        refuses -- which is the condition under test, not a workaround."""
        task_id, _run = a_task
        body = client.get(f"/tasks/{task_id}").text
        assert "Accepting will refuse" in body

    def test_the_page_still_renders_when_preflight_cannot_run(
            self, client, a_task, monkeypatch):
        """A page that 500s because a git read failed is worse than one that
        says it could not look. It must never silently omit the blocker."""
        from console import app as app_module

        def boom(*a, **k):
            raise OSError("git is not on the path")
        task_id, _run = a_task
        monkeypatch.setattr(app_module.merge, "preflight", boom)
        r = client.get(f"/tasks/{task_id}")
        assert r.status_code == 200
        assert "could not be" in r.text and "git is not on the path" in r.text

    def test_a_task_that_is_not_ready_has_no_blocker(self, client, console,
                                                     a_task):
        task_id, _run = a_task
        console.execute("UPDATE tasks SET status='MERGED' WHERE id=%s", (task_id,))
        console.commit()
        assert "Accepting will refuse" not in client.get(f"/tasks/{task_id}").text
