"""The brief's Sentry claim, and the sentence it must never print.

    "no unresolved issues" can never be printed while the query cannot run.

The claim is derived from the newest detector RUN and its status, never from
the newest OBSERVATION. That distinction is the whole guarantee, and
`test_a_stale_zero_is_not_printed_when_the_newest_run_failed` is the case it
exists for: a real zero, correctly recorded yesterday, describing a moment
nobody asked about. It would render as reassurance on the morning the token
expired.
"""
from __future__ import annotations

from datetime import timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from brief import sources as S
from brief.claims import Claim
from brief.pass_ import _sentry_claims
from support_proposals import slot_ends

DETECTOR = "dd_api_errors"
PROJECT = "sentry_project:deadly-digital-api"
KEY = "sentry.unresolved_issues"


def reader(dsns):
    """Connected EXACTLY as `run_pass` connects, and that is load-bearing.

    `run_pass` passes no `row_factory`, so `S.row()` yields TUPLES. The first
    version of this file used `dict_row`, and `_sentry_claims`' positional
    unpack then bound the column NAMES instead of the values — `status`
    became the string "status", every claim came back UNCOMPUTED, and the
    guarantee under test appeared to hold for entirely the wrong reason.

    A harness that connects differently from production tests a different
    program. This one does not.
    """
    conn = psycopg.connect(dsns["fleet"], autocommit=False)
    conn.read_only = True
    return conn, S.Reader(conn, "dd_detector_login@fleet")


def claim(dsns) -> Claim:
    conn, r = reader(dsns)
    try:
        out = _sentry_claims(r)
    finally:
        conn.close()
    assert len(out) == 1
    return out[0]


def arrange(admin, slot, *, status="OK", failed=None, unresolved=None,
            completed_at=None, worst="DD-API-1"):
    """One closed run, optionally carrying an observation."""
    reg = admin.execute(
        "SELECT * FROM detector_registry WHERE detector_key = %s",
        (DETECTOR,)).fetchone()
    run_id = admin.execute(
        """
        INSERT INTO detector_runs
            (detector_key, detector_version, issue_key_version, product,
             semantics, run_mode, coverage_mode, subjects_evaluated,
             subjects_failed, window_start, window_end, started_at,
             completed_at, status, error)
        VALUES (%(k)s,%(dv)s,%(v)s,%(p)s,%(sem)s,'SCHEDULED',%(cov)s,
                %(subj)s,%(failed)s,%(ws)s,%(we)s,%(we)s,
                coalesce(%(done)s, %(we)s + %(settle)s), 'RUNNING', %(err)s)
        RETURNING id
        """,
        {"k": DETECTOR, "dv": reg["current_detector_version"],
         "v": reg["issue_key_version"], "p": reg["product"],
         "sem": reg["semantics"], "cov": reg["coverage_mode"],
         # An EMPTY array, not NULL: `coverage_enumerated_ck` requires
         # ENUMERATED OK/PARTIAL runs to state what they evaluated, and
         # `base._close_run` writes `[]` for a run whose only subject failed.
         # NULL would arrange a row the real detector cannot produce.
         "subj": [] if failed else [PROJECT],
         "failed": [PROJECT] if failed else None,
         "ws": slot - reg["evaluation_window"], "we": slot,
         "settle": reg["settle_lag"], "done": completed_at,
         "err": failed}).fetchone()["id"]

    if unresolved is not None:
        admin.execute(
            """
            INSERT INTO observations
                (detector_run_id, detector_key, detector_version,
                 issue_key_version, product, run_mode, observation_type,
                 observed_at, subject_type, subject_id, fingerprint,
                 magnitude, unit, evidence_sample)
            VALUES (%(r)s,%(k)s,%(dv)s,%(v)s,%(p)s,'SCHEDULED',
                    'SENTRY_UNRESOLVED_ISSUES', %(we)s, 'sentry_project',
                    'deadly-digital-api', md5(random()::text),
                    %(mag)s, 'issues', %(sample)s)
            """,
            {"r": run_id, "k": DETECTOR, "dv": reg["current_detector_version"],
             "v": reg["issue_key_version"], "p": reg["product"], "we": slot,
             "mag": unresolved,
             "sample": psycopg.types.json.Jsonb(
                 {"unresolved_issues": unresolved, "worst_short_id": worst})})

    # Closed AFTER its observations, because that is the order the detector
    # works in and `enforce_observation_run_identity()` refuses any other:
    # a run that is already OK cannot accept observations.
    admin.execute("UPDATE detector_runs SET status = %s WHERE id = %s",
                  (status, run_id))
    return run_id


def slots(admin, n=3):
    return slot_ends(admin, DETECTOR, n)


# ---- the guarantee ---------------------------------------------------------

class TestAZeroIsNeverPrintedFromAReadThatDidNotHappen:

    def test_a_stale_zero_is_not_printed_when_the_newest_run_failed(
            self, admin, dsns):
        """THE TEST THIS FILE EXISTS FOR.

        Yesterday's run read Sentry cleanly and recorded nothing unresolved.
        Today's could not read it at all. Reporting yesterday's zero is
        reporting a real number about a moment nobody asked about, and it
        renders as "everything is fine" on the morning it is least true.
        """
        older, newer = slots(admin, 2)
        arrange(admin, older, status="OK", unresolved=None)   # a clean read
        arrange(admin, newer, status="PARTIAL",
                failed="1 subject(s) failed: %s -- SentryUnavailable: "
                       "HTTP 401 from Sentry" % PROJECT)

        c = claim(dsns)
        assert c.status == "UNCOMPUTED"
        assert c.value_num is None
        assert "401" in c.uncomputed_reason
        assert "PARTIAL" in c.uncomputed_reason

    def test_the_reason_names_the_subject_that_could_not_be_read(
            self, admin, dsns):
        arrange(admin, slots(admin, 1)[0], status="PARTIAL",
                failed="1 subject(s) failed: %s -- boom" % PROJECT)
        c = claim(dsns)
        assert PROJECT in c.uncomputed_reason

    def test_an_errored_run_is_uncomputed_too(self, admin, dsns):
        arrange(admin, slots(admin, 1)[0], status="ERROR",
                failed="enumeration failed: SENTRY_ORG is not set")
        c = claim(dsns)
        assert c.status == "UNCOMPUTED"
        assert "SENTRY_ORG" in c.uncomputed_reason

    def test_never_having_run_is_uncomputed_and_says_it_is_not_a_zero(
            self, admin, dsns):
        c = claim(dsns)
        assert c.status == "UNCOMPUTED"
        assert "not a report of zero errors" in c.uncomputed_reason

    def test_a_run_older_than_cadence_and_grace_is_not_todays_answer(
            self, admin, dsns):
        """An on-grid slot, far enough back. `enforce_scheduled_run_origin()`
        refuses an arbitrary timestamp, and rightly — a window nothing could
        have scheduled is a history the detector cannot produce."""
        old = slot_ends(admin, DETECTOR, 1, skip_newest=6)[0]
        arrange(admin, old, status="OK", unresolved=None)
        c = claim(dsns)
        assert c.status == "UNCOMPUTED"
        assert "cadence and grace" in c.uncomputed_reason


# ---- and what a good read does print ---------------------------------------

class TestWhatAnEstablishedReadReports:

    def test_a_clean_read_reports_zero_because_the_run_established_it(
            self, admin, dsns):
        """The only route to a zero: an OK run, fresh, with no observation."""
        arrange(admin, slots(admin, 1)[0], status="OK", unresolved=None)
        c = claim(dsns)
        assert c.status == "COMPUTED"
        assert c.value_num == 0
        assert "0 unresolved Sentry issues" in c.statement

    def test_unresolved_issues_are_counted_and_the_worst_is_named(
            self, admin, dsns):
        arrange(admin, slots(admin, 1)[0], status="OK", unresolved=7,
                worst="DD-API-9F")
        c = claim(dsns)
        assert c.status == "COMPUTED"
        assert c.value_num == 7
        assert "DD-API-9F" in c.statement

    def test_as_of_is_when_the_run_established_it_not_when_the_brief_read_it(
            self, admin, dsns):
        run_id = arrange(admin, slots(admin, 1)[0], status="OK", unresolved=2)
        completed = admin.execute(
            "SELECT completed_at FROM detector_runs WHERE id = %s",
            (run_id,)).fetchone()["completed_at"]
        c = claim(dsns)
        assert c.as_of == completed

    def test_a_newer_good_run_supersedes_an_older_failure(self, admin, dsns):
        older, newer = slots(admin, 2)
        arrange(admin, older, status="PARTIAL", failed="was broken")
        arrange(admin, newer, status="OK", unresolved=3)
        c = claim(dsns)
        assert c.status == "COMPUTED" and c.value_num == 3


class TestThereIsNoNumberForARendererToPrint:
    """The guarantee held one layer lower than the renderer.

    Asserting on rendered markdown would test the renderer's formatting; the
    property that matters is that a failed read produces a claim carrying no
    value at all, so no renderer — this one or a later one — has a number
    available to print.
    """

    def test_a_failed_read_carries_no_value_in_either_field(self, admin, dsns):
        arrange(admin, slots(admin, 1)[0], status="PARTIAL",
                failed="1 subject(s) failed: %s -- HTTP 401" % PROJECT)
        c = claim(dsns)
        assert c.status == "UNCOMPUTED"
        assert c.value_num is None and c.value_text is None
        assert c.section == "UNCOMPUTED"

    def test_the_claim_constructor_would_refuse_a_valued_uncomputed(self):
        """Belt and braces: `Claim.uncomputed` has no value parameter."""
        import inspect
        params = inspect.signature(Claim.uncomputed).parameters
        assert "value_num" not in params and "value_text" not in params
