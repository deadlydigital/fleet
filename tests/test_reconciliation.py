"""dd_analytics_reconciliation against the fixture gap."""
from __future__ import annotations

import pytest

from detectors import base, sqlfile
from detectors.emit import fingerprint
from support import observations, run_reconciliation, run_row, settled_slots

DETECTOR = "dd_analytics_reconciliation"
PRODUCT = "deadly_digital"


def fp(subject_id: str, observation_type: str) -> str:
    return fingerprint(DETECTOR, 1, PRODUCT, "tenant", subject_id, observation_type)


def test_known_gap_produces_one_observation_with_the_right_magnitude(fleet, dsns):
    """Per tenant, never per order: three missing orders are one observation."""
    result = run_reconciliation(fleet, dsns["dd"])

    missing = observations(fleet, result.run_id, "MISSING_ANALYTICS_ORDER")
    assert len(missing) == 1, "one issue per tenant, not one per order"
    row = missing[0]
    assert row["subject_type"] == "tenant"
    assert row["subject_id"] == "2"
    assert row["magnitude"] == 3
    assert row["unit"] == "orders"
    assert row["fingerprint"] == fp("2", "MISSING_ANALYTICS_ORDER")
    # Evidence: order ids and counts only, flat, capped at five.
    assert row["evidence_sample"] == {
        "sample_1": 2006, "sample_2": 2007, "sample_3": 2008,
        "sample_size": 3, "offending_count": 3}
    assert row["evidence_query_key"] == "missing_analytics_order"
    assert row["evidence_query_version"] == 1
    # Provenance is derived by the database, not asserted by the writer.
    assert row["detector_key"] == DETECTOR
    assert row["product"] == PRODUCT
    assert row["run_mode"] == "SCHEDULED"
    assert row["observed_at"] == run_row(fleet, result.run_id)["window_end"]

    issue = fleet.execute("SELECT * FROM issues WHERE fingerprint = %s",
                          (row["fingerprint"],)).fetchone()
    assert issue["status"] == "OPEN"
    assert issue["current_magnitude"] == 3
    assert issue["severity"] == "MEDIUM"      # routing_policy, not the detector
    assert issue["occurrence_count"] == 1


def test_all_four_invariants_and_a_clean_tenant(fleet, dsns):
    result = run_reconciliation(fleet, dsns["dd"])

    found = {(o["observation_type"], o["subject_id"]): o["magnitude"]
             for o in observations(fleet, result.run_id)}
    assert found == {
        ("MISSING_ANALYTICS_ORDER", "2"): 3,
        ("ORPHANED_ANALYTICS_ORDER", "2"): 1,
        ("ORDER_FIELD_DRIFT", "2"): 2,
        ("UNMATCHABLE_ORDER", "2"): 1,
    }, "tenant 1 reconciles exactly; float representation must not fake drift"

    # Severity is routed, and UNMATCHABLE_ORDER has no policy row yet.
    severities = {r["issue_type"]: r["severity"] for r in fleet.execute(
        "SELECT issue_type, severity FROM issues WHERE subject_id = '2'").fetchall()}
    assert severities["ORPHANED_ANALYTICS_ORDER"] == "HIGH"
    assert severities["ORDER_FIELD_DRIFT"] == "CRITICAL"
    assert severities["UNMATCHABLE_ORDER"] == "UNTRIAGED"


def test_inactive_tenant_is_never_enumerated(fleet, dsns):
    result = run_reconciliation(fleet, dsns["dd"])
    assert "tenant:4" not in result.subjects_evaluated
    assert "tenant:4" not in result.subjects_failed


def test_rerunning_the_same_window_creates_no_duplicate(fleet, dsns):
    slot = settled_slots(fleet, 1)[0]
    first = run_reconciliation(fleet, dsns["dd"], slot_end=slot)
    before = fleet.execute("SELECT count(*) AS n FROM observations").fetchone()["n"]

    second = run_reconciliation(fleet, dsns["dd"], slot_end=slot)

    assert second.run_id == first.run_id, "one logical run per scheduled window"
    assert second.status == "SKIPPED"
    after = fleet.execute("SELECT count(*) AS n FROM observations").fetchone()["n"]
    assert after == before
    assert run_row(fleet, first.run_id)["observations_created"] == before
    issue = fleet.execute(
        "SELECT occurrence_count FROM issues WHERE fingerprint = %s",
        (fp("2", "MISSING_ANALYTICS_ORDER"),)).fetchone()
    assert issue["occurrence_count"] == 1, "a re-run is not a new occurrence"


def test_enumeration_failure_is_error_with_no_observations(fleet, dsns, monkeypatch):
    """A failed query must never produce a zero-count observation."""
    real_load = sqlfile.load

    def broken(key, version=1):
        if key == "tenants_active":
            return sqlfile.Query(key, version,
                                 "SELECT id AS tenant_id FROM public.no_such_table")
        return real_load(key, version)

    monkeypatch.setattr(sqlfile, "load", broken)
    result = run_reconciliation(fleet, dsns["dd"])

    assert result.status == base.STATUS_ERROR
    assert result.observations_created == 0
    row = run_row(fleet, result.run_id)
    assert row["status"] == "ERROR"
    assert row["observations_created"] == 0
    assert row["completed_at"] is not None
    assert "enumeration failed" in row["error"]
    assert observations(fleet, result.run_id) == []


def test_failed_invariant_query_fails_the_subject_and_emits_nothing(
        fleet, dsns, monkeypatch):
    """Enumeration survived, so the run is PARTIAL, not ERROR -- and the
    broken invariant emits nothing at all rather than a count of zero."""
    real_load = sqlfile.load

    def broken(key, version=1):
        if key == "missing_analytics_order":
            # Fails for tenant 2 only, mid-snapshot, the way a real query does.
            return sqlfile.Query(key, version, """
                SELECT 0 / (CASE WHEN %(t)s = 2 THEN 0 ELSE 1 END) AS n
                 WHERE '{analytics_schema}' IS NOT NULL""")
        return real_load(key, version)

    monkeypatch.setattr(sqlfile, "load", broken)
    result = run_reconciliation(fleet, dsns["dd"])

    assert result.status == base.STATUS_PARTIAL
    assert "tenant:2" in result.subjects_failed
    assert "tenant:2" not in result.subjects_evaluated
    assert observations(fleet, result.run_id, "MISSING_ANALYTICS_ORDER") == []
    # The snapshot survived the failure: tenant 1 was still judged.
    assert "tenant:1" in result.subjects_evaluated


def test_missing_analytics_schema_is_partial_and_does_not_clear_issues(
        fleet, admin, dsns):
    """A tenant the run could not read must not clear that tenant's issues."""
    slots = settled_slots(fleet, 2)
    stale_fp = fp("3", "MISSING_ANALYTICS_ORDER")
    admin.execute(
        """
        INSERT INTO issues (fingerprint, product, issue_type, subject_type,
            subject_id, detector_key, issue_key_version, first_seen, last_seen,
            current_magnitude, current_unit, status, severity)
        VALUES (%s, 'deadly_digital', 'MISSING_ANALYTICS_ORDER', 'tenant', '3',
                %s, 1, %s, %s, 7, 'orders', 'OPEN', 'MEDIUM')
        """,
        (stale_fp, DETECTOR, slots[-1], slots[-1]))

    for slot in reversed(slots):
        result = run_reconciliation(fleet, dsns["dd"], slot_end=slot)
        assert result.status == base.STATUS_PARTIAL
        assert "tenant:3" in result.subjects_failed
        assert "tenant:3" not in result.subjects_evaluated, \
            "a subject must never be in both arrays"
        assert "tenant:5" in result.subjects_failed, "unreadable is also failed"
        assert "tenant:1" in result.subjects_evaluated

    # required_clear_runs covering runs have now happened, but none of them
    # looked at tenant 3, so the resolver must leave it alone.
    cleared = admin.execute("SELECT resolve_cleared_issues() AS n").fetchone()["n"]
    still_open = admin.execute("SELECT status FROM issues WHERE fingerprint = %s",
                               (stale_fp,)).fetchone()
    assert still_open["status"] == "OPEN"
    covered = admin.execute(
        """SELECT subject_horizon_covered(%s, 1, 'deadly_digital', 'tenant', '3',
                                          %s, %s, now()) AS ok""",
        (DETECTOR, slots[-1], slots[0])).fetchone()["ok"]
    assert covered is False
    assert cleared == 0


def test_crash_and_retry_reports_the_persisted_count(fleet, admin, dsns,
                                                     monkeypatch):
    """observations_created is recomputed, never carried in the process.

    The retry re-emits nothing (the idempotency indexes reject it), so an
    in-process counter would close the run claiming zero.
    """
    slot = settled_slots(fleet, 1)[0]

    # Attempt 1: the process dies before it can close the run.
    monkeypatch.setattr(base, "_close_run", lambda *a, **k: None)
    first = run_reconciliation(fleet, dsns["dd"], slot_end=slot)
    monkeypatch.undo()

    crashed = run_row(fleet, first.run_id)
    assert crashed["status"] == "RUNNING"
    assert crashed["observations_created"] == 0
    persisted = len(observations(fleet, first.run_id))
    assert persisted == 4

    # The instance is gone; only age is evidence of that.
    admin.execute("UPDATE detector_runs SET last_attempt_at = now() - interval '1 hour'"
                  " WHERE id = %s", (first.run_id,))

    second = run_reconciliation(fleet, dsns["dd"], slot_end=slot)

    assert second.run_id == first.run_id
    retried = run_row(fleet, second.run_id)
    assert retried["attempt_count"] == 2, "the window was reclaimed, not duplicated"
    assert retried["status"] == base.STATUS_PARTIAL
    distinct = fleet.execute(
        "SELECT count(DISTINCT fingerprint) AS n FROM observations"
        " WHERE detector_run_id = %s", (second.run_id,)).fetchone()["n"]
    assert retried["observations_created"] == persisted == distinct == 4
    assert second.observations_created == 4
    # And the retry did not double-count the issues.
    counts = fleet.execute(
        "SELECT DISTINCT occurrence_count FROM issues").fetchall()
    assert [r["occurrence_count"] for r in counts] == [1]


def test_evidence_sample_ids_are_identical_across_query_versions(dsns):
    """v2 added an OFFSET 0 planner fence. It must not change a single id.

    The fence stops the NOT EXISTS being pulled up into an anti-join, which
    is a planning change and nothing else -- but "nothing else" is the claim
    under test, so both versions are executed and compared.
    """
    import psycopg
    from psycopg.rows import dict_row

    from detectors.reconciliation import _load

    v1 = sqlfile.load("missing_analytics_order_sample", 1).bind_schema("analytics_2")
    v2 = sqlfile.load("missing_analytics_order_sample", 2).bind_schema("analytics_2")
    assert "OFFSET 0" in v2.sql and "OFFSET 0" not in v1.sql
    assert _load("missing_analytics_order_sample").version == 2, \
        "the detector must actually be running v2"

    with psycopg.connect(dsns["dd"], row_factory=dict_row) as conn:
        params = {"t": 2, "limit": 5}
        old = [r["offending_id"] for r in conn.execute(v1.sql, params).fetchall()]
        new = [r["offending_id"] for r in conn.execute(v2.sql, params).fetchall()]

    assert old, "the fixture must have offenders for this to prove anything"
    assert old == new
