-- Every registered, non-retired detector carrying a row for this product.
-- A detector under declared maintenance is still enumerated; the heartbeat
-- decides per observation type what maintenance suppresses.
SELECT detector_key, issue_key_version, product,
       cadence, grace, execution_timeout, max_attempts,
       maintenance_until,
       maintenance_until IS NOT NULL AND maintenance_until > now() AS in_maintenance
  FROM detector_registry
 WHERE product = %(p)s
   AND retired_at IS NULL
 ORDER BY detector_key, issue_key_version;
