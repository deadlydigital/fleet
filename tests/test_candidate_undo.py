"""Undoing one night's approval, before anything has been spent on it.

specs/auto-approval.md §5, correction 4. The morning brief prints this command
beside every unattended approval, so what it does has to match what that line
promises.

  the candidates come back and the task is abandoned -> TestItReturnsTheCandidates
  the original decision is NOT rewritten             -> TestTheLogIsNotTidied
  past the claim it says so instead of pretending    -> TestOnceItHasStarted
"""
from __future__ import annotations

import pytest

from console import autoapprove, undo
from tests.test_autoapprove import (
    ABSENT_FILE, API_PRESENT, EXISTS, PLATFORM, PLATFORM_FEATURE_MISSING,
    _batch, _cand, _pool)


def _an_approval(console, admin):
    """One real unattended approval, made the way the timer makes it."""
    _pool(admin)
    b = _batch(console)
    top = _cand(console, b, title="Forward the four order filters", repo=PLATFORM,
                probes=[API_PRESENT, PLATFORM_FEATURE_MISSING])
    _cand(console, b, title="A new report", probes=[EXISTS, ABSENT_FILE])
    out = autoapprove.sweep()
    assert out["approve_ids"] == [top]
    return out, top


class TestItReturnsTheCandidates:
    def test_the_candidate_is_pending_again_and_the_task_is_abandoned(
            self, dsns, console, admin):
        out, top = _an_approval(console, admin)
        task_id = out["queued_task_ids"][0]

        result = undo.undo_approval(out["decision_id"])
        assert [u["candidate_id"] for u in result["undone"]] == [top]

        c = console.execute(
            "SELECT disposition, decided_at, approval_decision_id, spec_task_id"
            " FROM candidates WHERE id=%s", (top,)).fetchone()
        assert c["disposition"] == "PENDING"
        # 013's candidates_decided_is_stamped_ck ties these together: a row that
        # is PENDING and still stamped cannot exist, so this is not cosmetic.
        assert c["decided_at"] is None
        assert c["approval_decision_id"] is None
        assert c["spec_task_id"] is None

        t = console.execute("SELECT status FROM tasks WHERE id=%s",
                            (task_id,)).fetchone()
        assert t["status"] == "ABANDONED"

    def test_the_returned_candidate_is_rankable_again(
            self, dsns, console, admin):
        """It goes back into the pool, not into limbo. Tomorrow night ranks it
        again -- which is what makes an undo with no reason a delay rather than
        a decision."""
        out, top = _an_approval(console, admin)
        undo.undo_approval(out["decision_id"])
        p = autoapprove.plan()
        assert top in p["eligible"]

    def test_a_dry_run_changes_nothing(self, dsns, console, admin):
        out, top = _an_approval(console, admin)
        result = undo.undo_approval(out["decision_id"], dry_run=True)
        assert [u["candidate_id"] for u in result["undone"]] == [top]
        assert result["follow_up_decision_id"] is None
        c = console.execute("SELECT disposition FROM candidates WHERE id=%s",
                            (top,)).fetchone()
        assert c["disposition"] == "APPROVED"


class TestTheLogIsNotTidied:
    def test_the_original_decision_survives_untouched(
            self, dsns, console, admin):
        """§0: the decided_via='unattended' rows stay as the record of the
        period when this was on. A log that can be tidied afterwards is not a
        record."""
        out, _ = _an_approval(console, admin)
        before = console.execute(
            "SELECT decision, reason, decided_via, mechanics FROM decision_log"
            " WHERE id=%s", (out["decision_id"],)).fetchone()

        undo.undo_approval(out["decision_id"], reason="the ranking was wrong")

        after = console.execute(
            "SELECT decision, reason, decided_via, mechanics FROM decision_log"
            " WHERE id=%s", (out["decision_id"],)).fetchone()
        assert after == before

    def test_a_second_decision_records_the_undo_and_cites_the_first(
            self, dsns, console, admin):
        out, top = _an_approval(console, admin)
        result = undo.undo_approval(out["decision_id"],
                                    reason="the ranking was wrong")
        row = console.execute(
            "SELECT decision, reason, evidence, decided_by FROM decision_log"
            " WHERE id=%s", (result["follow_up_decision_id"],)).fetchone()
        assert row["decision"] == "REJECTED"
        assert "the ranking was wrong" in row["reason"]
        assert f"Undoing decision {out['decision_id']}" in row["reason"]
        kinds = {(e["kind"], e["id"]) for e in row["evidence"]}
        assert ("decision", out["decision_id"]) in kinds
        assert ("candidate", top) in kinds
        # The login again, never a person's name.
        writer = console.execute("SELECT current_user AS u").fetchone()["u"]
        assert row["decided_by"] == writer

    def test_no_reason_is_recorded_as_no_reason_rather_than_invented(
            self, dsns, console, admin):
        out, _ = _an_approval(console, admin)
        result = undo.undo_approval(out["decision_id"])
        row = console.execute("SELECT reason FROM decision_log WHERE id=%s",
                              (result["follow_up_decision_id"],)).fetchone()
        assert "no reason typed" in row["reason"]


class TestOnceItHasStarted:
    def test_a_claimed_task_is_kept_and_said_so_rather_than_undone(
            self, dsns, console, admin, runner):
        """Past the claim the GBP 2 is committed and a branch exists. This
        reports what it could not do instead of a clean undo over a task that
        is already running."""
        out, top = _an_approval(console, admin)
        task_id = out["queued_task_ids"][0]
        runner.execute("UPDATE tasks SET status='RUNNING', claimed_at=now()"
                       " WHERE id=%s", (task_id,))
        runner.commit()

        with pytest.raises(undo.UndoRefused, match="RUNNING"):
            undo.undo_approval(out["decision_id"])

        c = console.execute("SELECT disposition FROM candidates WHERE id=%s",
                            (top,)).fetchone()
        assert c["disposition"] == "APPROVED", "nothing was changed"

    def test_an_unknown_decision_is_refused(self, dsns, console, admin):
        with pytest.raises(undo.UndoRefused, match="no decision"):
            undo.undo_approval(999999)

    def test_undoing_twice_says_it_has_already_been_undone(
            self, dsns, console, admin):
        out, _ = _an_approval(console, admin)
        undo.undo_approval(out["decision_id"])
        with pytest.raises(undo.UndoRefused, match="already have been undone"):
            undo.undo_approval(out["decision_id"])
