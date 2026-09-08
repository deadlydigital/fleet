"""dd_aws_cost — a pound ceiling measured against a dollar bill.

Two properties carry this file:

  * **A missing exchange rate produces no observation and a failed subject.**
    Not a zero, not a guess, not a default rate. The objective is in GBP and
    Cost Explorer answers in USD; with no recorded reading the two cannot be
    compared, and comparing them anyway is a 25% error in the direction of
    looking fine.
  * **The threshold is the objective's, not the detector's.** Nothing here
    knows the number 200. Change the ceiling in the objectives file and the
    percent moves; that is what "threshold from the objective" has to mean if
    it is to survive someone retuning it.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from detectors import base
from detectors.aws_cost import AwsCostDetector, CostUnavailable
from proposer.objectives import Ceiling

DETECTOR = "dd_aws_cost"
SUBJECT = "aws_account:aws"
GBP200 = Ceiling(amount=Decimal("200"), currency="GBP", period="month")

#: Roughly the September shape: $47.75 of first-of-month recurring charges
#: plus $6.93/day of usage.
SEPT = dt.date(2026, 9, 30)


class FakeCE:
    """Cost Explorer, or a refusal. Never an empty success."""

    def __init__(self, amount, currency="USD", raises=None, buckets=None):
        self.amount, self.currency, self.raises = amount, currency, raises
        self.buckets = buckets
        self.calls = []

    def get_cost_and_usage(self, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        if self.buckets is not None:
            return {"ResultsByTime": self.buckets}
        return {"ResultsByTime": [{"Total": {"UnblendedCost": {
            "Amount": str(self.amount), "Unit": self.currency}}}]}


def detector(amount=255, *, currency="USD", raises=None, buckets=None,
             ceiling=GBP200, today=SEPT):
    return AwsCostDetector(ceiling=ceiling, today=today,
                           client=FakeCE(amount, currency, raises, buckets))


def rate(admin, quote_per_base="0.7874", month="2026-09-01",
         base="USD", quote="GBP"):
    admin.execute(
        """INSERT INTO fx_rate (period_month, base_currency, quote_currency,
                                quote_per_base, source, read_at)
           VALUES (%s,%s,%s,%s,'a rate somebody read', now())""",
        (month, base, quote, quote_per_base))


def observations(admin, run_id):
    return admin.execute(
        "SELECT * FROM observations WHERE detector_run_id = %s", (run_id,)
    ).fetchall()


# ---- the refusal -----------------------------------------------------------

class TestAMissingRateRefusesRatherThanGuesses:

    def test_no_reading_fails_the_subject_and_emits_nothing(
            self, fleet, admin, dsns):
        result = base.execute(detector(), fleet)
        assert result.status == base.STATUS_PARTIAL
        assert result.subjects_failed == [SUBJECT]
        assert result.observations_created == 0

    def test_the_refusal_names_the_month_and_the_pair(self, fleet, admin, dsns):
        result = base.execute(detector(), fleet)
        assert "2026-09" in (result.error or "")
        assert "USD->GBP" in (result.error or "")

    def test_a_reading_for_a_different_month_does_not_count(
            self, fleet, admin, dsns):
        """A rate is a monthly reading. August's is not September's."""
        rate(admin, month="2026-08-01")
        result = base.execute(detector(), fleet)
        assert result.status == base.STATUS_PARTIAL

    def test_a_reading_for_a_different_pair_does_not_count(
            self, fleet, admin, dsns):
        rate(admin, base="USD", quote="EUR")
        result = base.execute(detector(), fleet)
        assert result.status == base.STATUS_PARTIAL

    def test_no_conversion_is_needed_when_the_units_already_match(
            self, fleet, admin, dsns):
        """A USD ceiling against a USD bill needs no reading at all."""
        usd = Ceiling(amount=Decimal("200"), currency="USD", period="month")
        result = base.execute(detector(255, ceiling=usd), fleet)
        assert result.status == base.STATUS_OK
        rows = observations(admin, result.run_id)
        assert rows and rows[0]["magnitude"] == 128     # 255/200


# ---- the measurement -------------------------------------------------------

class TestWhatItMeasures:

    def test_under_the_ceiling_emits_nothing(self, fleet, admin, dsns):
        rate(admin)                                    # 0.7874
        # $200 -> £157.48, 79% of the ceiling.
        result = base.execute(detector(200), fleet)
        assert result.status == base.STATUS_OK
        assert result.observations_created == 0

    def test_over_the_ceiling_emits_a_percent(self, fleet, admin, dsns):
        rate(admin)
        # $255 -> £200.79 -> 100%.
        result = base.execute(detector(255), fleet)
        rows = observations(admin, result.run_id)
        assert len(rows) == 1
        assert rows[0]["unit"] == "percent"
        assert rows[0]["magnitude"] == 100
        assert rows[0]["evidence_sample"]["base_currency"] == "USD"
        assert rows[0]["evidence_sample"]["quote_currency"] == "GBP"
        assert rows[0]["evidence_sample"]["spend_quote"] == 200.79

    def test_the_conversion_direction_is_quote_per_base(self, fleet, admin, dsns):
        """`quote_per_base` multiplies. The reciprocal is a 60% error.

        At 0.7874 USD->GBP, $255 is £200.79. Inverted it would be £323.83 and
        the detector would report 162% -- a confident CRITICAL from a rate
        applied upside down.
        """
        rate(admin, quote_per_base="0.7874")
        result = base.execute(detector(255), fleet)
        rows = observations(admin, result.run_id)
        assert rows[0]["evidence_sample"]["spend_quote"] == 200.79
        assert rows[0]["magnitude"] == 100

    def test_severity_comes_from_routing_policy(self, fleet, admin, dsns):
        rate(admin, quote_per_base="1.0")             # keeps the arithmetic plain
        for spend, expected in ((200, "MEDIUM"), (240, "HIGH"), (300, "CRITICAL")):
            admin.execute("DELETE FROM issue_occurrences")
            admin.execute("DELETE FROM observations")
            admin.execute("DELETE FROM issues")
            admin.execute("DELETE FROM detector_runs WHERE detector_key = %s",
                          (DETECTOR,))
            result = base.execute(detector(spend), fleet)
            row = admin.execute(
                "SELECT severity FROM issues WHERE issue_type = %s",
                ("AWS_SPEND_VS_CEILING",)).fetchone()
            assert row and row["severity"] == expected, spend


class TestTheThresholdIsTheObjectives:

    def test_changing_the_ceiling_moves_the_percent(self, fleet, admin, dsns):
        """Nothing in the detector knows the number 200."""
        rate(admin, quote_per_base="1.0")
        tighter = Ceiling(amount=Decimal("100"), currency="GBP", period="month")
        result = base.execute(detector(150, ceiling=tighter), fleet)
        rows = observations(admin, result.run_id)
        assert rows[0]["magnitude"] == 150            # 150/100, not 150/200

    def test_the_detector_carries_no_ceiling_of_its_own(self):
        """No numeric literal in the CODE is the ceiling.

        Checked over the AST rather than the file text. The first version
        grepped the source for "200" and failed on the docstring, which
        explains the objective -- a test that forbids documenting the thing
        is worse than no test. Comments and docstrings are not numeric
        constants, so the AST sees code only.
        """
        import ast
        import detectors.aws_cost as mod
        tree = ast.parse(open(mod.__file__).read())
        numbers = {n.value for n in ast.walk(tree)
                   if isinstance(n, ast.Constant)
                   and isinstance(n.value, (int, float))
                   and not isinstance(n.value, bool)}
        assert 200 not in numbers

    def test_a_ceiling_without_a_currency_is_refused_at_load(self, tmp_path):
        """The whole point of the block. An implied unit is the defect."""
        from proposer.objectives import load
        f = tmp_path / "o.yaml"
        f.write_text(
            "quarter: t\nobjectives:\n"
            "  - id: cost-discipline\n    statement: x\n    weight: 1.0\n"
            "    ceiling:\n      amount: 200\n      period: month\n")
        with pytest.raises(RuntimeError) as exc:
            load(f)
        assert "currency" in str(exc.value)

    def test_a_real_ceiling_declares_all_three_fields(self):
        from proposer import config
        from proposer.objectives import load
        c = load(config.PROJECT_ROOT / "objectives-2026-Q4.yaml") \
            .require("cost-discipline").ceiling
        assert (c.amount, c.currency, c.period) == (Decimal("200"), "GBP", "month")


# ---- a read that could not be made ----------------------------------------

class TestAFailedReadIsNeverAZeroBill:

    def test_cost_explorer_refusing_fails_the_subject(self, fleet, admin, dsns):
        rate(admin)
        result = base.execute(detector(raises=RuntimeError("AccessDenied")), fleet)
        assert result.status == base.STATUS_PARTIAL
        assert result.observations_created == 0

    def test_an_empty_period_list_is_a_failed_read_not_a_zero_bill(
            self, fleet, admin, dsns):
        rate(admin)
        result = base.execute(detector(buckets=[]), fleet)
        assert result.status == base.STATUS_PARTIAL
        assert "failed read, not a zero" in (result.error or "")

    def test_mixed_currencies_in_one_month_are_refused(self, fleet, admin, dsns):
        rate(admin)
        buckets = [{"Total": {"UnblendedCost": {"Amount": "10", "Unit": "USD"}}},
                   {"Total": {"UnblendedCost": {"Amount": "10", "Unit": "EUR"}}}]
        result = base.execute(detector(buckets=buckets), fleet)
        assert result.status == base.STATUS_PARTIAL
        assert "mixed currencies" in (result.error or "")


class TestTheFirstOfTheMonthIsNotAnAnomaly:

    def test_day_one_recurring_charges_do_not_fire(self, fleet, admin, dsns):
        """54.63 on 1 September is 8x the daily norm and 21% of the ceiling.

        A day-over-day detector fires on this every month forever. Measuring
        the month against a monthly objective makes it a non-event, which is
        the whole reason the subject is the month.
        """
        rate(admin)
        result = base.execute(
            detector(Decimal("54.63"), today=dt.date(2026, 9, 1)), fleet)
        assert result.status == base.STATUS_OK
        assert result.observations_created == 0


class TestTheWindowItAsksFor:

    def test_end_is_exclusive_so_today_is_included(self, fleet, admin, dsns):
        rate(admin)
        det = detector(100, today=dt.date(2026, 9, 8))
        base.execute(det, fleet)
        period = det._client.calls[0]["TimePeriod"]
        assert period["Start"] == "2026-09-01"
        assert period["End"] == "2026-09-09"      # today + 1, exclusive


# ---- what the brief says about it ------------------------------------------

class TestTheBriefClaim:
    """`cost-discipline` carried a standing UNCOMPUTED on every brief ever
    written. It now has an evidence path, and the failure modes still refuse.
    """

    @staticmethod
    def _claim(dsns):
        import psycopg
        from brief import sources as S
        from brief.pass_ import _aws_cost_claims
        # No row_factory, exactly as run_pass connects. See test_sentry_brief
        # for what a mismatched harness did last time.
        conn = psycopg.connect(dsns["fleet"], autocommit=False)
        conn.read_only = True
        try:
            out = _aws_cost_claims(S.Reader(conn, "dd_detector_login@fleet"))
        finally:
            conn.close()
        assert len(out) == 1
        return out[0]

    def test_never_run_is_uncomputed_and_says_it_is_not_a_pass(self, admin, dsns):
        c = self._claim(dsns)
        assert c.status == "UNCOMPUTED"
        assert "not a report that spend is within the ceiling" in c.uncomputed_reason

    def test_a_missing_rate_reads_as_a_refusal_not_as_compliance(
            self, fleet, admin, dsns):
        """The failure this whole design exists to make visible."""
        base.execute(detector(255), fleet)          # no fx_rate seeded
        c = self._claim(dsns)
        assert c.status == "UNCOMPUTED"
        assert c.value_num is None and c.value_text is None
        assert "dollars to pounds" in c.uncomputed_reason

    def test_under_the_ceiling_is_computed_with_no_number(
            self, fleet, admin, dsns):
        rate(admin)
        base.execute(detector(200), fleet)          # 79% -> no observation
        c = self._claim(dsns)
        assert c.status == "COMPUTED"
        assert c.value_num is None
        assert "within the 200 GBP/month ceiling" in c.statement

    def test_over_the_ceiling_carries_the_percent(self, fleet, admin, dsns):
        rate(admin)
        base.execute(detector(300), fleet)
        c = self._claim(dsns)
        assert c.status == "COMPUTED"
        assert c.value_num == 118                   # 300 * 0.7874 / 200
        assert "118%" in c.statement

    def test_the_label_names_the_ceiling_from_the_objectives_file(
            self, admin, dsns):
        c = self._claim(dsns)
        assert "200 GBP/month" in (c.statement or "")

    def test_a_settle_lag_does_not_make_a_fresh_run_read_as_stale(
            self, fleet, admin, dsns):
        """THE BUG THIS TEST EXISTS FOR.

        Staleness was measured as `now() - window_end`. dd_aws_cost has
        settle_lag of a full day, so its newest EXECUTABLE window closed
        ~2 days ago even when the run finished seconds ago — and the brief
        reported "past its cadence and grace" on a detector that had just
        succeeded. The freshness question is about the RUN, not the window.

        `_sentry_claims` carried the same rule and the same latent bug; its
        settle_lag is five minutes, so it was invisible there and would have
        appeared the day anyone raised it.
        """
        rate(admin)
        result = base.execute(detector(200), fleet)
        assert result.status == base.STATUS_OK

        run = admin.execute(
            "SELECT window_end, completed_at, now() - window_end AS window_age,"
            "       now() - completed_at AS run_age"
            "  FROM detector_runs WHERE detector_key = %s", (DETECTOR,)).fetchone()
        allowance = admin.execute(
            "SELECT cadence + grace AS a FROM detector_registry"
            " WHERE detector_key = %s", (DETECTOR,)).fetchone()["a"]

        # The window really is older than the allowance -- that is normal and
        # is what the old rule tripped on.
        assert run["window_age"] > allowance
        assert run["run_age"] < allowance
        assert self._claim(dsns).status == "COMPUTED"
