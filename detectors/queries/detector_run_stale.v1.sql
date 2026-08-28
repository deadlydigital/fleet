-- DETECTOR_RUN_STALE: still RUNNING past execution_timeout.
-- execution_timeout, not a cadence-derived guess: how often a detector runs
-- and how long one execution may take are different questions.
-- The caller's own run is excluded; it is running because we are running.
SELECT dr.id AS run_id,
       dr.window_end,
       dr.attempt_count,
       extract(epoch FROM now() - dr.last_attempt_at)::bigint AS running_seconds,
       extract(epoch FROM reg.execution_timeout)::bigint      AS timeout_seconds
  FROM detector_runs dr
  JOIN detector_registry reg
    ON reg.detector_key = dr.detector_key
   AND reg.issue_key_version = dr.issue_key_version
   AND reg.product = dr.product
 WHERE dr.detector_key = %(k)s AND dr.issue_key_version = %(v)s
   AND dr.product = %(p)s
   AND dr.run_mode = 'SCHEDULED'
   AND dr.status = 'RUNNING'
   AND dr.id <> %(self_run_id)s
   AND dr.last_attempt_at < now() - reg.execution_timeout
 ORDER BY dr.window_end;
