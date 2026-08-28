-- DETECTOR_WINDOW_ABANDONED: a run left ERROR having burned max_attempts.
-- Scoped to runs that closed within the last cadence + grace so that the
-- condition can stop being true, and the issue can clear the ordinary way
-- after required_clear_runs. An all-time count would never clear.
SELECT count(*)::bigint AS n,
       max(dr.window_end) AS latest_window_end,
       max(dr.attempt_count) AS attempts,
       (array_agg(dr.id ORDER BY dr.window_end DESC))[1:5] AS run_ids
  FROM detector_runs dr
  JOIN detector_registry reg
    ON reg.detector_key = dr.detector_key
   AND reg.issue_key_version = dr.issue_key_version
   AND reg.product = dr.product
 WHERE dr.detector_key = %(k)s AND dr.issue_key_version = %(v)s
   AND dr.product = %(p)s
   AND dr.run_mode = 'SCHEDULED'
   AND dr.status = 'ERROR'
   AND dr.attempt_count >= reg.max_attempts
   AND dr.completed_at > now() - (reg.cadence + reg.grace);
