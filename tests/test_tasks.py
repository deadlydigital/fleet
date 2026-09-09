"""Track 3 schema behaviour.

Every test drives the database through the identity that would do the thing
in production. The runner connection is not a member of fleet_console, and
that is the property most of this file is about: a process that produces a
branch must not be able to record that the branch was good.
"""
from __future__ import annotations

import json

import psycopg
import pytest

REPO = "deadly-digital-platform"

from tests.support import PLATFORM_FLOOR

FLOOR = PLATFORM_FLOOR

def contract(**over) -> str:
    c = {
        "work_type": "dd_feature",
        "repo": REPO,
        "base_branch": "main",
        "writable_paths": ["platform/app/**", "docs/**"],
        "protected_paths": list(FLOOR),
        "verification": ["pytest api/tests/"],
        "max_diff_lines": 800,
        "max_cost_gbp": 3.00,
    }
    c.update(over)
    return json.dumps(c)


def add_task(console, **over) -> int:
    fields = {
        "queue": "default",
        "title": "a task",
        "spec_md": "# do the thing",
        "repo": REPO,
        "base_branch": "main",
        "acceptance_contract": contract(),
        "max_cost_gbp": "3.00",
    }
    fields.update(over)
    cols = ", ".join(fields)
    marks = ", ".join(f"%({k})s" for k in fields)
    row = console.execute(
        f"INSERT INTO tasks ({cols}) VALUES ({marks}) RETURNING id", fields
    ).fetchone()
    console.commit()
    return row["id"]


# ---- the floor ------------------------------------------------------------

def test_contract_omitting_the_test_suite_is_refused(console):
    """The rule that cost several rounds to arrive at, as a write-time check."""
    without_tests = [g for g in FLOOR if g != "api/tests/**"]
    with pytest.raises(psycopg.errors.RaiseException, match="does not protect"):
        add_task(console, acceptance_contract=contract(protected_paths=without_tests))


def test_contract_omitting_migrations_is_refused(console):
    without_migrations = [g for g in FLOOR if g != "api/alembic/**"]
    with pytest.raises(psycopg.errors.RaiseException, match="api/alembic"):
        add_task(console,
                 acceptance_contract=contract(protected_paths=without_migrations))


def test_writable_path_that_swallows_a_protected_one_is_refused(console):
    """'api/**' writable and 'api/tests/**' protected is a contract that
    contradicts itself, and the runner would have to pick a winner."""
    with pytest.raises(psycopg.errors.RaiseException, match="self-contradictory"):
        add_task(console, acceptance_contract=contract(writable_paths=["api/**"]))


def test_a_conforming_contract_is_accepted(console):
    assert add_task(console) > 0


def test_contract_without_verification_is_refused(console):
    with pytest.raises(psycopg.errors.CheckViolation):
        add_task(console, acceptance_contract=contract(verification=[]))


# ---- authority ------------------------------------------------------------

def test_runner_cannot_write_the_queue(runner):
    """The queue is written by a person. No self-generated tasks in V1."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        runner.execute(
            "INSERT INTO tasks (title, spec_md, repo, acceptance_contract,"
            " max_cost_gbp) VALUES ('x','y',%s,%s,1.0)", (REPO, contract()))


def test_runner_claims_and_starts(console, runner):
    tid = add_task(console)
    got = runner.execute("SELECT claim_task(NULL) AS id").fetchone()["id"]
    runner.commit()
    assert got == tid
    row = runner.execute(
        "SELECT status, attempts, claimed_at FROM tasks WHERE id=%s", (tid,)
    ).fetchone()
    assert row["status"] == "RUNNING"
    assert row["attempts"] == 1
    assert row["claimed_at"] is not None


def test_claim_is_by_priority_then_id(console, runner):
    add_task(console, title="low", priority=200)
    urgent = add_task(console, title="high", priority=10)
    got = runner.execute("SELECT claim_task(NULL) AS id").fetchone()["id"]
    runner.commit()
    assert got == urgent


def test_two_runners_never_take_the_same_task(console, dsns):
    """SKIP LOCKED, as scheduled_checks does it."""
    add_task(console)
    a = psycopg.connect(dsns["runner"])
    b = psycopg.connect(dsns["runner"])
    try:
        first = a.execute("SELECT claim_task(NULL)").fetchone()[0]
        second = b.execute("SELECT claim_task(NULL)").fetchone()[0]
        assert first is not None
        assert second is None
    finally:
        a.close()
        b.close()


def test_runner_cannot_merge_its_own_branch(console, runner):
    """The one this whole track is built around."""
    tid = add_task(console)
    runner.execute("SELECT claim_task(NULL)")
    runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s,'dd_feature',1,1.00)", (tid,))
    runner.execute(
        "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name='fleet/task-1',"
        " completed_at=now() WHERE id=%s", (tid,))
    runner.commit()

    with pytest.raises(psycopg.errors.RaiseException, match="requires fleet_console"):
        runner.execute("UPDATE tasks SET status='MERGED' WHERE id=%s", (tid,))


def test_console_may_merge(console, runner):
    tid = add_task(console)
    runner.execute("SELECT claim_task(NULL)")
    runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s,'dd_feature',1,1.00)", (tid,))
    runner.execute(
        "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name='b' WHERE id=%s",
        (tid,))
    runner.commit()
    console.execute("UPDATE tasks SET status='MERGED' WHERE id=%s", (tid,))
    console.commit()
    assert console.execute(
        "SELECT status FROM tasks WHERE id=%s", (tid,)
    ).fetchone()["status"] == "MERGED"


def test_illegal_transition_is_refused(console, runner):
    tid = add_task(console)
    with pytest.raises(psycopg.errors.RaiseException, match="may not move"):
        console.execute("UPDATE tasks SET status='MERGED' WHERE id=%s", (tid,))


def test_ready_for_review_requires_a_branch(console, runner):
    """The status column's one chance to lie, closed."""
    tid = add_task(console)
    runner.execute("SELECT claim_task(NULL)")
    runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s,'dd_feature',1,1.00)", (tid,))
    with pytest.raises(psycopg.errors.RaiseException, match="without a branch"):
        runner.execute(
            "UPDATE tasks SET status='READY_FOR_REVIEW' WHERE id=%s", (tid,))


def test_ready_for_review_requires_a_run(console, runner):
    tid = add_task(console)
    runner.execute("SELECT claim_task(NULL)")
    with pytest.raises(psycopg.errors.RaiseException, match="without a run"):
        runner.execute(
            "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name='b'"
            " WHERE id=%s", (tid,))


# ---- the boundary cannot move while work is inside it ---------------------

def test_contract_is_frozen_once_running(console, runner):
    tid = add_task(console)
    runner.execute("SELECT claim_task(NULL)")
    runner.commit()
    wide = contract(writable_paths=["platform/app/**", "docs/**", "scripts/**"])
    with pytest.raises(psycopg.errors.RaiseException, match="frozen"):
        console.execute(
            "UPDATE tasks SET acceptance_contract=%s WHERE id=%s", (wide, tid))


def test_contract_may_be_corrected_while_queued(console):
    tid = add_task(console)
    console.execute(
        "UPDATE tasks SET acceptance_contract=%s WHERE id=%s",
        (contract(writable_paths=["platform/app/**"]), tid))
    console.commit()


def test_spec_is_append_only(console):
    tid = add_task(console)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        console.execute("UPDATE tasks SET spec_md='shorter' WHERE id=%s", (tid,))


def test_repo_and_base_branch_cannot_change(console):
    tid = add_task(console)
    with pytest.raises(psycopg.errors.RaiseException, match="may not change repo"):
        console.execute("UPDATE tasks SET base_branch='master' WHERE id=%s", (tid,))


# ---- budget and the wall clock --------------------------------------------

def test_a_run_cannot_outspend_its_task(console, runner):
    tid = add_task(console, max_cost_gbp="1.00")
    runner.execute("SELECT claim_task(NULL)")
    with pytest.raises(psycopg.errors.RaiseException, match="exceeds task"):
        runner.execute(
            "INSERT INTO runs (task_id, work_type, contract_version,"
            " spend_limit_gbp) VALUES (%s,'dd_feature',1,50.00)", (tid,))


def test_timeout_has_a_ceiling(console):
    with pytest.raises(psycopg.errors.CheckViolation):
        add_task(console, timeout_seconds=99999)


def test_timeout_cannot_be_zero(console):
    with pytest.raises(psycopg.errors.CheckViolation):
        add_task(console, timeout_seconds=0)


# ---- runs keep one origin -------------------------------------------------

def test_a_run_cannot_name_both_an_issue_and_a_task(console, admin):
    tid = add_task(console)
    iid = admin.execute(
        "INSERT INTO issues (fingerprint, product, issue_type, subject_type,"
        " subject_id, detector_key, first_seen, last_seen, severity)"
        " VALUES ('f','dd','t','tenant','1','fleet_heartbeat',now(),now(),'LOW')"
        " RETURNING id").fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute(
            "INSERT INTO runs (issue_id, task_id, work_type, contract_version,"
            " spend_limit_gbp) VALUES (%s,%s,'dd_feature',1,1.00)",
            (iid, tid))


def test_a_run_must_name_one_origin(admin):
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute(
            "INSERT INTO runs (work_type, contract_version, spend_limit_gbp)"
            " VALUES ('dd_feature',1,1.00)")


def test_one_active_run_per_task(console, runner):
    tid = add_task(console)
    runner.execute("SELECT claim_task(NULL)")
    runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s,'dd_feature',1,1.00)", (tid,))
    runner.commit()
    with pytest.raises(psycopg.errors.UniqueViolation):
        runner.execute(
            "INSERT INTO runs (task_id, work_type, contract_version,"
            " spend_limit_gbp) VALUES (%s,'dd_feature',1,1.00)", (tid,))


# ---- the agent does not certify itself ------------------------------------

def test_agent_cannot_write_a_verification_step(console, runner, agent_conn):
    """001's step_authority, still doing its job for track 3's runs."""
    tid = add_task(console)
    runner.execute("SELECT claim_task(NULL)")
    rid = runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s,'dd_feature',1,1.00) RETURNING id", (tid,)).fetchone()["id"]
    runner.commit()
    with pytest.raises(psycopg.errors.RaiseException, match="may not write step_type"):
        agent_conn.execute(
            "INSERT INTO run_steps (run_id, sequence, step_type, actor)"
            " VALUES (%s,1,'VERIFICATION_RUN','agent')", (rid,))


def test_verification_pass_needs_runner_derived_provenance(console, runner,
                                                           agent_conn,
                                                           verifier_conn):
    """A PASS without a derived boundary and full diff provenance is refused
    by 001's acceptance boundary. This is what stops the runner taking the
    agent's word for what it changed."""
    tid = add_task(console)
    runner.execute("SELECT claim_task(NULL)")
    rid = runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s,'dd_feature',1,1.00) RETURNING id", (tid,)).fetchone()["id"]
    runner.commit()
    agent_conn.execute(
        "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
        " VALUES (%s,1,'PATCH_PROPOSED','agent','{\"patch_commit_sha\":\"abc\"}')",
        (rid,))
    agent_conn.commit()
    with pytest.raises(psycopg.errors.RaiseException, match="boundary_clean"):
        verifier_conn.execute(
            "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
            " VALUES (%s,2,'VERIFICATION_RUN','verifier',"
            " '{\"result\":\"PASS\"}')", (rid,))


# ---- rework ---------------------------------------------------------------

def test_rework_appends_and_requeues(console, runner):
    tid = add_task(console)
    runner.execute("SELECT claim_task(NULL)")
    runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s,'dd_feature',1,1.00)", (tid,))
    runner.execute(
        "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name='b' WHERE id=%s",
        (tid,))
    runner.commit()

    console.execute("SELECT rework_task(%s, %s)",
                    (tid, "wrong table; use analytics_N not public"))
    console.commit()
    row = console.execute(
        "SELECT status, spec_md, branch_name FROM tasks WHERE id=%s", (tid,)
    ).fetchone()
    assert row["status"] == "QUEUED"
    assert row["branch_name"] is None
    assert "# do the thing" in row["spec_md"]
    assert "analytics_N" in row["spec_md"]


def test_rework_requires_a_note(console, runner):
    tid = add_task(console)
    runner.execute("SELECT claim_task(NULL)")
    runner.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp)"
        " VALUES (%s,'dd_feature',1,1.00)", (tid,))
    runner.execute(
        "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name='b' WHERE id=%s",
        (tid,))
    runner.commit()
    with pytest.raises(psycopg.errors.RaiseException, match="requires a note"):
        console.execute("SELECT rework_task(%s, %s)", (tid, "   "))
