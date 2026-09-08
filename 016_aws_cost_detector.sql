-- ============================================================================
-- 016_aws_cost_detector.sql  —  the FX reading, and dd_aws_cost
--
-- `cost-discipline` is 0.05 of the quarter and has carried no evidence path at
-- all: the brief has printed it UNCOMPUTED on every run since the brief
-- existed. Cost Explorer read access closes that, and this file is what turns
-- a dollar figure into a statement about a pound ceiling without inventing a
-- number to do it with.
--
-- THE PROBLEM THIS FILE IS SHAPED BY
--
-- The objective is 200 GBP/month. Cost Explorer answers in USD. Measured
-- September: about $255 for a 30-day month, which is £204 at 1.25 and £197 at
-- 1.30 -- it crosses the ceiling at roughly 1.278. So the exchange rate is not
-- a detail that rounds away; it is the thing that decides which side of the
-- objective the month lands on.
--
-- A HARDCODED RATE IS THE STORED NUMBER THIS SYSTEM KEEPS DELETING
--
-- So the rate is a RECORDED HUMAN READING, exactly as 014 made the credit pool
-- one, and for the argument 014 already makes in full: a rate is not a
-- decision anybody takes, it is a fact about the world that changes
-- continuously, and freezing it in a function means a migration due monthly --
-- which is a migration that gets rubber-stamped.
--
-- When no reading exists for the month, the detector EMITS NOTHING and the
-- brief says why. It refuses rather than comparing two different units.
--
-- THE RATE'S DIRECTION IS ITSELF A UNIT TRAP, SO IT IS NAMED NOT LABELLED
--
-- "USD/GBP = 1.27" is ambiguous -- dollars per pound, or pounds per dollar?
-- The two are reciprocals and both are plausible readings, so a column called
-- `rate` beside a pair called `USD/GBP` is a 60% error waiting to be made.
-- The column is `quote_per_base`: ONE UNIT OF base BUYS THIS MANY UNITS OF
-- quote. USD -> GBP at 0.787 means one dollar buys 0.787 pounds, and the
-- conversion is always `amount_in_base * quote_per_base`.
--
-- Target: PostgreSQL 15+, same floor as 010 and later.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- ============================================================ 1. THE READING

CREATE TABLE IF NOT EXISTS fx_rate (
    -- One reading per month per pair, keyed by the first of the month. The
    -- same grain as model_credit_pool and for the same reason: the objective
    -- is monthly, so the rate that evaluates it is monthly.
    period_month   date NOT NULL
                   CHECK (period_month = date_trunc('month', period_month)::date),

    base_currency  text NOT NULL CHECK (base_currency ~ '^[A-Z]{3}$'),
    quote_currency text NOT NULL CHECK (quote_currency ~ '^[A-Z]{3}$'),

    -- ONE UNIT OF base BUYS THIS MANY UNITS OF quote. See the header: the
    -- name carries the direction because a label beside a pair does not.
    quote_per_base numeric(18,8) NOT NULL CHECK (quote_per_base > 0),

    -- WHERE THE NUMBER CAME FROM, in words. 014's reasoning applies unchanged
    -- and is sharper here: no process can re-derive this, so if its
    -- provenance is lost there is nothing to check it against.
    source         text NOT NULL CHECK (length(btrim(source)) > 0),

    -- WHEN IT WAS READ, which is not when the row was written.
    read_at        timestamptz NOT NULL CHECK (read_at <= now()),

    recorded_by    text NOT NULL DEFAULT current_user,
    recorded_at    timestamptz NOT NULL DEFAULT now(),
    note           text,

    PRIMARY KEY (period_month, base_currency, quote_currency),
    CONSTRAINT fx_rate_not_self_ck CHECK (base_currency <> quote_currency)
);

COMMENT ON TABLE fx_rate IS
  'One recorded human reading of an exchange rate per month per pair. Not '
  'derived, not fetched, not defaulted -- when a month has no reading, every '
  'consumer refuses rather than guessing.';
COMMENT ON COLUMN fx_rate.quote_per_base IS
  'One unit of base_currency buys this many units of quote_currency. '
  'Convert with amount_in_base * quote_per_base.';

-- Nothing may edit a reading. A rate that was wrong is a new reading with its
-- own read_at, not a silent correction of the row a past comparison used --
-- the same append-only rule as decision_log and reconciliation_runs.
CREATE OR REPLACE FUNCTION guard_fx_rate_immutability() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION 'fx_rate readings are immutable; record a new reading'
        USING HINT = 'a corrected rate is a new row with its own read_at';
END; $$;

DROP TRIGGER IF EXISTS fx_rate_immutable ON fx_rate;
CREATE TRIGGER fx_rate_immutable BEFORE UPDATE ON fx_rate
    FOR EACH ROW EXECUTE FUNCTION guard_fx_rate_immutability();

-- ============================================================ 2. THE DETECTOR

-- GLOBAL, not ENUMERATED: there is one AWS account and one billing month, so
-- there is nothing to enumerate and no per-subject coverage to track.
--
-- product = 'deadly_digital' to match the two existing rows. The account in
-- fact carries everything, and cost-discipline says "neither venture" -- but
-- introducing a second product value here would be the first in the registry
-- and would ripple into _product_for_detector's one-product-per-key rule for
-- no gain today. Noted rather than smuggled.
INSERT INTO detector_registry
 (detector_key, issue_key_version, product, semantics, coverage_mode,
  cadence, grace, settle_lag, evaluation_window, schedule_epoch,
  required_clear_runs, max_attempts, execution_timeout,
  max_open_issues, max_observations_per_run, current_detector_version)
VALUES
 ('dd_aws_cost', 1, 'deadly_digital', 'LEVEL', 'GLOBAL',
  -- Daily. Cost Explorer updates a few times a day and charges $0.01 per
  -- request, so this is 30 calls and about 30 cents a month.
  '1 day',
  '6 hours',
  -- CE's most recent day is always partial -- measured at $1.26 against a
  -- $6.93 daily norm. A settled window keeps the run off data still landing.
  '1 day',
  '1 day', '2026-01-01 00:00:00+00',
  2, 3, '2 minutes', 50, 500, 1)
ON CONFLICT (detector_key, issue_key_version, product) DO NOTHING;

-- MAGNITUDE IS PERCENT OF THE CEILING CONSUMED, AND THAT IS WHAT KEEPS THE
-- EXCHANGE RATE OUT OF THIS TABLE.
--
-- Banding on USD would put a dollar number here standing in for a pound
-- objective -- a hardcoded rate hiding in a data table, which is the same
-- defect as a hardcoded rate in a function wearing a different hat. A percent
-- has no currency in it. Computing it requires the fx_rate reading, so with no
-- reading there is no observation and the brief reports the gap.
--
-- THERE IS NO EARLY-WARNING BAND, DELIBERATELY. 100 is the objective itself;
-- anything below it is a number nobody has chosen. Warning before a breach
-- needs a projection of the month, and projection is growth detection, which
-- is deferred until there is more than one month of history not distorted by
-- the infrastructure that has just been switched off.
INSERT INTO routing_policy (observation_type, policy_version, min_magnitude, severity)
VALUES
 ('AWS_SPEND_VS_CEILING', 1, 100, 'MEDIUM'),
 ('AWS_SPEND_VS_CEILING', 1, 120, 'HIGH'),
 ('AWS_SPEND_VS_CEILING', 1, 150, 'CRITICAL')
ON CONFLICT (observation_type, policy_version, min_magnitude) DO NOTHING;

-- ============================================================ 3. GRANTS

REVOKE ALL ON fx_rate FROM PUBLIC;

-- The detector reads the rate to compute the percent.
GRANT SELECT ON fx_rate TO fleet_detector;

-- The console records readings and reads them back; the read-only console
-- page and the brief reader see them.
GRANT SELECT, INSERT ON fx_rate TO fleet_console;
GRANT SELECT ON fx_rate TO fleet_console_reader;

-- No UPDATE to anybody but the admin: the trigger refuses it, and the absent
-- grant means the refusal is never reached.
GRANT SELECT, INSERT, DELETE ON fx_rate TO fleet_admin;

COMMIT;
