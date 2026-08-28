"""An ERRORed window is retried until max_attempts, then abandoned.

Before this, base.execute() treated any non-RUNNING status as a finished
window. reclaim_stale_detector_run() only ever reclaims RUNNING rows, so an
ERROR run was never handed back: attempt_count stayed at 1 for ever,
DETECTOR_WINDOW_ABANDONED could not fire, and max_attempts was configuration
that did nothing. One transient failure cost that window permanently, and
coverage_horizon_valid() -- which counts only OK and PARTIAL runs -- then
refused to clear issues across the hole.
"""
from __future__ import annotations

from contextlib import contextmanager

from detectors import base, sqlfile
from detectors.heartbeat import HeartbeatDetector
from support import (heartbeat_slots, observations, run_reconciliation,
                     run_row, settled_slots)

DETECTOR = "dd_analytics_reconciliation"
MAX_ATTEMPTS = 3          # detector_registry, asserted below rather than assumed


@contextmanager
def enumeration_broken(monkeypatch):
    """Break tenant enumeration: the failure that closes a run ERROR."""
    real = sqlfile.load
    monkeypatch.setattr(sqlfile, "load", lambda key, version=1: (
        sqlfile.Query(key, version, "SELECT * FROM no_such_table")
        if key == "tenants_active" else real(key, version)))
    try:
        yield
    finally:
        monkeypatch.setattr(sqlfile, "load", real)


@contextmanager
def only_readable_tenants(monkeypatch):
    """Enumerate just the two tenants whose analytics schema is readable.

    The fixture also carries a tenant with no analytics schema and one whose
    schema denies SELECT, and both correctly close a healthy run PARTIAL.
    These tests are about the retry transition, so the noise is narrowed away
    and a clean attempt closes genuinely OK.
    """
    real = sqlfile.load
    monkeypatch.setattr(sqlfile, "load", lambda key, version=1: (
        sqlfile.Query(key, version,
                      "SELECT id AS tenant_id FROM public.tenants "
                      "WHERE is_active AND id IN (1, 2) ORDER BY id")
        if key == "tenants_active" else real(key, version)))
    try:
        yield
    finally:
        monkeypatch.setattr(sqlfile, "load", real)


def test_registry_still_says_three_attempts(fleet):
    """The threshold is data. If it moves, the tests below must move with it."""
    row = fleet.execute(
        "SELECT max_attempts FROM detector_registry WHERE detector_key = %s",
        (DETECTOR,)).fetchone()
    assert row["max_attempts"] == MAX_ATTEMPTS


def test_errored_window_is_retried_and_can_reach_ok(fleet, dsns, monkeypatch):
    slot = settled_slots(fleet, 1)[0]
    with enumeration_broken(monkeypatch):
        first = run_reconciliation(fleet, dsns["dd"], slot_end=slot)
    assert first.status == base.STATUS_ERROR
    assert run_row(fleet, first.run_id)["attempt_count"] == 1

    with only_readable_tenants(monkeypatch):
        second = run_reconciliation(fleet, dsns["dd"], slot_end=slot)

    assert second.run_id == first.run_id, "the same logical window, retried in place"
    assert second.status == base.STATUS_OK
    row = run_row(fleet, second.run_id)
    assert row["attempt_count"] == 2
    assert row["status"] == "OK"
    assert row["error"] is None, "the retry clears the previous attempt's error"
    assert row["completed_at"] is not None
    assert row["subjects_evaluated"] is not None


def test_errored_window_at_max_attempts_is_not_retried(fleet, dsns, admin,
                                                       monkeypatch):
    slot = settled_slots(fleet, 1)[0]
    with enumeration_broken(monkeypatch):
        first = run_reconciliation(fleet, dsns["dd"], slot_end=slot)
    assert first.status == base.STATUS_ERROR
    admin.execute("UPDATE detector_runs SET attempt_count = %s WHERE id = %s",
                  (MAX_ATTEMPTS, first.run_id))

    again = run_reconciliation(fleet, dsns["dd"], slot_end=slot)

    assert again.status == "SKIPPED"
    assert again.skipped_reason == "abandoned"
    row = run_row(fleet, first.run_id)
    assert row["status"] == "ERROR", "spent windows stay ERROR, they do not clear"
    assert row["attempt_count"] == MAX_ATTEMPTS, "the limit is a limit"


def test_attempts_are_exhausted_then_the_heartbeat_raises_window_abandoned(
        fleet, dsns, monkeypatch):
    """End to end, without forging attempt_count: three real failures."""
    slot = settled_slots(fleet, 1)[0]
    with enumeration_broken(monkeypatch):
        attempts = [run_reconciliation(fleet, dsns["dd"], slot_end=slot)
                    for _ in range(MAX_ATTEMPTS)]
        spent = run_reconciliation(fleet, dsns["dd"], slot_end=slot)

    assert [r.status for r in attempts] == [base.STATUS_ERROR] * MAX_ATTEMPTS
    assert len({r.run_id for r in attempts}) == 1, "one window, three attempts"
    assert spent.skipped_reason == "abandoned"
    row = run_row(fleet, attempts[0].run_id)
    assert row["attempt_count"] == MAX_ATTEMPTS
    assert row["status"] == "ERROR"

    hb = base.execute(HeartbeatDetector(deadman_url=None), fleet,
                      slot_end=heartbeat_slots(fleet, 1)[0])

    fired = observations(fleet, hb.run_id, "DETECTOR_WINDOW_ABANDONED")
    assert len(fired) == 1, "unreachable before the retry path existed"
    assert fired[0]["subject_id"] == DETECTOR
    assert fired[0]["subject_type"] == "detector"
    assert fired[0]["evidence_sample"]["attempts"] == MAX_ATTEMPTS


def test_a_retried_window_that_succeeds_creates_no_duplicate_observations(
        fleet, dsns, admin, monkeypatch):
    slot = settled_slots(fleet, 1)[0]
    with only_readable_tenants(monkeypatch):
        first = run_reconciliation(fleet, dsns["dd"], slot_end=slot)
    assert first.status == base.STATUS_OK
    before = observations(fleet, first.run_id)
    assert before, "the fixture gap must produce something that could duplicate"

    # An attempt that persisted its observations and then failed before
    # closing cleanly. Only a superuser can forge that history.
    admin.execute(
        "UPDATE detector_runs SET status = 'ERROR', attempt_count = 1, "
        "completed_at = now(), error = 'forced' WHERE id = %s", (first.run_id,))

    with only_readable_tenants(monkeypatch):
        retried = run_reconciliation(fleet, dsns["dd"], slot_end=slot)

    assert retried.run_id == first.run_id
    assert retried.status == base.STATUS_OK
    after = observations(fleet, retried.run_id)
    assert [o["id"] for o in after] == [o["id"] for o in before], \
        "the retry re-emits nothing; the unique index holds"
    row = run_row(fleet, retried.run_id)
    assert row["attempt_count"] == 2
    assert row["observations_created"] == len(before), \
        "recomputed from the persisted rows, not from an in-process counter"
    occurrences = [r["occurrence_count"] for r in fleet.execute(
        "SELECT occurrence_count FROM issues").fetchall()]
    assert occurrences and set(occurrences) == {1}, \
        "a skipped observation insert must not still count an occurrence"
