-- Coverage gaps that block an open issue from ever resolving.
--
-- This mirrors resolve_cleared_issues() exactly, read-only, and reports why
-- each open LEVEL issue would not clear if that function ran now. The point
-- is the difference between "the condition is still happening" and "the
-- condition may well have stopped but no run is allowed to say so", which
-- look identical from the issues table alone.
--
-- eff is the window_end of the required_clear_runs'th qualifying run after
-- last_seen -- the same OFFSET/LIMIT as the resolver, not a recount.
WITH candidate AS (
    SELECT i.id, i.fingerprint, i.product, i.issue_type, i.severity,
           i.subject_type, i.subject_id, i.detector_key, i.issue_key_version,
           i.first_seen, i.last_seen, i.occurrence_count,
           reg.semantics, reg.required_clear_runs, reg.cadence, reg.grace,
           (i.last_seen >= now() - (reg.cadence + reg.settle_lag + reg.grace))
           AS still_observed,
           (SELECT count(*)
              FROM detector_runs dr
             WHERE dr.detector_key      = i.detector_key
               AND dr.issue_key_version = i.issue_key_version
               AND dr.product           = i.product
               AND dr.run_mode          = 'SCHEDULED'
               AND dr.status IN ('OK','PARTIAL')
               AND dr.observations_truncated = false
               AND dr.window_end > i.last_seen
               AND (dr.coverage_mode = 'GLOBAL'
                    OR ((i.subject_type || ':' || i.subject_id)
                        = ANY (dr.subjects_evaluated)
                        AND NOT ((i.subject_type || ':' || i.subject_id)
                                 = ANY (coalesce(dr.subjects_failed, '{}'))))))
               AS qualifying_runs_since,
           (SELECT dr.window_end
              FROM detector_runs dr
             WHERE dr.detector_key      = i.detector_key
               AND dr.issue_key_version = i.issue_key_version
               AND dr.product           = i.product
               AND dr.run_mode          = 'SCHEDULED'
               AND dr.status IN ('OK','PARTIAL')
               AND dr.observations_truncated = false
               AND dr.window_end > i.last_seen
               AND (dr.coverage_mode = 'GLOBAL'
                    OR ((i.subject_type || ':' || i.subject_id)
                        = ANY (dr.subjects_evaluated)
                        AND NOT ((i.subject_type || ':' || i.subject_id)
                                 = ANY (coalesce(dr.subjects_failed, '{}')))))
             ORDER BY dr.window_end
            OFFSET (reg.required_clear_runs - 1) LIMIT 1) AS eff
      FROM issues i
      JOIN detector_registry reg
        ON reg.detector_key      = i.detector_key
       AND reg.issue_key_version = i.issue_key_version
       AND reg.product           = i.product
     WHERE i.status = 'OPEN'
       AND reg.semantics = 'LEVEL'
)
SELECT c.*,
       CASE WHEN c.eff IS NOT NULL THEN
            coverage_horizon_valid(c.detector_key, c.issue_key_version,
                                   c.product, c.last_seen, c.eff, now())
       END AS horizon_valid,
       CASE WHEN c.eff IS NOT NULL THEN
            subject_horizon_covered(c.detector_key, c.issue_key_version,
                                    c.product, c.subject_type, c.subject_id,
                                    c.last_seen, c.eff, now())
       END AS subject_covered,
       CASE WHEN c.eff IS NOT NULL THEN
            subject_identity_stable(c.detector_key, c.issue_key_version,
                                    c.product, c.subject_type, c.subject_id,
                                    c.last_seen, c.eff)
       END AS identity_stable
  FROM candidate c
 ORDER BY c.first_seen, c.id;
