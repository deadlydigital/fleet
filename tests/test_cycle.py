"""The observation-only cycle.

What is being tested is mostly restraint: that it says at most five things,
that it says nothing it said recently, that it does not compute a finding
from stale evidence, that it never dresses an observation up as advice, and
that everything it cut is printed rather than dropped quietly.
"""
from __future__ import annotations

import copy
import uuid
from datetime import timedelta

import pytest

from proposer import config
from proposer import cycle as cycle_module
from proposer.findings import KIND_OBSERVATION, KIND_RISK
from proposer.objectives import load as load_objectives
from support_proposals import (HEARTBEAT, RECONCILIATION, all_detectors_healthy,
                               arrange_issue, arrange_observations, arrange_run,
                               arrange_runs, insert_proposal, slot_ends)

OBJECTIVES_FILE = config.PROJECT_ROOT / "objectives-2026-Q4.yaml"


@pytest.fixture
def objectives():
    return load_objectives(OBJECTIVES_FILE)


@pytest.fixture
def cycle_config():
    return copy.deepcopy(config.load_cycle_config())


def healthy(admin, *, reconciliation_slots: int = 3, heartbeat_slots: int = 3):
    """The two detectors these tests reason about, plus every other one.

    The two are named because several tests vary their slot counts. Anything
    else in the registry just needs to not be the finding under test:
    `detector_no_successful_run` fires for any detector that has never closed
    OK, so a helper that named only these two stopped meaning "healthy" the
    moment 015 registered a third.
    """
    arrange_runs(admin, RECONCILIATION,
                 slot_ends(admin, RECONCILIATION, reconciliation_slots))
    arrange_runs(admin, HEARTBEAT, slot_ends(admin, HEARTBEAT, heartbeat_slots))
    for key in _other_detectors(admin):
        arrange_runs(admin, key, slot_ends(admin, key, 3))


def _other_detectors(admin):
    return [r["detector_key"] for r in admin.execute(
        "SELECT detector_key FROM detector_registry"
        " WHERE retired_at IS NULL AND detector_key NOT IN (%s, %s)"
        " ORDER BY detector_key", (RECONCILIATION, HEARTBEAT)).fetchall()]


def open_issue(admin, days: int = 30, **kwargs):
    """Open a long time and still being observed: the condition is present."""
    opened, now = admin.execute(
        "SELECT now() - %s * interval '1 day' AS opened, now() AS t",
        (days,)).fetchone().values()
    return arrange_issue(admin, first_seen=opened, last_seen=now, **kwargs)


def stuck_issue(admin, days: int = 30, **kwargs):
    """Open a long time and not observed since: it may have stopped, and
    nothing is in a position to say so."""
    when = admin.execute("SELECT now() - %s * interval '1 day' AS t",
                         (days,)).fetchone()["t"]
    return arrange_issue(admin, first_seen=when, last_seen=when, **kwargs)


def run(dsns, cycle_config, objectives, **kwargs):
    return cycle_module.run_cycle(cycle_config=cycle_config,
                                  objectives=objectives, **kwargs)


# ---- the findings themselves ----------------------------------------------

def test_an_issue_open_past_its_severity_threshold_is_reported(
        admin, dsns, cycle_config, objectives):
    healthy(admin)
    open_issue(admin, days=30, severity="CRITICAL")
    result = run(dsns, cycle_config, objectives, dry_run=True)

    titles = [f.title for f in result.proposed]
    assert any("has been open 30 days" in t for t in titles)


def test_an_issue_inside_its_threshold_is_not(admin, dsns, cycle_config,
                                              objectives):
    healthy(admin)
    open_issue(admin, days=1, severity="MEDIUM")   # threshold is 14 days
    result = run(dsns, cycle_config, objectives, dry_run=True)
    assert [f for f in result.proposed
            if f.finding_type == "issue_open_too_long"] == []


def test_a_detector_that_has_never_succeeded_is_reported(
        admin, dsns, cycle_config, objectives):
    """And is reported even though every other reading is unusable because of
    it -- that is the point of detector_health being current by construction."""
    # Every detector but the one under test. `detector_no_successful_run`
    # fires per detector, so leaving a third one silent would make this
    # assert 2 and read as a bug in the finding rather than in the fixture.
    all_detectors_healthy(admin, exclude=[RECONCILIATION])
    result = run(dsns, cycle_config, objectives, dry_run=True)

    found = [f for f in result.proposed
             if f.finding_type == "detector_no_successful_run"]
    assert len(found) == 1
    assert RECONCILIATION in found[0].title
    assert "never" in found[0].finding_key


def test_a_lapsed_detector_is_reported_with_the_cadences_it_has_missed(
        admin, dsns, cycle_config, objectives):
    all_detectors_healthy(admin, exclude=[RECONCILIATION])
    arrange_runs(admin, RECONCILIATION,
                 slot_ends(admin, RECONCILIATION, 2, skip_newest=20))
    result = run(dsns, cycle_config, objectives, dry_run=True)

    found = [f for f in result.proposed
             if f.finding_type == "detector_no_successful_run"]
    assert len(found) == 1
    assert "lapsed" in found[0].finding_key
    assert "cadences" in found[0].title


def test_untriaged_observations_are_reported_once_they_are_old_enough(
        admin, dsns, cycle_config, objectives):
    healthy(admin, reconciliation_slots=0)
    arrange_runs(admin, RECONCILIATION, slot_ends(admin, RECONCILIATION, 1))
    # An observation's observed_at is the run's window_end and is written by
    # the database, so the way to arrange an old observation is an old window.
    old_slot = slot_ends(admin, RECONCILIATION, 1, skip_newest=480)[0]
    arrange_observations(admin, RECONCILIATION, old_slot, count=3)

    result = run(dsns, cycle_config, objectives, dry_run=True)
    found = [f for f in result.proposed if f.finding_type == "untriaged_observations"]
    assert len(found) == 1
    assert "3 untriaged" in found[0].title


def test_a_coverage_gap_that_blocks_resolution_is_reported(
        admin, dsns, cycle_config, objectives):
    # The detector is healthy and enumerating tenant 2. Tenant 99's issue is
    # therefore not being covered by anything, which is the gap.
    healthy(admin)
    stuck_issue(admin, days=5, severity="LOW", subject_id="99")
    result = run(dsns, cycle_config, objectives, dry_run=True)

    found = [f for f in result.proposed if f.finding_type == "coverage_gap"]
    assert len(found) == 1
    assert "NO_CLEARING_RUNS" in found[0].title


def test_an_issue_that_is_both_old_and_stuck_is_reported_once(
        admin, dsns, cycle_config, objectives):
    """Two producers reach the same issue. It gets one of the five slots, not
    two, and the fold is printed rather than done quietly."""
    healthy(admin)
    stuck_issue(admin, days=30, severity="CRITICAL", subject_id="99")

    result = run(dsns, cycle_config, objectives, dry_run=True)
    assert [f.finding_type for f in result.computed] == ["coverage_gap"]
    assert any(kind == "issue_open_too_long" and "folded" in reason
               for kind, reason in result.skipped)


def test_a_rising_false_positive_rate_is_reported(admin, dsns, cycle_config,
                                                  objectives):
    healthy(admin, reconciliation_slots=0)
    arrange_runs(admin, RECONCILIATION, slot_ends(admin, RECONCILIATION, 1))
    # The window is 14 days, so 20 slots-of-a-day back lands in the prior
    # window and a recent slot lands in the current one.
    prior = slot_ends(admin, RECONCILIATION, 1, skip_newest=480)[0]
    recent = slot_ends(admin, RECONCILIATION, 1, skip_newest=1)[0]
    arrange_observations(admin, RECONCILIATION, prior, count=6, verdict="VALID")
    arrange_observations(admin, RECONCILIATION, recent, count=6,
                         verdict="FALSE_POSITIVE")

    result = run(dsns, cycle_config, objectives, dry_run=True)
    found = [f for f in result.proposed
             if f.finding_type == "false_positive_rate_rising"]
    assert len(found) == 1
    assert "0% to 100%" in found[0].title


def test_too_few_verdicts_is_reported_as_unknown_not_as_unchanged(
        admin, dsns, cycle_config, objectives):
    healthy(admin, reconciliation_slots=0)
    arrange_runs(admin, RECONCILIATION, slot_ends(admin, RECONCILIATION, 1))
    slot = slot_ends(admin, RECONCILIATION, 1, skip_newest=1)[0]
    arrange_observations(admin, RECONCILIATION, slot, count=2,
                         verdict="FALSE_POSITIVE")

    result = run(dsns, cycle_config, objectives, dry_run=True)
    assert not [f for f in result.proposed
                if f.finding_type == "false_positive_rate_rising"]
    assert any(kind == "false_positive_rate_rising" and "below the" in reason
               for kind, reason in result.skipped)


# ---- staleness ------------------------------------------------------------

def test_no_finding_is_computed_from_a_stale_reading(admin, dsns, cycle_config,
                                                     objectives):
    """The issue is thirty days old and would fire on any fresh reading. The
    detector behind it stopped a day ago, so the reading cannot be trusted to
    say the issue is still open, and the cycle says so instead of saying it."""
    arrange_runs(admin, HEARTBEAT, slot_ends(admin, HEARTBEAT, 3))
    arrange_runs(admin, RECONCILIATION,
                 slot_ends(admin, RECONCILIATION, 2, skip_newest=30))
    open_issue(admin, days=30, severity="CRITICAL")

    result = run(dsns, cycle_config, objectives, dry_run=True)

    assert not [f for f in result.proposed if f.finding_type == "issue_open_too_long"]
    assert any(kind == "issue_open_too_long" for kind, _ in result.skipped)
    assert result.adapter_output.stale


def test_a_stale_reading_is_named_in_the_report(admin, dsns, cycle_config,
                                               objectives):
    arrange_runs(admin, HEARTBEAT, slot_ends(admin, HEARTBEAT, 3))
    arrange_runs(admin, RECONCILIATION,
                 slot_ends(admin, RECONCILIATION, 2, skip_newest=30))
    result = run(dsns, cycle_config, objectives, dry_run=True)
    text = cycle_module.report(result, objectives)
    assert "STALE READINGS" in text


# ---- the cap --------------------------------------------------------------

def test_the_cap_is_five_and_the_rest_are_printed(admin, dsns, cycle_config,
                                                  objectives):
    healthy(admin)
    for n in range(8):
        open_issue(admin, days=30, subject_id=str(100 + n), severity="CRITICAL")

    result = run(dsns, cycle_config, objectives, dry_run=True)

    assert len(result.computed) == 8
    assert len(result.proposed) == cycle_module.MAX_ITEMS
    assert len(result.dropped) == 3

    text = cycle_module.report(result, objectives)
    assert "cut by the 5-item cap" in text
    for finding in result.dropped:
        assert finding.title in text


def test_the_database_would_refuse_a_sixth_even_if_the_cycle_tried(
        admin, dsns, cycle_config, objectives):
    """The cap is not the cycle's promise. It is the database's."""
    import psycopg
    from proposer.findings import Evidence, Finding

    healthy(admin)
    now = admin.execute("SELECT now() AS t").fetchone()["t"]
    findings = [
        Finding(finding_type="t", finding_key=f"k{n}",
                product="deadly_digital", area="deadly_digital",
                title="t", body="b", objective_ref="dd-trustworthy",
                evidence=(Evidence(adapter="detectors", query_key="open_issues",
                                   value={"n": n}, fetched_at=now,
                                   freshness_bound=admin.execute(
                                       "SELECT interval '1 hour' AS i"
                                   ).fetchone()["i"], stale=False),))
        for n in range(6)]
    with pytest.raises(psycopg.errors.CheckViolation):
        cycle_module.write(findings, uuid.uuid4(), dsns["proposer"])


# ---- ranking --------------------------------------------------------------

def test_ranking_is_by_objective_weight_and_nothing_else(
        admin, dsns, cycle_config, objectives):
    """Two findings of identical shape, one mapped to a 0.35 objective and one
    to a 0.15 objective. Weight decides, and nothing about severity does."""
    healthy(admin)
    cycle_config["objective_map"]["issue_open_too_long"]["MISSING_ANALYTICS_ORDER"] = \
        "dd-first-revenue"
    cycle_config["objective_map"]["issue_open_too_long"]["ORDER_FIELD_DRIFT"] = \
        "dd-trustworthy"
    # The lower-weighted one is the more severe, so a severity-aware ranking
    # would put it first.
    open_issue(admin, days=60, issue_type="MISSING_ANALYTICS_ORDER",
               subject_id="10", severity="LOW")
    open_issue(admin, days=60, issue_type="ORDER_FIELD_DRIFT",
               subject_id="11", severity="CRITICAL")

    result = run(dsns, cycle_config, objectives, dry_run=True)
    assert [f.objective_ref for f in result.proposed] == \
        ["dd-first-revenue", "dd-trustworthy"]


def test_a_risk_outranks_the_weighted_items(admin, dsns, cycle_config, objectives):
    """A risk has no objective and so cannot be weighed. It goes first, so the
    cap cannot silently drop something actively breaking."""
    healthy(admin)
    cycle_config["objective_map"]["issue_open_too_long"].pop("ORDER_FIELD_DRIFT", None)
    open_issue(admin, days=60, issue_type="MISSING_ANALYTICS_ORDER",
               subject_id="10", severity="CRITICAL")
    open_issue(admin, days=60, issue_type="ORDER_FIELD_DRIFT",
               subject_id="11", severity="LOW")

    result = run(dsns, cycle_config, objectives, dry_run=True)
    assert result.proposed[0].kind == KIND_RISK
    assert result.proposed[0].objective_ref is None


def test_ranking_is_stable_across_runs(admin, dsns, cycle_config, objectives):
    healthy(admin)
    for n in range(8):
        open_issue(admin, days=30, subject_id=str(200 + n), severity="CRITICAL")
    first = run(dsns, cycle_config, objectives, dry_run=True)
    second = run(dsns, cycle_config, objectives, dry_run=True)
    assert [f.finding_key for f in first.proposed] == \
           [f.finding_key for f in second.proposed]


# ---- objectives -----------------------------------------------------------

def test_every_proposal_names_an_objective_or_is_a_risk(
        admin, dsns, cycle_config, objectives):
    healthy(admin)
    open_issue(admin, days=30, severity="CRITICAL")
    result = run(dsns, cycle_config, objectives, dry_run=True)
    for finding in result.computed:
        assert finding.objective_ref is not None or finding.kind == KIND_RISK
        if finding.objective_ref is not None:
            assert objectives.contains(finding.objective_ref)


def test_an_unmapped_finding_becomes_a_risk(admin, dsns, cycle_config, objectives):
    healthy(admin)
    cycle_config["objective_map"]["issue_open_too_long"] = {}
    open_issue(admin, days=30, severity="CRITICAL")
    result = run(dsns, cycle_config, objectives, dry_run=True)
    assert result.proposed[0].kind == KIND_RISK
    assert "no objective is mapped" in result.proposed[0].body


def test_an_out_of_scope_product_is_demoted_to_a_risk(
        admin, dsns, cycle_config, objectives):
    healthy(admin)
    cycle_config["out_of_scope_products"] = ["deadly_digital"]
    open_issue(admin, days=30, severity="CRITICAL")
    result = run(dsns, cycle_config, objectives, dry_run=True)
    assert result.proposed[0].kind == KIND_RISK
    assert "out of scope" in result.proposed[0].body


def test_a_mapping_to_an_objective_that_does_not_exist_stops_the_cycle(
        admin, dsns, cycle_config, objectives):
    cycle_config["objective_map"]["issue_open_too_long"]["MISSING_ANALYTICS_ORDER"] = \
        "dd-imaginary"
    with pytest.raises(RuntimeError) as caught:
        run(dsns, cycle_config, objectives, dry_run=True)
    assert "dd-imaginary" in str(caught.value)


def test_objective_inactivity_cannot_fire_before_the_layer_is_old_enough(
        admin, dsns, cycle_config, objectives):
    healthy(admin)
    result = run(dsns, cycle_config, objectives, dry_run=True)
    assert not [f for f in result.computed
                if f.finding_type == "objective_no_activity"]
    assert any(kind == "objective_no_activity" and "switched on" in reason
               for kind, reason in result.skipped)


def test_objective_inactivity_fires_once_the_layer_has_history(
        admin, dsns, proposer, cycle_config, objectives):
    healthy(admin)
    long_ago = admin.execute("SELECT now() - interval '60 days' AS t").fetchone()["t"]
    insert_proposal(proposer, finding_key="ancient", created_at=long_ago,
                    objective_ref="dd-trustworthy")

    result = run(dsns, cycle_config, objectives, dry_run=True)
    inactive = {f.objective_ref for f in result.computed
                if f.finding_type == "objective_no_activity"}
    assert "dd-first-revenue" in inactive
    assert "dd-trustworthy" in inactive  # 60 days ago is not recent either


# ---- suppression ----------------------------------------------------------

def test_a_finding_already_proposed_is_not_proposed_again(
        admin, dsns, cycle_config, objectives):
    healthy(admin)
    open_issue(admin, days=30, severity="CRITICAL")

    first = run(dsns, cycle_config, objectives)
    assert len(first.proposed) == 1
    assert len(first.written) == 1

    second = run(dsns, cycle_config, objectives)
    assert second.proposed == []
    assert len(second.suppressed) == 1
    assert "suppressed, already proposed" in cycle_module.report(second, objectives)


def test_suppression_expires(admin, dsns, proposer, cycle_config, objectives):
    """Proposals are append-only, so the old row is arranged rather than aged."""
    healthy(admin)
    issue = open_issue(admin, days=30, severity="CRITICAL")
    long_ago = admin.execute("SELECT now() - interval '30 days' AS t").fetchone()["t"]
    key = f"issue_open_too_long:{issue['fingerprint']}"
    insert_proposal(proposer, finding_key=key, created_at=long_ago)

    again = run(dsns, cycle_config, objectives)
    assert key in [f.finding_key for f in again.proposed]
    assert again.suppressed == []


# ---- writing --------------------------------------------------------------

def test_the_cycle_writes_proposals_and_their_evidence(admin, dsns, cycle_config,
                                                       objectives):
    healthy(admin)
    open_issue(admin, days=30, severity="CRITICAL")
    result = run(dsns, cycle_config, objectives)

    row = admin.execute(
        """
        SELECT p.kind, p.objective_ref, p.est_effort, p.est_impact,
               p.confidence, p.cycle_id,
               (SELECT count(*) FROM proposal_evidence e
                 WHERE e.proposal_id = p.id) AS evidence
          FROM proposals p WHERE p.id = %s
        """, (result.written[0],)).fetchone()

    assert row["kind"] == KIND_OBSERVATION
    assert row["objective_ref"] == "dd-trustworthy"
    assert row["est_effort"] is None and row["est_impact"] is None
    assert row["evidence"] >= 1
    assert row["cycle_id"] == result.cycle_id


def test_evidence_records_the_bound_it_was_judged_by(admin, dsns, cycle_config,
                                                     objectives):
    healthy(admin)
    open_issue(admin, days=30, severity="CRITICAL")
    result = run(dsns, cycle_config, objectives)

    row = admin.execute("SELECT adapter, query_key, freshness_bound, stale, value "
                        "FROM proposal_evidence WHERE proposal_id = %s",
                        (result.written[0],)).fetchone()
    assert row["adapter"] == "detectors"
    assert row["query_key"] == "open_issues"
    assert row["stale"] is False
    assert row["freshness_bound"].total_seconds() > 0
    assert "threshold_seconds" in row["value"]


def test_a_dry_run_writes_nothing(admin, dsns, cycle_config, objectives):
    healthy(admin)
    open_issue(admin, days=30, severity="CRITICAL")
    result = run(dsns, cycle_config, objectives, dry_run=True)

    assert result.proposed
    assert result.written == []
    assert admin.execute("SELECT count(*) AS n FROM proposals").fetchone()["n"] == 0


def test_the_cycle_says_nothing_when_nothing_crossed_a_threshold(
        admin, dsns, cycle_config, objectives):
    healthy(admin)
    result = run(dsns, cycle_config, objectives)
    assert result.proposed == []
    assert "Nothing crossed a threshold" in cycle_module.report(result, objectives)


class TestHealthyIsHealthyAtEveryMinute:
    """The guard on the flake this suite had for nine minutes of every hour.

    THE BUG, because a fixed test with no record of what it was is a test
    somebody deletes. `arrange_run` defaulted `completed_at` to the slot end.
    `slot_ends` returns SETTLED slots, so with reconciliation's cadence 1h and
    settle_lag 15m the newest settled slot at HH:MM is:

        MM >= 15  ->  HH:00        age = MM
        MM <  15  ->  (HH-1):00    age = 60 + MM

    and the silence budget is cadence + grace = 65m. So `healthy()` produced a
    STALE reading whenever 60 + MM > 65 -- minutes :06 to :14 -- the readings
    the whole cycle rests on were dropped, and fifteen tests failed. Measured
    failing at :11, :12, :13 and passing at :16 and :35.

    A wall-clock-dependent test passes in CI most of the time and fails in the
    ten minutes somebody happens to push, which is the worst shape available.

    So this asserts the property directly, for all sixty minutes, using the
    registry's own geometry rather than a restatement of it. It is arithmetic
    on the schedule and does not run a cycle, so it cannot itself be flaky --
    and it fails loudly if anyone narrows `grace` far enough to reopen the gap.
    """

    #: The schedule geometry only. arrange_run()'s contribution -- how long
    #: after window_end it says a run completed -- is MEASURED from a real
    #: insert below rather than restated here. A guard that copied the formula
    #: would pass whether or not the fixture still used it, which is the one
    #: way this test could be worthless.
    GEOMETRY = """
    WITH reg AS (
        SELECT detector_key, schedule_epoch, cadence, settle_lag,
               cadence + grace AS budget
          FROM detector_registry WHERE retired_at IS NULL
    ), at AS (
        SELECT reg.*, date_trunc('hour', now()) + (mm || ' min')::interval AS fake_now, mm
          FROM reg, generate_series(0, 59) AS mm
    ), slot AS (
        SELECT at.*,
               schedule_epoch + floor(
                   extract(epoch FROM (fake_now - settle_lag - schedule_epoch))
                   / extract(epoch FROM cadence))::bigint * cadence AS slot_end
          FROM at
    )
    SELECT detector_key, mm, budget, fake_now, slot_end FROM slot
     ORDER BY detector_key, mm
    """

    def _offsets(self, admin):
        """What arrange_run ACTUALLY puts in completed_at, per detector.

        Inserted and read back, so this tracks the fixture rather than
        describing it. Revert arrange_run's default and these become zero and
        the sweep below fails, which is the whole point of measuring.
        """
        offsets = {}
        for key in (RECONCILIATION, HEARTBEAT):
            slot = slot_ends(admin, key, 1)[0]
            run_id = arrange_run(admin, key, slot)
            row = admin.execute(
                "SELECT completed_at - window_end AS offset FROM detector_runs"
                " WHERE id = %s", (run_id,)).fetchone()
            offsets[key] = row["offset"]
        return offsets

    def _ages(self, admin):
        offsets = self._offsets(admin)
        out = []
        for r in admin.execute(self.GEOMETRY).fetchall():
            offset = offsets.get(r["detector_key"])
            if offset is None:
                continue
            out.append({**r, "age": r["fake_now"] - (r["slot_end"] + offset)})
        return out

    def test_no_minute_of_the_hour_leaves_a_detector_stale(self, admin):
        rows = self._ages(admin)
        assert rows, "no active detectors in the registry to check"

        stale = [(r["detector_key"], r["mm"], r["age"], r["budget"])
                 for r in rows if r["age"] > r["budget"]]
        assert not stale, (
            "healthy() leaves a detector STALE at these minutes past the hour, "
            "so the proposer suite is flaky by wall clock: "
            + "; ".join(f"{k} at :{mm:02d} age {age} > budget {b}"
                        for k, mm, age, b in stale))

    def test_the_margin_is_stated_rather_than_assumed(self, admin):
        """How much room the fix actually has, made visible.

        The worst case is a slot that closed 59 minutes ago against a 65-minute
        budget. Six minutes is not much, and a reader tightening `grace` should
        find that out from this assertion rather than from a flaky suite.
        """
        rows = self._ages(admin)
        worst = max(rows, key=lambda r: r["age"] - r["budget"])
        margin = worst["budget"] - worst["age"]
        assert margin > timedelta(0), (
            f"{worst['detector_key']} at :{worst['mm']:02d} has no margin: "
            f"age {worst['age']} against budget {worst['budget']}")
        assert margin >= timedelta(minutes=5), (
            f"the freshest arrangement healthy() can make is only {margin} "
            f"inside {worst['detector_key']}'s silence budget "
            f"({worst['budget']}). That is too thin to rely on: widen the "
            f"budget, or make healthy() arrange a more recent completed_at.")
