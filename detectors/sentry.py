"""dd_api_errors — what Sentry is holding that nobody has looked at.

Sentry has been collecting from `deadly-digital-api` and the worker since the
DSN was set. Nothing has ever read it, so every error it holds has been
invisible: `docker logs` shows a handled exception only if something logged
it, and an unhandled one only until the buffer rolls.

THE DSN IN THE APP CONTAINER CANNOT DO THIS, AND THAT IS NOT A DETAIL

`SENTRY_DSN` is an INGEST key. It authorises sending events; there is no read
path through it at all. Reading needs an organisation auth token with
`event:read`, a different credential with a different lifetime, and it lives
in `fleet/.env` rather than the app container. The app writes to Sentry, fleet
reads from it, and neither holds the other's credential. Anyone who reads
"the DSN is already there" as "the data is already reachable" will lose an
afternoon to it.

WHAT THIS DETECTOR REFUSES TO DO

**It never reports zero from a read it could not make.** That is the whole
discipline of the module and it has three separate expressions:

  * a project that could not be read is a FAILED SUBJECT, never an
    observation of absence -- `base.py` then closes the run PARTIAL, and the
    coverage predicates already know what PARTIAL means
  * enumeration REFUSES to return an empty subject list. Zero subjects would
    close the run OK, and an OK run with nothing in it is indistinguishable
    from a clean project -- the single most dangerous state this could reach
  * the brief reads the RUN, not the newest observation, so a stale zero from
    yesterday cannot be printed on a day the query failed (see
    `brief/pass_.py::_sentry_claims`)

WHAT IT CANNOT TELL YOU, AND THE BRIEF SHOULD NOT IMPLY OTHERWISE

  * **Not that an error did not happen.** Sentry drops events on quota
    exhaustion and on SDK-side network failure. "0 unresolved" means Sentry
    holds none, which is a claim about Sentry.
  * **Not which tenant.** `send_default_pii=False` and no tenant tag is set
    at any of the six `capture_exception` sites, so an error on HIB's revenue
    page arrives indistinguishable from any other.
  * **Not whether it mattered.** Volume is not severity, which is why
    magnitude is the count of issues a person would triage and the event
    totals ride along as evidence rather than being folded into a score.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Sequence

from . import config
from .base import RunContext, Detector, Subject
from .emit import Observation, emit, evidence_sample

log = logging.getLogger(__name__)

SUBJECT_TYPE = "sentry_project"
OBSERVATION_TYPE = "SENTRY_UNRESOLVED_ISSUES"

#: The org is EU-hosted (`o…ingest.de.sentry.io` in the DSN), and an EU org's
#: API is served from `https://de.sentry.io/api/0`. Defaulted to the global
#: host because that is what an ordinary org uses; SENTRY_API_BASE overrides
#: it. Which host answers for this org is settled by the first authenticated
#: call, not by reading the DSN -- a 404 from the wrong base looks exactly
#: like a project that does not exist.
DEFAULT_API_BASE = "https://sentry.io/api/0"

#: One page. Above this the count is reported CAPPED rather than as an exact
#: number, the same way analytics `setup-status` caps its row counts: an
#: understated total presented as exact is worse than a total that says it is
#: a floor.
PAGE_LIMIT = 100

REQUEST_TIMEOUT_SECONDS = 20


class SentryUnavailable(Exception):
    """The read could not be made. Never caught to produce a zero."""


def _cfg(name: str, default: str | None = None) -> str | None:
    return config.get(name, default)


class SentryDetector(Detector):
    key = "dd_api_errors"

    def __init__(self, *, token: str | None = None, org: str | None = None,
                 projects: Sequence[str] | None = None,
                 api_base: str | None = None,
                 fetch=None) -> None:
        self._token = token if token is not None else _cfg("SENTRY_AUTH_TOKEN")
        self._org = org if org is not None else _cfg("SENTRY_ORG")
        raw = projects if projects is not None else _cfg("SENTRY_PROJECTS")
        if isinstance(raw, str):
            raw = [p.strip() for p in raw.split(",") if p.strip()]
        self._projects = list(raw or ())
        self._api_base = (api_base or _cfg("SENTRY_API_BASE")
                          or DEFAULT_API_BASE).rstrip("/")
        #: Injected in tests. The real one is _http_get; nothing else in this
        #: module knows what an HTTP response is.
        self._fetch = fetch or self._http_get

    # ---- enumeration ------------------------------------------------------

    def enumerate_subjects(self, ctx: RunContext) -> Sequence[Subject]:
        """The configured projects, and it REFUSES to return none.

        An empty list closes the run OK with nothing evaluated, which reads
        downstream as a clean project rather than as an unconfigured
        detector. Raising here closes it ERROR, which is what an unconfigured
        detector is, and the heartbeat escalates it rather than the brief
        quietly printing a zero.

        A missing TOKEN is deliberately not checked here -- that is a
        per-subject failure and belongs in evaluate(), so the run closes
        PARTIAL with the project named rather than ERROR with nothing named.
        """
        if not self._org or not self._projects:
            raise SentryUnavailable(
                "SENTRY_ORG and SENTRY_PROJECTS are not both set, so there is "
                "no project to read; refusing to close a run OK with no "
                "subjects, which would read as a clean project")
        return [Subject(SUBJECT_TYPE, slug, {"org": self._org})
                for slug in self._projects]

    # ---- evaluation -------------------------------------------------------

    def evaluate(self, ctx: RunContext, subject: Subject) -> None:
        issues, capped = self._unresolved(subject.subject_id)

        # Nothing unresolved: emit no observation. That is what lets
        # required_clear_runs resolve an open issue, and it is only reachable
        # because a failed read raised above rather than arriving here as an
        # empty list.
        if not issues:
            log.info("%s: no unresolved issues", subject.label)
            return

        events = sum(_int(i.get("count")) for i in issues)
        users = sum(_int(i.get("userCount")) for i in issues)
        worst = max(issues, key=lambda i: _int(i.get("count")))
        newest = max((i.get("lastSeen") or "") for i in issues)

        sample = evidence_sample(
            [_int(i.get("id")) for i in issues[:5]],
            unresolved_issues=len(issues),
            capped=capped,
            total_events=events,
            users_affected=users,
            worst_short_id=str(worst.get("shortId") or "")[:100],
            worst_event_count=_int(worst.get("count")),
            worst_level=str(worst.get("level") or "")[:20],
            newest_last_seen=str(newest)[:40],
        )

        result = emit(ctx, Observation(
            observation_type=OBSERVATION_TYPE,
            subject_type=SUBJECT_TYPE,
            subject_id=subject.subject_id,
            magnitude=len(issues), unit="issues",
            # There is no "expected" number of errors to compare against, and
            # inventing one would put a threshold in the detector that
            # routing_policy already owns. Zero is the only defensible
            # expectation for an unresolved error.
            expected=0, actual=len(issues), delta=len(issues),
            evidence_query_key="sentry_unresolved_issues",
            evidence_query_version=1,
            evidence_params={"org": subject.payload["org"],
                             "project": subject.subject_id,
                             "query": "is:unresolved"},
            evidence_sample=sample,
            evidence_source=f"sentry:{subject.payload['org']}/{subject.subject_id}",
        ))
        log.info("%s SENTRY_UNRESOLVED_ISSUES magnitude=%s severity=%s new=%s "
                 "capped=%s", subject.label, len(issues), result.severity,
                 result.inserted, capped)

    # ---- the read ---------------------------------------------------------

    def _unresolved(self, project: str) -> tuple[list[dict[str, Any]], bool]:
        if not self._token:
            raise SentryUnavailable(
                "SENTRY_AUTH_TOKEN is not set. The DSN in the app container "
                "is an ingest key and cannot read; this needs an organisation "
                "auth token with event:read")

        url = (f"{self._api_base}/projects/{urllib.parse.quote(self._org)}/"
               f"{urllib.parse.quote(project)}/issues/?"
               + urllib.parse.urlencode({"query": "is:unresolved",
                                         "statsPeriod": "24h",
                                         "limit": PAGE_LIMIT}))
        payload = self._fetch(url)
        if not isinstance(payload, list):
            raise SentryUnavailable(
                f"expected a list of issues from {self._api_base}, got "
                f"{type(payload).__name__}")
        # At the page limit the count is a floor, not a total. Said rather
        # than silently truncated.
        return payload, len(payload) >= PAGE_LIMIT

    def _http_get(self, url: str) -> Any:
        request = urllib.request.Request(url, method="GET")
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(request,
                                        timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            # Every one of these is a failure to read, never an absence of
            # errors. 401/403 is the token, 404 is very often the wrong API
            # base for an EU org rather than a missing project, and 429 is
            # Sentry asking us to slow down -- reporting any of them as zero
            # is the failure this detector is built around.
            detail = exc.read(400).decode("utf-8", "replace").strip()
            hint = ""
            if exc.code == 404:
                hint = (f" -- a 404 here is as often the wrong API base as a "
                        f"missing project; this used {self._api_base}")
            elif exc.code in (401, 403):
                hint = " -- check the token carries event:read on this org"
            raise SentryUnavailable(
                f"HTTP {exc.code} from Sentry: {detail[:200]}{hint}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise SentryUnavailable(f"could not reach Sentry: {exc}") from exc

        try:
            return json.loads(body)
        except ValueError as exc:
            raise SentryUnavailable(f"Sentry returned unparseable JSON: {exc}") from exc


def _int(value: Any) -> int:
    """Sentry sends counts as strings. A value that will not parse is 0."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
