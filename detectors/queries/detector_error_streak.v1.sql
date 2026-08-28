-- DETECTOR_ERROR_STREAK: three consecutive non-OK runs.
-- Only completed runs count. A run that is still RUNNING has not failed yet,
-- and counting it would make every in-flight detector look like a streak.
WITH ordered AS (
    SELECT id, status, window_end,
           row_number() OVER (ORDER BY window_end DESC) AS rn
      FROM detector_runs
     WHERE detector_key = %(k)s AND issue_key_version = %(v)s AND product = %(p)s
       AND run_mode = 'SCHEDULED'
       AND status IN ('OK','PARTIAL','ERROR','TIMEOUT')
), boundary AS (
    SELECT coalesce(min(rn), 2147483647) AS rn FROM ordered WHERE status = 'OK'
)
SELECT count(*)::bigint AS streak_length,
       min(o.window_end) AS streak_start,
       max(o.window_end) AS streak_end,
       (array_agg(o.id ORDER BY o.window_end DESC))[1:5] AS run_ids
  FROM ordered o, boundary b
 WHERE o.rn < b.rn;
