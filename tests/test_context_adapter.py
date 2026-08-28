"""The detectors adapter: what it reports, and when it refuses to.

The adapter's job is to hand the cycle track 1's facts together with how old
they are. These tests are mostly about the second half, because the first
half is a SELECT and the second half is the part that decides whether a
morning's findings mean anything.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from proposer import adapter as adapter_module
from proposer.detector_adapter import (COVERAGE_GAPS, DETECTOR_HEALTH,
                                       FALSE_POSITIVE_RATE, OPEN_ISSUES,
                                       REGISTRY_GEOMETRY,
                                       UNTRIAGED_OBSERVATIONS,
                                       DetectorsAdapter)
from support_proposals import (HEARTBEAT, RECONCILIATION, arrange_issue,
                               arrange_observations, arrange_run, arrange_runs,
                               slot_ends)


def healthy(admin, *, reconciliation_slots: int = 3,
            heartbeat_slots: int = 3) -> None:
    """Both detectors running on schedule, which is what makes a reading fresh."""
    arrange_runs(admin, RECONCILIATION,
                 slot_ends(admin, RECONCILIATION, reconciliation_slots))
    arrange_runs(admin, HEARTBEAT, slot_ends(admin, HEARTBEAT, heartbeat_slots))


def read(reader, cycle_config=None):
    return DetectorsAdapter(cycle_config=cycle_config or _config()).read(reader)


def _config():
    from proposer import config
    return config.load_cycle_config()


# ---- shape ----------------------------------------------------------------

def test_every_reading_carries_a_fetch_time_and_a_declared_bound(admin, reader):
    healthy(admin)
    out = read(reader)
    expected = {REGISTRY_GEOMETRY, DETECTOR_HEALTH, OPEN_ISSUES,
                FALSE_POSITIVE_RATE, UNTRIAGED_OBSERVATIONS, COVERAGE_GAPS,
                "verdict_recency"}
    assert expected <= set(out.readings)
    for reading in out.readings.values():
        assert reading.fetched_at == out.fetched_at
        assert reading.freshness_bound > timedelta(0)
        assert reading.bound_source in ("detector_registry", "cycle.yaml")


def test_a_healthy_fleet_reads_fresh(admin, reader):
    healthy(admin)
    out = read(reader)
    assert out.stale == []
    assert out[OPEN_ISSUES].status == adapter_module.FRESH


# ---- freshness ------------------------------------------------------------

def test_a_detector_that_never_succeeded_makes_dependent_readings_unusable(
        admin, reader):
    """No successful run is not the same as an old one, and must not read as
    'no data', which is what an empty issues table also looks like."""
    arrange_runs(admin, HEARTBEAT, slot_ends(admin, HEARTBEAT, 3))
    # reconciliation has never produced anything at all
    out = read(reader)

    issues = out[OPEN_ISSUES]
    assert issues.status == adapter_module.STALE
    assert not issues.usable
    assert RECONCILIATION in issues.data_missing_reason


def test_a_lapsed_detector_makes_dependent_readings_stale(admin, reader):
    """The reconciliation detector last succeeded many cadences ago."""
    healthy(admin, reconciliation_slots=0)
    arrange_runs(admin, RECONCILIATION,
                 slot_ends(admin, RECONCILIATION, 2, skip_newest=20))
    out = read(reader)

    issues = out[OPEN_ISSUES]
    assert issues.status == adapter_module.STALE
    assert issues.age > issues.freshness_bound


def test_the_bound_is_set_by_the_detector_furthest_past_its_own_budget(
        admin, reader):
    """Not by the oldest timestamp.

    The heartbeat's budget is fifteen minutes and reconciliation's is over an
    hour. A heartbeat quiet for half an hour is further gone than a
    reconciliation quiet for the same half hour, even though their last
    successes are the same age -- and picking by timestamp would report
    whichever happened to be a minute older.
    """
    arrange_runs(admin, RECONCILIATION, slot_ends(admin, RECONCILIATION, 1))
    arrange_runs(admin, HEARTBEAT, slot_ends(admin, HEARTBEAT, 1, skip_newest=12))
    out = read(reader)

    issues = out[OPEN_ISSUES]
    assert issues.note.endswith(HEARTBEAT)
    assert issues.status == adapter_module.STALE


def test_detector_health_stays_readable_when_everything_else_is_stale(
        admin, reader):
    """The one reading that must survive an outage is the one that explains it."""
    out = read(reader)  # no runs at all
    health = out[DETECTOR_HEALTH]
    assert health.status == adapter_module.CURRENT_BY_CONSTRUCTION
    assert health.usable
    assert {r["detector_key"] for r in health.rows} == {RECONCILIATION, HEARTBEAT}
    assert all(r["successful_runs"] == 0 for r in health.rows)


def test_a_retired_detector_does_not_make_everything_stale(admin, reader):
    healthy(admin, reconciliation_slots=0)
    admin.execute("UPDATE detector_registry SET retired_at = now() "
                  "WHERE detector_key = %s", (RECONCILIATION,))
    out = read(reader)
    assert out[OPEN_ISSUES].status == adapter_module.FRESH


def test_a_detector_in_maintenance_does_not_make_everything_stale(admin, reader):
    healthy(admin, reconciliation_slots=0)
    admin.execute("UPDATE detector_registry "
                  "SET maintenance_until = now() + interval '1 day' "
                  "WHERE detector_key = %s", (RECONCILIATION,))
    out = read(reader)
    assert out[OPEN_ISSUES].status == adapter_module.FRESH


def test_the_false_positive_rate_ages_on_a_human_cadence(admin, reader):
    """It is only as fresh as the last verdict a person entered, so its bound
    comes from cycle.yaml and not from any detector's cadence."""
    healthy(admin)
    out = read(reader)
    rate = out[FALSE_POSITIVE_RATE]
    assert rate.bound_source == "cycle.yaml"
    assert rate.status == adapter_module.NO_DATA  # nobody has ruled on anything


# ---- content --------------------------------------------------------------

def test_open_issues_reports_severity_magnitude_occurrences_and_age(admin, reader):
    healthy(admin)
    arrange_issue(admin, severity="HIGH", magnitude=29603,
                  occurrence_count=4,
                  first_seen=admin.execute(
                      "SELECT now() - interval '9 days' AS t").fetchone()["t"])
    out = read(reader)

    row = out[OPEN_ISSUES].rows[0]
    assert row["severity"] == "HIGH"
    assert row["current_magnitude"] == 29603
    assert row["occurrence_count"] == 4
    assert row["age_seconds"] > 8 * 86400


def test_resolved_issues_are_not_reported_as_open(admin, reader):
    healthy(admin)
    issue = arrange_issue(admin)
    admin.execute("UPDATE issues SET status='RESOLVED', resolution_type='CLEARED', "
                  "resolved_at=now(), resolution_effective_at=now() WHERE id=%s",
                  (issue["id"],))
    out = read(reader)
    assert out[OPEN_ISSUES].rows == ()


def test_false_positive_rate_is_split_by_detector_and_observation_type(admin, reader):
    healthy(admin, reconciliation_slots=0)
    slots = slot_ends(admin, RECONCILIATION, 2)
    arrange_observations(admin, RECONCILIATION, slots[0], count=3,
                         verdict="FALSE_POSITIVE")
    arrange_observations(admin, RECONCILIATION, slots[1], count=2,
                         verdict="VALID")
    out = read(reader)

    rows = {(r["detector_key"], r["observation_type"]): r
            for r in out[FALSE_POSITIVE_RATE].rows}
    row = rows[(RECONCILIATION, "MISSING_ANALYTICS_ORDER")]
    assert row["verdicts"] == 5
    assert row["false_positives"] == 3


def test_untriaged_counts_only_what_has_no_verdict(admin, reader):
    healthy(admin, reconciliation_slots=0)
    slots = slot_ends(admin, RECONCILIATION, 2)
    arrange_observations(admin, RECONCILIATION, slots[0], count=2, verdict="VALID")
    arrange_observations(admin, RECONCILIATION, slots[1], count=3)
    out = read(reader)

    row = out[UNTRIAGED_OBSERVATIONS].rows[0]
    assert row["untriaged"] == 3


def test_coverage_gaps_says_why_an_issue_cannot_resolve(admin, reader):
    """An issue last seen long ago with no qualifying run since is blocked,
    and the reason is the one the resolver would hit."""
    healthy(admin, reconciliation_slots=0)
    arrange_runs(admin, RECONCILIATION,
                 slot_ends(admin, RECONCILIATION, 1, skip_newest=30))
    old = admin.execute("SELECT now() - interval '5 days' AS t").fetchone()["t"]
    arrange_issue(admin, first_seen=old, last_seen=old)

    out = read(reader)
    row = out[COVERAGE_GAPS].rows[0]
    assert row["still_observed"] is False
    assert row["eff"] is None
    assert row["qualifying_runs_since"] < row["required_clear_runs"]


def test_an_issue_still_being_observed_is_not_a_coverage_gap(admin, reader):
    healthy(admin)
    slots = slot_ends(admin, RECONCILIATION, 1)
    arrange_issue(admin, first_seen=slots[0], last_seen=slots[0])
    out = read(reader)
    assert out[COVERAGE_GAPS].rows[0]["still_observed"] is True


def test_the_reader_cannot_write_through_the_adapter_connection(reader):
    """Belt and braces: the role cannot write, and the session refuses to."""
    import psycopg
    with pytest.raises((psycopg.errors.InsufficientPrivilege,
                        psycopg.errors.ReadOnlySqlTransaction)):
        reader.execute("UPDATE issues SET severity = 'LOW'")
