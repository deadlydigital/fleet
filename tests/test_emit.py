"""Issue lifecycle at the emit boundary."""
from __future__ import annotations

import pytest
from psycopg.types.json import Jsonb

from detectors.emit import evidence_sample, fingerprint
from support import observations, run_reconciliation, settled_slots

DETECTOR = "dd_analytics_reconciliation"
MISSING_FP = fingerprint(DETECTOR, 1, "deadly_digital", "tenant", "2",
                         "MISSING_ANALYTICS_ORDER")


def test_a_resolved_issue_reopens_and_counts_the_reopen(fleet, admin, dsns):
    slots = settled_slots(fleet, 2)
    run_reconciliation(fleet, dsns["dd"], slot_end=slots[1])

    admin.execute(
        """UPDATE issues SET status = 'RESOLVED', resolution_type = 'CLEARED',
                  resolved_at = now(), resolution_effective_at = now()
            WHERE fingerprint = %s""", (MISSING_FP,))

    run_reconciliation(fleet, dsns["dd"], slot_end=slots[0])

    issue = fleet.execute("SELECT * FROM issues WHERE fingerprint = %s",
                          (MISSING_FP,)).fetchone()
    assert issue["status"] == "OPEN"
    assert issue["reopen_count"] == 1
    assert issue["occurrence_count"] == 2
    assert issue["resolved_at"] is None
    assert issue["resolution_effective_at"] is None
    assert issue["last_seen"] == slots[0]
    # The trigger opens a second occurrence rather than reusing the closed one.
    occurrences = fleet.execute(
        "SELECT count(*) AS n FROM issue_occurrences WHERE issue_id = %s",
        (issue["id"],)).fetchone()["n"]
    assert occurrences == 2


def test_a_suppressed_issue_is_left_alone(fleet, admin, dsns):
    slots = settled_slots(fleet, 2)
    run_reconciliation(fleet, dsns["dd"], slot_end=slots[1])
    admin.execute("UPDATE issues SET status = 'SUPPRESSED' WHERE fingerprint = %s",
                  (MISSING_FP,))

    result = run_reconciliation(fleet, dsns["dd"], slot_end=slots[0])

    # The observation is still recorded: suppression silences the issue, not
    # the evidence.
    assert len(observations(fleet, result.run_id, "MISSING_ANALYTICS_ORDER")) == 1
    issue = fleet.execute("SELECT * FROM issues WHERE fingerprint = %s",
                          (MISSING_FP,)).fetchone()
    assert issue["status"] == "SUPPRESSED"
    assert issue["occurrence_count"] == 1
    assert issue["last_seen"] == slots[1]


def test_severity_follows_magnitude_through_routing_policy(fleet, admin, dsns):
    """route_severity, never a literal: 3 missing is MEDIUM, 7 is HIGH."""
    result = run_reconciliation(fleet, dsns["dd"])
    issue = fleet.execute("SELECT severity FROM issues WHERE fingerprint = %s",
                          (MISSING_FP,)).fetchone()
    assert issue["severity"] == "MEDIUM"
    routed = fleet.execute(
        "SELECT route_severity('MISSING_ANALYTICS_ORDER', 7) AS s").fetchone()["s"]
    assert routed == "HIGH"


def test_evidence_sample_is_scalar_only(fleet, dsns):
    with pytest.raises(ValueError):
        evidence_sample([1, 2], nested={"a": 1})

    slot = settled_slots(fleet, 1)[0]
    run_id = fleet.execute(
        "SELECT open_scheduled_run(%s, 1, 'deadly_digital', %s) AS id",
        (DETECTOR, slot)).fetchone()["id"]
    # The column rejects nested objects. It does NOT reject an array of
    # scalars: jsonb_path_exists runs in lax mode, so `$.*` unwraps the array
    # and only ever sees the numbers inside it. The helper flattens anyway --
    # relying on a constraint that does not quite say what it means is how
    # free text eventually gets in.
    with pytest.raises(Exception) as excinfo:
        fleet.execute(
            """INSERT INTO observations (detector_run_id, detector_key,
                   detector_version, issue_key_version, product, observation_type,
                   observed_at, subject_type, subject_id, fingerprint,
                   evidence_sample)
               VALUES (%s,'x',1,1,'deadly_digital','MISSING_ANALYTICS_ORDER',
                       now(),'tenant','999','deadbeef', %s)""",
            (run_id, Jsonb({"detail": {"ids": [1, 2, 3]}})))
    assert "evidence_sample_shape_ck" in str(excinfo.value)


def test_fingerprint_is_stable_and_per_subject():
    a = fingerprint(DETECTOR, 1, "deadly_digital", "tenant", "2",
                    "MISSING_ANALYTICS_ORDER")
    b = fingerprint(DETECTOR, 1, "deadly_digital", "tenant", "2",
                    "ORPHANED_ANALYTICS_ORDER")
    c = fingerprint(DETECTOR, 1, "deadly_digital", "tenant", "1",
                    "MISSING_ANALYTICS_ORDER")
    d = fingerprint(DETECTOR, 2, "deadly_digital", "tenant", "2",
                    "MISSING_ANALYTICS_ORDER")
    assert a == MISSING_FP and len(a) == 64
    assert len({a, b, c, d}) == 4, "type, subject and key version all separate"
