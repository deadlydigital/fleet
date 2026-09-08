"""The approval surface: ticked candidates become queued draft-spec tasks.

specs/approval-surface.md. What these protect, in one line each:

  a tick makes a DRAFT SPEC, never a code task    -> TestATickMakesADraftSpec
  the reason is about the selection, once         -> TestTheBatchReason
  rejections are kept and say why                 -> TestRejectionsAreTheHalfThatMatters
  NOT_NOW is not a rejection and is not discarded -> TestNotNowIsCarried
  the ceilings hold, and they replace the human   -> TestTheCeilings
"""
from __future__ import annotations

import json

import pytest

from console import approve


def _batch(console, doc="specs/metorik-gap.md", sha="deadbee") -> int:
    row = console.execute(
        "INSERT INTO candidate_batches (source_document, source_sha, source_repo)"
        " VALUES (%s,%s,'fleet') RETURNING id", (doc, sha)).fetchone()
    console.commit()
    return row["id"]


def _cand(console, batch_id, title="Do the thing", repo="deadly-digital-platform",
          paths=None) -> int:
    row = console.execute(
        "INSERT INTO candidates (batch_id, title, rationale, repo,"
        " suggested_paths, evidence) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
        (batch_id, title, "because the finding said so", repo,
         paths or ["platform/lib/api-auth.ts"],
         json.dumps([{"kind": "document", "path": "specs/metorik-gap.md",
                      "read_at_sha": "deadbee"}]))).fetchone()
    console.commit()
    return row["id"]


class TestATickMakesADraftSpec:
    def test_a_tick_queues_a_draft_spec_and_not_a_code_task(self, console, dsns):
        b = _batch(console)
        cid = _cand(console, b)

        out = approve.approve_batch(
            reason="this is what first onboarding is blocked on",
            approve_ids=[cid], reject={}, not_now_ids=[], decided_by="test")

        assert len(out["queued_task_ids"]) == 1
        task = console.execute(
            "SELECT title, status, acceptance_contract, spec_md FROM tasks"
            " WHERE id=%s", (out["queued_task_ids"][0],)).fetchone()
        assert task["status"] == "QUEUED"
        # THE assertion: a tick does not produce a code task.
        assert task["acceptance_contract"]["work_type"] == "draft_spec"
        assert task["title"].startswith("Draft spec:")
        # And the agent is told what the check will refuse, because a check the
        # agent cannot see is a gate it fails by accident.
        assert "does not resolve" in task["spec_md"]
        assert "You choose the `work_type`" in task["spec_md"]

    def test_the_candidate_records_which_task_it_produced(self, console):
        b = _batch(console)
        cid = _cand(console, b)
        out = approve.approve_batch(reason="r", approve_ids=[cid], reject={},
                                    not_now_ids=[], decided_by="test")
        c = console.execute("SELECT disposition, spec_task_id,"
                            " approval_decision_id FROM candidates WHERE id=%s",
                            (cid,)).fetchone()
        assert c["disposition"] == "APPROVED"
        assert c["spec_task_id"] == out["queued_task_ids"][0]
        assert c["approval_decision_id"] is not None


class TestTheBatchReason:
    def test_one_reason_covers_the_batch_and_lands_in_decision_log(self, console):
        b = _batch(console)
        ids = [_cand(console, b, f"item {i}") for i in range(3)]
        reason = "these three are the reconciliation blockers"

        approve.approve_batch(reason=reason, approve_ids=ids, reject={},
                              not_now_ids=[], decided_by="test")

        rows = console.execute(
            "SELECT reason, evidence FROM decision_log WHERE decided_by='test'"
        ).fetchall()
        # ONE row, not three. Three paraphrases of "yes" would satisfy the NOT
        # NULL while emptying the column.
        assert len(rows) == 1
        assert rows[0]["reason"] == reason
        assert len(rows[0]["evidence"]) == 3

    def test_a_batch_with_no_reason_is_refused(self, console):
        b = _batch(console)
        cid = _cand(console, b)
        with pytest.raises(approve.ApprovalRefused, match="SELECTION"):
            approve.approve_batch(reason="   ", approve_ids=[cid], reject={},
                                  not_now_ids=[], decided_by="test")


class TestRejectionsAreTheHalfThatMatters:
    def test_a_rejection_is_kept_with_its_reason(self, console):
        b = _batch(console)
        cid = _cand(console, b)
        approve.approve_batch(reason="r", approve_ids=[], not_now_ids=[],
                              reject={cid: "the gap list is wrong about this"},
                              decided_by="test")
        c = console.execute("SELECT disposition, disposition_reason FROM"
                            " candidates WHERE id=%s", (cid,)).fetchone()
        assert c["disposition"] == "REJECTED"
        assert "wrong about this" in c["disposition_reason"]

    def test_a_rejection_without_a_reason_is_refused(self, console):
        b = _batch(console)
        cid = _cand(console, b)
        with pytest.raises(approve.ApprovalRefused, match="informative half"):
            approve.approve_batch(reason="r", approve_ids=[], not_now_ids=[],
                                  reject={cid: "  "}, decided_by="test")


class TestNotNowIsCarried:
    def test_not_now_keeps_its_batch_and_stays_reviewable(self, console):
        b = _batch(console)
        cid = _cand(console, b)
        approve.approve_batch(reason="r", approve_ids=[], reject={},
                              not_now_ids=[cid], decided_by="test")
        c = console.execute("SELECT disposition, batch_id, disposition_reason"
                            " FROM candidates WHERE id=%s", (cid,)).fetchone()
        # Not a rejection: no reason demanded, and it keeps its ORIGINAL batch
        # so the number of times it has been passed over stays visible.
        assert c["disposition"] == "NOT_NOW"
        assert c["batch_id"] == b
        assert c["disposition_reason"] is None


class TestTheCeilings:
    def test_ticking_past_the_batch_cap_is_refused(self, console):
        b = _batch(console)
        cap = console.execute("SELECT fleet_max_approval_batch() AS n"
                              ).fetchone()["n"]
        ids = [_cand(console, b, f"c{i}") for i in range(cap + 1)]
        with pytest.raises(approve.ApprovalRefused, match="cap"):
            approve.approve_batch(reason="r", approve_ids=ids, reject={},
                                  not_now_ids=[], decided_by="test")

    def test_a_full_queue_refuses_the_batch_rather_than_half_queueing_it(
        self, console
    ):
        """The refusal is whole. Half a batch queued would leave candidates
        approved with nothing to build them, which is a state nobody tracks."""
        b = _batch(console)
        depth = console.execute("SELECT fleet_max_queued_tasks() AS n"
                                ).fetchone()["n"]
        floor = console.execute(
            "SELECT jsonb_agg(glob) AS g FROM protected_path_floor"
            " WHERE repo='fleet'").fetchone()["g"]
        contract = json.dumps({
            "work_type": "research", "writable_paths": ["research/x.md"],
            "protected_paths": floor, "verification": ["true"],
            "max_diff_lines": 10})
        for i in range(depth):
            console.execute(
                "INSERT INTO tasks (title, spec_md, repo, acceptance_contract,"
                " max_cost_gbp) VALUES (%s,'x','fleet',%s,1.0)",
                (f"filler {i}", contract))
        console.commit()

        cid = _cand(console, b)
        with pytest.raises(approve.ApprovalRefused, match="QUEUED"):
            approve.approve_batch(reason="r", approve_ids=[cid], reject={},
                                  not_now_ids=[], decided_by="test")
        # Nothing half-written: the candidate is still open for decision.
        c = console.execute("SELECT disposition FROM candidates WHERE id=%s",
                            (cid,)).fetchone()
        assert c["disposition"] == "PENDING"


class TestTheMonthlyCredit:
    """The third ceiling (spec §6 ceiling 2, built in 014).

    The pool is not readable from this host, so the figure is recorded by hand.
    Everything here is about what happens when it is absent, wrong, or nearly
    used up — a ceiling only ever fails by permitting.
    """

    def _pool(self, admin, gbp, source="test"):
        admin.execute("DELETE FROM model_credit_pool"
                      " WHERE period_month = date_trunc('month', now())::date")
        if gbp is not None:
            admin.execute(
                "INSERT INTO model_credit_pool (period_month, pool_gbp, source,"
                " read_at) VALUES (date_trunc('month', now())::date,%s,%s,now())",
                (gbp, source))

    def test_no_reading_refuses_the_batch_rather_than_assuming_a_number(
        self, console, admin
    ):
        """The one that matters. An absent pool is a refusal, never a default.

        This is where the design differs from the brief, which prints the AWS
        figure as UNCOMPUTED and lets a reader supply the judgement. A ceiling
        is consulted when nobody is reading, so it has nothing to fall back on.
        """
        self._pool(admin, None)
        b = _batch(console)
        cid = _cand(console, b)

        with pytest.raises(approve.ApprovalRefused, match="unknown"):
            approve.approve_batch(reason="r", approve_ids=[cid], reject={},
                                  not_now_ids=[], decided_by="test")

        # Whole, like every other refusal here: nothing half-written.
        c = console.execute("SELECT disposition FROM candidates WHERE id=%s",
                            (cid,)).fetchone()
        assert c["disposition"] == "PENDING"

    def test_an_unknown_pool_reports_no_figures_at_all(self, console, admin):
        """UNCOMPUTED carries a reason and NULLs, not a reason and a zero.

        Zero is a number; every comparison against it quietly succeeds. NULL
        makes a caller that forgot to check the status get a refusal it did not
        write rather than an approval it did not mean.
        """
        self._pool(admin, None)
        k = console.execute("SELECT * FROM fleet_month_credit()").fetchone()
        assert k["status"] == "UNCOMPUTED"
        assert k["pool_gbp"] is None
        assert k["remaining_gbp"] is None
        assert k["uncomputed_reason"]
        # committed is derivable and is still reported: what is missing is the
        # pool, not the spend, and blanking both would hide a real figure.
        assert k["committed_gbp"] is not None

    def test_a_batch_beyond_the_remaining_credit_is_refused(self, console, admin):
        committed = console.execute(
            "SELECT fleet_month_committed_gbp() AS n").fetchone()["n"]
        # Room for one draft-spec task at £2.00, and not for two.
        self._pool(admin, committed + 3)
        b = _batch(console)
        ids = [_cand(console, b, "one"), _cand(console, b, "two")]

        with pytest.raises(approve.ApprovalRefused, match="remains"):
            approve.approve_batch(reason="r", approve_ids=ids, reject={},
                                  not_now_ids=[], decided_by="test")

        assert console.execute(
            "SELECT count(*) AS n FROM tasks WHERE title LIKE 'Draft spec:%'"
        ).fetchone()["n"] == 0

    def test_a_batch_within_the_remaining_credit_is_queued(self, console, admin):
        committed = console.execute(
            "SELECT fleet_month_committed_gbp() AS n").fetchone()["n"]
        self._pool(admin, committed + 3)
        b = _batch(console)
        out = approve.approve_batch(
            reason="one task fits", approve_ids=[_cand(console, b)], reject={},
            not_now_ids=[], decided_by="test")
        assert len(out["queued_task_ids"]) == 1

    def test_a_queued_task_is_committed_money_before_it_spends_any(
        self, console, admin
    ):
        """The window the whole ceiling exists for.

        Five approved tasks have no model_calls and no reservations. A pool
        checked against spend alone would approve five more, and the first
        evidence would be the bill.
        """
        self._pool(admin, 10000)
        before = console.execute(
            "SELECT fleet_month_committed_gbp() AS n").fetchone()["n"]
        b = _batch(console)
        approve.approve_batch(reason="r", approve_ids=[_cand(console, b)],
                              reject={}, not_now_ids=[], decided_by="test")
        after = console.execute(
            "SELECT fleet_month_committed_gbp() AS n").fetchone()["n"]

        # £2.00 is the draft-spec contract's max_cost_gbp, and it is what a
        # task reserves — not an estimate of what it will probably cost.
        assert round(after - before, 2) == 2.00

    def test_the_ceiling_is_on_tasks_and_not_only_in_the_surface(
        self, console, admin
    ):
        """A direct insert is refused too.

        approve_batch() only makes draft-spec tasks, so code tasks are inserted
        directly — that has already happened on this host. A ceiling that only
        the surface respected would not have been consulted at all.
        """
        self._pool(admin, None)
        floor = console.execute(
            "SELECT jsonb_agg(glob) AS g FROM protected_path_floor"
            " WHERE repo='fleet'").fetchone()["g"]
        contract = json.dumps({
            "work_type": "research", "writable_paths": ["research/x.md"],
            "protected_paths": floor, "verification": ["true"],
            "max_diff_lines": 10})
        with pytest.raises(Exception, match="credit is unknown"):
            console.execute(
                "INSERT INTO tasks (title, spec_md, repo, acceptance_contract,"
                " max_cost_gbp) VALUES ('direct','x','fleet',%s,0.01)",
                (contract,))

    def test_the_spending_identity_cannot_write_its_own_ceiling(self, console):
        """Same rule as a runner that cannot set MERGED on its own branch."""
        p = console.execute(
            "SELECT has_table_privilege('fleet_console','model_credit_pool','SELECT') AS r,"
            " has_table_privilege('fleet_console','model_credit_pool','INSERT') AS w,"
            " has_table_privilege('fleet_console','model_credit_pool','UPDATE') AS u"
        ).fetchone()
        assert p["r"] is True
        assert p["w"] is False and p["u"] is False
