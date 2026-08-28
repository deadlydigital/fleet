"""fleet_heartbeat: the detector that watches the detectors."""
from __future__ import annotations

from datetime import timedelta

import pytest

from detectors import base
from detectors.emit import fingerprint
from detectors.heartbeat import HeartbeatDetector
from support import heartbeat_slots, observations, run_row, settled_slots

HEARTBEAT = "fleet_heartbeat"
TARGET = "dd_analytics_reconciliation"
PRODUCT = "deadly_digital"


def fp(subject_id: str, observation_type: str) -> str:
    return fingerprint(HEARTBEAT, 1, PRODUCT, "detector", subject_id, observation_type)


def run_heartbeat(fleet, slot_end=None, deadman_url=None):
    return base.execute(HeartbeatDetector(deadman_url=deadman_url), fleet,
                        slot_end=slot_end)


def close_run(admin, run_id, status, completed_ago, subjects=("tenant:1",),
              attempt_count=1):
    """Arrange a finished run. Only a superuser may forge history like this."""
    admin.execute(
        """UPDATE detector_runs
              SET status = %(s)s, completed_at = now() - %(ago)s::interval,
                  subjects_evaluated = %(subj)s, attempt_count = %(att)s,
                  observations_created = 0, duration_ms = 1
            WHERE id = %(id)s""",
        {"s": status, "ago": completed_ago, "subj": list(subjects),
         "att": attempt_count, "id": run_id})


def open_target_run(fleet, slot_end):
    return fleet.execute(
        "SELECT open_scheduled_run(%s, 1, %s, %s) AS id",
        (TARGET, PRODUCT, slot_end)).fetchone()["id"]


def test_run_missing_fires_after_cadence_plus_grace_and_not_before(fleet, admin):
    """cadence 1h + grace 5m = 65 minutes of allowance, from the registry."""
    slots = settled_slots(fleet, 2)
    hb_slots = heartbeat_slots(fleet, 2)

    run_id = open_target_run(fleet, slots[0])
    close_run(admin, run_id, "OK", "60 minutes")      # inside the allowance

    early = run_heartbeat(fleet, slot_end=hb_slots[1])
    assert early.status == base.STATUS_OK
    assert observations(fleet, early.run_id, "DETECTOR_RUN_MISSING") == [], \
        "65 minutes of allowance means 60 minutes is not yet missing"

    close_run(admin, run_id, "OK", "70 minutes")      # past the allowance

    late = run_heartbeat(fleet, slot_end=hb_slots[0])
    fired = observations(fleet, late.run_id, "DETECTOR_RUN_MISSING")
    assert len(fired) == 1
    row = fired[0]
    assert row["subject_type"] == "detector"
    assert row["subject_id"] == TARGET
    assert row["fingerprint"] == fp(TARGET, "DETECTOR_RUN_MISSING")
    assert row["unit"] == "seconds"
    assert 240 <= row["magnitude"] <= 360, "roughly five minutes overdue"
    assert row["evidence_sample"]["ever_succeeded"] is True

    issue = fleet.execute("SELECT * FROM issues WHERE fingerprint = %s",
                          (row["fingerprint"],)).fetchone()
    assert issue["status"] == "OPEN"
    assert issue["severity"] == "HIGH"


def test_heartbeat_never_reports_itself_missing(fleet, admin):
    hb_slots = heartbeat_slots(fleet, 2)
    first = run_heartbeat(fleet, slot_end=hb_slots[1])
    admin.execute("UPDATE detector_runs SET completed_at = now() - interval '2 hours'"
                  " WHERE id = %s", (first.run_id,))

    second = run_heartbeat(fleet, slot_end=hb_slots[0])

    self_reports = [o for o in observations(fleet, second.run_id,
                                            "DETECTOR_RUN_MISSING")
                    if o["subject_id"] == HEARTBEAT]
    assert self_reports == [], "it cannot be running and missing at once"


def test_backfill_does_not_mask_a_dead_scheduler(fleet, admin):
    """Every heartbeat query filters run_mode = 'SCHEDULED'."""
    slots = settled_slots(fleet, 2)
    hb_slots = heartbeat_slots(fleet, 1)

    scheduled = open_target_run(fleet, slots[1])
    close_run(admin, scheduled, "OK", "3 hours")

    # A backfill that finished seconds ago. It is real work, but it is not
    # evidence that the scheduler is alive.
    admin.execute(
        """INSERT INTO detector_runs (detector_key, detector_version,
               issue_key_version, product, semantics, run_mode, backfill_batch_id,
               coverage_mode, subjects_evaluated, window_start, window_end,
               status, completed_at, observations_created)
           VALUES (%s, 1, 1, %s, 'LEVEL', 'BACKFILL', gen_random_uuid(),
                   'ENUMERATED', ARRAY['tenant:1'], %s, %s, 'OK', now(), 0)""",
        (TARGET, PRODUCT, slots[0] - timedelta(hours=1), slots[0]))

    result = run_heartbeat(fleet, slot_end=hb_slots[0])
    fired = observations(fleet, result.run_id, "DETECTOR_RUN_MISSING")
    assert len(fired) == 1 and fired[0]["subject_id"] == TARGET


def test_error_streak_fires_at_three_consecutive_non_ok_runs(fleet, admin):
    slots = settled_slots(fleet, 4)
    hb_slots = heartbeat_slots(fleet, 3)

    close_run(admin, open_target_run(fleet, slots[3]), "OK", "4 hours")
    close_run(admin, open_target_run(fleet, slots[2]), "ERROR", "3 hours")
    close_run(admin, open_target_run(fleet, slots[1]), "PARTIAL", "2 hours")

    two = run_heartbeat(fleet, slot_end=hb_slots[1])
    assert observations(fleet, two.run_id, "DETECTOR_ERROR_STREAK") == []

    close_run(admin, open_target_run(fleet, slots[0]), "ERROR", "1 hour")

    three = run_heartbeat(fleet, slot_end=hb_slots[0])
    fired = observations(fleet, three.run_id, "DETECTOR_ERROR_STREAK")
    assert len(fired) == 1
    assert fired[0]["subject_id"] == TARGET
    assert fired[0]["magnitude"] == 3
    assert fired[0]["unit"] == "runs"


def test_window_abandoned_fires_at_max_attempts(fleet, admin):
    slots = settled_slots(fleet, 1)
    hb_slots = heartbeat_slots(fleet, 1)
    run_id = open_target_run(fleet, slots[0])
    close_run(admin, run_id, "ERROR", "1 minute", attempt_count=3)   # max_attempts

    result = run_heartbeat(fleet, slot_end=hb_slots[0])
    fired = observations(fleet, result.run_id, "DETECTOR_WINDOW_ABANDONED")
    assert len(fired) == 1
    assert fired[0]["subject_id"] == TARGET
    assert fired[0]["magnitude"] == 1
    assert fired[0]["evidence_sample"]["attempts"] == 3
    issue = fleet.execute("SELECT severity FROM issues WHERE fingerprint = %s",
                          (fp(TARGET, "DETECTOR_WINDOW_ABANDONED"),)).fetchone()
    assert issue["severity"] == "CRITICAL"


def test_run_stale_is_observed_then_reclaimed(fleet, admin):
    """execution_timeout is 2 minutes in the registry; nothing in code."""
    slots = settled_slots(fleet, 1)
    hb_slots = heartbeat_slots(fleet, 1)
    run_id = open_target_run(fleet, slots[0])
    admin.execute("UPDATE detector_runs SET last_attempt_at = now() - interval "
                  "'30 minutes' WHERE id = %s", (run_id,))

    result = run_heartbeat(fleet, slot_end=hb_slots[0])

    fired = observations(fleet, result.run_id, "DETECTOR_RUN_STALE")
    assert len(fired) == 1
    assert fired[0]["magnitude"] == 1
    assert fired[0]["evidence_sample"]["sample_1"] == run_id
    reclaimed = run_row(fleet, run_id)
    assert reclaimed["status"] == "RUNNING"
    assert reclaimed["attempt_count"] == 2, "reclaimed for another attempt"


def test_deadman_switch_is_not_pinged_when_the_run_fails(fleet, monkeypatch):
    """A ping that survives failure is a switch that reports health while broken."""
    pings: list[str] = []
    monkeypatch.setattr(HeartbeatDetector, "on_success",
                        lambda self, ctx: pings.append("ping"))
    hb_slots = heartbeat_slots(fleet, 2)

    from detectors import sqlfile
    real_load = sqlfile.load
    monkeypatch.setattr(sqlfile, "load", lambda key, version=1: (
        sqlfile.Query(key, version, "SELECT * FROM no_such_table")
        if key == "registered_detectors" else real_load(key, version)))

    failed = run_heartbeat(fleet, slot_end=hb_slots[1])
    assert failed.status == base.STATUS_ERROR
    assert pings == []

    monkeypatch.setattr(sqlfile, "load", real_load)
    ok = run_heartbeat(fleet, slot_end=hb_slots[0])
    assert ok.status == base.STATUS_OK
    assert pings == ["ping"]
