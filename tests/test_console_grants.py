"""The verdict path, end to end, as roles that own nothing.

Two roles may record an observation verdict: fleet_console and
fleet_evaluator. The false-positive rate gates detector trust, and the only
way a verdict gets recorded is a person finding an untriaged observation and
ruling on it. That path is two statements, not one: read what has not been
ruled on, then record the ruling. A grant covering only the second half
leaves a role that can record a judgement about something it cannot see.

The deployed database hid this, because its console member also happens to
own every table and an owner needs no grants. The evaluator's copy hid for a
second reason: the half of its job that runs on a timer goes through
SECURITY DEFINER functions, which never needed the grant, so exercising the
automated path proved nothing about the manual one.

Every test here connects as a login role that owns nothing, so they fail the
way a fresh install fails.
"""
from __future__ import annotations

import psycopg
import pytest

from support_proposals import RECONCILIATION, arrange_observations, slot_ends

RECORD_VERDICT = """
INSERT INTO observation_verdicts
    (observation_id, detector_key, detector_version, issue_key_version,
     observation_type, verdict, verdict_by, reason)
SELECT o.id, o.detector_key, o.detector_version, o.issue_key_version,
       o.observation_type, %(verdict)s, %(by)s, %(reason)s
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


@pytest.fixture(params=["console", "evaluator"])
def verdict_role(request):
    """Both roles the verdict trigger accepts, exercised identically.

    They are parametrised rather than tested separately because the path is
    the same path; the gap existed in both, and a fix that reached only one
    of them would pass a test written for that one.
    """
    return request.param, request.getfixturevalue(request.param)


def test_the_untriaged_observation_can_be_found_and_ruled_on(admin, verdict_role):
    """The whole path in the order a person walks it."""
    name, conn = verdict_role
    slot = slot_ends(admin, RECONCILIATION, 1)[0]
    arrange_observations(admin, RECONCILIATION, slot, count=2)

    pending = conn.execute(UNTRIAGED).fetchall()
    assert len(pending) == 2

    recorded = conn.execute(RECORD_VERDICT,
                            {"verdict": "VALID", "by": name,
                             "reason": "confirmed by direct query"}).fetchall()
    conn.commit()
    assert len(recorded) == 2

    assert conn.execute(UNTRIAGED).fetchall() == []


def test_the_issues_a_verdict_bears_on_can_be_read(admin, verdict_role):
    """A verdict is a judgement about an observation in the context of the
    issue it opened. Reading one without the other is guessing."""
    _, conn = verdict_role
    slot = slot_ends(admin, RECONCILIATION, 1)[0]
    arrange_observations(admin, RECONCILIATION, slot, count=1)
    conn.execute("SELECT id, fingerprint, severity, status FROM issues")


def test_the_evidence_underneath_a_verdict_stays_read_only(verdict_role):
    """Reading is the whole of the new grant. Neither role may edit the
    evidence its own verdict rests on."""
    _, conn = verdict_role
    for statement in (
            "UPDATE observations SET magnitude = 1",
            "DELETE FROM observations",
            "UPDATE issues SET severity = 'LOW'",
            "INSERT INTO issues (fingerprint, product, issue_type, subject_type, "
            "subject_id, detector_key, first_seen, last_seen) "
            "VALUES ('x','deadly_digital','T','tenant','2','k',now(),now())"):
        conn.rollback()
        with pytest.raises((psycopg.errors.InsufficientPrivilege,
                            psycopg.errors.RaiseException)):
            conn.execute(statement)


def test_the_evaluators_automated_path_never_needed_the_grant(admin, evaluator):
    """Why the gap survived being exercised.

    resolve_cleared_issues() and execute_due_outcome_checks() are SECURITY
    DEFINER, so the half of the evaluator's job that runs on a timer works
    with or without SELECT on the tables it touches. Running the timer
    therefore proved nothing about the half a person walks, which is the one
    that was broken.
    """
    slot = slot_ends(admin, RECONCILIATION, 1)[0]
    arrange_observations(admin, RECONCILIATION, slot, count=1)

    assert evaluator.execute("SELECT resolve_cleared_issues() AS n"
                             ).fetchone()["n"] == 0
    assert evaluator.execute("SELECT execute_due_outcome_checks() AS n"
                             ).fetchone()["n"] == 0


def test_a_role_with_neither_membership_still_cannot_record_a_verdict(fleet):
    """The grant widened reading, not authority. The detector writes
    observations and still does not get a vote on them."""
    with pytest.raises((psycopg.errors.InsufficientPrivilege,
                        psycopg.errors.RaiseException)):
        fleet.execute(RECORD_VERDICT,
                      {"verdict": "VALID", "by": "detector", "reason": "no"})
