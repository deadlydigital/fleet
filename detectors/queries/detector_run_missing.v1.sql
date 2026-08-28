-- DETECTOR_RUN_MISSING
-- now() > last successful run's completed_at + cadence + grace.
--
-- "Successful" is OK or PARTIAL. PARTIAL is what the schema itself counts as
-- a covering run (coverage_horizon_valid, resolve_cleared_issues), and a
-- detector that runs every hour and always loses one tenant is not a dead
-- scheduler -- that is what DETECTOR_ERROR_STREAK is for.
--
-- run_mode = 'SCHEDULED' throughout: a backfill would otherwise mask a dead
-- scheduler by looking exactly like a recent successful run.
WITH reg AS (
    SELECT cadence, grace FROM detector_registry
     WHERE detector_key = %(k)s AND issue_key_version = %(v)s AND product = %(p)s
), last_good AS (
    SELECT max(completed_at) AS at FROM detector_runs
     WHERE detector_key = %(k)s AND issue_key_version = %(v)s AND product = %(p)s
       AND run_mode = 'SCHEDULED' AND status IN ('OK','PARTIAL')
       AND completed_at IS NOT NULL
), first_ever AS (
    -- Fallback for a detector that has been scheduled but has never yet
    -- succeeded. With no run at all there is no evidence it was ever
    -- expected to run, and firing on registration alone is a false positive.
    SELECT min(started_at) AS at FROM detector_runs
     WHERE detector_key = %(k)s AND issue_key_version = %(v)s AND product = %(p)s
       AND run_mode = 'SCHEDULED'
)
SELECT coalesce(lg.at, fe.at)                        AS reference_at,
       (lg.at IS NOT NULL)                           AS has_successful_run,
       coalesce(lg.at, fe.at) + reg.cadence + reg.grace AS due_at,
       extract(epoch FROM reg.cadence + reg.grace)::bigint AS allowance_seconds,
       extract(epoch FROM now() - coalesce(lg.at, fe.at))::bigint AS since_seconds,
       greatest(0, extract(epoch FROM
           now() - (coalesce(lg.at, fe.at) + reg.cadence + reg.grace)))::bigint
                                                     AS overdue_seconds
  FROM reg, last_good lg, first_ever fe;
