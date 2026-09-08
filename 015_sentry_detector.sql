-- ============================================================================
-- 015_sentry_detector.sql  —  registering dd_api_errors
--
-- Sentry has been collecting from the API and the worker since the DSN was set
-- and nothing has ever read it. This registers the third detector so that it
-- can be, and it is DATA ONLY: a detector_registry row and its routing_policy
-- bands. No table, no function, no grant.
--
-- THE DSN IS NOT A READ CREDENTIAL, AND THAT IS WHY THIS NEEDED A NEW SECRET
--
-- SENTRY_DSN in the deadly-digital-api container is an INGEST key. It
-- authorises sending events and nothing else; there is no read path through
-- it. Reading issues needs an organisation auth token with event:read, which
-- is a different credential with a different lifetime, and it lives in
-- fleet/.env with every other fleet secret rather than in the app container.
-- The app writes to Sentry; fleet reads from it; neither holds the other's
-- credential.
--
-- WHY LEVEL/ENUMERATED
--
-- "How many issues are unresolved" is a level, not an event count: it is true
-- at an instant, it goes down when someone resolves one, and required_clear_runs
-- is what stops a single quiet poll closing an issue that is still live. The
-- subject is the Sentry PROJECT, enumerated rather than global, because a
-- second project (the frontend has its own DSN) must be able to fail
-- independently rather than taking the whole run down with it.
--
-- THE BANDS ARE A GUESS AND SAY SO
--
-- Nothing has ever read this project, so there is no measured distribution to
-- set them against -- the first week of readings is the evidence, and these
-- numbers should be revisited once it exists. They are deliberately not tuned
-- to make the first run look calm.
--
-- Target: PostgreSQL 15+, same floor as 010 and later.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- Idempotent: this file is replayed into every test database and may be
-- re-applied to production without a second row appearing.
INSERT INTO detector_registry
 (detector_key, issue_key_version, product, semantics, coverage_mode,
  cadence, grace, settle_lag, evaluation_window, schedule_epoch,
  required_clear_runs, max_attempts, execution_timeout,
  max_open_issues, max_observations_per_run, current_detector_version)
VALUES
 ('dd_api_errors', 1, 'deadly_digital', 'LEVEL', 'ENUMERATED',
  -- cadence 15m: fast enough that an error surfacing at 09:00 is in the
  -- 09:15 reading, slow enough that 96 calls a day is nothing against any
  -- Sentry tier.
  '15 minutes',
  -- grace 10m: the heartbeat raises DETECTOR_RUN_MISSING past cadence+grace.
  '10 minutes',
  -- settle_lag 5m: Sentry ingestion is not instant. This is a LEVEL read
  -- rather than a windowed count so the lag matters less than it would for
  -- the reconciliation detector, but reading a window the instant it closes
  -- still measures a project that has not finished telling us about it.
  '5 minutes',
  '15 minutes', '2026-01-01 00:00:00+00',
  -- required_clear_runs 2: one quiet poll is not a fix. Same as the other two.
  2, 3, '2 minutes', 50, 500, 1)
ON CONFLICT (detector_key, issue_key_version, product) DO NOTHING;

-- Magnitude is the count of UNRESOLVED ISSUES, not of events. An issue with
-- ten thousand events is one issue: the count is what a person triages, and
-- the event totals ride along in evidence_sample rather than being folded
-- into a composite nobody can decompose later.
--
-- 1-4 MEDIUM, 5-24 HIGH, 25+ CRITICAL. Guesses, as the header says. The
-- detector only emits when the count is above zero, so the min_magnitude 0
-- band is reached from 1 upward and a clean project produces no observation
-- at all -- which is what lets required_clear_runs resolve the issue.
INSERT INTO routing_policy (observation_type, policy_version, min_magnitude, severity)
VALUES
 ('SENTRY_UNRESOLVED_ISSUES', 1,  0, 'MEDIUM'),
 ('SENTRY_UNRESOLVED_ISSUES', 1,  5, 'HIGH'),
 ('SENTRY_UNRESOLVED_ISSUES', 1, 25, 'CRITICAL')
ON CONFLICT (observation_type, policy_version, min_magnitude) DO NOTHING;

COMMIT;
