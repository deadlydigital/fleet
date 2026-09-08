"""dd_api_errors, and the one thing it must never do.

**It must never report zero from a read it could not make.** Every test in the
first two classes is a different way of failing to read, and every one of them
must land as a FAILED SUBJECT rather than as a clean run — because a clean run
is what the brief turns into "no unresolved issues", and that sentence in front
of a live incident is the whole reason this detector was built with a token
rather than pointed at the DSN.

The HTTP layer is injected. What is under test is the detector's judgement
about what an answer means, not urllib.
"""
from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import psycopg
import pytest

from detectors import base
from detectors.sentry import SentryDetector, SentryUnavailable
from support_proposals import slot_ends

DETECTOR = "dd_api_errors"
PROJECT = "deadly-digital-api"
ORG = "deadly-digital"
SUBJECT = f"sentry_project:{PROJECT}"


def issue(n: int, *, events: int = 1, level: str = "error",
          project: str = PROJECT, lifetime: int | None = None):
    """One issue as the ORGANIZATION endpoint returns it.

    `project.slug` is what the detector groups on, and `count` is the
    WINDOWED figure with `lifetime.count` beside it -- the project endpoint
    returns neither, which is why it is not used.
    """
    return {"id": str(1000 + n), "shortId": f"DD-API-{n}", "level": level,
            "title": f"an error {n}", "culprit": "app.py in thing",
            "count": str(events), "userCount": 0,
            "project": {"slug": project},
            "lifetime": {"count": str(lifetime if lifetime is not None else events)},
            "firstSeen": "2026-09-08T09:00:00Z",
            "lastSeen": "2026-09-08T09:30:00Z"}


def detector(payload=None, *, raises=None, token="tok", org=ORG,
             projects=(PROJECT,), per_project=None):
    """Injected at the JSON layer, for tests about what an ANSWER means."""
    def fetch(url):
        if raises is not None:
            raise raises
        if per_project is not None:
            # ONE call returns every project; the detector groups by slug.
            flat = []
            for slug, body in per_project.items():
                for i in body:
                    flat.append({**i, "project": {"slug": slug}})
            return flat
        return payload
    return SentryDetector(token=token, org=org, projects=list(projects),
                          api_base="https://sentry.io/api/0", fetch=fetch)


def http_detector(monkeypatch, *, raises, token="tok"):
    """Injected at urlopen, so `_http_get` itself is under test.

    The HTTP-status reasoning — which codes are failures, and the hint that a
    404 is as often the wrong API base as a missing project — lives in
    `_http_get`. A stub at `fetch` replaces that method and would test
    nothing; the first version of these tests did exactly that and asserted a
    message the code never had the chance to produce.
    """
    def fake_urlopen(*a, **kw):
        raise raises
    monkeypatch.setattr("detectors.sentry.urllib.request.urlopen", fake_urlopen)
    return SentryDetector(token=token, org=ORG, projects=[PROJECT],
                          api_base="https://sentry.io/api/0")


def run(fleet, det, admin=None):
    return base.execute(det, fleet)


def observations(admin, run_id: int):
    return admin.execute(
        "SELECT * FROM observations WHERE detector_run_id = %s", (run_id,)
    ).fetchall()


# ---- a read that could not be made ----------------------------------------

class TestAFailedReadIsNeverAZero:
    """Each of these would, uncaught, produce an empty list of issues."""

    def test_a_missing_token_fails_the_subject(self, fleet, admin, dsns):
        """`token=""`, not `token=None`.

        The constructor reads `None` as "not supplied, go and look in the
        environment", so once a real token existed in .env this test started
        picking it up and closing OK. It began failing the moment the
        credential landed, which is the test being honest rather than the
        code changing — but the ambiguity is real, and an explicitly-absent
        token is the empty string.
        """
        result = run(fleet, detector([], token=""))
        assert result.status == base.STATUS_PARTIAL
        assert result.subjects_failed == [SUBJECT]
        assert result.observations_created == 0
        assert "ingest key" in (result.error or "")

    def test_an_unauthorised_token_fails_the_subject(self, fleet, admin, dsns,
                                                     monkeypatch):
        err = urllib.error.HTTPError(
            "u", 401, "Unauthorized", {}, BytesIO(b'{"detail":"invalid token"}'))
        result = run(fleet, http_detector(monkeypatch, raises=err))
        assert result.status == base.STATUS_PARTIAL
        assert result.subjects_failed == [SUBJECT]
        assert result.observations_created == 0
        assert "event:read" in (result.error or "")

    def test_a_404_names_the_api_base_because_that_is_usually_the_cause(
            self, fleet, admin, dsns, monkeypatch):
        """An EU org served from the global host 404s on a real project.

        Reported as "project not found" that costs an afternoon, so the
        message names the base it used.
        """
        err = urllib.error.HTTPError("u", 404, "Not Found", {}, BytesIO(b"{}"))
        result = run(fleet, http_detector(monkeypatch, raises=err))
        assert result.status == base.STATUS_PARTIAL
        assert "api base" in (result.error or "").lower()
        assert "sentry.io/api/0" in (result.error or "")

    def test_rate_limiting_fails_the_subject(self, fleet, admin, dsns,
                                             monkeypatch):
        err = urllib.error.HTTPError("u", 429, "Too Many", {}, BytesIO(b"{}"))
        result = run(fleet, http_detector(monkeypatch, raises=err))
        assert result.status == base.STATUS_PARTIAL
        assert result.observations_created == 0

    def test_an_unreachable_sentry_fails_the_subject(self, fleet, admin, dsns,
                                                     monkeypatch):
        result = run(fleet, http_detector(
            monkeypatch, raises=urllib.error.URLError("no route")))
        assert result.status == base.STATUS_PARTIAL
        assert result.observations_created == 0

    def test_a_response_that_is_not_a_list_fails_the_subject(
            self, fleet, admin, dsns):
        result = run(fleet, detector({"detail": "something else"}))
        assert result.status == base.STATUS_PARTIAL
        assert result.observations_created == 0


class TestEnumerationRefusesToBeEmpty:
    """Zero subjects would close the run OK, which reads as a clean project.

    The most dangerous state available to this detector, and the only one the
    harness would happily record as success.
    """

    def test_no_project_configured_is_an_error_not_a_clean_run(
            self, fleet, admin, dsns):
        result = run(fleet, detector([], projects=()))
        assert result.status == base.STATUS_ERROR
        assert result.subjects_evaluated == []
        assert result.observations_created == 0

    def test_no_org_configured_is_an_error_too(self, fleet, admin, dsns):
        """`org=""`, not `org=None` -- the constructor reads None as "go and
        look in the environment", and SENTRY_ORG is now set there. The same
        ambiguity the token test hit the day the credential landed."""
        result = run(fleet, detector([], org=""))
        assert result.status == base.STATUS_ERROR

    def test_the_refusal_says_why_rather_than_failing_obscurely(self):
        det = detector([], projects=())
        with pytest.raises(SentryUnavailable) as exc:
            det.enumerate_subjects(None)
        assert "clean project" in str(exc.value)


# ---- a read that succeeded -------------------------------------------------

class TestWhatASuccessfulReadRecords:

    def test_a_clean_project_emits_nothing_and_closes_ok(self, fleet, admin, dsns):
        """No observation is what lets required_clear_runs resolve an issue.

        Reachable only because every failure above raised instead of
        arriving here as an empty list.
        """
        result = run(fleet, detector([]))
        assert result.status == base.STATUS_OK
        assert result.subjects_evaluated == [SUBJECT]
        assert result.observations_created == 0

    def test_the_observation_is_measured_in_events_with_issues_as_evidence(
            self, fleet, admin, dsns):
        """Magnitude is EVENT VOLUME; the issue count rides along.

        Both numbers are kept and they are deliberately different: one issue
        at nine thousand events is an incident, twenty-five at one event each
        is a backlog, and a single number cannot say which this is.
        """
        result = run(fleet, detector([issue(1, events=9000), issue(2)]))
        assert result.status == base.STATUS_OK
        rows = observations(admin, result.run_id)
        assert len(rows) == 1
        assert rows[0]["observation_type"] == "SENTRY_UNRESOLVED_ISSUES"
        assert rows[0]["magnitude"] == 9001
        assert rows[0]["unit"] == "events"
        assert rows[0]["evidence_sample"]["unresolved_issues"] == 2
        assert rows[0]["evidence_sample"]["total_events"] == 9001
        assert rows[0]["evidence_sample"]["window"] == "24h"
        assert rows[0]["evidence_sample"]["worst_short_id"] == "DD-API-1"

    def test_severity_comes_from_routing_policy_not_from_the_detector(
            self, fleet, admin, dsns):
        """015's bands, applied by route_severity. No threshold in Python.

        Three projects in ONE run rather than three runs: the window is the
        same for all three, and `open_scheduled_run` resolves a repeat to the
        same logical run, so three runs would be one execution and two skips.
        It also exercises the ENUMERATED path with more than one subject.
        """
        result = run(fleet, detector(
            projects=("p-low", "p-mid", "p-high"),
            # Banded on EVENTS: 1-99 MEDIUM, 100-999 HIGH, 1000+ CRITICAL.
            # One issue each, so the issue count cannot be what decides.
            per_project={"p-low": [issue(1, events=50)],
                         "p-mid": [issue(1, events=500)],
                         "p-high": [issue(1, events=5000)]}))
        assert result.status == base.STATUS_OK
        # Severity lives on the ISSUE, not the observation: route_severity
        # decides it at upsert time from routing_policy.
        rows = {r["subject_id"]: r["severity"] for r in admin.execute(
            "SELECT subject_id, severity FROM issues WHERE issue_type = %s",
            ("SENTRY_UNRESOLVED_ISSUES",)).fetchall()}
        assert rows == {"p-low": "MEDIUM", "p-mid": "HIGH",
                        "p-high": "CRITICAL"}

    def test_a_full_page_is_reported_capped_rather_than_as_an_exact_total(
            self, fleet, admin, dsns):
        """An understated total presented as exact is worse than a floor."""
        result = run(fleet, detector([issue(i) for i in range(100)]))
        rows = observations(admin, result.run_id)
        assert rows[0]["evidence_sample"]["capped"] is True

    def test_a_short_page_is_not_capped(self, fleet, admin, dsns):
        result = run(fleet, detector([issue(1)]))
        rows = observations(admin, result.run_id)
        assert rows[0]["evidence_sample"]["capped"] is False

    def test_the_evidence_names_the_project_it_read(self, fleet, admin, dsns):
        result = run(fleet, detector([issue(1)]))
        rows = observations(admin, result.run_id)
        assert rows[0]["evidence_source"] == f"sentry:{ORG}/{PROJECT}"
        assert rows[0]["evidence_params"]["query"] == "is:unresolved"


class TestTheRegistryOwnsEveryThreshold:

    def test_the_detector_carries_no_cadence_or_grace_of_its_own(self):
        import detectors.sentry as mod
        source = open(mod.__file__).read()
        for forbidden in ("timedelta(", "cadence =", "grace ="):
            assert forbidden not in source, forbidden

    def test_015_registered_it_with_level_and_enumerated_semantics(self, admin):
        row = admin.execute(
            "SELECT * FROM detector_registry WHERE detector_key = %s",
            (DETECTOR,)).fetchone()
        assert row is not None, "015_sentry_detector.sql did not apply"
        assert row["semantics"] == "LEVEL"
        assert row["coverage_mode"] == "ENUMERATED"
        assert row["required_clear_runs"] == 2
