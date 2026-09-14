"""Retiring a candidate the tree has already answered. 043, console/retire.py.

THE POOL ONLY EVER GREW. 24 candidates considered on 14 Sep 2026, none
approved, and eight of the twenty held were finished work re-ranked and
re-refused nightly. `probes_failed` is the same word for "somebody did this"
and "the ground this stood on has gone", and only the first is a retirement.

These tests are mostly about the SECOND one: the ways a failing probe must not
be read as done.
"""
from __future__ import annotations

import types

import psycopg
import pytest

from console import rank, retire


# ---- the direction of a failing probe --------------------------------------

class TestWhichFailuresMeanTheWorkLanded:

    @pytest.mark.parametrize("kind,arg,absence", [
        ("path_absent", "platform/app/x/route.ts", True),
        ("path_exists", "api/analytics/routes/orders.py", False),
        ("grep_count", {"glob": "a.py", "pattern": "x", "expected": 0}, True),
        ("grep_count", {"glob": "a.py", "pattern": "x", "expected": 1}, False),
        ("grep_count", {"glob": "a.py", "pattern": "x"}, False),
        ("grep_count", {"glob": "a.py", "pattern": "x", "expected": "0"}, False),
    ])
    def test_only_a_claim_of_absence_can_be_answered_by_presence(
            self, kind, arg, absence):
        assert retire._asserts_absence(kind, arg) is absence

    def test_a_missing_expected_is_not_guessed(self):
        """`expected` absent is neither claim. Guessing is how a row gets
        retired on a probe nobody can read."""
        assert retire._asserts_absence("grep_count", {"glob": "a.py"}) is False


# ---- classify --------------------------------------------------------------

def _stub(monkeypatch, results):
    """A shape-check module whose run_probe returns what the test says.

    The real one reads the platform checkout, which makes every branch here
    depend on what shipped this week -- the expiry-dated fixture
    tests/test_autoapprove.py warns about at PLATFORM_FEATURE_MISSING.
    """
    calls = iter(results)
    mod = types.SimpleNamespace(
        REPOS={"deadly-digital-platform": "/nonexistent"},
        run_probe=lambda repo, probe: next(calls))
    monkeypatch.setattr(rank, "_shape_check", lambda: mod)
    return mod


ABSENT = {"path_absent": "platform/app/api/x/route.ts"}
PRESENT = {"path_exists": "api/analytics/routes/orders.py"}
COUNT0 = {"grep_count": {"glob": "a.py", "pattern": "x", "expected": 0}}


class TestClassify:

    def _c(self, probes):
        return {"id": 1, "repo": "deadly-digital-platform", "probes": probes}

    def test_every_absence_probe_now_finding_presence_retires(self, monkeypatch):
        _stub(monkeypatch, [(False, "path_absent: x exists"),
                            (False, "grep_count ... = 18, expected 0")])
        v = retire.classify(self._c([ABSENT, COUNT0]))
        assert v["retire"] is True
        assert "finds it present" in v["why"]

    def test_a_row_whose_probes_all_hold_is_live_work(self, monkeypatch):
        _stub(monkeypatch, [(True, "ok"), (True, "ok")])
        v = retire.classify(self._c([ABSENT, COUNT0]))
        assert v["retire"] is False
        assert "has not been done" in v["why"]

    def test_a_ground_moved_failure_is_not_a_retirement(self, monkeypatch):
        """`expected 1, found 0` -- what the work RESTS ON has gone. Reading
        that as done is reading "my premise is broken" as "my job is done"."""
        _stub(monkeypatch, [(False, "grep_count ... = 0, expected 1")])
        v = retire.classify(self._c([PRESENT]))
        assert v["retire"] is False
        assert "ground moved" in v["why"]

    def test_one_of_each_is_not_settled(self, monkeypatch):
        """c23 and c32 tonight: the export route now exists AND a count they
        rested on moved. EVERY failing probe must be shipped-shaped."""
        _stub(monkeypatch, [(False, "path_absent: x exists"),
                            (False, "grep_count ... = 2, expected 1")])
        v = retire.classify(self._c([ABSENT, PRESENT]))
        assert v["retire"] is False
        assert "1 of 2" in v["why"]

    def test_no_probes_cannot_have_been_answered(self, monkeypatch):
        _stub(monkeypatch, [])
        v = retire.classify(self._c([]))
        assert v["retire"] is False
        assert "no probes" in v["why"]

    def test_a_repo_this_host_does_not_have_is_not_a_retirement(
            self, monkeypatch):
        _stub(monkeypatch, [])
        v = retire.classify({"id": 1, "repo": "not-a-repo", "probes": [ABSENT]})
        assert v["retire"] is False
        assert "not one this host has" in v["why"]


# ---- 043, at the database --------------------------------------------------

class TestTheDatabaseRequiresTheEvidence:
    """A retirement nobody can check is a row that vanished."""

    @pytest.fixture
    def cid(self, dsns, console) -> int:
        """A PENDING row, SEEDED rather than found.

        It skipped on the seeded database, so 043's trigger had no test that
        could fail -- which is the defect principles.md names under "a check
        that has never had the chance to fail". The helpers come from
        tests/test_autoapprove.py rather than being written again here: a
        second way to build a candidate is a second thing to keep in step with
        the triggers.
        """
        from tests.test_autoapprove import _batch, _cand
        return _cand(console, _batch(console))

    def test_shipped_without_a_reason_is_refused(self, console, cid):
        with pytest.raises(psycopg.errors.RaiseException,
                           match="cannot be SHIPPED with no reason"):
            console.execute(
                "UPDATE candidates SET disposition='SHIPPED' WHERE id=%s",
                (cid,))
        console.rollback()

    def test_whitespace_is_not_a_reason(self, console, cid):
        with pytest.raises(psycopg.errors.RaiseException):
            console.execute(
                "UPDATE candidates SET disposition='SHIPPED',"
                " disposition_reason='   ' WHERE id=%s", (cid,))
        console.rollback()

    def test_shipped_with_the_probe_that_answered_it_is_accepted(
            self, console, cid):
        console.execute(
            "UPDATE candidates SET disposition='SHIPPED',"
            " disposition_reason=%s, decided_at=now() WHERE id=%s",
            ("path_absent: platform/app/api/x/route.ts exists", cid))
        got = console.execute(
            "SELECT disposition FROM candidates WHERE id=%s", (cid,)).fetchone()
        assert got["disposition"] == "SHIPPED"
        console.rollback()

    def test_the_four_older_dispositions_survived_the_rewrite(self, console):
        """040 deleted three migrations' checks by rebuilding from an old
        copy. 043 rewrites a CHECK constraint, which is the same hazard.

        READ RATHER THAN EXERCISED, because APPROVED and NOT_NOW each carry
        their own constraints -- a decision id, a stamp -- and an UPDATE that
        trips one of those proves nothing about the vocabulary.
        """
        defn = console.execute(
            "SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint"
            " WHERE conname = 'candidates_disposition_check'").fetchone()["d"]
        for d in ("PENDING", "APPROVED", "NOT_NOW", "REJECTED", "SHIPPED"):
            assert d in defn, d

    def test_shipped_must_carry_a_stamp_like_every_other_decision(
            self, console, cid):
        """Inherited, not added: `candidates_decided_is_stamped_ck` is
        `(disposition = 'PENDING') = (decided_at IS NULL)`, so SHIPPED needs
        the stamp and console/undo.py's `decided_at=NULL` still returns it to
        the pool. A new disposition that slipped past that would be a row
        nothing could take back."""
        with pytest.raises(psycopg.errors.CheckViolation):
            console.execute(
                "UPDATE candidates SET disposition='SHIPPED',"
                " disposition_reason='x' WHERE id=%s", (cid,))
        console.rollback()
