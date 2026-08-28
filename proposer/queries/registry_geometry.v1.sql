-- Schedule geometry and last-success time per registered detector.
--
-- Two jobs. It is the freshness bound for every reading that rests on
-- detector output -- cadence + grace is how long a healthy detector may be
-- silent -- and it is the "as of" for those readings, taken as the OLDEST
-- last-success across active detectors rather than the newest. A healthy
-- heartbeat must not vouch for a reconciliation detector that died: the
-- weakest link is what the answer is actually as fresh as.
--
-- run_mode = 'SCHEDULED' throughout: a backfill looks exactly like a healthy
-- recent execution, and counting one would let a backfill mask a dead
-- scheduler.
SELECT reg.detector_key,
       reg.issue_key_version,
       reg.product,
       reg.semantics,
       reg.coverage_mode,
       reg.cadence,
       reg.grace,
       reg.settle_lag,
       reg.required_clear_runs,
       reg.max_attempts,
       reg.retired_at,
       reg.maintenance_until,
       (reg.cadence + reg.grace)                       AS silence_budget,
       last_ok.completed_at                            AS last_ok_at,
       last_ok.window_end                              AS last_ok_window_end,
       last_any.started_at                             AS last_run_at,
       last_any.status                                 AS last_run_status
  FROM detector_registry reg
  LEFT JOIN LATERAL (
       SELECT dr.completed_at, dr.window_end
         FROM detector_runs dr
        WHERE dr.detector_key      = reg.detector_key
          AND dr.issue_key_version = reg.issue_key_version
          AND dr.product           = reg.product
          AND dr.run_mode          = 'SCHEDULED'
          AND dr.status IN ('OK','PARTIAL')
          AND dr.completed_at IS NOT NULL
        ORDER BY dr.completed_at DESC
        LIMIT 1) last_ok ON true
  LEFT JOIN LATERAL (
       SELECT dr.started_at, dr.status
         FROM detector_runs dr
        WHERE dr.detector_key      = reg.detector_key
          AND dr.issue_key_version = reg.issue_key_version
          AND dr.product           = reg.product
          AND dr.run_mode          = 'SCHEDULED'
        ORDER BY dr.started_at DESC
        LIMIT 1) last_any ON true
 ORDER BY reg.detector_key, reg.issue_key_version, reg.product;
