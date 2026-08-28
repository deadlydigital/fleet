"""Observation insert and issue upsert.

One observation and its issue move together or not at all, so they share a
transaction. Nothing in here decides severity: that is
route_severity(observation_type, magnitude), a routing_policy lookup, so
retuning priorities is a data change and not a redeploy.

Evidence discipline:
  * order ids and numbers only -- no emails, names, addresses;
  * scalar values only, because the evidence_sample check constraint rejects
    nested objects and arrays.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

import psycopg

log = logging.getLogger(__name__)

MAX_EVIDENCE_SAMPLE = 5


def fingerprint(detector_key: str, issue_key_version: int, product: str,
                subject_type: str, subject_id: str, observation_type: str) -> str:
    """sha256 over the issue identity, hex.

    Per subject, never per row: 29,603 missing orders on one tenant are one
    issue with magnitude 29603, not 29,603 issues.
    """
    material = "|".join((detector_key, str(issue_key_version), product,
                         subject_type, subject_id, observation_type))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def evidence_sample(ids: Sequence[Any], **counts: Any) -> dict[str, Any]:
    """Flat, scalar-only evidence: up to five offending ids plus counts."""
    sample: dict[str, Any] = {}
    for n, value in enumerate(list(ids)[:MAX_EVIDENCE_SAMPLE], start=1):
        sample[f"sample_{n}"] = int(value) if value is not None else None
    sample["sample_size"] = min(len(ids), MAX_EVIDENCE_SAMPLE)
    for key, value in counts.items():
        if isinstance(value, Decimal):
            value = int(value) if value == value.to_integral_value() else float(value)
        sample[key] = value
    for key, value in sample.items():
        if isinstance(value, (dict, list, tuple, set)):
            raise ValueError(f"evidence_sample[{key}] is not a scalar")
    return sample


@dataclass
class Observation:
    observation_type: str
    subject_type: str
    subject_id: str
    magnitude: Any = None
    unit: str | None = None
    expected: Any = None
    actual: Any = None
    delta: Any = None
    evidence_query_key: str | None = None
    evidence_query_version: int | None = None
    evidence_params: Mapping[str, Any] = field(default_factory=dict)
    evidence_sample: Mapping[str, Any] | None = None
    evidence_source: str | None = None


@dataclass
class EmitResult:
    observation_id: int | None
    fingerprint: str
    severity: str | None
    inserted: bool
    issue_id: int | None
    suppressed: bool = False


_INSERT_OBSERVATION = """
INSERT INTO observations (
    detector_run_id, detector_key, detector_version, issue_key_version, product,
    run_mode, observation_type, observed_at, subject_type, subject_id,
    fingerprint, magnitude, unit, expected, actual, delta,
    evidence_query_key, evidence_query_version, evidence_params,
    evidence_sample, evidence_source)
VALUES (
    %(run_id)s, %(detector_key)s, %(detector_version)s, %(issue_key_version)s,
    %(product)s, 'SCHEDULED', %(observation_type)s, %(observed_at)s,
    %(subject_type)s, %(subject_id)s, %(fingerprint)s, %(magnitude)s, %(unit)s,
    %(expected)s, %(actual)s, %(delta)s, %(evidence_query_key)s,
    %(evidence_query_version)s, %(evidence_params)s, %(evidence_sample)s,
    %(evidence_source)s)
ON CONFLICT DO NOTHING
RETURNING id
"""

# On conflict by fingerprint the issue is the same issue: refresh its
# evidence pointer and magnitude, count the occurrence, and reopen it if it
# had been resolved. SUPPRESSED means "stop telling me" and is left alone.
_UPSERT_ISSUE = """
INSERT INTO issues (
    fingerprint, product, issue_type, subject_type, subject_id, detector_key,
    issue_key_version, first_observation_id, latest_observation_id,
    first_seen, last_seen, occurrence_count, current_magnitude, current_unit,
    status, severity, routing_policy_version)
VALUES (
    %(fingerprint)s, %(product)s, %(issue_type)s, %(subject_type)s,
    %(subject_id)s, %(detector_key)s, %(issue_key_version)s,
    %(observation_id)s, %(observation_id)s, %(observed_at)s, %(observed_at)s,
    1, %(magnitude)s, %(unit)s, 'OPEN', %(severity)s, %(policy_version)s)
ON CONFLICT (fingerprint) DO UPDATE SET
    latest_observation_id = EXCLUDED.latest_observation_id,
    last_seen             = GREATEST(issues.last_seen, EXCLUDED.last_seen),
    current_magnitude     = EXCLUDED.current_magnitude,
    current_unit          = EXCLUDED.current_unit,
    severity              = EXCLUDED.severity,
    occurrence_count      = issues.occurrence_count + 1,
    reopen_count          = issues.reopen_count
                            + CASE WHEN issues.status = 'RESOLVED' THEN 1 ELSE 0 END,
    status                = 'OPEN',
    resolution_type       = NULL,
    resolved_at           = NULL,
    resolution_effective_at = NULL,
    updated_at            = now()
WHERE issues.status <> 'SUPPRESSED'
RETURNING id
"""


def emit(ctx, observation: Observation) -> EmitResult:
    """Insert the observation and upsert its issue, atomically."""
    from psycopg.types.json import Jsonb

    fp = fingerprint(ctx.registry.detector_key, ctx.registry.issue_key_version,
                     ctx.registry.product, observation.subject_type,
                     observation.subject_id, observation.observation_type)

    params = {
        "run_id": ctx.run_id,
        "detector_key": ctx.registry.detector_key,
        "detector_version": ctx.detector_version,
        "issue_key_version": ctx.registry.issue_key_version,
        "product": ctx.registry.product,
        "observation_type": observation.observation_type,
        # LEVEL semantics: the database overwrites this with window_end. Pass
        # the right value anyway rather than relying on being corrected.
        "observed_at": ctx.window_end,
        "subject_type": observation.subject_type,
        "subject_id": observation.subject_id,
        "fingerprint": fp,
        "magnitude": observation.magnitude,
        "unit": observation.unit,
        "expected": observation.expected,
        "actual": observation.actual,
        "delta": observation.delta,
        "evidence_query_key": observation.evidence_query_key,
        "evidence_query_version": observation.evidence_query_version,
        "evidence_params": Jsonb(dict(observation.evidence_params or {})),
        "evidence_sample": (Jsonb(dict(observation.evidence_sample))
                            if observation.evidence_sample is not None else None),
        "evidence_source": observation.evidence_source,
    }

    with ctx.fleet.transaction():
        row = ctx.fleet.execute(_INSERT_OBSERVATION, params).fetchone()
        if row is None:
            # Already recorded for this window (or this run). The issue upsert
            # ran in the same transaction as that insert, so replaying it here
            # would double-count occurrence_count.
            log.info("observation %s/%s already recorded for window_end %s",
                     observation.observation_type, observation.subject_id,
                     ctx.window_end)
            return EmitResult(None, fp, None, False, None)
        observation_id = row["id"]

        severity = ctx.fleet.execute(
            "SELECT route_severity(%s, %s) AS severity",
            (observation.observation_type, observation.magnitude)).fetchone()["severity"]

        issue = ctx.fleet.execute(_UPSERT_ISSUE, {
            "fingerprint": fp,
            "product": ctx.registry.product,
            "issue_type": observation.observation_type,
            "subject_type": observation.subject_type,
            "subject_id": observation.subject_id,
            "detector_key": ctx.registry.detector_key,
            "issue_key_version": ctx.registry.issue_key_version,
            "observation_id": observation_id,
            "observed_at": ctx.window_end,
            "magnitude": observation.magnitude,
            "unit": observation.unit,
            "severity": severity,
            "policy_version": 1,
        }).fetchone()

    suppressed = issue is None
    if suppressed:
        log.info("issue %s is SUPPRESSED; observation %s recorded, issue untouched",
                 fp, observation_id)
    return EmitResult(observation_id, fp, severity, True,
                      None if suppressed else issue["id"], suppressed)
