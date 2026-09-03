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
    review.record(console, proposal_id, "ACCEPT", None, 4.25, "worth doing")
    assert review.undecided(console) == []


def test_the_decision_records_who_and_how_long(proposer, console, admin):
    proposal_id = insert_proposal(proposer, finding_key="k1")
    review.record(console, proposal_id, "REJECT", "WRONG_PRIORITY", 12.75,
                  "real, but not this quarter")

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
        review.record(console, proposal_id, "REJECT", None, 1.0, "why not")
    assert review.undecided(console)   # still undecided


def test_an_unknown_verdict_is_refused(proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="k1")
    with pytest.raises(ValueError):
        review.record(console, proposal_id, "MAYBE", None, 1.0, "why not")


def test_an_unknown_reason_code_is_refused(proposer, console):
    proposal_id = insert_proposal(proposer, finding_key="k1")
    with pytest.raises(ValueError):
        review.record(console, proposal_id, "REJECT", "BECAUSE_I_SAY_SO", 1.0,
                      "why not")


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
        review.record(fleet, proposal_id, "ACCEPT", None, 1.0, "worth doing")


def test_the_decide_command_records_one_decision(proposer, admin, capsys):
    proposal_id = insert_proposal(proposer, finding_key="k1")
    code = review.main(["decide", "--proposal", str(proposal_id),
                        "--verdict", "DEFER_30D", "--reason", "NOT_MY_CALL",
                        "--seconds", "9", "--why", "waiting on the sync window"])
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
    monkeypatch.setattr(review, "prompt_why", lambda: "worth doing")

    assert review.review(console) == 1
    row = admin.execute("SELECT decision_seconds FROM decisions "
                        "WHERE proposal_id = %s", (proposal_id,)).fetchone()
    assert float(row["decision_seconds"]) == pytest.approx(7.5)


def test_quitting_mid_review_leaves_the_rest_undecided(proposer, console, admin,
                                                       monkeypatch):
    for n in range(3):
        insert_proposal(proposer, finding_key=f"k{n}")
    monkeypatch.setattr(review, "prompt_verdict", lambda: None)
    # Patched to raise: quitting must not reach the reason prompt at all.
    monkeypatch.setattr(review, "prompt_why", lambda: pytest.fail(
        "a quit reached the reason prompt"))

    assert review.review(console) == 0
    assert admin.execute("SELECT count(*) AS n FROM decisions").fetchone()["n"] == 0
    assert len(review.undecided(console)) == 3


def test_skipping_leaves_that_one_undecided(proposer, console, admin, monkeypatch):
    insert_proposal(proposer, finding_key="k1")
    monkeypatch.setattr(review, "prompt_verdict", lambda: ("SKIP", None))
    # SKIP logs nothing, so it must not ask for a reason either.
    monkeypatch.setattr(review, "prompt_why", lambda: pytest.fail(
        "a skip reached the reason prompt"))
    assert review.review(console) == 0
    assert len(review.undecided(console)) == 1


# ---- the decision log -----------------------------------------------------
#
# Every verdict now opens a decision_log row as well. `decisions` is the
# countable grade on this layer; the log is the sentence, across everything.


class TestEveryVerdictOpensADecision:

    def test_an_acceptance_is_logged(self, proposer, console, admin):
        pid = insert_proposal(proposer, finding_key="k1", title="Close the gap")
        _, log_id = review.record(console, pid, "ACCEPT", None, 4.0,
                                  "cheap, reversible, and it unblocks the page")
        row = admin.execute("SELECT * FROM decision_outcomes WHERE id = %s",
                            (log_id,)).fetchone()
        assert row["decision"] == "APPROVED"
        assert row["proposal_id"] == pid
        assert row["reason"].startswith("cheap, reversible")

    def test_a_rejection_is_logged_exactly_as_readily(self, proposer, console,
                                                      admin):
        """The asymmetry the log exists to remove.

        Logging accepts and dropping rejects would rebuild it: an approval
        leaves a branch behind, a rejection leaves nothing but this row.
        """
        pid = insert_proposal(proposer, finding_key="k1")
        _, log_id = review.record(console, pid, "REJECT", "NOT_MY_CALL", 8.0,
                                  "right diagnosis, but the fix is a product "
                                  "call I am not making this quarter")
        row = admin.execute("SELECT decision, reason FROM decision_log "
                            "WHERE id = %s", (log_id,)).fetchone()
        assert row["decision"] == "REJECTED"
        assert "product call" in row["reason"]

    def test_a_deferral_is_logged(self, proposer, console, admin):
        pid = insert_proposal(proposer, finding_key="k1")
        _, log_id = review.record(console, pid, "DEFER_30D", "MISSING_CONTEXT",
                                  3.0, "waiting on the sync window to clear")
        assert admin.execute("SELECT decision FROM decision_log WHERE id = %s",
                             (log_id,)).fetchone()["decision"] == "DEFERRED"

    def test_the_code_and_the_sentence_are_both_kept(self, proposer, console,
                                                     admin):
        """One is what gets counted, the other is what gets read."""
        pid = insert_proposal(proposer, finding_key="k1")
        decision_id, log_id = review.record(
            console, pid, "REJECT", "ALREADY_KNOWN", 5.0,
            "we found this ourselves in August and it is in TODO as BUG-014")
        code = admin.execute("SELECT reason_code FROM decisions WHERE id = %s",
                             (decision_id,)).fetchone()["reason_code"]
        sentence = admin.execute("SELECT reason FROM decision_log WHERE id = %s",
                                 (log_id,)).fetchone()["reason"]
        assert code == "ALREADY_KNOWN"
        assert sentence != "ALREADY_KNOWN"
        assert "BUG-014" in sentence

    def test_the_product_comes_from_the_proposal(self, proposer, console, admin):
        """Not prompted for, and not inferred from the evidence."""
        pid = insert_proposal(proposer, finding_key="k1", product="fleet")
        _, log_id = review.record(console, pid, "ACCEPT", None, 1.0, "yes")
        assert admin.execute("SELECT product FROM decision_log WHERE id = %s",
                             (log_id,)).fetchone()["product"] == "fleet"

    def test_the_subject_and_evidence_are_captured_from_the_proposal(
            self, proposer, console, admin):
        pid = insert_proposal(proposer, finding_key="k1",
                              title="Tenant 2 has an old gap")
        _, log_id = review.record(console, pid, "ACCEPT", None, 1.0, "yes")
        row = admin.execute("SELECT subject, evidence FROM decision_log "
                            "WHERE id = %s", (log_id,)).fetchone()
        assert row["subject"] == "Tenant 2 has an old gap"
        assert row["evidence"][0]["kind"] == "proposal_evidence"

    def test_a_verdict_with_no_sentence_is_refused_before_the_database(
            self, proposer, console, admin):
        pid = insert_proposal(proposer, finding_key="k1")
        with pytest.raises(ValueError, match="in words"):
            review.record(console, pid, "REJECT", "WRONG_PRIORITY", 1.0, "  ")
        assert admin.execute("SELECT count(*) AS n FROM decisions"
                             ).fetchone()["n"] == 0

    def test_the_enum_code_is_not_reused_as_the_sentence(self, proposer, console):
        """Falling back to the code would put ALREADY_KNOWN in the field whose
        entire purpose is to hold what the code could not."""
        pid = insert_proposal(proposer, finding_key="k1")
        with pytest.raises(ValueError):
            review.record(console, pid, "REJECT", "ALREADY_KNOWN", 1.0, None)


class TestBothOrNeither:

    def test_a_failed_log_write_takes_the_verdict_with_it(
            self, proposer, console, admin, monkeypatch):
        """A verdict with no record of why is the split the log closes.

        The failure is forced on the SECOND insert, and the connection is then
        committed as a caller that swallowed the error would -- which is what
        makes this distinguish a rolled-back pair from two statements that
        happen not to have been committed yet.
        """
        pid = insert_proposal(proposer, finding_key="k1")
        real_execute = console.execute
        calls = {"n": 0}

        def flaky(query, *args, **kwargs):
            if "INSERT INTO decision_log" in str(query):
                calls["n"] += 1
                raise psycopg.errors.CheckViolation("forced")
            return real_execute(query, *args, **kwargs)

        monkeypatch.setattr(console, "execute", flaky)
        with pytest.raises(psycopg.errors.CheckViolation):
            review.record(console, pid, "ACCEPT", None, 1.0, "yes")
        monkeypatch.undo()
        console.commit()

        assert calls["n"] == 1
        assert admin.execute("SELECT count(*) AS n FROM decisions"
                             ).fetchone()["n"] == 0
        assert admin.execute("SELECT count(*) AS n FROM decision_log"
                             ).fetchone()["n"] == 0


class TestSkipLogsNothing:

    def test_a_skip_records_neither(self, proposer, console, admin, monkeypatch):
        insert_proposal(proposer, finding_key="k1")
        monkeypatch.setattr(review, "prompt_verdict", lambda: ("SKIP", None))
        monkeypatch.setattr(review, "prompt_why", lambda: pytest.fail(
            "a skip reached the reason prompt"))
        assert review.review(console) == 0
        assert admin.execute("SELECT count(*) AS n FROM decision_log"
                             ).fetchone()["n"] == 0
