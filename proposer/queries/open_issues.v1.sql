-- Open issues with severity, magnitude, occurrence count and age.
--
-- No ordering by severity: 'CRITICAL' < 'HIGH' < 'LOW' alphabetically, which
-- is not a priority order, and imposing a real one here would be the adapter
-- deciding what matters. It reports; the cycle ranks.
SELECT i.id,
       i.fingerprint,
       i.product,
       i.issue_type,
       i.subject_type,
       i.subject_id,
       i.detector_key,
       i.issue_key_version,
       i.severity,
       i.current_magnitude,
       i.current_unit,
       i.occurrence_count,
       i.reopen_count,
       i.first_seen,
       i.last_seen,
       i.created_at,
       extract(epoch FROM now() - i.first_seen)::bigint AS age_seconds,
       extract(epoch FROM now() - i.last_seen)::bigint  AS since_last_seen_seconds,
       -- The condition is still being observed, as opposed to observed once
       -- and never cleared. A detector that has stopped running produces the
       -- same "open" row as a condition that is still happening, and the two
       -- want opposite responses.
       --
       -- settle_lag is in the budget because a window is not judgeable until
       -- it has settled: without it an hourly detector with a 15-minute lag
       -- reads as "no longer observing" for a quarter of every hour.
       (i.last_seen >= now() - (reg.cadence + reg.settle_lag + reg.grace))
           AS still_observed,
       reg.cadence,
       reg.grace,
       reg.settle_lag,
       reg.semantics,
       reg.required_clear_runs
  FROM issues i
  LEFT JOIN detector_registry reg
    ON reg.detector_key      = i.detector_key
   AND reg.issue_key_version = i.issue_key_version
   AND reg.product           = i.product
 WHERE i.status = 'OPEN'
 ORDER BY i.first_seen, i.id;
