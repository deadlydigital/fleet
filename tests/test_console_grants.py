"""The console's verdict path, end to end, as a role that owns nothing.

The false-positive rate gates detector trust, and the only way a verdict gets
recorded is a person finding an untriaged observation and ruling on it. That
path is two statements, not one: read what has not been ruled on, then record
the ruling. A grant covering only the second half leaves a role that can
record a judgement about something it cannot see.

The deployed database hid this, because its console member also happens to
own every table and an owner needs no grants. These tests connect as
fleet_test_console, which owns nothing, so they fail the way a fresh install
fails.
"""
from __future__ import annotations

from support import settled_slots
from support_proposals import RECONCILIATION, arrange_observations, slot_ends

RECORD_VERDICT = """
INSERT INTO observation_verdicts
    (observation_id, detector_key, detector_version, issue_key_version,
     observation_type, verdict, verdict_by, reason)
SELECT o.id, o.detector_key, o.detector_version, o.issue_key_version,
       o.observation_type, %(verdict)s, 'console', %(reason)s
  FROM observations o
  LEFT JOIN observation_verdicts v ON v.observation_id = o.id
 WHERE v.id IS NULL
RETURNING id
"""

UNTRIAGED = """
SELECT o.id, o.observation_type, o.subject_id, o.magnitude
  FROM observations o
  LEFT JOIN observation_verdicts v ON v.observation_id = o.id
 WHERE v.id IS NULL
 ORDER BY o.id
"""


def test_the_console_can_find_and_rule_on_an_untriaged_observation(admin, console):
    """The whole path in the order a person walks it."""
    slot = slot_ends(admin, RECONCILIATION, 1)[0]
    arrange_observations(admin, RECONCILIATION, slot, count=2)

    pending = console.execute(UNTRIAGED).fetchall()
    assert len(pending) == 2

    recorded = console.execute(RECORD_VERDICT,
                               {"verdict": "VALID",
                                "reason": "confirmed by direct query"}).fetchall()
    console.commit()
    assert len(recorded) == 2

    assert console.execute(UNTRIAGED).fetchall() == []


def test_the_console_can_read_the_issues_a_verdict_bears_on(admin, console):
    """A verdict is a judgement about an observation in the context of the
    issue it opened. Reading one without the other is guessing."""
    slot = slot_ends(admin, RECONCILIATION, 1)[0]
    arrange_observations(admin, RECONCILIATION, slot, count=1)
    console.execute("SELECT id, fingerprint, severity, status FROM issues")


def test_the_console_still_cannot_write_what_it_judges(console):
    """Reading is the whole of the new grant. It must not have acquired a way
    to edit the evidence underneath its own verdict."""
    import psycopg
    import pytest

    for statement in (
            "UPDATE observations SET magnitude = 1",
            "DELETE FROM observations",
            "INSERT INTO issues (fingerprint, product, issue_type, subject_type, "
            "subject_id, detector_key, first_seen, last_seen) "
            "VALUES ('x','deadly_digital','T','tenant','2','k',now(),now())"):
        console.rollback()
        with pytest.raises((psycopg.errors.InsufficientPrivilege,
                            psycopg.errors.RaiseException)):
            console.execute(statement)
