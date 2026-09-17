"""049: the ceiling is a rate against a window that resets, not a stock.

The money ceiling 014 built measured an account nobody holds -- the balance
auto-reloads, nothing is billed, and the period was a month against a limit
that resets on Sunday. These are the properties of what replaced it.
"""
from __future__ import annotations

import json

import psycopg
import pytest

# The contract and floor the suite already agrees on: an empty contract is
# refused by enforce_contract_floor(), and this file is not about that.
from tests.test_runner_cycle import contract


def _target(admin, tokens: int) -> None:
    """Make `tokens` the target in effect, after the suite's own seed."""
    admin.execute(
        "INSERT INTO model_window_target (output_tokens_per_week, set_by,"
        " effective_from, rationale) VALUES (%s, 'test', now(), 'test')",
        (tokens,))


def _queue(admin, *, ceiling: int, status: str = "QUEUED") -> int:
    row = admin.execute(
        "INSERT INTO tasks (title, spec_md, repo, base_branch,"
        " acceptance_contract, max_cost_gbp, max_attempts, status,"
        " max_output_tokens)"
        " VALUES ('t', '# t', 'deadly-digital-platform', 'main', %s::jsonb,"
        " 3.00, 1, %s, %s) RETURNING id",
        (json.dumps(contract()), status, ceiling)).fetchone()
    return row["id"]


def _claim(conn, task_id: int) -> None:
    conn.execute("UPDATE tasks SET status='RUNNING', claimed_at=now(),"
                 " attempts = attempts + 1 WHERE id=%s", (task_id,))


def test_the_window_starts_on_sunday_not_monday(dsns, admin):
    """date_trunc('week') is ISO and starts Monday. The plan resets Sunday,
    and a ceiling measuring a different seven days is wrong twice a week."""
    dow = admin.execute(
        "SELECT extract(dow from fleet_window_start()) AS d").fetchone()["d"]
    assert int(dow) == 0, "window does not start on a Sunday"


def test_a_claim_that_fits_is_admitted(dsns, admin):
    _target(admin, 1_000_000)
    tid = _queue(admin, ceiling=50_000)
    _claim(admin, tid)
    assert admin.execute("SELECT status FROM tasks WHERE id=%s",
                         (tid,)).fetchone()["status"] == "RUNNING"


def test_a_claim_that_would_cross_the_window_is_refused(dsns, admin):
    _target(admin, 40_000)
    tid = _queue(admin, ceiling=50_000)
    with pytest.raises(psycopg.errors.RaiseException) as raised:
        _claim(admin, tid)
    msg = str(raised.value)
    assert "usage window" in msg, msg
    assert "Sunday" in msg, "the hint must say when it resets"


def test_work_already_running_is_counted_at_its_ceiling(dsns, admin):
    """014's argument, with the currency changed: a RUNNING task has written
    no model_call yet, so a window checked against settled output alone would
    admit another one on top of it."""
    _target(admin, 100_000)
    running = _queue(admin, ceiling=60_000, status="QUEUED")
    _claim(admin, running)

    second = _queue(admin, ceiling=60_000)
    with pytest.raises(psycopg.errors.RaiseException) as raised:
        _claim(admin, second)
    assert "in flight" in str(raised.value)


def test_a_backlog_larger_than_the_window_still_admits_the_first_task(
        dsns, admin):
    """THE BUG THIS TEST EXISTS FOR. Counting QUEUED work at the gate -- which
    is right for the POSITION readout -- would make `remaining` negative and
    refuse every claim, so a queue of ten against room for five would run
    none instead of five. Queued work consumes nothing until it is claimed."""
    _target(admin, 100_000)
    # Three at 40k is 120k of backlog against a 100k window -- overdrawn on
    # the readout. 013 caps the queue at 8, so the point is made with three.
    first = _queue(admin, ceiling=40_000)
    _queue(admin, ceiling=40_000)
    _queue(admin, ceiling=40_000)

    over = admin.execute(
        "SELECT remaining_tokens FROM fleet_window_position()"
    ).fetchone()["remaining_tokens"]
    assert over < 0, "the readout should show the backlog overdrawing"

    _claim(admin, first)          # must not raise
    assert admin.execute("SELECT status FROM tasks WHERE id=%s",
                         (first,)).fetchone()["status"] == "RUNNING"


def test_the_position_does_count_the_backlog(dsns, admin):
    """The readout and the gate ask different questions on purpose: a reader
    who cannot see the backlog is blind in the window that matters."""
    _target(admin, 100_000)
    before = admin.execute(
        "SELECT committed_tokens FROM fleet_window_position()"
    ).fetchone()["committed_tokens"]
    _queue(admin, ceiling=40_000)
    after = admin.execute(
        "SELECT committed_tokens FROM fleet_window_position()"
    ).fetchone()["committed_tokens"]
    assert after - before == 40_000


def test_no_target_refuses_rather_than_assumes(dsns, admin):
    """014's rule, and its reason: a ceiling that cannot read its limit
    refuses, because nobody is reading at 03:00."""
    admin.execute("DELETE FROM model_window_target")
    tid = _queue(admin, ceiling=1_000)
    with pytest.raises(psycopg.errors.RaiseException) as raised:
        _claim(admin, tid)
    assert "unknown" in str(raised.value)
    assert "no output-token target" in str(raised.value)


def test_an_uncomputed_position_carries_no_numbers(dsns, admin):
    """A caller one coalesce() away from turning 'I do not know' into 'plenty'
    is the failure 014 names, and the reason remaining is NULL not zero."""
    admin.execute("DELETE FROM model_window_target")
    row = admin.execute(
        "SELECT status, target_tokens, remaining_tokens, uncomputed_reason"
        "  FROM fleet_window_position()").fetchone()
    assert row["status"] == "UNCOMPUTED"
    assert row["target_tokens"] is None
    assert row["remaining_tokens"] is None
    assert row["uncomputed_reason"]


def test_only_the_claim_edge_is_gated(dsns, admin):
    """The gate is the QUEUED -> RUNNING edge and nothing else.

    A RUNNING task being requeued -- which is what the could-not-run path
    does -- must not be re-checked against a window that filled while it ran,
    or a refusal would strand it in RUNNING forever.
    """
    _target(admin, 100_000)
    tid = _queue(admin, ceiling=50_000)
    _claim(admin, tid)

    _target(admin, 1)             # window now far too small

    # RUNNING -> RUNNING: not the claim edge.
    admin.execute("UPDATE tasks SET claimed_at=now() WHERE id=%s", (tid,))
    # RUNNING -> QUEUED: the requeue the could-not-run path performs.
    admin.execute("UPDATE tasks SET status='QUEUED', claimed_at=NULL,"
                  " attempts=GREATEST(attempts-1,0) WHERE id=%s", (tid,))

    assert admin.execute("SELECT status FROM tasks WHERE id=%s",
                         (tid,)).fetchone()["status"] == "QUEUED"

    # And the next claim IS gated again, now that the window is tiny.
    with pytest.raises(psycopg.errors.RaiseException):
        _claim(admin, tid)


def test_the_target_needs_an_author_and_a_reason(dsns, admin):
    """Provenance for a decision, not for a reading: 014 carried source and
    read_at because the pool was looked up. This is chosen."""
    for bad in ("set_by", "rationale"):
        cols = {"output_tokens_per_week": 1000, "set_by": "x",
                "rationale": "y", "effective_from": "now()"}
        cols[bad] = "  "
        with pytest.raises(psycopg.errors.CheckViolation):
            admin.execute(
                "INSERT INTO model_window_target (output_tokens_per_week,"
                " set_by, effective_from, rationale)"
                " VALUES (%(output_tokens_per_week)s, %(set_by)s, now(),"
                " %(rationale)s)", cols)
        admin.execute("ROLLBACK")
