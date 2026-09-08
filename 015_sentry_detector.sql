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
-- EDITED IN PLACE RATHER THAN SUPERSEDED BY A 016
--
-- 015 has never been applied anywhere but test databases -- verified against
-- production, which holds zero dd_api_errors registry rows and zero
-- SENTRY_UNRESOLVED_ISSUES routing rows. A forward-only 016 that immediately
-- contradicted an unapplied 015 would leave two files disagreeing about the
-- bands and nothing in the fleet database to explain which won.
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

-- MAGNITUDE IS EVENT VOLUME, NOT THE NUMBER OF ISSUES.
--
-- This reverses the first version of this file, which banded on issue count
-- and argued that volume is not severity. The case that settled it is the one
-- that prompted the detector: twenty-five unresolved issues had accumulated
-- unseen, and under an issue-count rule that reads CRITICAL and stops. The
-- first thing a person needs to know is whether ONE of them is firing in a
-- loop right now, which is a count of events. One issue at fifty thousand
-- events is an incident; twenty-five at one event each is a backlog, and the
-- issue count cannot tell those apart. It is still carried, in evidence_sample,
-- and it is what the brief's sentence leads with.
--
-- Events are counted over the detector's 24h query window, across all
-- unresolved issues in the project.
--
-- 1-99 MEDIUM, 100-999 HIGH, 1000+ CRITICAL. GUESSES, as the header says --
-- nothing has read this project, so there is no distribution to set them
-- against and the first week of readings is the evidence. The detector emits
-- only when there is something unresolved, so the min_magnitude 0 band is
-- reached from 1 event upward and a clean project produces no observation at
-- all -- which is what lets required_clear_runs resolve the issue.
INSERT INTO routing_policy (observation_type, policy_version, min_magnitude, severity)
VALUES
 ('SENTRY_UNRESOLVED_ISSUES', 1,    0, 'MEDIUM'),
 ('SENTRY_UNRESOLVED_ISSUES', 1,  100, 'HIGH'),
 ('SENTRY_UNRESOLVED_ISSUES', 1, 1000, 'CRITICAL')
ON CONFLICT (observation_type, policy_version, min_magnitude) DO NOTHING;

COMMIT;
