"""Ranking candidates and ticking them with nobody watching.

specs/auto-approval.md §2.2, §2.3, §2.5. What these protect, in one line each:

  key 1 reads the probes, and creation differs from modification
                                              -> TestKeyOneReadsTheProbes
  the gates run AHEAD of the sort             -> TestTheGates
  the pace and the 60% stop bind the cut      -> TestTheCut
  no discriminator means no approval          -> TestTheReasonOrNothing
  the record carries its working              -> TestWhatIsRecorded
  a dry run writes nothing                    -> TestDryRun

THE FAILURE THESE EXIST FOR is a machine writing "approved" into a NOT NULL
reason column with nothing behind it. 010 §4: ten paraphrases of "yes" satisfy
the constraint while emptying the column, and an approval nobody made is
exactly where that arrives by a new route.
"""
from __future__ import annotations

import json

import pytest

from console import approve, autoapprove, rank


def _producer_task(console) -> int:
    """A candidate_producer task, so a batch can point at one.

    A batch with no producer is not a shape the loader makes for a produced
    document, and since 034 it is the shape gate 2 declines to supersede
    against. A fixture that left it NULL would be testing a state production
    does not reach -- see the note at the top of tests/conftest.py.
    """
    floor = console.execute(
        "SELECT jsonb_agg(glob) AS g FROM protected_path_floor"
        " WHERE repo='fleet'").fetchone()["g"]
    contract = json.dumps({
        "work_type": "candidate_producer",
        "writable_paths": ["research/candidates.md"],
        "protected_paths": floor, "verification": ["true"],
        "max_diff_lines": 10})
    row = console.execute(
        "INSERT INTO tasks (title, spec_md, repo, acceptance_contract,"
        " max_cost_gbp) VALUES ('produce','x','fleet',%s,1.0) RETURNING id",
        (contract,)).fetchone()
    console.commit()
    return row["id"]


def _batch(console, doc="research/candidates.md", sha="4041d15",
           producer: bool = True) -> int:
    row = console.execute(
        "INSERT INTO candidate_batches (source_document, source_sha,"
        " source_repo, produced_by_task_id)"
        " VALUES (%s,%s,'fleet',%s) RETURNING id",
        (doc, sha, _producer_task(console) if producer else None)).fetchone()
    console.commit()
    return row["id"]


def _cand(console, batch_id, *, title="Do the thing", band="daily",
          probes=None, paths=None, signal=None, repo="fleet",
          premise=None) -> int:
    """`premise` DEFAULTS TO NONE, which is the state every row in the real
    pool was in on 10 Sep 2026 -- 030 added the column and nothing backfilled
    it. Tests that are about gate 6 pass one; the rest inherit the silence the
    pool actually has, which is what keeps them testing what they are about.
    """
    row = console.execute(
        "INSERT INTO candidates (batch_id, title, rationale, repo, band,"
        " hib_signal, probes, premise, suggested_paths, evidence)"
        " VALUES (%s,%s,'because the finding said so',%s,%s,%s,%s,%s,%s,'[]')"
        " RETURNING id",
        (batch_id, title, repo, band,
         json.dumps(signal) if signal else None,
         json.dumps(probes if probes is not None else [
             {"path_exists": "console/approve.py"}]),
         json.dumps(premise or []),
         paths or [])).fetchone()
    console.commit()
    return row["id"]


def _pace(admin, n: int = 1):
    """Pin the pace this test means, rather than inheriting the deployed one.

    029 raised fleet_autoapprove_per_night() from 1 to 3 and twenty-four tests
    failed -- all of them written when the pace was 1 and reading it from the
    database. That is the tests being coupled to a ceiling they are not about:
    a test of the DISCRIMINATOR ("no key separates the top two, so approve
    nothing") needs a cut of 1 to have a top two at all, and says nothing about
    what the pace should be.

    AND THE COUPLING WAS WORTH FINDING. At a pace of 3 with three eligible
    rows there is no row below the line, so `_reason` takes its
    "only candidate that passed the gates" branch and §2.3's refusal cannot
    fire. The refusal does not apply when nothing was chosen OVER anything --
    but it stops applying quietly, and specs/auto-approval.md §9.14 records
    that rather than leaving it to be noticed when it matters.
    """
    admin.execute(
        f"CREATE OR REPLACE FUNCTION fleet_autoapprove_per_night()"
        f" RETURNS int LANGUAGE sql IMMUTABLE AS $$ SELECT {int(n)} $$")
    admin.commit()


def _pool(admin, gbp="158.00"):
    # Pace pinned with the pool: both are ceilings a test inherits from the
    # deployed database unless it says otherwise, and 029 proved that inheriting
    # them silently is how twenty-four tests change meaning under a migration.
    _pace(admin, 1)
    admin.execute("DELETE FROM model_credit_pool"
                  " WHERE period_month = date_trunc('month', now())::date")
    admin.execute(
        "INSERT INTO model_credit_pool (period_month, pool_gbp, source, read_at)"
        " VALUES (date_trunc('month', now())::date, %s, 'test fixture', now())",
        (gbp,))
    admin.commit()


# Probes that resolve against the real fleet checkout, which is what
# candidate_block_shape.REPOS points at.
EXISTS = {"path_exists": "console/approve.py"}
ABSENT_FILE = {"path_absent": "console/no_such_module.py"}
FEATURE_MISSING = {"grep_count": {"glob": "console/approve.py",
                                  "pattern": "zzz_not_present_anywhere",
                                  "expected": 0}}
GLOB_MISSING = {"grep_count": {"glob": "console/*.py",
                               "pattern": "zzz_not_present_anywhere",
                               "expected": 0}}
#: Resolved against the PLATFORM checkout, so a candidate carrying these
#: must declare that repo -- gate 4 runs every probe against the tree the
#: candidate names, and naming the wrong one is itself a probe failure.
PLATFORM = "deadly-digital-platform"
API_PRESENT = {"path_exists": "api/analytics/routes/orders.py"}
#: A SENTINEL, not a real gap, and it became one on 10 Sep 2026. This asserted
#: that platform/app/api/analytics/orders/route.ts does not mention
#: `payment_method` -- true when it was written, and false the moment task 53
#: forwarded the four order filters through that proxy. Twelve tests failed on
#: a merge, which is gate 5 doing precisely its job: a candidate whose claim has
#: stopped being true is not approved.
#:
#: The fleet-side constants in this file already use `zzz_not_present_anywhere`
#: for the same reason. A fixture that encodes a real gap is a fixture with an
#: expiry date nobody wrote down, and the thing under test here is the SHAPE of
#: an absent-feature probe, not the absence of that particular feature.
PLATFORM_FEATURE_MISSING = {
    "grep_count": {"glob": "platform/app/api/analytics/orders/route.ts",
                   "pattern": "zzz_not_present_anywhere", "expected": 0}}


class TestKeyOneReadsTheProbes:
    """The key is a GUESS -- five runs, confounded -- and it is first anyway.

    specs/auto-approval.md §2.2 and §7.1. These tests fix what it MEANS, not
    that it is right; RANK_VERSION is what makes being wrong cheap.
    """

    def test_a_file_that_does_not_exist_is_creation(self):
        """path_absent means the work makes a new file."""
        klass, why = rank.work_class([EXISTS, ABSENT_FILE])
        assert klass == rank.CREATE
        assert why["creates"] == ["console/no_such_module.py"]

    def test_a_named_file_missing_a_feature_is_modification(self):
        """THE DISTINCTION THE KEY TURNS ON.

        Both of these are absence. Only one is a new file. The three specs that
        failed did so on invented paths, and the agent invented a filename
        exactly when the candidate gave it nothing to read.
        """
        klass, _ = rank.work_class([EXISTS, FEATURE_MISSING])
        assert klass == rank.MODIFY

    def test_a_glob_finding_nothing_anywhere_is_creation(self):
        """"Nothing under console/*.py mentions it" says the feature has no
        home yet, which is not the same as one file missing a line."""
        klass, _ = rank.work_class([EXISTS, GLOB_MISSING])
        assert klass == rank.CREATE

    def test_the_frontend_only_gap_sorts_at_the_top(self):
        """Presence under api/** with the feature missing from an existing
        platform/** file: computed, returned, and dropped one layer from a
        person."""
        klass, why = rank.work_class([API_PRESENT, PLATFORM_FEATURE_MISSING])
        assert klass == rank.FRONTEND_ONLY
        assert why["api_presence"] == ["api/analytics/routes/orders.py"]
        assert why["platform_feature_absent"]

    def test_presence_alone_is_modification(self):
        assert rank.work_class([EXISTS])[0] == rank.MODIFY

    def test_no_probes_is_not_a_class_it_can_defend(self):
        """An empty list cannot be frontend-only or modify: there is nothing
        asserting anything exists. It sorts with creation and gate 4 refuses it
        outright, which is the answer that matters."""
        assert rank.work_class([])[0] == rank.CREATE

    def test_with_no_floor_the_coverage_key_is_off_and_v1_order_stands(self):
        """A caller that has not been taught to read the floor loses the key.

        It does NOT get a threshold this module invented -- that is the safe
        direction, and it is why coverage_floor has no default value of its
        own.
        """
        rich = {"id": 1, "band": "daily", "probes": [EXISTS],
                "hib_signal": {"coverage": {"metric": "m", "populated": 99,
                                            "total": 100}}}
        poor = {"id": 2, "band": "daily", "probes": [EXISTS],
                "hib_signal": {"coverage": {"metric": "m", "populated": 1,
                                            "total": 1000000}}}
        assert rank.rank(rich)[1] == rank.rank(poor)[1] == rank.COVERAGE_NONE
        assert rank.rank(rich) < rank.rank(poor)   # by id alone, as in v1

    def test_the_keys_sort_class_then_band_then_id(self):
        assert rank.rank({"id": 9, "band": "daily",
                          "probes": [API_PRESENT, PLATFORM_FEATURE_MISSING]}) \
            < rank.rank({"id": 1, "band": "daily", "probes": [EXISTS]})
        assert rank.rank({"id": 9, "band": "daily", "probes": [EXISTS]}) \
            < rank.rank({"id": 1, "band": "weekly", "probes": [EXISTS]})
        assert rank.rank({"id": 1, "band": "daily", "probes": [EXISTS]}) \
            < rank.rank({"id": 2, "band": "daily", "probes": [EXISTS]})

    def test_a_null_band_sorts_last_and_does_not_gate(self):
        assert rank.rank({"id": 1, "band": None, "probes": [EXISTS]}) \
            > rank.rank({"id": 99, "band": "rarely", "probes": [EXISTS]})


class TestTheGates:
    def test_not_now_is_a_veto_the_machine_does_not_overrule(
            self, dsns, console, admin):
        """The cheapest correction in §5: one click, no deploy, no migration."""
        _pool(admin)
        b = _batch(console)
        cid = _cand(console, b)
        console.execute("UPDATE candidates SET disposition='NOT_NOW',"
                        " decided_at=now() WHERE id=%s", (cid,))
        console.commit()
        p = autoapprove.plan()
        row = next(r for r in p["ranked"] if r["candidate_id"] == cid)
        assert row["eligible"] is False
        assert row["rule"] == "not_pending"

    def test_an_older_batch_is_superseded_by_construction(
            self, dsns, console, admin):
        _pool(admin)
        old, new = _batch(console), _batch(console)
        stale = _cand(console, old, title="CSV export of the order list")
        fresh = _cand(console, new, title="CSV export, honouring the filters")
        p = autoapprove.plan()
        assert next(r for r in p["ranked"]
                    if r["candidate_id"] == stale)["rule"] == "older_batch"
        assert next(r for r in p["ranked"]
                    if r["candidate_id"] == fresh)["eligible"] is True

    def test_a_path_a_live_task_declares_holds_the_candidate(
            self, dsns, console, admin):
        """Candidate 22 and queued task 49 in miniature: nothing links them,
        because task 49 was a hand INSERT and carries no candidate id."""
        _pool(admin)
        b = _batch(console)
        cid = _cand(console, b, paths=["platform/app/(dashboard)/analytics/page.tsx"])
        # The floor comes from protected_path_floor rather than being typed:
        # enforce_contract_floor() refuses a task whose contract does not cover
        # it, so a typed copy makes the fixture fail for a reason that has
        # nothing to do with what is being tested.
        floor = [r["glob"] for r in console.execute(
            "SELECT glob FROM protected_path_floor WHERE repo=%s",
            ("deadly-digital-platform",)).fetchall()]
        console.execute(
            "INSERT INTO tasks (title, spec_md, repo, base_branch,"
            " acceptance_contract, max_cost_gbp, timeout_seconds)"
            " VALUES ('a queued frontend task', %s, 'deadly-digital-platform',"
            " 'main', %s, 1.00, 600)",
            ("```fleet-spec\nwork_type: dd_frontend\nrepo: x\ntitle: t\n"
             "writable_paths:\n  - platform/app/(dashboard)/analytics/page.tsx\n```",
             json.dumps({"work_type": "dd_frontend",
                         "writable_paths": [
                             "platform/app/(dashboard)/analytics/page.tsx"],
                         "protected_paths": floor})))
        console.commit()
        p = autoapprove.plan()
        row = next(r for r in p["ranked"] if r["candidate_id"] == cid)
        assert row["eligible"] is False
        assert row["rule"] == "path_overlap"

    def test_the_spec_block_is_preferred_over_the_wide_contract(self):
        """A fallback match is a much weaker statement than a spec match, so
        which one matched is recorded rather than flattened into 'overlapped'.

        Task 49's contract claims twenty-seven globs across the whole analytics
        frontend; its fleet-spec block names two files. Using the contract when
        the block parses would hold every frontend candidate there is.
        """
        task = {"spec_md": "```fleet-spec\nwritable_paths:\n  - a/b.ts\n```",
                "acceptance_contract": {"writable_paths": ["a/**", "c/**"]}}
        paths, source = rank.declared_paths(task)
        assert (paths, source) == (["a/b.ts"], "spec")

        broken = {"spec_md": "```fleet-spec\n: not: valid: yaml:\n```",
                  "acceptance_contract": {"writable_paths": ["a/**"]}}
        paths, source = rank.declared_paths(broken)
        assert source == "contract"

    def test_a_claim_that_no_longer_holds_is_not_built(
            self, dsns, console, admin):
        _pool(admin)
        b = _batch(console)
        cid = _cand(console, b, probes=[{"path_exists": "console/gone.py"}])
        p = autoapprove.plan()
        row = next(r for r in p["ranked"] if r["candidate_id"] == cid)
        assert row["eligible"] is False
        assert row["rule"] == "probes_failed"

    def test_zero_probes_is_a_check_that_cannot_fail_and_is_refused(
            self, dsns, console, admin):
        """Every hand-loaded row carries '[]'. "All zero of its probes held" is
        green forever, which is 024's named recurring defect."""
        _pool(admin)
        b = _batch(console)
        cid = _cand(console, b, probes=[])
        p = autoapprove.plan()
        row = next(r for r in p["ranked"] if r["candidate_id"] == cid)
        assert row["eligible"] is False
        assert row["rule"] == "probes_failed"
        assert "cannot fail" in row["detail"]


class TestGateSixTheGroundNotTheGap:
    """§9.9.1. Candidate 38 passed five gates and was still wrong about the
    tree, because every one of its probes tested the GAP.

    The failure these tests describe is not hypothetical: c38 said the Payment,
    Country and Coupon values in the order table "are inert", the table had
    never rendered those columns, and the £2.25 run that followed added three
    of them that no spec asked for.
    """

    def test_a_premise_that_no_longer_holds_refuses_the_candidate(
            self, dsns, console, admin):
        _pool(admin)
        b = _batch(console)
        cid = _cand(console, b, premise=[{
            "claim": "the console still has a module that ranks candidates",
            "probe": {"path_exists": "console/a_file_that_is_not_here.py"}}])
        p = autoapprove.plan()
        row = next(r for r in p["ranked"] if r["candidate_id"] == cid)
        assert row["eligible"] is False
        assert row["rule"] == "premise_failed"

    def test_the_rule_is_not_probes_failed_because_they_mean_opposite_things(
            self, dsns, console, admin):
        """A failing probe says the gap closed: drop the row. A failing premise
        says the ground is not there: the row is a DIFFERENT piece of work from
        the one described. One rule name for both would send a reader the wrong
        way, and the brief prints the rule.
        """
        _pool(admin)
        b = _batch(console)
        gone = _cand(console, b, title="the gap closed",
                     probes=[{"path_absent": "console/rank.py"}])
        ground = _cand(console, b, title="the ground is missing",
                       premise=[{"claim": "the ranking module is a package "
                                          "module in the console",
                                 "probe": {"path_absent": "console/rank.py"}}])
        p = autoapprove.plan()
        assert next(r for r in p["ranked"]
                    if r["candidate_id"] == gone)["rule"] == "probes_failed"
        assert next(r for r in p["ranked"]
                    if r["candidate_id"] == ground)["rule"] == "premise_failed"

    def test_a_holding_premise_is_eligible_and_records_the_claim(
            self, dsns, console, admin):
        """The sentence is recorded beside the verdict, because the open
        question -- does the predicate test the claim, or something adjacent --
        cannot be asked of a predicate on its own."""
        _pool(admin)
        b = _batch(console)
        cid = _cand(console, b, premise=[{
            "claim": "the console still has a module that ranks candidates",
            "probe": {"path_exists": "console/rank.py"}}])
        p = autoapprove.plan()
        row = next(r for r in p["ranked"] if r["candidate_id"] == cid)
        assert row["eligible"] is True
        assert row["premise"] == [{
            "held": True,
            "claim": "the console still has a module that ranks candidates",
            "probe": "path_exists: console/rank.py exists"}]

    def test_a_candidate_with_no_premise_is_not_refused_and_is_counted(
            self, dsns, console, admin):
        """THE HOLE, ASSERTED RATHER THAN LEFT TO BE DISCOVERED.

        Every row in the pool on 10 Sep 2026 was emitted before the key
        existed, so refusing an empty premise would have stopped unattended
        approval dead for rows whose producers were never asked. What must NOT
        happen is the silence reading as a pass: `silent` counts it, and
        candidate_block_shape.py refuses a new block that omits one, so the
        hole closes from the producer end.
        """
        _pool(admin)
        b = _batch(console)
        cid = _cand(console, b)          # no premise, like every real row
        p = autoapprove.plan()
        row = next(r for r in p["ranked"] if r["candidate_id"] == cid)
        assert row["eligible"] is True
        assert p["premise"]["silent"] >= 1
        assert p["premise"]["declared"] == 0
        # and the zero is not reported as a verified pool
        assert p["premise"]["held"] == 0

    def test_the_premise_tally_reaches_the_decision(self, dsns, console, admin):
        """026 requires an unattended decision to carry its working. A gate
        that ran and left no trace is a gate nobody can audit afterwards."""
        _pool(admin)
        b = _batch(console)
        _cand(console, b, title="one", premise=[{
            "claim": "the console still has a module that ranks candidates",
            "probe": {"path_exists": "console/rank.py"}}])
        out = autoapprove.sweep()
        assert out["approve_ids"], out
        row = console.execute(
            "SELECT mechanics FROM decision_log WHERE id=%s",
            (out["decision_id"],)).fetchone()
        assert row["mechanics"]["premise"]["declared"] == 1
        assert row["mechanics"]["premise"]["held"] == 1


class TestTheCut:
    def test_the_pace_is_one_and_it_binds(self, dsns, console, admin):
        _pool(admin)
        b = _batch(console)
        for i in range(3):
            _cand(console, b, title=f"Candidate {i}",
                  band=["daily", "weekly", "monthly"][i])
        p = autoapprove.plan()
        assert len(p["eligible"]) == 3
        assert p["cut"]["n"] == 1
        assert "per_night" in p["cut"]["bound_by"]
        assert len(p["approve_ids"]) == 1

    def test_the_60_percent_stop_binds_before_the_100_percent_ceiling(
            self, dsns, console, admin):
        """specs/unattended-operation.md §5.1, which nothing built until 026.

        A pool with £3 left has room for a £2 draft spec at 100% and none at
        60%. A person keeps the larger number -- that is what "leaving £63 for
        work a person chooses" means.
        """
        _pool(admin, "3.00")
        b = _batch(console)
        _cand(console, b)
        p = autoapprove.plan()
        assert p["credit"]["remaining"] >= 2.00, "a person could still tick this"
        assert p["credit"]["autonomous_remaining"] < 2.00
        assert p["cut"]["n"] == 0
        assert p["approve_ids"] == []
        assert "autonomous_credit" in p["cut"]["bound_by"]

    def test_an_uncomputed_pool_approves_nothing(self, dsns, console, admin):
        # The batch first. Since 034 `_batch` creates the candidate_producer
        # task it points at, and enforce_credit_ceiling() refuses a task
        # insert while the pool is unknown -- which is the behaviour a
        # different test asserts, and would fail this one in the fixture
        # rather than in the thing it is about.
        b = _batch(console)
        _cand(console, b)
        admin.execute("DELETE FROM model_credit_pool")
        admin.commit()
        p = autoapprove.plan()
        assert p["cut"]["n"] == 0
        assert p["approve_ids"] == []


class TestTheReasonOrNothing:
    def test_two_rows_alike_on_every_key_produce_no_approval(
            self, dsns, console, admin):
        """THE REFUSAL. Both frontend-only, both daily, and only the id
        separates them -- so taking the first is approving because it was
        first, which is a decision nobody made."""
        _pool(admin)
        b = _batch(console)
        _cand(console, b, title="One", repo=PLATFORM,
              probes=[API_PRESENT, PLATFORM_FEATURE_MISSING])
        _cand(console, b, title="Two", repo=PLATFORM,
              probes=[API_PRESENT, PLATFORM_FEATURE_MISSING])
        p = autoapprove.plan()
        assert len(p["eligible"]) == 2
        assert p["approve_ids"] == []
        assert p["reason"] is None
        assert "indistinguishable" in p["refused"]
        assert "because it was first" in p["refused"]

    def test_a_different_class_is_a_discriminator_and_is_named(
            self, dsns, console, admin):
        _pool(admin)
        b = _batch(console)
        top = _cand(console, b, title="Forward the filters", repo=PLATFORM,
                    probes=[API_PRESENT, PLATFORM_FEATURE_MISSING])
        _cand(console, b, title="A new report", probes=[EXISTS, ABSENT_FILE])
        p = autoapprove.plan()
        assert p["approve_ids"] == [top]
        assert "frontend-only" in p["reason"]
        assert "create" in p["reason"]

    def test_a_different_band_is_a_discriminator(self, dsns, console, admin):
        _pool(admin)
        b = _batch(console)
        top = _cand(console, b, title="Daily one", band="daily")
        _cand(console, b, title="Weekly one", band="weekly")
        p = autoapprove.plan()
        assert p["approve_ids"] == [top]
        assert "daily" in p["reason"] and "weekly" in p["reason"]

    def test_the_only_eligible_row_says_so_rather_than_claiming_a_contest(
            self, dsns, console, admin):
        """"The only one that passed the gates" is a much weaker claim than
        "the best of nine" and the record must not let them read alike."""
        _pool(admin)
        b = _batch(console)
        only = _cand(console, b, title="The only one")
        _cand(console, b, title="Held one", probes=[{"path_exists": "nope.py"}])
        p = autoapprove.plan()
        assert p["approve_ids"] == [only]
        assert "only candidate that passed the gates" in p["reason"]
        assert "there was none" in p["reason"]


class TestWhatIsRecorded:
    def test_an_unattended_approval_writes_its_working(
            self, dsns, console, admin):
        _pool(admin)
        b = _batch(console)
        top = _cand(console, b, title="Forward the filters", repo=PLATFORM,
                    probes=[API_PRESENT, PLATFORM_FEATURE_MISSING])
        _cand(console, b, title="A new report", probes=[EXISTS, ABSENT_FILE])

        out = autoapprove.sweep()
        assert out["approve_ids"] == [top]

        row = console.execute(
            "SELECT decided_via, decided_by, reason, mechanics, decision"
            " FROM decision_log WHERE id=%s", (out["decision_id"],)).fetchone()
        assert row["decided_via"] == "unattended"
        assert row["decision"] == "APPROVED"
        m = row["mechanics"]
        assert m["rank_version"] == rank.RANK_VERSION
        assert m["platform_sha"]
        assert m["cut"]["n"] == 1
        assert m["credit"]["pool"] == 158.0
        assert any(r["candidate_id"] == top for r in m["ranked"])
        # Every row below the line carries the rule that held it.
        for r in m["ranked"]:
            if not r["eligible"]:
                assert r["rule"]

    def test_decided_by_is_the_login_and_never_a_person(
            self, dsns, console, admin):
        """console/app.py defaults decided_by to "eamonn". A log that reads as
        a person's decision is the one thing this record exists to prevent."""
        _pool(admin)
        b = _batch(console)
        _cand(console, b, title="Forward the filters", repo=PLATFORM,
              probes=[API_PRESENT, PLATFORM_FEATURE_MISSING])
        _cand(console, b, title="A new report", probes=[EXISTS, ABSENT_FILE])
        out = autoapprove.sweep()
        row = console.execute("SELECT decided_by FROM decision_log WHERE id=%s",
                              (out["decision_id"],)).fetchone()
        # The identity that WROTE the row, resolved by the database rather than
        # typed by the caller -- asserted against current_user rather than
        # against a literal, because the login differs between this suite and
        # production and the property is "it is the writer", not "it is
        # fleet_console_login".
        writer = console.execute("SELECT current_user AS u").fetchone()["u"]
        assert row["decided_by"] == writer
        assert "eamonn" not in row["decided_by"]
        # And the plan never names an identity it did not write as: plan() holds
        # the read-only connection, whose login could not have inserted this.
        assert autoapprove.plan()["decided_by"] is None

    def test_an_unattended_approval_without_mechanics_is_refused(
            self, dsns, console, admin):
        _pool(admin)
        b = _batch(console)
        cid = _cand(console, b)
        with pytest.raises(approve.ApprovalRefused, match="must carry its mechanics"):
            approve.approve_batch(reason="r", approve_ids=[cid], reject={},
                                  not_now_ids=[], decided_by="x",
                                  decided_via="unattended")

    def test_an_unattended_approval_cannot_override_the_repeat_stop(
            self, dsns, console, admin):
        _pool(admin)
        b = _batch(console)
        cid = _cand(console, b)
        with pytest.raises(approve.ApprovalRefused, match="repeat_overrides"):
            approve.approve_batch(reason="r", approve_ids=[cid], reject={},
                                  not_now_ids=[], decided_by="x",
                                  decided_via="unattended",
                                  mechanics={"rank_version": 1},
                                  repeat_overrides={cid: "it is different"})

    def test_a_console_approval_is_unchanged_and_carries_no_mechanics(
            self, dsns, console, admin):
        _pool(admin)
        b = _batch(console)
        cid = _cand(console, b)
        out = approve.approve_batch(reason="a person read it", approve_ids=[cid],
                                    reject={}, not_now_ids=[], decided_by="eamonn")
        row = console.execute(
            "SELECT decided_via, mechanics FROM decision_log WHERE id=%s",
            (out["decision_id"],)).fetchone()
        assert row["decided_via"] == "console"
        assert row["mechanics"] is None

    def test_a_person_cannot_be_given_mechanics(self, dsns, console, admin):
        _pool(admin)
        b = _batch(console)
        cid = _cand(console, b)
        with pytest.raises(approve.ApprovalRefused, match="cannot carry mechanics"):
            approve.approve_batch(reason="r", approve_ids=[cid], reject={},
                                  not_now_ids=[], decided_by="eamonn",
                                  mechanics={"rank_version": 1})


class TestDryRun:
    def test_a_dry_run_ranks_everything_and_writes_nothing(
            self, dsns, console, admin):
        _pool(admin)
        b = _batch(console)
        _cand(console, b, title="Forward the filters", repo=PLATFORM,
              probes=[API_PRESENT, PLATFORM_FEATURE_MISSING])
        _cand(console, b, title="A new report", probes=[EXISTS, ABSENT_FILE])

        before = console.execute(
            "SELECT count(*) AS n FROM decision_log").fetchone()["n"]
        p = autoapprove.sweep(dry_run=True)
        after = console.execute(
            "SELECT count(*) AS n FROM decision_log").fetchone()["n"]

        assert after == before
        assert p["queued_task_ids"] == []
        assert p["decision_id"] is None
        # It still says exactly what it would have done, which is the point.
        assert p["approve_ids"]
        assert p["reason"]
        assert len(p["ranked"]) == 2

    def test_the_dry_run_and_the_real_run_agree_by_construction(
            self, dsns, console, admin):
        """Both call plan(). A dry run that is a second implementation agrees
        with the real one only until somebody edits one of them."""
        _pool(admin)
        b = _batch(console)
        _cand(console, b, title="Forward the filters", repo=PLATFORM,
              probes=[API_PRESENT, PLATFORM_FEATURE_MISSING])
        _cand(console, b, title="A new report", probes=[EXISTS, ABSENT_FILE])
        dry = autoapprove.sweep(dry_run=True)
        real = autoapprove.sweep()
        assert dry["approve_ids"] == real["approve_ids"]
        assert dry["reason"] == real["reason"]


# ---- key 2: the data the report would be over ------------------------------

FLOOR = 0.01

C20 = {"metric": "payment_method", "populated": 2782530, "total": 2844177}
C21 = {"metric": "refund_total", "populated": 1, "total": 2844177}


def _cov(cid, cov, band="daily", probes=None):
    return {"id": cid, "band": band, "probes": probes or [EXISTS],
            "hib_signal": None if cov is None else
            {"value": "measured", "as_of": "2026-08-28", "coverage": cov}}


class TestCoverageRanks:
    """028. The discriminator that was in the evidence and out of reach.

    On 10 Sep 2026 the ranker approved nothing: c20 and c21 are both
    frontend-only and both Daily. Their signals are 2,782,530 of 2,844,177 and
    1 of 2,844,177, and 025 stored both as prose because no sort key gets that
    out of a sentence. This is the key that reads the numbers instead.
    """

    def test_the_real_pair_is_separated_and_in_the_right_direction(self):
        """c20 over c21, which is what a person decided independently.

        decision_log 23: the netting arithmetic is not exercised by live data
        at all -- "net_revenue therefore equals revenue in every window on
        every tenant today".
        """
        assert rank.rank(_cov(20, C20), coverage_floor=FLOOR) \
            < rank.rank(_cov(21, C21), coverage_floor=FLOOR)
        # ... and NOT by candidate id, which is the thing §2.3 refuses.
        assert rank.rank(_cov(99, C20), coverage_floor=FLOOR) \
            < rank.rank(_cov(1, C21), coverage_floor=FLOOR)

    def test_a_row_with_no_figure_sorts_between_the_two(self):
        """"the document stated no fraction" is not "the column is empty".

        Ordering them together is exactly how a ranker gets net revenue wrong,
        and it is the distinction 025 refused to lose.
        """
        present = rank.rank(_cov(1, C20), coverage_floor=FLOOR)
        silent = rank.rank(_cov(1, None), coverage_floor=FLOOR)
        absent = rank.rank(_cov(1, C21), coverage_floor=FLOOR)
        assert present < silent < absent

    def test_a_bad_number_ranks_below_no_number_and_that_is_deliberate(self):
        """Otherwise silence is the cheap option and the producer takes it."""
        assert rank.rank(_cov(1, C21), coverage_floor=FLOOR) \
            > rank.rank(_cov(2, None), coverage_floor=FLOOR)

    def test_coverage_outranks_the_band(self):
        """A Weekly row over populated data beats a Daily row over none.

        The band is one person's estimate of how often an agency would open
        the report; coverage is a measurement of whether the report would have
        anything in it. §2.2 ranks a measurement above an estimate.
        """
        assert rank.rank(_cov(1, C20, band="weekly"), coverage_floor=FLOOR) \
            < rank.rank(_cov(2, None, band="daily"), coverage_floor=FLOOR)

    def test_the_work_class_still_outranks_coverage(self):
        """Key 1 did not move. A frontend-only row with no figure still beats
        a create row with a perfect one."""
        frontend = {"id": 1, "band": "daily", "hib_signal": None,
                    "probes": [API_PRESENT, PLATFORM_FEATURE_MISSING],
                    "repo": PLATFORM}
        creating = _cov(2, C20, probes=[ABSENT_FILE])
        assert rank.rank(frontend, coverage_floor=FLOOR) \
            < rank.rank(creating, coverage_floor=FLOOR)

    def test_the_floor_comes_from_the_argument_not_the_module(self):
        """Same rows, two floors, two answers -- so the floor is doing work.

        028 puts it in the database with the other ceilings; a literal in
        rank.py would be the second copy that drifts.
        """
        five_percent = _cov(1, {"metric": "coupon_code", "populated": 146136,
                                "total": 2844177})
        assert rank.coverage_class(five_percent, 0.01)[0] == rank.COVERAGE_PRESENT
        assert rank.coverage_class(five_percent, 0.10)[0] == rank.COVERAGE_ABSENT

    def test_the_ratio_and_the_floor_are_both_recorded(self):
        """"data-absent" is a verdict; the morning gets the number too."""
        k = rank.key_values(_cov(21, C21), coverage_floor=FLOOR)
        assert k["key2_coverage"] == "data-absent"
        assert k["key2_ratio"] == pytest.approx(1 / 2844177)
        assert k["key2_floor"] == FLOOR

    def test_a_half_stated_ratio_is_not_read_as_zero(self):
        """A numerator with no denominator reads as NO FIGURE, never as empty.

        The shape check refuses to let a producer emit one; this is what
        happens if a hand-loaded row carries it anyway, and guessing a
        denominator would be the invented number this whole key avoids.
        """
        half = _cov(1, {"metric": "coupon_code", "populated": 146136})
        assert rank.coverage_ratio(half) is None
        assert rank.coverage_class(half, FLOOR)[0] == rank.COVERAGE_NONE


class TestTheFourNightLimit:
    """WHAT THIS KEY DOES NOT FIX, as a test rather than as a caveat.

    Coverage is complete on 2 of the 9 rows in the live pool. It separates the
    pair that tied on 10 Sep and then runs out: c23, c24, c26 and c27 are four
    `create / daily / no-figure` rows -- CSV export, scheduled digest,
    cross-store roll-up, product cost -- and nothing in the system tells them
    apart. What would is what HIB's team actually opens, which nobody has
    asked and nothing observes.

    This test exists so that "coverage fixed the ranker" cannot be believed by
    reading the code.
    """

    def test_four_rows_alike_but_for_their_ids_still_tie(self):
        rows = [_cov(cid, None) for cid in (23, 24, 26, 27)]
        keys = {rank.rank(r, coverage_floor=FLOOR)[:3] for r in rows}
        assert len(keys) == 1, "the pool's bottom four are not separable"

    def test_and_the_ranker_refuses_rather_than_taking_the_first(
            self, dsns, console, admin):
        """The refusal is the designed answer and it still fires."""
        _pool(admin)
        b = _batch(console)
        for title in ("CSV export", "Scheduled digest", "Cross-store roll-up"):
            _cand(console, b, title=title, band="daily",
                  probes=[ABSENT_FILE], repo="fleet")
        p = autoapprove.plan()
        assert p["approve_ids"] == []
        assert "indistinguishable on every key" in p["refused"]


# ---------------------------------------------------------------------------
# Gates 5 and 6: work no single task can do.
#
# Added 10 Sep 2026. A draft spec produces ONE task under ONE contract, and
# the two that matter are strictly disjoint -- dd_api writes only api/**,
# dd_frontend only platform/**. A candidate spanning them ships one half and
# nothing queues the other: `tasks` has no dependency column, `claim_task`
# orders by (priority, id), `work_key` names the gap ROW rather than the half,
# and gate 3 releases the sibling the moment the first half reaches MERGED.
#
# Task 28 is the instance. It merged the comparison-window backend on 9 Sep;
# task 49, the half that would have made it reachable, was queued BY HAND six
# hours later and failed; candidates 22 and 30 are still PENDING. A person
# caught it by opening a page. Under the unattended chain the backend half
# merges at 03:30 and deploys at 04:15.
#
# THE FIXTURES READ THE REAL CONTRACTS AND THE REAL FLOOR. See the note at the
# top of tests/conftest.py: a fixture more permissive than production is a
# test that cannot fail for the reason it exists, and these gates are entirely
# about what the real yaml says.
# ---------------------------------------------------------------------------

REPO = "deadly-digital-platform"


def _writables():
    return rank.contract_writables(REPO)


def _floor(console):
    return [r["glob"] for r in console.execute(
        "SELECT glob FROM protected_path_floor WHERE repo = %s",
        (REPO,)).fetchall()]


def _row(paths, **over):
    c = {"id": 900, "disposition": "PENDING", "batch_id": 1, "repo": REPO,
         "suggested_paths": list(paths)}
    c.update(over)
    return c


def _g(candidate, console, **over):
    kw = {"newest_batch": candidate["batch_id"], "live_tasks": [],
          "prior_failures": 0, "writables": _writables(),
          "floor": _floor(console)}
    kw.update(over)
    return rank.gate(candidate, **kw)


class TestWorkThatSpansTwoContracts:
    def test_one_sided_backend_work_is_eligible(self, console):
        """The gate must not hold ordinary work. Paths taken from the real
        deadly-digital-platform-api.yaml writable list."""
        g = _g(_row(["api/analytics/routes/orders.py",
                      "api/analytics/services/order_query.py"]), console)
        assert g["rule"] not in ("spans_contracts", "unwritable_path",
                                 "protected_path"), g["detail"]

    def test_one_sided_frontend_work_is_eligible(self, console):
        g = _g(_row(["platform/app/(dashboard)/analytics/orders/page.tsx",
                      "platform/app/api/analytics/orders/route.ts"]), console)
        assert g["rule"] not in ("spans_contracts", "unwritable_path",
                                 "protected_path"), g["detail"]

    def test_work_needing_both_halves_is_held(self, console):
        g = _g(_row(["api/analytics/routes/dashboard.py",
                      "platform/app/(dashboard)/analytics/page.tsx"]), console)
        assert not g["eligible"]
        assert g["rule"] == "spans_contracts"

    def test_the_refusal_names_what_is_left_over(self, console):
        """Naming the contracts alone does not tell a reader how to split the
        candidate. Naming the remainder does."""
        g = _g(_row(["api/analytics/routes/dashboard.py",
                      "platform/app/(dashboard)/analytics/page.tsx"]), console)
        assert g["not_covered"] == ["api/analytics/routes/dashboard.py"] or \
            g["not_covered"] == ["platform/app/(dashboard)/analytics/page.tsx"]
        assert "task 28" in g["detail"]

    def test_it_withholds_the_approval_and_not_the_candidate(self, console):
        """Same shape as the repeat-failure stop: the row stays PENDING and a
        person may still tick it in the console having seen both halves."""
        g = _g(_row(["api/analytics/routes/dashboard.py",
                      "platform/app/(dashboard)/analytics/page.tsx"]), console)
        assert g["eligible"] is False
        assert "paths" in g and "covered_by" in g


class TestAPathNoContractCovers:
    def test_a_directory_rather_than_a_file_is_its_own_rule(self, console):
        """The producer writes `api/analytics/routes` on four open rows. That
        is a candidate to rewrite, not work to split, so it must not report
        spans_contracts and send the reader to the wrong repair."""
        g = _g(_row(["api/analytics/routes"]), console)
        assert g["rule"] == "unwritable_path"

    def test_a_file_outside_every_boundary_is_held(self, console):
        g = _g(_row(["platform/app/(dashboard)/segments/builder/page.tsx"]),
               console)
        assert g["rule"] == "unwritable_path"


class TestAPathTheFleetMayNeverWrite:
    """c35 and c27, and the reason is stronger than gates 6's.

    A migration is on protected_path_floor and is console/autodeploy.py's
    third refusal: deploy.sh migrates before the code swap, and a migration is
    the one action here git does not make reversible. No contract can make it
    writable, so this is not unattended work however the candidate is cut.
    """

    def test_a_migration_is_held_and_reported_as_its_own_rule(self, console):
        g = _g(_row(["api/analytics/routes/products.py",
                      "api/analytics/migrations/versions/v0008_x.py"]), console)
        assert g["rule"] == "protected_path"

    def test_the_floor_is_checked_before_the_contract_coverage(self, console):
        """A row that is BOTH two-sided and names a migration must report the
        floor: splitting it would not help."""
        g = _g(_row(["api/analytics/migrations/versions/v0008_x.py",
                      "platform/app/(dashboard)/analytics/products/page.tsx"]),
               console)
        assert g["rule"] == "protected_path"

    def test_c35_on_the_live_row_if_it_is_here(self, console):
        row = console.execute(
            "SELECT * FROM candidates WHERE id = 35").fetchone()
        if row is None:
            pytest.skip("candidate 35 is not in this database")
        g = _g(dict(row), console, newest_batch=row["batch_id"])
        assert g["rule"] == "protected_path", g["detail"]


class TestTheGateStaysPure:
    def test_omitting_the_inputs_skips_the_gates(self, console):
        """A caller that does not supply them is asking a narrower question.
        Reading the contracts directory here instead would make the answer
        depend on when it was asked."""
        both = _row(["api/analytics/routes/dashboard.py",
                      "platform/app/(dashboard)/analytics/page.tsx"])
        g = rank.gate(both, newest_batch=1, live_tasks=[], prior_failures=0)
        assert g["rule"] not in ("spans_contracts", "unwritable_path",
                                 "protected_path")

    def test_the_earlier_gates_still_win(self, console):
        """A row held by gate 3 today must keep reporting gate 3, or a rule
        change reads as a behaviour change in the brief."""
        both = _row(["api/analytics/routes/dashboard.py",
                      "platform/app/(dashboard)/analytics/page.tsx"])
        g = _g(both, console, live_tasks=[{
            "id": 7, "status": "QUEUED", "title": "t", "repo": REPO,
            "spec_md": "x", "acceptance_contract": {
                "writable_paths": ["api/analytics/routes/dashboard.py"]}}])
        assert g["rule"] == "path_overlap"

    def test_the_repeat_stop_still_wins(self, console):
        both = _row(["api/analytics/routes/dashboard.py",
                      "platform/app/(dashboard)/analytics/page.tsx"])
        g = _g(both, console, prior_failures=rank.REPEAT_FAILURE_STOP)
        assert g["rule"] == "repeat_failure"


class TestTheGateAndAutoqueueAgree:
    """rank._inside is a copy of autoqueue._inside, and a copy is only
    acceptable if something asserts they answer the same. If they diverge,
    the gate approves work the accept route then refuses -- after the spec
    has been written and paid for."""

    def test_they_answer_the_same_on_every_real_writable_glob(self):
        from console import autoqueue
        probes = ["api/analytics/routes/orders.py",
                  "api/analytics/routes",
                  "api/analytics/migrations/versions/v0008_x.py",
                  "platform/app/(dashboard)/analytics/page.tsx",
                  "platform/app/(dashboard)/segments/builder/page.tsx",
                  "platform/components/layout/Sidebar.tsx",
                  "drafts/a.md", ""]
        for _name, globs in rank.contract_writables(REPO):
            for p in probes:
                assert rank._inside(p, globs) == autoqueue._inside(p, list(globs)), \
                    (p, _name)


class TestOnlyAProducerBatchSupersedes:
    """034. Gate 2's argument is "the newer batch re-verified these claims
    against a later sha", and only a candidate_producer run does that.

    On 10 Sep 2026 batch 11 -- one candidate, written by hand from a draft,
    its own note saying "NOT A PRODUCER BATCH" -- was the newest, so gate 2
    reported all twenty real candidates as superseded and the first live
    sweep would have approved nothing and looked like an ordinary quiet
    night.
    """

    def test_a_hand_made_batch_does_not_supersede_a_produced_one(
            self, dsns, console, admin):
        _pool(admin)
        produced = _batch(console)
        cid = _cand(console, produced, title="CSV export of the order list")
        # Newer, higher id, and nothing produced it.
        _batch(console, doc="drafts/one-row.md", producer=False)
        p = autoapprove.plan()
        row = next(r for r in p["ranked"] if r["candidate_id"] == cid)
        assert row["rule"] != "older_batch", row["detail"]

    def test_a_newer_produced_batch_still_supersedes(
            self, dsns, console, admin):
        """The gate must keep working. This is the property 034 preserves."""
        _pool(admin)
        old, new = _batch(console), _batch(console, doc="research/b.md")
        stale = _cand(console, old, title="CSV export of the order list")
        _cand(console, new, title="CSV export, honouring the filters")
        p = autoapprove.plan()
        assert next(r for r in p["ranked"]
                    if r["candidate_id"] == stale)["rule"] == "older_batch"

    def test_no_producer_batch_at_all_supersedes_nobody(self, dsns, console,
                                                        admin):
        """Supersession is the whole content of the gate. With nothing to
        have re-verified anything, holding every row would shut the pool on
        the absence of a thing."""
        _pool(admin)
        b = _batch(console, producer=False)
        cid = _cand(console, b)
        p = autoapprove.plan()
        row = next(r for r in p["ranked"] if r["candidate_id"] == cid)
        assert row["rule"] != "older_batch", row["detail"]
