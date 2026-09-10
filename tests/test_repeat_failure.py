"""The repeat-failure ceiling, and the two ways it was counting the wrong thing.

027 and specs/auto-approval.md §9.2. The defect these exist for is not a bug in
a branch; it is a SAFETY CONTROL THAT COULD NEVER FIRE, and it read as working
for two batches because "0 prior failures" and "we cannot tell" print the same.

    c14  "Coupon and discount performance report"                 -> 1
    c28  "Coupon and discount performance report, over a column
          that is already populated"                              -> 0

One row of one findings document, eleven days apart, retitled by a producer
that is FORBIDDEN to deduplicate. The stop fires at 2 and the count restarted
at 0 every batch.

    the identity survives a retitle and a new batch  -> TestTheIdentity
    an attempt is not the same thing as a status     -> TestWhatCountsAsAFailure
    the count, and the ceiling firing at 2           -> TestTheCount
    one task cannot be counted twice                 -> TestNoDoubleCounting
    the record is not rewritten to make a number     -> TestHistoryIsNotEdited
    the dry run and the real run ask ONE predicate   -> TestOnePredicate
    a title-keyed count fails these on purpose       -> TestMutationOfTheIdentity

THE THRESHOLD IS NOT UNDER TEST HERE and is not changed by any of this. It is
2, it is console/approve.py's, and 027 changed what is counted rather than how
many are allowed.
"""
from __future__ import annotations

import json

import pytest

from console import approve, autoapprove, db, rank, work_key

#: The real findings document, at the two real shas batches 8 and 9 cite. Not a
#: fixture: the whole claim is that two DIFFERENT quotations of one heading in
#: one real document resolve to one row, and a fixture document written for
#: this test would be a fixture written to agree with the resolver.
DOC = "specs/metorik-gap.md"
SHA_BATCH_8 = "73dc37fac0f57eb39b0bd6d5a82297d2b8034e46"
SHA_BATCH_9 = "b198634063e5f9e3fc17467a6b6fe361013cfee3"

#: The two spellings, verbatim from candidates 14 and 28 in production.
SECTION_8 = "Weekly — coupon and discount performance"
SECTION_9 = ("Weekly — Coupon and discount performance: usage, discount total, "
             "orders, AOV with/without")

PLATFORM = "deadly-digital-platform"
EXISTS = {"path_exists": "api/analytics/routes/orders.py"}


# ---- arranging history -----------------------------------------------------

def _producer_task(console) -> int:
    """A candidate_producer task, so a batch can point at one.

    Since 034 `console/rank.py` gate 2 supersedes only against a batch a
    producer run made, and every batch here stands for one the loader would
    have created from a produced document. Left NULL, gate 2 would stop
    firing and rows held by it would report a later rule instead -- which is
    what happened to this file's repeat counts before the fixture was fixed.
    See the note at the top of tests/conftest.py.
    """
    floor = console.execute(
        "SELECT jsonb_agg(glob) AS g FROM protected_path_floor"
        " WHERE repo='fleet'").fetchone()["g"]
    contract = json.dumps({
        "work_type": "candidate_producer",
        "writable_paths": ["research/produced.md"],
        "protected_paths": floor, "verification": ["true"],
        "max_diff_lines": 10})
    row = console.execute(
        "INSERT INTO tasks (title, spec_md, repo, acceptance_contract,"
        " max_cost_gbp) VALUES ('produce','x','fleet',%s,1.0) RETURNING id",
        (contract,)).fetchone()
    console.commit()
    return row["id"]


def _batch(console, doc=DOC, sha=SHA_BATCH_9) -> int:
    row = console.execute(
        "INSERT INTO candidate_batches (source_document, source_sha,"
        " source_repo, produced_by_task_id)"
        " VALUES (%s,%s,'fleet',%s) RETURNING id",
        (doc, sha, _producer_task(console))).fetchone()
    console.commit()
    return row["id"]


def _cand(console, batch_id, *, title, section=None, sha=SHA_BATCH_9,
          band="weekly", repo=PLATFORM, probes=None, paths=None,
          document=DOC) -> int:
    """One candidate, keyed the way console/load_candidates.py keys one.

    The key is derived by the REAL derivation rather than typed, so a test that
    passes cannot be passing against a key this file invented.
    """
    evidence = ([{"kind": "document", "document": document, "repo": "fleet",
                  "sha": sha, "section": section}] if section else [])
    key = work_key.derive({"repo": repo, "evidence": evidence})["key"]
    row = console.execute(
        "INSERT INTO candidates (batch_id, title, rationale, repo, band,"
        " probes, suggested_paths, evidence, work_key)"
        " VALUES (%s,%s,'because the finding said so',%s,%s,%s,%s,%s,%s)"
        " RETURNING id",
        (batch_id, title, repo, band,
         json.dumps(probes if probes is not None else [EXISTS]),
         paths or [], json.dumps(evidence), key)).fetchone()
    console.commit()
    return row["id"]


def _failed_task(admin, *, title="Draft spec: something", verification="FAIL",
                 repo="fleet", status="FAILED") -> int:
    """A FAILED task, and the verdict its acceptance check recorded.

    `verification` is 'FAIL', 'PASS', or None for a task that died before it
    reached verification at all -- which is a real state on this host and the
    one specs/auto-approval.md §9.3 says the database cannot explain.
    """
    # The REAL draft-spec contract, read the way approve.py reads it. 003's
    # protected-path floor refuses a fleet task whose contract does not protect
    # the migrations, the contracts and the suite, and a contract invented here
    # to get past that would be a fixture that proves the floor is off.
    contract, _, _, _ = approve._draft_spec_contract()
    tid = admin.execute(
        "INSERT INTO tasks (title, spec_md, repo, acceptance_contract,"
        " max_cost_gbp, status) VALUES (%s,'spec',%s,%s,2.00,%s)"
        " RETURNING id",
        (title, repo, json.dumps(contract), status)).fetchone()["id"]
    rid = admin.execute(
        "INSERT INTO runs (task_id, work_type, contract_version,"
        " spend_limit_gbp, status) VALUES (%s,'draft_spec',1,2.00,'FAILED')"
        " RETURNING id", (tid,)).fetchone()["id"]
    base, patch = "a" * 40, "b" * 40
    admin.execute(
        "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
        " VALUES (%s,1,'PATCH_PROPOSED','fleet-runner/agent',%s)",
        (rid, json.dumps({"base_commit_sha": base, "patch_commit_sha": patch,
                          "files_changed": [], "derived_by": "runner"})))
    if verification is not None:
        # A PASS carries its provenance because 001's acceptance boundary makes
        # it: `boundary_clean` must be verifier-derived and the diff shas must
        # match the proposal. That is the trigger doing its job, and a fixture
        # that shortcut it would be arranging a PASS the runner could not.
        payload = {"result": verification}
        if verification == "PASS":
            payload.update({"boundary_clean": True, "base_commit_sha": base,
                            "patch_commit_sha": patch,
                            "suite_commit_sha": "s" * 40, "contract_version": 1})
        admin.execute(
            "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
            " VALUES (%s,2,'VERIFICATION_RUN','fleet-runner/verifier',%s)",
            (rid, json.dumps(payload)))
    admin.commit()
    return tid


def _attach(admin, candidate_id, task_id, *, column="spec_task_id") -> None:
    """Link an attempt to the candidate it came from, as approve_batch does."""
    admin.execute(f"UPDATE candidates SET {column}=%s WHERE id=%s",
                  (task_id, candidate_id))
    admin.commit()


def _fails(conn, candidate_id) -> int:
    return conn.execute("SELECT candidate_prior_failures(%s) AS n",
                        (candidate_id,)).fetchone()["n"]


def _identity(conn, candidate_id) -> str:
    return conn.execute("SELECT candidate_work_identity(%s) AS k",
                        (candidate_id,)).fetchone()["k"]


def _pool(admin, gbp="158.00"):
    # Pace pinned with the pool. These tests build two tied candidates and
    # expect the night to refuse; that needs a cut of 1 to have a top two at
    # all. 029 raised the deployed pace to 3 and they began approving both.
    from tests.test_autoapprove import _pace
    _pace(admin, 1)
    admin.execute("DELETE FROM model_credit_pool"
                  " WHERE period_month = date_trunc('month', now())::date")
    admin.execute(
        "INSERT INTO model_credit_pool (period_month, pool_gbp, source, read_at)"
        " VALUES (date_trunc('month', now())::date, %s, 'test fixture', now())",
        (gbp,))
    admin.commit()


# ---- the identity ----------------------------------------------------------

class TestTheIdentity:
    """A: same title, new id. B: retitled, new batch. D: similar words, not it."""

    def test_the_two_spellings_of_one_heading_resolve_to_one_row(self):
        """The whole fix, without a database: c14's heading and c28's are one row.

        Batch 8 quoted the heading short and batch 9 quoted the cell verbatim.
        Neither is compared to the other -- both are resolved against the
        document at the sha they cite -- and they land on the same row.
        """
        a = work_key.derive({"repo": PLATFORM, "evidence": [
            {"document": DOC, "repo": "fleet", "sha": SHA_BATCH_8,
             "section": SECTION_8}]})
        b = work_key.derive({"repo": PLATFORM, "evidence": [
            {"document": DOC, "repo": "fleet", "sha": SHA_BATCH_9,
             "section": SECTION_9}]})
        assert a["kind"] == b["kind"] == "row"
        assert a["key"] == b["key"]
        assert "coupon-and-discount-performance" in a["key"]

    def test_the_batch_8_spelling_of_evidence_keys_too(self):
        """`path` and `read_at_sha`, which is how the hand-loaded batch wrote it.

        Reading only the current spelling would key batch 9 and leave the batch
        it is a repeat OF unkeyed, which is exactly the row that has to match.
        """
        old = work_key.derive({"repo": PLATFORM, "evidence": [
            {"kind": "document", "path": DOC, "repo": "fleet",
             "read_at_sha": SHA_BATCH_8, "section": SECTION_8}]})
        new = work_key.derive({"repo": PLATFORM, "evidence": [
            {"document": DOC, "repo": "fleet", "sha": SHA_BATCH_9,
             "section": SECTION_9}]})
        assert old["key"] == new["key"]

    def test_A_same_work_same_title_new_candidate_id(self, dsns, console, admin):
        """A. A fresh row for identical work still sees the earlier failure."""
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        first = _cand(console, old, title="Coupon report", section=SECTION_8,
                      sha=SHA_BATCH_8)
        _attach(admin, first, _failed_task(admin, verification="FAIL"))
        second = _cand(console, new, title="Coupon report", section=SECTION_9)

        with db.connect() as conn:
            assert _identity(conn, first) == _identity(conn, second)
            assert _fails(conn, second) == 1

    def test_B_same_work_retitled_in_a_new_producer_batch(self, dsns, console,
                                                          admin):
        """B. THE DEMONSTRATED CASE. c14 and c28, reproduced.

        Different candidate id, different batch, different title, different
        heading spelling, different sha. One row of one document, and the count
        crosses all five.
        """
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        c14 = _cand(console, old, title="Coupon and discount performance report",
                    section=SECTION_8, sha=SHA_BATCH_8, band=None)
        _attach(admin, c14, _failed_task(
            admin, title="Draft spec: Coupon and discount performance report",
            verification="FAIL"))
        c28 = _cand(console, new, section=SECTION_9, title=(
            "Coupon and discount performance report, over a column that is "
            "already populated"))

        with db.connect() as conn:
            assert _fails(conn, c14) == 1
            # 0 before 027, on a title nobody typed twice.
            assert _fails(conn, c28) == 1

    def test_D_similar_wording_over_different_work_is_not_counted(
            self, dsns, console, admin):
        """D. Two headings that read alike and name different document rows.

        "CSV export of orders / customers / products" and "Export with chosen
        columns, reordered, incl. custom fields" share four words and are two
        rows of the gap list. specs/auto-approval.md §1.5 calls the second a
        SUBSET of the first -- which is a reason for the overlap gate to hold
        one of them, and not a reason for the ceiling to charge one with the
        other's failure.
        """
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        exporting = _cand(console, old, title="CSV export of the order list",
                          section="Daily — CSV export", sha=SHA_BATCH_8)
        _attach(admin, exporting, _failed_task(admin, verification="FAIL"))
        columns = _cand(console, new, band="daily",
                        title="Export with chosen columns rather than a fixed header",
                        section="Daily — export with chosen columns",
                        sha=SHA_BATCH_8)

        with db.connect() as conn:
            assert _identity(conn, exporting) != _identity(conn, columns)
            assert _fails(conn, exporting) == 1
            assert _fails(conn, columns) == 0

    def test_an_ambiguous_heading_resolves_to_nothing_rather_than_to_the_longer(self):
        """Two rows match and neither is chosen. Merging is the expensive error."""
        rows = ["refund-reports-refund-rate-over-time",
                "refund-reports-by-country-and-region"]
        assert work_key.resolve("refund-reports", rows) is None
        # ... and an exact quotation is never ambiguous.
        assert work_key.resolve(rows[0], rows) == rows[0]

    def test_an_unkeyable_candidate_falls_back_and_never_counts_zero_silently(
            self, dsns, console, admin):
        """NULL work_key is 022's behaviour, not a free pass.

        This is the property that makes 027 safe to deploy over a table where
        every existing row has a NULL: the ceiling degrades to matching titles,
        which is what it did yesterday, rather than degrading to counting
        nothing.
        """
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        a = _cand(console, old, title="Unkeyable work", section=None)
        _attach(admin, a, _failed_task(admin, verification="FAIL"))
        b = _cand(console, new, title="Unkeyable work", section=None)

        with db.connect() as conn:
            assert conn.execute(
                "SELECT work_key FROM candidates WHERE id=%s",
                (b,)).fetchone()["work_key"] is None
            assert _identity(conn, b).startswith("title::")
            assert _fails(conn, b) == 1


# ---- what counts as a failure ----------------------------------------------

class TestWhatCountsAsAFailure:
    """E. FAILED is a status. An unsuccessful attempt is an outcome."""

    def test_a_failed_task_that_passed_verification_is_not_an_attempt(
            self, dsns, console, admin):
        """Task 21's shape: draft_spec_shape.py exit 0, task FAILED, promoted.

        specs/auto-approval.md §9.3: a task that fails AFTER verification writes
        no reason anywhere, so `tasks.status` alone cannot separate this from a
        real failure. The verification verdict can.
        """
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        first = _cand(console, old, title="Net revenue", section=SECTION_8,
                      sha=SHA_BATCH_8)
        _attach(admin, first, _failed_task(admin, verification="PASS"))
        second = _cand(console, new, title="Net revenue, retitled",
                       section=SECTION_9)

        with db.connect() as conn:
            assert _fails(conn, second) == 0

    def test_a_failed_task_that_failed_verification_is_an_attempt(
            self, dsns, console, admin):
        """Task 23's shape, which is the one c28 would have bought again."""
        old = _batch(console, sha=SHA_BATCH_8)
        first = _cand(console, old, title="Coupons", section=SECTION_8,
                      sha=SHA_BATCH_8)
        _attach(admin, first, _failed_task(admin, verification="FAIL"))
        with db.connect() as conn:
            assert _fails(conn, first) == 1

    def test_a_failed_task_that_never_reached_verification_is_an_attempt(
            self, dsns, console, admin):
        """It produced nothing. A missing verdict is not a pass.

        Treating silence as success would let a task that died before it was
        checked buy the next attempt, which is the direction that costs money.
        """
        old = _batch(console, sha=SHA_BATCH_8)
        first = _cand(console, old, title="Coupons", section=SECTION_8,
                      sha=SHA_BATCH_8)
        _attach(admin, first, _failed_task(admin, verification=None))
        with db.connect() as conn:
            assert _fails(conn, first) == 1

    def test_a_merged_task_is_not_an_attempt(self, dsns, console, admin):
        old = _batch(console, sha=SHA_BATCH_8)
        first = _cand(console, old, title="Coupons", section=SECTION_8,
                      sha=SHA_BATCH_8)
        # Inserted MERGED rather than moved there: 003's transition table has
        # no FAILED -> MERGED edge, and a test that reached for one would be
        # arranging a state the runner cannot produce.
        tid = _failed_task(admin, verification="FAIL", status="MERGED")
        _attach(admin, first, tid)
        with db.connect() as conn:
            assert _fails(conn, first) == 0

    def test_both_task_columns_count(self, dsns, console, admin):
        """022's rule, kept: a spec task and a work task are both this work.

        The first failing means the spec could not be written and the second
        that it could not be built. Either is a failure of the candidate.
        """
        old = _batch(console, sha=SHA_BATCH_8)
        first = _cand(console, old, title="Coupons", section=SECTION_8,
                      sha=SHA_BATCH_8)
        _attach(admin, first, _failed_task(admin, verification="FAIL"))
        _attach(admin, first, _failed_task(admin, verification="FAIL"),
                column="work_task_id")
        with db.connect() as conn:
            assert _fails(conn, first) == 2


# ---- the count and the ceiling ---------------------------------------------

class TestTheCount:
    """C. The second qualifying failure, and the stop firing at 2."""

    def test_C_the_ceiling_fires_at_two_across_three_batches(
            self, dsns, console, admin):
        old = _batch(console, sha=SHA_BATCH_8)
        mid = _batch(console)
        new = _batch(console)
        a = _cand(console, old, title="Coupon report", section=SECTION_8,
                  sha=SHA_BATCH_8)
        _attach(admin, a, _failed_task(admin, verification="FAIL"))
        b = _cand(console, mid, title="Coupon report, restated", section=SECTION_9)
        _attach(admin, b, _failed_task(admin, verification="FAIL"))
        c = _cand(console, new, title="Coupon report, restated again",
                  section=SECTION_9)

        with db.connect() as conn:
            n = _fails(conn, c)
        assert n == approve.REPEAT_FAILURE_STOP == 2

        held = rank.gate({"disposition": "PENDING", "batch_id": new,
                          "suggested_paths": [], "repo": PLATFORM,
                          "probes": [EXISTS], "id": c},
                         newest_batch=new, live_tasks=[], prior_failures=n)
        assert held["eligible"] is False
        assert held["rule"] == "repeat_failure"
        assert "2 unsuccessful attempt" in held["detail"]

    def test_one_failure_does_not_fire(self, dsns, console, admin):
        """The stop is at two, and two is where a repeat stops being bad luck."""
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        a = _cand(console, old, title="Coupon report", section=SECTION_8,
                  sha=SHA_BATCH_8)
        _attach(admin, a, _failed_task(admin, verification="FAIL"))
        c = _cand(console, new, title="Coupon report again", section=SECTION_9)
        with db.connect() as conn:
            n = _fails(conn, c)
        assert n == 1
        g = rank.gate({"disposition": "PENDING", "batch_id": new,
                       "suggested_paths": [], "repo": PLATFORM,
                       "probes": [EXISTS], "id": c},
                      newest_batch=new, live_tasks=[], prior_failures=n)
        assert g["eligible"] is True
        assert g["prior_failures"] == 1

    def test_approve_batch_still_refuses_at_the_ceiling(self, dsns, console,
                                                        admin):
        """The backstop, inside the approving transaction.

        The gate holds the row during ranking; this is what happens if anything
        reaches approve_batch with it anyway -- a stale plan, a console tick, a
        second caller. The ceiling is not the ranking's to keep.
        """
        _pool(admin)
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        for _ in range(2):
            a = _cand(console, old, title="Coupon report", section=SECTION_8,
                      sha=SHA_BATCH_8)
            _attach(admin, a, _failed_task(admin, verification="FAIL"))
        c = _cand(console, new, title="Coupon report, third time",
                  section=SECTION_9)

        with pytest.raises(approve.ApprovalRefused) as exc:
            approve.approve_batch(reason="because it looked good",
                                  approve_ids=[c], reject={}, not_now_ids=[],
                                  decided_by="eamonn")
        assert "unsuccessful attempt" in str(exc.value)

    def test_the_unattended_path_cannot_override_it(self, dsns, console, admin):
        """026's rule, unchanged by 027 and re-asserted against the new count.

        An override is a person saying it is different this time. There is no
        such sentence when nobody is there.
        """
        with pytest.raises(approve.ApprovalRefused) as exc:
            approve.approve_batch(reason="r", approve_ids=[1], reject={},
                                  not_now_ids=[], decided_by=None,
                                  decided_via="unattended",
                                  mechanics={"rank_version": 1},
                                  repeat_overrides={1: "it is different"})
        assert "repeat_overrides" in str(exc.value)


class TestNoDoubleCounting:
    """F. One task, reachable from two candidates, is one attempt."""

    def test_a_task_reachable_from_two_candidates_counts_once(
            self, dsns, console, admin):
        """The dedupe gate refuses the duplicate; the ceiling must not bill it twice.

        Two candidates of the same work can point at one task -- a re-emitted
        row carried forward, a NOT_NOW row later linked by hand. `count(DISTINCT
        t.id)` is what keeps the ceiling counting ATTEMPTS rather than rows.
        """
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        tid = _failed_task(admin, verification="FAIL")
        a = _cand(console, old, title="Coupon report", section=SECTION_8,
                  sha=SHA_BATCH_8)
        b = _cand(console, old, title="Coupon report, duplicate emission",
                  section=SECTION_8, sha=SHA_BATCH_8)
        _attach(admin, a, tid)
        _attach(admin, b, tid)
        c = _cand(console, new, title="Coupon report, next batch",
                  section=SECTION_9)

        with db.connect() as conn:
            assert _fails(conn, c) == 1

    def test_the_same_task_in_both_columns_counts_once(self, dsns, console,
                                                       admin):
        old = _batch(console, sha=SHA_BATCH_8)
        a = _cand(console, old, title="Coupon report", section=SECTION_8,
                  sha=SHA_BATCH_8)
        tid = _failed_task(admin, verification="FAIL")
        _attach(admin, a, tid)
        _attach(admin, a, tid, column="work_task_id")
        with db.connect() as conn:
            assert _fails(conn, a) == 1


class TestHistoryIsNotEdited:
    """G. An undo appends. Nothing here rewrites what happened."""

    def test_an_undo_leaves_the_original_decision_and_the_count_alone(
            self, dsns, console, admin):
        """specs/auto-approval.md §5, correction 4: the original row stays.

        The count is derived from `tasks` and `run_steps`, which an undo does
        not touch, so a correction cannot erase the evidence a later night
        needs -- and cannot manufacture it either.
        """
        from console import undo

        _pool(admin)
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        prior = _cand(console, old, title="Coupon report", section=SECTION_8,
                      sha=SHA_BATCH_8)
        _attach(admin, prior, _failed_task(admin, verification="FAIL"))
        c = _cand(console, new, title="Coupon report, retitled",
                  section=SECTION_9)

        with db.connect() as conn:
            before = _fails(conn, c)
        assert before == 1

        out = approve.approve_batch(reason="one prior failure is not two",
                                    approve_ids=[c], reject={}, not_now_ids=[],
                                    decided_by="eamonn")
        undone = undo.undo_approval(out["decision_id"], reason="not tonight")

        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, decision FROM decision_log ORDER BY id").fetchall()
            after = _fails(conn, c)
            disposition = conn.execute(
                "SELECT disposition FROM candidates WHERE id=%s",
                (c,)).fetchone()["disposition"]

        # The approval row is still there, and the undo is a SECOND row citing
        # it rather than an edit of it.
        assert out["decision_id"] in [r["id"] for r in rows]
        assert undone["follow_up_decision_id"] > out["decision_id"]
        assert disposition == "PENDING"
        # The prior failure is still a prior failure. An undo is a delay.
        assert after == before == 1

    def test_the_backfill_only_ever_fills_a_null(self, dsns, console, admin):
        """It writes one column, where it is NULL, and is idempotent.

        The corrected count has to be DERIVABLE from history, not written into
        it. A backfill that could overwrite a key is a backfill that could
        change what an old decision was made against.
        """
        b = _batch(console)
        cid = _cand(console, b, title="Coupons", section=SECTION_9)
        admin.execute("UPDATE candidates SET work_key='hand::written' WHERE id=%s",
                      (cid,))
        admin.commit()

        out = work_key.backfill(dry_run=False)
        assert cid not in [p["candidate_id"] for p in out["plan"]]

        with db.connect() as conn:
            assert conn.execute("SELECT work_key FROM candidates WHERE id=%s",
                                (cid,)).fetchone()["work_key"] == "hand::written"

    def test_the_backfill_is_idempotent(self, dsns, console, admin):
        b = _batch(console)
        cid = _cand(console, b, title="Coupons", section=SECTION_9)
        admin.execute("UPDATE candidates SET work_key=NULL WHERE id=%s", (cid,))
        admin.commit()

        first = work_key.backfill(dry_run=False)
        second = work_key.backfill(dry_run=False)
        assert first["written"] >= 1
        assert second["written"] == 0


# ---- one predicate ---------------------------------------------------------

class TestOnePredicate:
    """H. The dry run and the real decision ask the same question."""

    def test_the_plan_carries_the_count_for_every_row(self, dsns, console,
                                                      admin):
        """Including rows an earlier gate held.

        §10 asks for the count AND the other hold reason. They are different
        facts: a row held tonight by a path overlap with two failures behind it
        will be held for another reason the moment that overlap clears, and
        reading only the first rule that fired is how that arrives as a
        surprise.
        """
        _pool(admin)
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        for _ in range(2):
            a = _cand(console, old, title="Coupon report", section=SECTION_8,
                      sha=SHA_BATCH_8)
            _attach(admin, a, _failed_task(admin, verification="FAIL"))
        blocked = _cand(console, new, title="Coupon report, third time",
                        section=SECTION_9)
        clean = _cand(console, new, title="Something else entirely",
                      section="Daily — CSV export", sha=SHA_BATCH_8, band="daily")

        p = autoapprove.plan()
        by_id = {r["candidate_id"]: r for r in p["ranked"]}

        assert by_id[blocked]["prior_failures"] == 2
        assert by_id[blocked]["repeat_stop_matched"] is True
        assert by_id[blocked]["eligible"] is False
        assert by_id[clean]["prior_failures"] == 0
        assert by_id[clean]["repeat_stop_matched"] is False
        # Every row carries the identity the count was taken over, so a 0 can
        # be read as "none" rather than "we could not tell".
        assert all(r["work_identity"] for r in p["ranked"])
        assert blocked not in p["approve_ids"]
        assert p["repeat"]["stop_at"] == 2
        assert p["repeat"]["blocked"] == 1

    def test_the_plan_and_approve_batch_agree_on_the_same_rows(
            self, dsns, console, admin):
        """The one that would have caught this defect on night one.

        Before 027 the stop lived only inside approve_batch(), which
        sweep(dry_run=True) never calls -- so a dry run could not show that the
        ceiling was broken, and it had to be found by hand against production.
        """
        _pool(admin)
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        for _ in range(2):
            a = _cand(console, old, title="Coupon report", section=SECTION_8,
                      sha=SHA_BATCH_8)
            _attach(admin, a, _failed_task(admin, verification="FAIL"))
        blocked = _cand(console, new, title="Coupon report, third time",
                        section=SECTION_9)

        p = autoapprove.plan()
        planned = {r["candidate_id"]: r["prior_failures"] for r in p["ranked"]}

        with db.connect() as conn:
            enforced = {cid: _fails(conn, cid) for cid in planned}
        assert planned == enforced

        # And the row the plan holds is the row approve_batch refuses.
        with pytest.raises(approve.ApprovalRefused):
            approve.approve_batch(reason="forcing it", approve_ids=[blocked],
                                  reject={}, not_now_ids=[], decided_by="eamonn")

    def test_a_dry_run_writes_nothing_while_evaluating_the_stop(
            self, dsns, console, admin):
        _pool(admin)
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        for _ in range(2):
            a = _cand(console, old, title="Coupon report", section=SECTION_8,
                      sha=SHA_BATCH_8)
            _attach(admin, a, _failed_task(admin, verification="FAIL"))
        _cand(console, new, title="Coupon report, third time", section=SECTION_9)

        before = admin.execute(
            "SELECT count(*) AS n FROM decision_log").fetchone()["n"]
        out = autoapprove.sweep(dry_run=True)
        after = admin.execute(
            "SELECT count(*) AS n FROM decision_log").fetchone()["n"]

        assert before == after
        assert out["decision_id"] is None
        assert out["repeat"]["blocked"] == 1


# ---- the mutation proof ----------------------------------------------------

class TestMutationOfTheIdentity:
    """The predicate, deliberately broken, and the tests that must notice.

    A test that passes against both the fix and the defect is a test that is
    not testing the fix. These assert the OLD behaviour explicitly, so that
    reverting 027's identity or its outcome rule makes a named test fail rather
    than quietly restoring a ceiling that reads correct and never fires.
    """

    def test_a_title_keyed_count_misses_the_retitle(self, dsns, console, admin):
        """022's key, evaluated on 027's data. It scores 0 on a real repeat."""
        old = _batch(console, sha=SHA_BATCH_8)
        new = _batch(console)
        c14 = _cand(console, old, title="Coupon and discount performance report",
                    section=SECTION_8, sha=SHA_BATCH_8)
        _attach(admin, c14, _failed_task(admin, verification="FAIL"))
        c28 = _cand(console, new, section=SECTION_9, title=(
            "Coupon and discount performance report, over a column that is "
            "already populated"))

        with db.connect() as conn:
            title_keyed = conn.execute(
                "SELECT count(DISTINCT t.id)::int AS n FROM candidates c"
                " JOIN tasks t ON t.id=c.spec_task_id OR t.id=c.work_task_id"
                " WHERE c.title=(SELECT title FROM candidates WHERE id=%s)"
                "   AND c.repo=(SELECT repo FROM candidates WHERE id=%s)"
                "   AND t.status='FAILED'", (c28, c28)).fetchone()["n"]
            keyed = _fails(conn, c28)

        assert title_keyed == 0, "022's key is the defect; if this is 1 the " \
                                 "mutation no longer reproduces the bug"
        assert keyed == 1

    def test_a_status_only_rule_over_counts_a_promoted_draft(
            self, dsns, console, admin):
        """022's outcome rule, evaluated on task 21's shape. It counts a success."""
        old = _batch(console, sha=SHA_BATCH_8)
        a = _cand(console, old, title="Net revenue", section=SECTION_8,
                  sha=SHA_BATCH_8)
        _attach(admin, a, _failed_task(admin, verification="PASS"))

        with db.connect() as conn:
            status_only = conn.execute(
                "SELECT count(*)::int AS n FROM candidates c"
                " JOIN tasks t ON t.id=c.spec_task_id"
                " WHERE c.id=%s AND t.status='FAILED'", (a,)).fetchone()["n"]
            assert status_only == 1
            assert _fails(conn, a) == 0

    def test_dropping_the_word_boundary_would_merge_two_rows(self):
        """`startswith` without the hyphen is the tempting simplification.

        "csv-export" is a prefix of "csv-exportable-somethings" as a STRING and
        is not a prefix of it as a PHRASE. The boundary is what stops the
        resolver merging two document rows that share an opening word.
        """
        rows = ["csv-exporter-configuration-for-segments"]
        assert work_key.resolve("csv-export", rows) is None
        assert "csv-exporter-configuration-for-segments".startswith("csv-export")

    def test_the_two_argument_function_is_gone(self, dsns, console):
        """One function answers this, and the losing answer read 0.

        Leaving 022's signature callable beside 027's is the drift
        console/load_candidates.py refuses for the probe vocabulary: two
        answers to one question, and the one that is wrong is the one that
        silently approves.
        """
        with db.connect() as conn:
            n = conn.execute(
                "SELECT count(*)::int AS n FROM pg_proc"
                " WHERE proname='candidate_prior_failures'").fetchone()["n"]
            assert n == 1
            args = conn.execute(
                "SELECT pg_get_function_identity_arguments(oid) AS a"
                " FROM pg_proc WHERE proname='candidate_prior_failures'"
            ).fetchone()["a"]
        assert args == "p_candidate_id bigint"


# ---- a refused night is a recorded night -----------------------------------

class TestTheRefusalIsRecorded:
    """A night that decided nothing used to leave no row anywhere.

    approve_batch is the only thing that writes decision_log on this path and
    it is not called when there is nothing to approve, so a correct refusal and
    a dead timer left the same trace: none. Refusing IS the designed behaviour
    -- §2.3 approves nothing when the top two are indistinguishable -- and a
    correct refusal every night for a week is a fact about the pool that can
    only be read if each night leaves a row.
    """

    def _two_tied(self, console, admin):
        """Two candidates alike on every key that means anything."""
        _pool(admin)
        b = _batch(console)
        a = _cand(console, b, title="One thing", section=SECTION_9,
                  band="weekly", probes=[EXISTS])
        c = _cand(console, b, title="Another thing",
                  section="Weekly — product performance by category",
                  sha=SHA_BATCH_8, band="weekly", probes=[EXISTS])
        return a, c

    def test_a_refused_night_writes_exactly_one_row(self, dsns, console, admin):
        self._two_tied(console, admin)
        before = admin.execute(
            "SELECT count(*) AS n FROM decision_log").fetchone()["n"]

        out = autoapprove.sweep()

        assert out["approve_ids"] == []
        assert out["decision_id"] is None
        assert out["refusal_decision_id"] is not None
        rows = admin.execute(
            "SELECT id, decision, decided_via, reason, mechanics, evidence"
            " FROM decision_log ORDER BY id DESC LIMIT 1").fetchone()
        assert admin.execute(
            "SELECT count(*) AS n FROM decision_log").fetchone()["n"] == before + 1
        assert rows["decision"] == "DEFERRED"
        assert rows["decided_via"] == "unattended"
        assert "indistinguishable" in rows["reason"]
        # The working, on the same argument 026 requires it for an approval.
        assert rows["mechanics"]["ranked"]
        assert rows["mechanics"]["cut"]["n"] >= 1
        # And which rows it was looking at.
        assert {e["id"] for e in rows["evidence"]} == set(self_ids(admin))

    def test_it_queues_nothing_and_touches_no_candidate(
            self, dsns, console, admin):
        a, c = self._two_tied(console, admin)
        tasks_before = admin.execute(
            "SELECT count(*) AS n FROM tasks").fetchone()["n"]

        autoapprove.sweep()

        assert admin.execute(
            "SELECT count(*) AS n FROM tasks").fetchone()["n"] == tasks_before
        for cid in (a, c):
            row = admin.execute(
                "SELECT disposition, decided_at, approval_decision_id"
                " FROM candidates WHERE id=%s", (cid,)).fetchone()
            assert row["disposition"] == "PENDING"
            assert row["decided_at"] is None
            assert row["approval_decision_id"] is None

    def test_a_dry_run_still_writes_nothing(self, dsns, console, admin):
        """The invariant is not relaxed to make the refusal visible.

        A dry run that wrote a row would be a dry run with a side effect, and
        the whole argument for reading dry runs is that they have none. The
        consequence is stated rather than worked around: while the unit carries
        --dry-run, a refusal is recorded in the journal and nowhere else.
        """
        self._two_tied(console, admin)
        before = admin.execute(
            "SELECT count(*) AS n FROM decision_log").fetchone()["n"]

        out = autoapprove.sweep(dry_run=True)

        assert out["approve_ids"] == []
        assert out["refusal_decision_id"] is None
        assert admin.execute(
            "SELECT count(*) AS n FROM decision_log").fetchone()["n"] == before

    def test_a_refusal_needs_its_working_like_an_approval_does(self):
        with pytest.raises(approve.ApprovalRefused) as exc:
            approve.record_unattended_refusal(
                reason="nothing separated them", mechanics={}, considered=[1])
        assert "mechanics" in str(exc.value)

    def test_a_refusal_needs_a_reason(self):
        with pytest.raises(approve.ApprovalRefused) as exc:
            approve.record_unattended_refusal(
                reason="   ", mechanics={"rank_version": 1}, considered=[1])
        assert "only thing distinguishing" in str(exc.value)

    def test_an_empty_pool_is_recorded_too(self, dsns, console, admin):
        """Nothing to do is a fact, and it is not the same as nothing running."""
        _pool(admin)
        out = autoapprove.sweep()
        assert out["refusal_decision_id"] is not None
        row = admin.execute(
            "SELECT reason, evidence FROM decision_log WHERE id=%s",
            (out["refusal_decision_id"],)).fetchone()
        assert "no candidate passed the gates" in row["reason"]
        assert row["evidence"] == []


def self_ids(admin):
    return [r["id"] for r in admin.execute(
        "SELECT id FROM candidates WHERE disposition IN ('PENDING','NOT_NOW')"
        " ORDER BY id").fetchall()]
