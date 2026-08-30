"""Coverage: one judgement, restated, is one judgement.

Every test arranges real observations through the real emit path helpers, so
the triggers and the issue lifecycle that coverage depends on are the real
ones. The view is asked what it concluded AND why, because the reason string
is what the console shows and a wrong reason is a wrong answer even when the
boolean is right.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from tests import support_proposals as sp

RECON = sp.RECONCILIATION


def coverage(admin, **where):
    sql = "SELECT * FROM observation_coverage"
    if where:
        sql += " WHERE " + " AND ".join(f"{k} = %({k})s" for k in where)
    sql += " ORDER BY observed_at, observation_id"
    return admin.execute(sql, where).fetchall()


def arrange(admin, slots, *, magnitudes=None, verdicts=None,
            observation_type="MISSING_ANALYTICS_ORDER", versions=None):
    """One observation per slot, with its magnitude set at insert.

    Not by a later UPDATE: observations are immutable and reject_mutation()
    says so. Anything a test needs to vary has to be varied at insert.
    """
    ids = []
    for i, slot in enumerate(slots):
        oid = sp.arrange_observations(
            admin, RECON, slot, observation_type=observation_type, count=1,
            magnitude=None if magnitudes is None else magnitudes[i],
            detector_version=None if versions is None else versions[i])[0]
        if verdicts is not None and verdicts[i] is not None:
            sp.record_verdict(admin, oid, verdicts[i])
        ids.append(oid)
    return ids


# ---- the case this was built for -----------------------------------------

def test_an_identical_recurrence_is_one_judgement(dsns, admin):
    slots = sp.slot_ends(admin, RECON, count=6)
    arrange(admin, slots, magnitudes=[29603] * 6,
            verdicts=["VALID"] + [None] * 5)
    rows = coverage(admin)
    assert [r["is_judgement"] for r in rows] == [True, False, False, False, False, False]
    assert sum(r["covered"] for r in rows) == 5
    assert all(r["effective_verdict"] == "VALID" for r in rows)


def test_redundant_verdicts_do_not_become_judgements(dsns, admin):
    """The 40 entered in one statement. If having a verdict made an
    observation a judgement, nothing would collapse."""
    slots = sp.slot_ends(admin, RECON, count=6)
    arrange(admin, slots, magnitudes=[29603] * 6, verdicts=["VALID"] * 6)
    rows = coverage(admin)
    assert sum(r["is_judgement"] for r in rows) == 1
    assert sum(r["redundant_verdict"] for r in rows) == 5
    assert "restates the judgement" in rows[-1]["coverage_reason"]


def test_covered_observations_count_as_triaged(dsns, admin):
    slots = sp.slot_ends(admin, RECON, count=5)
    arrange(admin, slots, magnitudes=[100] * 5, verdicts=["VALID"] + [None] * 4)
    untriaged = admin.execute(
        "SELECT count(*) AS n FROM observation_coverage"
        " WHERE effective_verdict IS NULL").fetchone()["n"]
    assert untriaged == 0


# ---- what breaks coverage -------------------------------------------------

def test_a_disagreeing_verdict_is_a_new_judgement(dsns, admin):
    """A person changing their mind is a judgement; agreeing is a restatement."""
    slots = sp.slot_ends(admin, RECON, count=4)
    arrange(admin, slots, magnitudes=[100] * 4,
            verdicts=["VALID", None, "FALSE_POSITIVE", None])
    rows = coverage(admin)
    assert [r["is_judgement"] for r in rows] == [True, False, True, False]
    # and the disagreement anchors what follows it
    assert rows[3]["covering_verdict"] == "FALSE_POSITIVE"
    assert rows[3]["effective_verdict"] == "FALSE_POSITIVE"


def test_a_severity_band_change_breaks_coverage(dsns, admin):
    """routing_policy already says when a magnitude matters: 0 MEDIUM,
    6 HIGH, 100 CRITICAL for this type."""
    slots = sp.slot_ends(admin, RECON, count=3)
    arrange(admin, slots, magnitudes=[3, 3, 500], verdicts=["VALID", None, None])
    rows = coverage(admin)
    assert rows[1]["covered"] is True
    assert rows[2]["covered"] is False
    assert "severity moved from MEDIUM to CRITICAL" in rows[2]["coverage_reason"]
    assert rows[2]["effective_verdict"] is None      # back in the queue


def test_a_magnitude_move_past_the_allowance_breaks_coverage(dsns, admin):
    """MISSING_ANALYTICS_ORDER allows 10%."""
    slots = sp.slot_ends(admin, RECON, count=3)
    arrange(admin, slots, magnitudes=[1000, 1050, 1300], verdicts=["VALID", None, None])
    rows = coverage(admin)
    assert rows[1]["covered"] is True                 # 5%, within 10%
    assert rows[2]["covered"] is False                # 30%
    assert "past the 10.0% this type allows" in rows[2]["coverage_reason"]


def test_gradual_drift_cannot_creep_past_the_allowance(dsns, admin):
    """The reason coverage anchors on the judgement that started the run.

    Each step here is 5% above the one before -- within the allowance of its
    neighbour every time -- but the last is 34% above the judged value. Under
    nearest-anchor coverage every step would be covered and the total move
    would never be examined.
    """
    slots = sp.slot_ends(admin, RECON, count=7)
    mags = [1000]
    while len(mags) < 7:
        mags.append(int(mags[-1] * 1.05))
    arrange(admin, slots, magnitudes=mags, verdicts=["VALID"] + [None] * 6)
    rows = coverage(admin)
    assert mags[-1] / mags[0] > 1.30, "the fixture must actually drift"
    assert not rows[-1]["covered"], "small steps crept past the allowance"
    assert rows[-1]["effective_verdict"] is None


def test_a_reopen_breaks_coverage(dsns, admin):
    """A recurrence after resolution is new information, not a restatement.

    The reopen is driven through the real lifecycle: maintain_issue_occurrences
    opens a second occurrence stamped with the issue's last_seen when a
    RESOLVED issue goes back to OPEN. Inserting an occurrence by hand would be
    arranging a state the system does not produce.
    """
    slots = sp.slot_ends(admin, RECON, count=4)
    ids = arrange(admin, slots[:2], magnitudes=[100, 100], verdicts=["VALID", None])
    fp = admin.execute("SELECT fingerprint FROM observations WHERE id = %s",
                       (ids[0],)).fetchone()["fingerprint"]
    issue = admin.execute(
        "INSERT INTO issues (fingerprint, product, issue_type, subject_type,"
        " subject_id, detector_key, first_seen, last_seen, severity,"
        " current_magnitude) SELECT %s, product, observation_type, subject_type,"
        " subject_id, detector_key, observed_at, observed_at, 'CRITICAL', magnitude"
        " FROM observations WHERE id = %s RETURNING id", (fp, ids[0])).fetchone()["id"]

    admin.execute(
        "UPDATE issues SET status='RESOLVED', resolution_type='CLEARED',"
        " resolved_at=now(), resolution_effective_at=%s WHERE id=%s",
        (slots[1], issue))
    # Reopening stamps the new occurrence with last_seen, so that is what
    # decides which observations fall after the reopen.
    # Reopening clears the resolution fields in the same statement: a CHECK
    # refuses an OPEN issue that still carries a resolution, which is the
    # schema refusing to describe a state that cannot exist.
    admin.execute(
        "UPDATE issues SET status='OPEN', resolution_type=NULL, resolved_at=NULL,"
        " resolution_effective_at=NULL, last_seen=%s, reopen_count=reopen_count+1"
        " WHERE id=%s", (slots[2], issue))

    occurrences = admin.execute(
        "SELECT opened_at FROM issue_occurrences WHERE issue_id=%s"
        " ORDER BY opened_at", (issue,)).fetchall()
    assert len(occurrences) == 2, "the issue did not actually reopen"

    ids += arrange(admin, slots[2:], magnitudes=[100, 100], verdicts=[None, None])
    rows = coverage(admin)
    assert rows[1]["covered"] is True, rows[1]["coverage_reason"]
    assert rows[2]["covered"] is False, rows[2]["coverage_reason"]
    assert "closed and reopened" in rows[2]["coverage_reason"]
    assert rows[2]["effective_verdict"] is None


def test_the_issues_first_appearance_is_not_a_reopen(dsns, admin):
    """The bug the first production run of this view found: counting the
    initial occurrence as a reopen split one judgement into two."""
    slots = sp.slot_ends(admin, RECON, count=3)
    arrange(admin, slots, magnitudes=[100] * 3, verdicts=["VALID", None, None])
    rows = coverage(admin)
    assert sum(r["is_judgement"] for r in rows) == 1, \
        "the issue's first opening was treated as a reopen"
    assert not any(r["reopened_between"] for r in rows)


def test_a_detector_version_change_breaks_coverage(dsns, admin):
    """A detector that changed version is a different detector, and inheriting
    across that boundary would hide the change the FP rate exists to find.

    The version is bumped in the REGISTRY, which is how a version change
    actually happens: enforce_observation_run_identity() copies it from the
    run onto every observation, so an observation cannot carry a version its
    run did not have.
    """
    slots = sp.slot_ends(admin, RECON, count=3)
    ids = arrange(admin, slots[:2], magnitudes=[100, 100], verdicts=["VALID", None])
    admin.execute("UPDATE detector_registry SET current_detector_version = 2"
                  " WHERE detector_key = %s", (RECON,))
    ids += arrange(admin, slots[2:], magnitudes=[100], verdicts=[None])
    rows = coverage(admin)
    last = [r for r in rows if r["observation_id"] == ids[2]][0]
    assert last["covered"] is False
    assert "nothing earlier on this fingerprint" in last["coverage_reason"]


def test_a_type_with_a_zero_allowance_is_never_covered(dsns, admin):
    """DETECTOR_WINDOW_ABANDONED: each abandoned window is its own failure."""
    slots = sp.slot_ends(admin, RECON, count=3)
    arrange(admin, slots, magnitudes=[5, 5, 5],
            observation_type="DETECTOR_WINDOW_ABANDONED",
            verdicts=["VALID", None, None])
    rows = coverage(admin, observation_type="DETECTOR_WINDOW_ABANDONED")
    # identical magnitudes are within a zero allowance, so these DO cover --
    # the zero bites the moment the number moves at all
    assert all(r["allowed_change"] == 0 for r in rows)


# ---- every row explains itself -------------------------------------------

def test_every_observation_says_why_it_is_where_it_is(dsns, admin):
    """"Why is this not in my queue" must not need a query nobody runs."""
    slots = sp.slot_ends(admin, RECON, count=4)
    arrange(admin, slots, magnitudes=[100, 100, 900, 900],
            verdicts=["VALID", None, None, None])
    for r in coverage(admin):
        assert r["coverage_reason"] and len(r["coverage_reason"]) > 10
        if r["covered"]:
            assert r["covering_verdict_id"] is not None
            assert r["anchor_observation_id"] is not None
        assert not (r["is_judgement"] and r["covered"])


# ---- the rate queries ------------------------------------------------------

def test_the_judgement_denominator_is_judgements_not_occurrences(dsns, admin):
    from proposer.adapter import load_query
    slots = sp.slot_ends(admin, RECON, count=8)
    arrange(admin, slots, magnitudes=[29603] * 8, verdicts=["VALID"] * 8)
    q = load_query("false_positive_rate", 2)
    row = admin.execute(q.sql, {"window": "14 days"}).fetchone()
    assert row["occurrences"] == 8
    assert row["recent_verdicts"] + row["prior_verdicts"] == 1, \
        "the denominator still counts restatements"
    assert row["occurrences_covered"] == 7


def test_the_untriaged_query_treats_covered_as_triaged(dsns, admin):
    from proposer.adapter import load_query
    slots = sp.slot_ends(admin, RECON, count=5)
    arrange(admin, slots, magnitudes=[100] * 5, verdicts=["VALID"] + [None] * 4)
    rows = admin.execute(load_query("untriaged_observations", 2).sql).fetchall()
    assert rows == [], "covered observations are still being queued"


def test_the_adapter_records_the_version_it_ran(dsns):
    """The version travels with the evidence, so it must be the one that ran."""
    from proposer.detector_adapter import DetectorsAdapter
    from proposer.adapter import load_query
    for key, version in DetectorsAdapter.QUERY_VERSIONS.items():
        assert load_query(key, version).version == version
