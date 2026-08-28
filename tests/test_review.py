"""review.py: the console side.

The review command is where this layer costs a person something, so what is
tested here is that it shows the evidence, that it records who decided and
how long it took, and that it cannot be used by anything except the console.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import review
from support_proposals import insert_proposal


def test_undecided_lists_proposals_with_their_evidence(proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="k1", evidence=2)
    rows = review.undecided(console)
    assert [r["id"] for r in rows] == [proposal_id]
    assert len(rows[0]["evidence"]) == 2


def test_a_decided_proposal_drops_out_of_the_list(proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="k1")
    review.record(console, proposal_id, "ACCEPT", None, 4.25)
    assert review.undecided(console) == []


def test_the_decision_records_who_and_how_long(proposer, console, admin):
    proposal_id = insert_proposal(proposer, finding_key="k1")
    review.record(console, proposal_id, "REJECT", "WRONG_PRIORITY", 12.75)

    row = admin.execute("SELECT * FROM decisions WHERE proposal_id = %s",
                        (proposal_id,)).fetchone()
    assert row["verdict"] == "REJECT"
    assert row["reason_code"] == "WRONG_PRIORITY"
    assert float(row["decision_seconds"]) == pytest.approx(12.75)
    assert row["decided_by"] == "fleet_test_console"
    assert row["executed"] is None and row["abandoned_at"] is None


def test_a_rejection_without_a_reason_is_refused_before_it_reaches_the_database(
        proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="k1")
    with pytest.raises(ValueError):
        review.record(console, proposal_id, "REJECT", None, 1.0)
    assert review.undecided(console)   # still undecided


def test_an_unknown_verdict_is_refused(proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="k1")
    with pytest.raises(ValueError):
        review.record(console, proposal_id, "MAYBE", None, 1.0)


def test_an_unknown_reason_code_is_refused(proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="k1")
    with pytest.raises(ValueError):
        review.record(console, proposal_id, "REJECT", "BECAUSE_I_SAY_SO", 1.0)


def test_the_rendered_proposal_shows_its_evidence(proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="k1", title="a title")
    text = review.render(review.undecided(console)[0])
    assert "a title" in text
    assert "evidence:" in text
    assert "detectors.open_issues" in text


def test_a_stale_evidence_row_is_marked_in_the_rendering(proposer, console):
    """Evidence is append-only, so the stale row is written stale."""
    proposal_id = insert_proposal(proposer, finding_key="k1")
    proposer.execute(
        """
        INSERT INTO proposal_evidence (proposal_id, adapter, query_key, value,
                                       fetched_at, freshness_bound, stale)
        VALUES (%s, 'detectors', 'open_issues', '{"n": 1}'::jsonb, now(),
                interval '15 minutes', true)
        """, (proposal_id,))
    proposer.commit()
    text = review.render(review.undecided(console)[0])
    assert "STALE WHEN READ" in text


def test_a_detector_role_cannot_record_a_decision(proposer, fleet):
    """The detection layer writes observations. It does not get a vote."""
    proposal_id = insert_proposal(proposer, finding_key="k1")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        review.record(fleet, proposal_id, "ACCEPT", None, 1.0)


def test_the_decide_command_records_one_decision(proposer, admin, capsys):
    proposal_id = insert_proposal(proposer, finding_key="k1")
    code = review.main(["decide", "--proposal", str(proposal_id),
                        "--verdict", "DEFER_30D", "--reason", "NOT_MY_CALL",
                        "--seconds", "9"])
    assert code == 0
    row = admin.execute("SELECT verdict, reason_code, decision_seconds "
                        "FROM decisions WHERE proposal_id = %s",
                        (proposal_id,)).fetchone()
    assert row["verdict"] == "DEFER_30D"
    assert row["reason_code"] == "NOT_MY_CALL"
    assert float(row["decision_seconds"]) == 9.0


def test_the_list_command_prints_and_changes_nothing(proposer, admin, capsys):
    insert_proposal(proposer, finding_key="k1", title="unreviewed thing")
    assert review.main(["list"]) == 0
    assert "unreviewed thing" in capsys.readouterr().out
    assert admin.execute("SELECT count(*) AS n FROM decisions").fetchone()["n"] == 0


def test_the_default_command_is_list(proposer, admin, capsys):
    insert_proposal(proposer, finding_key="k1", title="unreviewed thing")
    assert review.main([]) == 0
    assert "unreviewed thing" in capsys.readouterr().out


def test_reviewing_measures_the_time_taken(proposer, console, admin, monkeypatch):
    """The clock runs from the moment the proposal is on screen."""
    proposal_id = insert_proposal(proposer, finding_key="k1")
    clock = iter([100.0, 107.5])
    monkeypatch.setattr(review.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(review, "prompt_verdict", lambda: ("ACCEPT", None))

    assert review.review(console) == 1
    row = admin.execute("SELECT decision_seconds FROM decisions "
                        "WHERE proposal_id = %s", (proposal_id,)).fetchone()
    assert float(row["decision_seconds"]) == pytest.approx(7.5)


def test_quitting_mid_review_leaves_the_rest_undecided(proposer, console, admin,
                                                       monkeypatch):
    for n in range(3):
        insert_proposal(proposer, finding_key=f"k{n}")
    monkeypatch.setattr(review, "prompt_verdict", lambda: None)

    assert review.review(console) == 0
    assert admin.execute("SELECT count(*) AS n FROM decisions").fetchone()["n"] == 0
    assert len(review.undecided(console)) == 3


def test_skipping_leaves_that_one_undecided(proposer, console, admin, monkeypatch):
    insert_proposal(proposer, finding_key="k1")
    monkeypatch.setattr(review, "prompt_verdict", lambda: ("SKIP", None))
    assert review.review(console) == 0
    assert len(review.undecided(console)) == 1
