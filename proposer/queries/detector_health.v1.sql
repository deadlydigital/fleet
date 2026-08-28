-- Detector health from detector_runs.
--
-- Answered from the run history's own timestamps, so it is correct whenever
-- it is asked and cannot itself be stale. Everything else this adapter
-- returns depends on it being true.
--
-- consecutive_errors is the length of the ERROR streak at the head of the
-- history: the position of the most recent non-ERROR run, minus one. When
-- every run is an ERROR that is every run.
WITH sched AS (
    SELECT dr.detector_key, dr.issue_key_version, dr.product,
           dr.status, dr.window_end, dr.started_at, dr.completed_at,
           dr.attempt_count, dr.observations_created, dr.observations_truncated,
           dr.duration_ms,
           row_number() OVER (PARTITION BY dr.detector_key, dr.issue_key_version,
                                           dr.product
                              ORDER BY dr.window_end DESC) AS rn
      FROM detector_runs dr
     WHERE dr.run_mode = 'SCHEDULED'
), streak AS (
    SELECT detector_key, issue_key_version, product,
           coalesce(min(rn) FILTER (WHERE status <> 'ERROR'), max(rn) + 1) - 1
               AS consecutive_errors
      FROM sched
     GROUP BY 1, 2, 3
), tally AS (
    SELECT detector_key, issue_key_version, product,
           count(*)                                            AS total_runs,
           count(*) FILTER (WHERE status IN ('OK','PARTIAL'))   AS successful_runs,
           count(*) FILTER (WHERE status = 'ERROR')             AS error_runs,
           count(*) FILTER (WHERE status = 'RUNNING')           AS running_runs,
           count(*) FILTER (WHERE status = 'TIMEOUT')           AS timeout_runs,
           count(*) FILTER (WHERE observations_truncated)       AS truncated_runs,
           max(window_end) FILTER (WHERE status IN ('OK','PARTIAL'))
                                                                AS last_ok_window_end,
           max(completed_at) FILTER (WHERE status IN ('OK','PARTIAL'))
                                                                AS last_ok_at,
           max(started_at)                                      AS last_run_at
      FROM sched
     GROUP BY 1, 2, 3
)
SELECT reg.detector_key,
       reg.issue_key_version,
       reg.product,
       reg.cadence,
       reg.grace,
       reg.settle_lag,
       (reg.cadence + reg.grace)                    AS silence_budget,
       reg.max_attempts,
       reg.retired_at,
       reg.maintenance_until,
       coalesce(t.total_runs, 0)                    AS total_runs,
       coalesce(t.successful_runs, 0)               AS successful_runs,
       coalesce(t.error_runs, 0)                    AS error_runs,
       coalesce(t.running_runs, 0)                  AS running_runs,
       coalesce(t.timeout_runs, 0)                  AS timeout_runs,
       coalesce(t.truncated_runs, 0)                AS truncated_runs,
       coalesce(s.consecutive_errors, 0)            AS consecutive_errors,
       t.last_ok_at,
       t.last_ok_window_end,
       t.last_run_at,
       CASE WHEN t.last_ok_at IS NULL THEN NULL
            ELSE extract(epoch FROM now() - t.last_ok_at)::bigint END
                                                    AS seconds_since_ok,
       -- How many whole cadences of silence the missing runs amount to,
       -- measured against the newest window that is currently judgeable
       -- rather than against now(). A window cannot be executed until it has
       -- settled, so counting from now() reports every healthy detector with
       -- a settle_lag as one slot behind for most of each cadence.
       CASE WHEN t.last_ok_window_end IS NULL THEN NULL
            ELSE greatest(0, floor(extract(epoch FROM now() - reg.settle_lag
                                           - reg.grace - t.last_ok_window_end)
                                   / extract(epoch FROM reg.cadence)))::bigint END
                                                    AS missed_slots
  FROM detector_registry reg
  LEFT JOIN tally  t ON t.detector_key = reg.detector_key
                    AND t.issue_key_version = reg.issue_key_version
                    AND t.product = reg.product
  LEFT JOIN streak s ON s.detector_key = reg.detector_key
                    AND s.issue_key_version = reg.issue_key_version
                    AND s.product = reg.product
 ORDER BY reg.detector_key, reg.issue_key_version, reg.product;
