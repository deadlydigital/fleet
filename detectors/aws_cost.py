"""dd_aws_cost — month-to-date AWS spend against the objective's ceiling.

`cost-discipline` is 0.05 of the quarter and until Cost Explorer access
landed it had no evidence path at all: the brief printed it UNCOMPUTED on
every run it ever made.

WHAT THIS MEASURES, AND WHY IT IS A PERCENT

Magnitude is PERCENT OF THE CEILING CONSUMED, month to date. Not dollars.
The objective is 200 GBP/month and Cost Explorer answers in USD, so a
dollar-denominated magnitude would put a currency-crossing assumption into
`routing_policy` -- a hardcoded exchange rate hiding in a data table, which
is the same defect as one in a function wearing a different hat. A percent
has no currency in it.

Computing the percent REQUIRES the fx_rate reading, so a month with no
reading produces no observation and the brief says why. That is the intended
behaviour, not a degradation: refusing is better than comparing two numbers
denominated in different things.

THE THRESHOLD COMES FROM THE OBJECTIVE, NOT FROM HERE

`objectives-2026-Q4.yaml` declares `ceiling: {amount, currency, period}` and
the loader REFUSES a ceiling that does not state its currency. No number in
this module is the ceiling, and changing the objective retunes the detector
without a deploy -- the same rule as every threshold living in
`detector_registry`.

WHAT IT DELIBERATELY DOES NOT DO

  * **No early warning.** It fires at 100% of the ceiling and not before,
    because anything below that is a number nobody has chosen. Warning ahead
    of a breach needs a projection of the month, and a projection IS growth
    detection -- deferred until there is more than one month of history not
    distorted by the infrastructure just switched off. Measured: VPC fell
    from $88.26 in August to $1.74 across the first eight days of September,
    and ECS, ELB, Lambda, ElastiCache and CloudWatch all went to zero.
  * **No daily anomaly detection.** The first of the month carries recurring
    charges -- $47.75 of Business Support, Tax and Route 53 in September,
    against a $6.93 daily norm -- so a day-over-day detector fires every
    month forever. The objective is monthly; the subject is the month.
  * **It does not claim to know the bill.** Cost Explorer lags: its most
    recent day is always partial (measured $1.26 against a $6.93 norm), so
    month-to-date UNDERSTATES. That direction is safe -- it can be late to
    report a breach, never early -- and it is stated rather than corrected
    for.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Sequence

from . import config
from .base import Detector, RunContext, Subject
from .emit import Observation, emit, evidence_sample

log = logging.getLogger(__name__)

SUBJECT_TYPE = "aws_account"
OBSERVATION_TYPE = "AWS_SPEND_VS_CEILING"
OBJECTIVE_ID = "cost-discipline"

#: One account, so a stable literal rather than a lookup that would need a
#: second IAM permission. If a second account ever exists this detector
#: becomes ENUMERATED and this becomes the enumeration.
DEFAULT_SUBJECT = "aws"

#: Cost Explorer is a global endpoint.
CE_REGION = "us-east-1"


class CostUnavailable(Exception):
    """The comparison could not be made. Never caught to produce a zero."""


class AwsCostDetector(Detector):
    key = "dd_aws_cost"

    def __init__(self, *, ceiling=None, client=None, subject: str | None = None,
                 today: dt.date | None = None) -> None:
        self._ceiling = ceiling            # injected in tests
        self._client = client              # injected in tests
        self._subject = subject or config.get("AWS_ACCOUNT_LABEL") or DEFAULT_SUBJECT
        self._today = today

    # ---- enumeration ------------------------------------------------------

    def enumerate_subjects(self, ctx: RunContext) -> Sequence[Subject]:
        return [Subject(SUBJECT_TYPE, self._subject, {})]

    # ---- evaluation -------------------------------------------------------

    def evaluate(self, ctx: RunContext, subject: Subject) -> None:
        today = self._today or dt.datetime.now(dt.timezone.utc).date()
        month_start = today.replace(day=1)

        ceiling = self._read_ceiling()
        spend, spend_currency = self._month_to_date(month_start, today)
        rate, rate_source, rate_read_at = self._rate(
            ctx, month_start, spend_currency, ceiling.currency)

        converted = (spend * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)
        percent = int((converted / ceiling.amount * 100)
                      .quantize(Decimal("1"), ROUND_HALF_UP))
        days = (today - month_start).days + 1

        log.info("%s month-to-date %s %s -> %s %s, %s%% of %s (day %s)",
                 subject.label, spend, spend_currency, converted,
                 ceiling.currency, percent, ceiling.describe(), days)

        # UNDER THE CEILING EMITS NOTHING, which is what lets an open issue
        # clear through required_clear_runs. Reachable only because every
        # failure above raised rather than arriving here as a zero.
        if percent < 100:
            return

        sample = evidence_sample(
            [],
            period_month=month_start.isoformat(),
            days_elapsed=days,
            spend_base=float(spend),
            base_currency=spend_currency,
            spend_quote=float(converted),
            quote_currency=ceiling.currency,
            quote_per_base=float(rate),
            rate_source=str(rate_source)[:120],
            rate_read_at=str(rate_read_at)[:40],
            ceiling_amount=float(ceiling.amount),
            percent_of_ceiling=percent,
        )
        result = emit(ctx, Observation(
            observation_type=OBSERVATION_TYPE,
            subject_type=SUBJECT_TYPE,
            subject_id=subject.subject_id,
            magnitude=percent, unit="percent",
            expected=100, actual=percent, delta=percent - 100,
            evidence_query_key="aws_cost_month_to_date",
            evidence_query_version=1,
            evidence_params={"objective": OBJECTIVE_ID,
                             "period_month": month_start.isoformat(),
                             "granularity": "MONTHLY"},
            evidence_sample=sample,
            evidence_source=f"aws:cost-explorer+fleet:fx_rate",
        ))
        log.warning("%s AWS_SPEND_VS_CEILING %s%% severity=%s new=%s",
                    subject.label, percent, result.severity, result.inserted)

    # ---- the three inputs -------------------------------------------------

    def _read_ceiling(self):
        """The objective's ceiling. Imported, not re-parsed.

        `proposer.objectives` reads the YAML and touches no database and no
        track-1 state, so this is a dependency on the objectives FILE rather
        than on the proposal layer. A second parser here is how the ceiling
        ends up with two readings that disagree. If a third caller appears,
        lift the module to the repo root -- the same call made for
        console.deploys.
        """
        if self._ceiling is not None:
            return self._ceiling
        from proposer.objectives import load
        objectives = load()
        objective = objectives.by_id.get(OBJECTIVE_ID)
        if objective is None or objective.ceiling is None:
            raise CostUnavailable(
                f"{OBJECTIVE_ID} declares no ceiling in "
                f"{objectives.path.name}; there is nothing to compare against")
        return objective.ceiling

    def _month_to_date(self, month_start: dt.date, today: dt.date):
        """(amount, currency) as Cost Explorer reports it, unconverted."""
        client = self._client
        if client is None:
            try:
                import boto3
            except ImportError as exc:                       # pragma: no cover
                raise CostUnavailable(f"boto3 is not installed: {exc}") from exc
            client = boto3.client("ce", region_name=CE_REGION)
        try:
            resp = client.get_cost_and_usage(
                # End is EXCLUSIVE, so today+1 includes today's partial data.
                TimePeriod={"Start": month_start.isoformat(),
                            "End": (today + dt.timedelta(days=1)).isoformat()},
                Granularity="MONTHLY", Metrics=["UnblendedCost"])
        except Exception as exc:
            raise CostUnavailable(f"Cost Explorer refused the read: {exc}") from exc

        buckets = resp.get("ResultsByTime") or []
        if not buckets:
            raise CostUnavailable(
                "Cost Explorer returned no period at all for "
                f"{month_start}..{today}; that is a failed read, not a zero bill")
        total = Decimal("0")
        currency = None
        for b in buckets:
            amount = b["Total"]["UnblendedCost"]
            total += Decimal(str(amount["Amount"]))
            unit = amount["Unit"]
            if currency is not None and unit != currency:
                raise CostUnavailable(
                    f"Cost Explorer mixed currencies in one month: "
                    f"{currency} and {unit}")
            currency = unit
        return total, currency

    def _rate(self, ctx: RunContext, month_start: dt.date,
              base: str, quote: str):
        """The month's recorded rate, or a refusal naming where to get one."""
        if base == quote:
            return Decimal("1"), "no conversion needed", month_start.isoformat()
        row = ctx.fleet.execute(
            """
            SELECT quote_per_base, source, read_at
              FROM fx_rate
             WHERE period_month = %(m)s
               AND base_currency = %(b)s AND quote_currency = %(q)s
            """, {"m": month_start, "b": base, "q": quote}).fetchone()
        if row is None:
            raise CostUnavailable(
                f"no fx_rate reading for {month_start:%Y-%m} {base}->{quote}. "
                f"Cost Explorer answers in {base} and the objective is in "
                f"{quote}; record a reading (INSERT INTO fx_rate ...) rather "
                f"than have this guess a rate")
        return (Decimal(str(row["quote_per_base"])), row["source"],
                row["read_at"].isoformat() if row["read_at"] else None)
