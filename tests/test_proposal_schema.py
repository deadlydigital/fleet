"""002_proposals.sql: the invariants that must hold in the database.

Not one of these is checked in Python at runtime. Every one of them is
checked here through a connection holding exactly the privileges the real
process holds, because a rule enforced by the application is a rule that
holds until someone writes a second client.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest

from support_proposals import insert_proposal

CYCLE = uuid.UUID("11111111-1111-1111-1111-111111111111")

BARE_PROPOSAL = """
INSERT INTO proposals (cycle_id, kind, product, area, finding_key, title, body,
                       objective_ref, reversibility, confidence)
VALUES (%(c)s, 'OBSERVATION', 'deadly_digital', 'deadly_digital', %(key)s,
        't', 'b', 'dd-trustworthy', 'TRIVIAL', 1.0)
RETURNING id
"""


# ---- evidence -------------------------------------------------------------

def test_proposal_without_evidence_is_rejected_at_commit(proposer):
    """The whole point of the deferrable trigger: the check happens at COMMIT.

    The INSERT itself must succeed -- the evidence rows reference the
    proposal id and cannot exist before it -- and the transaction must then
    refuse to commit.
    """
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        with proposer.transaction():
            proposer.execute(BARE_PROPOSAL, {"c": CYCLE, "key": "bare"})
    assert "carries no evidence" in str(caught.value)


def test_proposal_with_evidence_in_the_same_transaction_commits(proposer, admin):
    proposal_id = insert_proposal(proposer, cycle_id=CYCLE, finding_key="withev")
    row = admin.execute("SELECT count(*) AS n FROM proposal_evidence "
                        "WHERE proposal_id = %s", (proposal_id,)).fetchone()
    assert row["n"] == 1


def test_deleting_the_last_evidence_row_leaves_no_bare_proposal(proposer, admin):
    """Retention is allowed to delete evidence. It is not allowed to strand a
    proposal without any."""
    proposal_id = insert_proposal(proposer, cycle_id=CYCLE, finding_key="retain")
    admin.execute("GRANT fleet_admin TO CURRENT_USER")
    with pytest.raises(psycopg.errors.CheckViolation):
        with admin.transaction():
            admin.execute("DELETE FROM proposal_evidence WHERE proposal_id = %s",
                          (proposal_id,))


def test_evidence_may_not_be_updated(proposer, admin):
    proposal_id = insert_proposal(proposer, cycle_id=CYCLE, finding_key="immutable")
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute("UPDATE proposal_evidence SET adapter = 'forged' "
                      "WHERE proposal_id = %s", (proposal_id,))


def test_proposals_are_append_only(proposer, admin):
    proposal_id = insert_proposal(proposer, cycle_id=CYCLE, finding_key="append")
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute("UPDATE proposals SET title = 'rewritten' WHERE id = %s",
                      (proposal_id,))


# ---- the cap --------------------------------------------------------------

def test_a_sixth_proposal_in_one_cycle_is_refused(proposer):
    for n in range(5):
        insert_proposal(proposer, cycle_id=CYCLE, finding_key=f"cap-{n}")
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        insert_proposal(proposer, cycle_id=CYCLE, finding_key="cap-6")
    assert "cap is 5" in str(caught.value)


def test_the_cap_is_per_cycle_not_global(proposer):
    for n in range(5):
        insert_proposal(proposer, cycle_id=CYCLE, finding_key=f"first-{n}")
    other = uuid.uuid4()
    insert_proposal(proposer, cycle_id=other, finding_key="second-0")


# ---- shape ----------------------------------------------------------------

def test_a_non_risk_must_name_an_objective(proposer):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_proposal(proposer, kind="OBSERVATION", objective_ref=None,
                        finding_key="noobjective")


def test_a_risk_needs_no_objective(proposer):
    insert_proposal(proposer, kind="RISK", objective_ref=None, finding_key="risk")


def test_an_observation_may_not_carry_an_effort_estimate(proposer):
    """An observation with an effort and an impact is a recommendation."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with proposer.transaction():
            proposer.execute(
                """
                INSERT INTO proposals (cycle_id, kind, product, area,
                                       finding_key, title, body, objective_ref,
                                       reversibility, confidence, est_effort,
                                       est_impact)
                VALUES (%s, 'OBSERVATION', 'deadly_digital', 'x', 'est', 't',
                        'b', 'dd-trustworthy', 'TRIVIAL', 1.0, 'HOURS', 'HIGH')
                """, (CYCLE,))


def test_a_recommendation_must_carry_one(proposer):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_proposal(proposer, kind="RECOMMENDATION", finding_key="norec")


def test_confidence_is_bounded(proposer):
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_proposal(proposer, confidence="1.5", finding_key="overconfident")


# ---- who may do what ------------------------------------------------------

def test_the_proposer_cannot_read_its_own_proposals(proposer):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        proposer.execute("SELECT title FROM proposals")


def test_the_proposer_may_read_only_the_id_it_needs_for_evidence(proposer):
    proposer.execute("SELECT id FROM proposals")


def test_the_proposer_cannot_read_track_one(proposer):
    for table in ("detector_runs", "observations", "issues",
                  "observation_verdicts"):
        proposer.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            proposer.execute(f"SELECT count(*) FROM {table}")


def test_the_proposer_cannot_decide(proposer, admin):
    admin.execute("SELECT 1")  # keep the fixture ordering explicit
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        proposer.execute("INSERT INTO decisions (proposal_id, verdict, "
                         "decision_seconds) VALUES (1, 'ACCEPT', 1)")


def test_the_reader_cannot_write_proposals(reader):
    with pytest.raises((psycopg.errors.InsufficientPrivilege,
                        psycopg.errors.ReadOnlySqlTransaction)):
        reader.execute(BARE_PROPOSAL, {"c": CYCLE, "key": "reader"})


def test_the_reader_cannot_see_decisions(reader):
    """The layer may see what it said. Not how it was graded."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader.execute("SELECT count(*) FROM decisions")


def test_the_reader_can_see_track_one_and_its_own_proposals(reader):
    for table in ("detector_runs", "observations", "issues",
                  "observation_verdicts", "detector_registry", "proposals",
                  "proposal_evidence"):
        reader.execute(f"SELECT count(*) FROM {table}")


# ---- decisions ------------------------------------------------------------

def test_only_the_console_may_decide(proposer, console, admin):
    proposal_id = insert_proposal(proposer, finding_key="decide-me")
    row = console.execute(
        "INSERT INTO decisions (proposal_id, verdict, reason_code, "
        "decision_seconds) VALUES (%s, 'REJECT', 'ALREADY_KNOWN', 12.5) "
        "RETURNING id, decided_by", (proposal_id,)).fetchone()
    console.commit()
    assert row["decided_by"] == "fleet_test_console"


def test_a_role_outside_the_console_is_refused_by_trigger(proposer, admin, dsns):
    """Not by grant -- by trigger, the same way observation_verdicts is.

    Granting a role every privilege on the table is not enough: the rule is
    about authority, not permissions, so a role holding INSERT and no
    fleet_console membership is still refused. Without the trigger this test
    would pass the INSERT.
    """
    proposal_id = insert_proposal(proposer, finding_key="not-console")
    admin.execute("DROP ROLE IF EXISTS decision_probe")
    admin.execute("CREATE ROLE decision_probe LOGIN PASSWORD 'decision_probe'")
    admin.execute("GRANT USAGE ON SCHEMA public TO decision_probe")
    admin.execute("GRANT SELECT, INSERT ON decisions TO decision_probe")
    admin.execute("GRANT USAGE, SELECT ON SEQUENCE decisions_id_seq "
                  "TO decision_probe")
    probe_dsn = dsns["console"].replace("fleet_test_console:fleet_test_console",
                                        "decision_probe:decision_probe")
    try:
        with psycopg.connect(probe_dsn) as probe:
            with pytest.raises(psycopg.errors.RaiseException) as caught:
                probe.execute("INSERT INTO decisions (proposal_id, verdict, "
                              "decision_seconds) VALUES (%s, 'ACCEPT', 1)",
                              (proposal_id,))
            assert "may not record decisions" in str(caught.value)
    finally:
        admin.execute("REASSIGN OWNED BY decision_probe TO CURRENT_USER")
        admin.execute("DROP OWNED BY decision_probe")
        admin.execute("DROP ROLE IF EXISTS decision_probe")


def test_a_rejection_needs_a_reason(proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="reasonless")
    with pytest.raises(psycopg.errors.CheckViolation):
        console.execute("INSERT INTO decisions (proposal_id, verdict, "
                        "decision_seconds) VALUES (%s, 'REJECT', 1)",
                        (proposal_id,))


def test_an_acceptance_needs_none(proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="accepted")
    console.execute("INSERT INTO decisions (proposal_id, verdict, "
                    "decision_seconds) VALUES (%s, 'ACCEPT', 3)", (proposal_id,))
    console.commit()


def test_one_decision_per_proposal(proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="twice")
    console.execute("INSERT INTO decisions (proposal_id, verdict, "
                    "decision_seconds) VALUES (%s, 'ACCEPT', 3)", (proposal_id,))
    console.commit()
    with pytest.raises(psycopg.errors.UniqueViolation):
        console.execute("INSERT INTO decisions (proposal_id, verdict, "
                        "reason_code, decision_seconds) "
                        "VALUES (%s, 'REJECT', 'ALREADY_KNOWN', 3)",
                        (proposal_id,))


def test_the_verdict_freezes_and_the_outcome_does_not(proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="outcome")
    console.execute("INSERT INTO decisions (proposal_id, verdict, "
                    "decision_seconds) VALUES (%s, 'ACCEPT', 3)", (proposal_id,))
    console.commit()

    console.execute("UPDATE decisions SET executed = true, "
                    "outcome_note = 'shipped' WHERE proposal_id = %s",
                    (proposal_id,))
    console.commit()

    # Two layers, and both are load-bearing. The console's UPDATE grant is
    # column-level, so it cannot name verdict at all...
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        console.execute("UPDATE decisions SET verdict = 'REJECT' "
                        "WHERE proposal_id = %s", (proposal_id,))
    console.rollback()


def test_the_verdict_is_frozen_by_trigger_as_well_as_by_grant(proposer, console,
                                                              admin):
    """...and a role that does hold column-wide UPDATE is still refused.

    The superuser bypasses every grant in the database and must still not be
    able to rewrite a judgement after the fact.
    """
    proposal_id = insert_proposal(proposer, finding_key="frozen")
    console.execute("INSERT INTO decisions (proposal_id, verdict, "
                    "decision_seconds) VALUES (%s, 'ACCEPT', 3)", (proposal_id,))
    console.commit()

    with pytest.raises(psycopg.errors.RaiseException) as caught:
        admin.execute("UPDATE decisions SET verdict = 'REJECT' "
                      "WHERE proposal_id = %s", (proposal_id,))
    assert "settled" in str(caught.value)

    admin.execute("UPDATE decisions SET outcome_note = 'later' "
                  "WHERE proposal_id = %s", (proposal_id,))


def test_the_console_cannot_delete_a_decision(proposer, console):
    """It may record one and it may fill in what happened. It may not
    unrecord one.

    Deletion is left to fleet_admin, on the same retention terms as
    observations and run_steps -- reject_mutation is shared with them
    deliberately, so retention policy is one rule and not four.
    """
    proposal_id = insert_proposal(proposer, finding_key="undeletable")
    console.execute("INSERT INTO decisions (proposal_id, verdict, "
                    "decision_seconds) VALUES (%s, 'ACCEPT', 3)", (proposal_id,))
    console.commit()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        console.execute("DELETE FROM decisions WHERE proposal_id = %s",
                        (proposal_id,))
