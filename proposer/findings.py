"""Computable findings.

Every finding here is arithmetic over track 1's tables against a threshold
from cycle.yaml. None of them needs a model to be correct, and none of them
would be more correct with one: a count of days is a count of days, and
wrapping it in a generated sentence would turn something checkable into
something that has to be trusted.

Each producer refuses to run on a stale reading. A finding computed from
evidence that is out of date is worse than no finding, because it arrives
looking exactly like a fresh one.

Nothing here decides what matters. Producers emit findings; the cycle ranks
them by objective weight and cuts at five.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Iterable, Sequence

from . import config
from .adapter import AdapterOutput, Reading, flatten
from .detector_adapter import (COVERAGE_GAPS, DETECTOR_HEALTH,
                               FALSE_POSITIVE_RATE, OPEN_ISSUES,
                               UNTRIAGED_OBSERVATIONS)
from .history import PROPOSAL_ACTIVITY, ProposalHistory
from .objectives import Objectives

log = logging.getLogger(__name__)

KIND_OBSERVATION = "OBSERVATION"
KIND_RISK = "RISK"

ISSUE_OPEN_TOO_LONG = "issue_open_too_long"
DETECTOR_NO_SUCCESSFUL_RUN = "detector_no_successful_run"
FALSE_POSITIVE_RATE_RISING = "false_positive_rate_rising"
OBJECTIVE_NO_ACTIVITY = "objective_no_activity"
UNTRIAGED = "untriaged_observations"
COVERAGE_GAP = "coverage_gap"

# An observation changes nothing, so there is nothing to reverse. It is
# recorded rather than left implicit because the column exists for the day
# this layer proposes something that does change state.
OBSERVATION_REVERSIBILITY = "TRIVIAL"

# Arithmetic over a table the database itself maintains. Confidence is in the
# claim being true, not in it being worth anything.
COMPUTED_CONFIDENCE = Decimal("1.000")


@dataclass(frozen=True)
class Evidence:
    adapter: str
    query_key: str
    value: dict[str, Any]
    fetched_at: datetime
    freshness_bound: timedelta
    stale: bool

    @classmethod
    def of(cls, reading: Reading, value: dict[str, Any]) -> "Evidence":
        return cls(adapter=reading.adapter, query_key=reading.query_key,
                   value=value, fetched_at=reading.fetched_at,
                   freshness_bound=reading.freshness_bound, stale=reading.stale)


@dataclass(frozen=True)
class Finding:
    finding_type: str
    finding_key: str
    area: str
    title: str
    body: str
    objective_ref: str | None
    evidence: tuple[Evidence, ...]
    kind: str = KIND_OBSERVATION
    confidence: Decimal = COMPUTED_CONFIDENCE
    reversibility: str = OBSERVATION_REVERSIBILITY
    # What the finding is about, when two producers can reach the same thing.
    # The issue fingerprint, for the two that can.
    subject_key: str | None = None

    def as_risk(self, why: str) -> "Finding":
        """Demote to a risk. A risk names no objective, by definition."""
        return Finding(finding_type=self.finding_type, finding_key=self.finding_key,
                       area=self.area, title=self.title,
                       body=f"{self.body}\n\nRaised as a risk: {why}",
                       objective_ref=None, evidence=self.evidence,
                       kind=KIND_RISK, confidence=self.confidence,
                       reversibility=self.reversibility,
                       subject_key=self.subject_key)


@dataclass
class FindingRun:
    findings: list[Finding] = field(default_factory=list)
    # Producers that did not run, and why. Never silent: a finding type that
    # could not be computed is a hole in the morning's answer.
    skipped: list[tuple[str, str]] = field(default_factory=list)


# ---- helpers --------------------------------------------------------------

def _days(seconds: float | int | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = int(seconds)
    if seconds >= 172800:
        return f"{seconds // 86400} days"
    if seconds >= 7200:
        return f"{seconds // 3600} hours"
    if seconds >= 120:
        return f"{seconds // 60} minutes"
    return f"{seconds} seconds"


def _interval(spec: Any) -> timedelta:
    return config.parse_interval(spec)


def _objective_for(cycle_config: dict[str, Any], finding_type: str,
                   subtype: str | None = None) -> str | None:
    mapping = cycle_config.get("objective_map", {}).get(finding_type)
    if mapping is None:
        return None
    if isinstance(mapping, str):
        return mapping
    if subtype is None:
        return None
    return mapping.get(subtype)


def _usable(run: FindingRun, finding_type: str, reading: Reading) -> bool:
    if reading.usable:
        return True
    run.skipped.append((finding_type,
                        f"{reading.query_key} is {reading.status}: "
                        f"{reading.data_missing_reason or _stale_note(reading)}"))
    return False


def _stale_note(reading: Reading) -> str:
    from .adapter import _humanise
    return (f"data is {_humanise(reading.age)} old against a bound of "
            f"{_humanise(reading.freshness_bound)}")


# ---- producers ------------------------------------------------------------

def issue_open_too_long(out: AdapterOutput, cycle_config: dict[str, Any],
                        run: FindingRun) -> None:
    """An issue that has been open longer than its severity earns."""
    reading = out[OPEN_ISSUES]
    if not _usable(run, ISSUE_OPEN_TOO_LONG, reading):
        return

    thresholds = cycle_config["findings"][ISSUE_OPEN_TOO_LONG]
    for row in reading.rows:
        severity = row["severity"]
        if severity not in thresholds:
            run.skipped.append(
                (ISSUE_OPEN_TOO_LONG,
                 f"issue {row['id']} has severity {severity}, which cycle.yaml "
                 f"gives no patience for"))
            continue
        limit = _interval(thresholds[severity])
        age = timedelta(seconds=int(row["age_seconds"]))
        if age <= limit:
            continue

        magnitude = row["current_magnitude"]
        unit = row["current_unit"] or ""
        still = "still being observed" if row["still_observed"] else \
                "not observed in the most recent settled window"
        run.findings.append(Finding(
            finding_type=ISSUE_OPEN_TOO_LONG,
            finding_key=f"{ISSUE_OPEN_TOO_LONG}:{row['fingerprint']}",
            area=row["product"],
            title=(f"{row['issue_type']} on {row['subject_type']} "
                   f"{row['subject_id']} has been open {_days(row['age_seconds'])}"),
            body=(f"Issue {row['id']} ({row['severity']}) opened "
                  f"{row['first_seen']:%Y-%m-%d %H:%M} and is still OPEN "
                  f"{_days(row['age_seconds'])} later, against a "
                  f"{_days(limit.total_seconds())} threshold for {severity}.\n"
                  f"Current magnitude {magnitude} {unit}, seen "
                  f"{row['occurrence_count']} times, last seen "
                  f"{row['last_seen']:%Y-%m-%d %H:%M} ({still}).\n"
                  f"Detector {row['detector_key']}."),
            objective_ref=_objective_for(cycle_config, ISSUE_OPEN_TOO_LONG,
                                         row["issue_type"]),
            subject_key=row["fingerprint"],
            evidence=(Evidence.of(reading, flatten(
                row, keys=("id", "fingerprint", "product", "issue_type",
                           "subject_type", "subject_id", "detector_key",
                           "severity", "current_magnitude", "current_unit",
                           "occurrence_count", "reopen_count", "first_seen",
                           "last_seen", "age_seconds", "still_observed"),
                threshold_seconds=int(limit.total_seconds()))),)))


def detector_no_successful_run(out: AdapterOutput, cycle_config: dict[str, Any],
                               run: FindingRun) -> None:
    """A detector that has never succeeded, or has stopped succeeding.

    Reads detector_health, which is answered from the run history's own
    timestamps and so cannot itself be stale. That matters here more than
    anywhere else: this is the finding that explains why everything else
    might be.
    """
    reading = out[DETECTOR_HEALTH]
    limit = int(cycle_config["findings"][DETECTOR_NO_SUCCESSFUL_RUN]["missed_slots"])
    objective = _objective_for(cycle_config, DETECTOR_NO_SUCCESSFUL_RUN)

    for row in reading.rows:
        if row["retired_at"] is not None:
            continue
        until = row["maintenance_until"]
        if until is not None and until > reading.fetched_at:
            continue

        never = int(row["successful_runs"]) == 0
        missed = row["missed_slots"]
        lapsed = (not never) and missed is not None and int(missed) >= limit
        if not (never or lapsed):
            continue

        variant = "never" if never else "lapsed"
        if never:
            title = (f"Detector {row['detector_key']} has never completed a "
                     f"successful run")
            body = (f"{int(row['total_runs'])} scheduled runs on record, "
                    f"{int(row['error_runs'])} of them ERROR, "
                    f"{int(row['running_runs'])} still RUNNING, and no OK or "
                    f"PARTIAL among them. Consecutive errors: "
                    f"{int(row['consecutive_errors'])}.\n"
                    f"Nothing this detector is supposed to watch is being "
                    f"watched, and every reading that rests on it is "
                    f"unusable rather than merely old.")
        else:
            title = (f"Detector {row['detector_key']} has not succeeded for "
                     f"{int(missed)} cadences")
            body = (f"Last successful window ended "
                    f"{row['last_ok_window_end']:%Y-%m-%d %H:%M}, "
                    f"{_days(row['seconds_since_ok'])} ago, which is "
                    f"{int(missed)} whole cadences of "
                    f"{_days(row['cadence'].total_seconds())} against a "
                    f"threshold of {limit}.\n"
                    f"{int(row['error_runs'])} ERROR runs on record, "
                    f"{int(row['consecutive_errors'])} of them consecutive.")

        run.findings.append(Finding(
            finding_type=DETECTOR_NO_SUCCESSFUL_RUN,
            finding_key=f"{DETECTOR_NO_SUCCESSFUL_RUN}:{row['detector_key']}:{variant}",
            area=row["product"],
            title=title,
            body=body,
            objective_ref=objective,
            evidence=(Evidence.of(reading, flatten(
                row, keys=("detector_key", "issue_key_version", "product",
                           "total_runs", "successful_runs", "error_runs",
                           "running_runs", "timeout_runs", "consecutive_errors",
                           "last_ok_at", "last_ok_window_end", "last_run_at",
                           "seconds_since_ok", "missed_slots"),
                missed_slots_threshold=limit)),)))


def false_positive_rate_rising(out: AdapterOutput, cycle_config: dict[str, Any],
                               run: FindingRun) -> None:
    """A detector telling more lies than it used to."""
    reading = out[FALSE_POSITIVE_RATE]
    if not _usable(run, FALSE_POSITIVE_RATE_RISING, reading):
        return

    settings = cycle_config["findings"][FALSE_POSITIVE_RATE_RISING]
    window = _interval(settings["window"])
    minimum = int(settings["min_verdicts_per_window"])
    increase = Decimal(str(settings["absolute_increase"]))
    objective = _objective_for(cycle_config, FALSE_POSITIVE_RATE_RISING)

    for row in reading.rows:
        recent_n, prior_n = int(row["recent_verdicts"]), int(row["prior_verdicts"])
        if recent_n < minimum or prior_n < minimum:
            # Not a null result: too few verdicts is a different answer from
            # "the rate has not moved", and reporting it as the latter would
            # be inventing a comparison that was never made.
            run.skipped.append(
                (FALSE_POSITIVE_RATE_RISING,
                 f"{row['detector_key']}/{row['observation_type']}: "
                 f"{recent_n} recent and {prior_n} prior judgements, "
                 f"below the {minimum} each window needs. "
                 f"({int(row.get('recent_observations') or 0)} and "
                 f"{int(row.get('prior_observations') or 0)} observations "
                 f"respectively -- a recurring issue restates one judgement "
                 f"per cadence, and restatements are not evidence.)"))
            continue

        recent = Decimal(int(row["recent_false_positives"])) / Decimal(recent_n)
        prior = Decimal(int(row["prior_false_positives"])) / Decimal(prior_n)
        if recent - prior < increase:
            continue

        run.findings.append(Finding(
            finding_type=FALSE_POSITIVE_RATE_RISING,
            finding_key=(f"{FALSE_POSITIVE_RATE_RISING}:{row['detector_key']}:"
                         f"{row['observation_type']}"),
            area=row["detector_key"],
            title=(f"False-positive rate on {row['detector_key']}/"
                   f"{row['observation_type']} rose from {prior:.0%} to "
                   f"{recent:.0%}"),
            body=(f"Over the last {_days(window.total_seconds())}: "
                  f"{int(row['recent_false_positives'])} false positives in "
                  f"{recent_n} judgements ({recent:.0%}). The window before: "
                  f"{int(row['prior_false_positives'])} in {prior_n} "
                  f"({prior:.0%}).\n"
                  f"This is the JUDGEMENT rate -- of the things a person ruled "
                  f"on, the fraction that were wrong. A recurring issue "
                  f"restates one judgement per cadence and those restatements "
                  f"are not counted: the recent window holds "
                  f"{int(row['recent_observations'])} observations behind "
                  f"those {recent_n} judgements.\n"
                  f"Bucketed by when the observation was made, not when the "
                  f"verdict was entered, so the recent window is the less "
                  f"triaged of the two."),
            objective_ref=objective,
            evidence=(Evidence.of(reading, flatten(
                row, threshold_absolute_increase=float(increase),
                min_verdicts_per_window=minimum,
                window_seconds=int(window.total_seconds()))),)))


def untriaged_observations(out: AdapterOutput, cycle_config: dict[str, Any],
                           run: FindingRun) -> None:
    """Observations nobody has ruled on. The false-positive rate's input."""
    reading = out[UNTRIAGED_OBSERVATIONS]
    if not _usable(run, UNTRIAGED, reading):
        return

    settings = cycle_config["findings"][UNTRIAGED]
    max_age = _interval(settings["max_age"])
    min_count = int(settings["min_count"])
    objective = _objective_for(cycle_config, UNTRIAGED)

    for row in reading.rows:
        count = int(row["untriaged"])
        oldest = int(row["oldest_age_seconds"])
        if count < min_count or oldest <= max_age.total_seconds():
            continue

        run.findings.append(Finding(
            finding_type=UNTRIAGED,
            finding_key=(f"{UNTRIAGED}:{row['detector_key']}:"
                         f"{row['observation_type']}"),
            area=row["detector_key"],
            title=(f"{count} untriaged {row['observation_type']} observations, "
                   f"oldest {_days(oldest)}"),
            body=(f"{count} observations from {row['detector_key']} have no "
                  f"verdict. The oldest was observed "
                  f"{row['oldest_observed_at']:%Y-%m-%d %H:%M}, "
                  f"{_days(oldest)} ago, against a "
                  f"{_days(max_age.total_seconds())} threshold.\n"
                  f"Until they are ruled on, the false-positive rate for this "
                  f"detector is computed from a sample that excludes them."),
            objective_ref=objective,
            evidence=(Evidence.of(reading, flatten(
                row, max_age_seconds=int(max_age.total_seconds()),
                min_count=min_count)),)))


def coverage_gap(out: AdapterOutput, cycle_config: dict[str, Any],
                 run: FindingRun) -> None:
    """An open issue that no run is in a position to close.

    The distinction this finding exists for: an issue stays OPEN both when
    the condition is still happening and when the condition may well have
    stopped but no detector run is allowed to say so. They look identical in
    the issues table and want opposite responses.
    """
    reading = out[COVERAGE_GAPS]
    if not _usable(run, COVERAGE_GAP, reading):
        return

    min_age = _interval(cycle_config["findings"][COVERAGE_GAP]["min_age"])
    objective = _objective_for(cycle_config, COVERAGE_GAP)

    for row in reading.rows:
        if row["still_observed"]:
            continue  # open because it is happening, not because it is stuck
        age = reading.fetched_at - row["first_seen"]
        if age <= min_age:
            continue

        reason = _blocking_reason(row)
        if reason is None:
            continue

        run.findings.append(Finding(
            finding_type=COVERAGE_GAP,
            finding_key=f"{COVERAGE_GAP}:{row['fingerprint']}:{reason}",
            area=row["product"],
            title=(f"{row['issue_type']} on {row['subject_type']} "
                   f"{row['subject_id']} cannot resolve: {reason}"),
            body=_coverage_body(row, reason),
            objective_ref=objective,
            subject_key=row["fingerprint"],
            evidence=(Evidence.of(reading, flatten(
                row, keys=("id", "fingerprint", "product", "issue_type",
                           "severity", "subject_type", "subject_id",
                           "detector_key", "first_seen", "last_seen",
                           "required_clear_runs", "qualifying_runs_since",
                           "eff", "horizon_valid", "subject_covered",
                           "identity_stable", "still_observed"),
                blocking_reason=reason)),)))


def _blocking_reason(row: dict[str, Any]) -> str | None:
    if row["eff"] is None:
        return "NO_CLEARING_RUNS"
    if row["horizon_valid"] is False:
        return "HORIZON_INVALID"
    if row["subject_covered"] is False:
        return "SUBJECT_NOT_COVERED"
    if row["identity_stable"] is False:
        return "IDENTITY_UNSTABLE"
    return None


def _coverage_body(row: dict[str, Any], reason: str) -> str:
    head = (f"Issue {row['id']} ({row['severity']}) was last observed "
            f"{row['last_seen']:%Y-%m-%d %H:%M} and has not been seen since, "
            f"but it cannot be resolved.\n")
    if reason == "NO_CLEARING_RUNS":
        return head + (
            f"{int(row['qualifying_runs_since'])} qualifying runs have covered "
            f"{row['subject_type']} {row['subject_id']} since then; "
            f"{int(row['required_clear_runs'])} are required. Either the "
            f"detector is not running, or its runs are not evaluating this "
            f"subject.")
    if reason == "HORIZON_INVALID":
        return head + (
            "Enough runs exist, but the interval between last_seen and the "
            "clearing run has a hole in it: a missing slot, a truncated run, "
            "or a definition boundary inside the horizon.")
    if reason == "SUBJECT_NOT_COVERED":
        return head + (
            f"The clearing runs exist but did not all evaluate "
            f"{row['subject_type']} {row['subject_id']}, so they cannot speak "
            f"for it.")
    return head + (
        "The subject was superseded inside the clearing horizon, so the runs "
        "before and after are not talking about the same thing.")


def objective_no_activity(history: ProposalHistory, objectives: Objectives,
                          cycle_config: dict[str, Any], run: FindingRun,
                          now: datetime) -> None:
    """An objective this layer has said nothing about.

    Guarded on the layer's own age. "Nothing in 14 days" is unknowable until
    the layer is 14 days old, and firing it before then would fill the first
    fortnight's cycles with the news that it had just been switched on.
    """
    after = _interval(cycle_config["findings"][OBJECTIVE_NO_ACTIVITY]["after"])
    epoch = history.first_proposal_at
    if epoch is None or (now - epoch) <= after:
        how_old = ("this layer has no history yet" if epoch is None else
                   f"this layer's own history is only "
                   f"{_days((now - epoch).total_seconds())} old")
        run.skipped.append(
            (OBJECTIVE_NO_ACTIVITY,
             f"{how_old}, less than the {_days(after.total_seconds())} the "
             f"finding measures, so 'no activity' would only be reporting "
             f"that it was recently switched on"))
        return

    reading = history.reading(PROPOSAL_ACTIVITY, after, now)
    for objective in objectives.by_id.values():
        last = history.last_activity_on(objective.id)
        if last is not None and (now - last) <= after:
            continue

        quiet = "never" if last is None else _days((now - last).total_seconds())
        row = history.activity_row(objective.id) or {"objective_ref": objective.id,
                                                     "proposals": 0,
                                                     "last_proposed_at": None,
                                                     "first_proposed_at": None}
        run.findings.append(Finding(
            finding_type=OBJECTIVE_NO_ACTIVITY,
            finding_key=f"{OBJECTIVE_NO_ACTIVITY}:{objective.id}",
            area="fleet",
            title=(f"Objective {objective.id} (weight {objective.weight}) has "
                   f"had no proposal for {quiet}"),
            body=(f"{objective.statement}\n\n"
                  f"This layer has raised {int(row['proposals'])} proposals "
                  f"against {objective.id}, last "
                  f"{'never' if last is None else format(last, '%Y-%m-%d %H:%M')}, "
                  f"against a {_days(after.total_seconds())} threshold.\n"
                  f"That is a statement about this layer's coverage, not about "
                  f"whether work is happening: the layer sees proposals and "
                  f"nothing else."),
            objective_ref=objective.id,
            evidence=(Evidence.of(reading, flatten(
                row, objective_ref=objective.id,
                objective_weight=float(objective.weight),
                threshold_seconds=int(after.total_seconds()),
                layer_first_proposal_at=epoch)),)))


PRODUCERS: tuple[Callable[..., None], ...] = (
    issue_open_too_long,
    detector_no_successful_run,
    false_positive_rate_rising,
    untriaged_observations,
    coverage_gap,
)


def _fold_overlaps(run: FindingRun) -> None:
    """One issue, one finding.

    An issue that is old AND cannot resolve reaches two producers, and would
    take two of the five slots to say one thing twice. The coverage gap is
    the more informative of the pair -- it explains why the issue is still
    open rather than only noting that it is -- so it wins, and the fold is
    recorded rather than done quietly.
    """
    blocked = {f.subject_key for f in run.findings
               if f.finding_type == COVERAGE_GAP and f.subject_key}
    kept: list[Finding] = []
    for finding in run.findings:
        if (finding.finding_type == ISSUE_OPEN_TOO_LONG
                and finding.subject_key in blocked):
            run.skipped.append(
                (ISSUE_OPEN_TOO_LONG,
                 f"{finding.title}: folded into the coverage gap for the same "
                 f"issue, which says why it is still open"))
            continue
        kept.append(finding)
    run.findings = kept


def compute(out: AdapterOutput, history: ProposalHistory, objectives: Objectives,
            cycle_config: dict[str, Any], now: datetime) -> FindingRun:
    run = FindingRun()
    for producer in PRODUCERS:
        producer(out, cycle_config, run)
    objective_no_activity(history, objectives, cycle_config, run, now)
    _fold_overlaps(run)
    return run
