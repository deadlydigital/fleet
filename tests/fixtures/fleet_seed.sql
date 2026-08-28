-- Registry and routing policy, mirroring the deployed fleet database.
-- Tests read thresholds from here exactly as production reads them from the
-- live registry; nothing in the detector code carries a threshold.
INSERT INTO detector_registry
 (detector_key, issue_key_version, product, semantics, coverage_mode,
  cadence, grace, settle_lag, evaluation_window, schedule_epoch,
  required_clear_runs, max_attempts, execution_timeout,
  max_open_issues, max_observations_per_run, current_detector_version)
VALUES
 ('dd_analytics_reconciliation',1,'deadly_digital','LEVEL','ENUMERATED',
  '1 hour','5 minutes','15 minutes','1 hour','2026-01-01 00:00:00+00',
  2,3,'2 minutes',50,500,1),
 ('fleet_heartbeat',1,'deadly_digital','LEVEL','GLOBAL',
  '5 minutes','10 minutes','0','5 minutes','2026-01-01 00:00:00+00',
  2,3,'2 minutes',50,500,1);

INSERT INTO routing_policy (observation_type, policy_version, min_magnitude, severity)
VALUES
 ('DETECTOR_CARDINALITY_EXCEEDED',1,0,'HIGH'),
 ('DETECTOR_RUN_MISSING',1,0,'HIGH'),
 ('DETECTOR_WINDOW_ABANDONED',1,0,'CRITICAL'),
 ('MISSING_ANALYTICS_ORDER',1,0,'MEDIUM'),
 ('MISSING_ANALYTICS_ORDER',1,6,'HIGH'),
 ('MISSING_ANALYTICS_ORDER',1,100,'CRITICAL'),
 ('ORDER_FIELD_DRIFT',1,0,'CRITICAL'),
 ('ORPHANED_ANALYTICS_ORDER',1,0,'HIGH');

-- The runtime principal, with exactly the production grants: fleet_detector
-- and nothing else. Tests that exercise the detector must hit the same
-- privilege boundary the real process hits.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_test_detector') THEN
    CREATE ROLE fleet_test_detector LOGIN PASSWORD 'fleet_test_detector';
  END IF;
END $$;
GRANT fleet_detector TO fleet_test_detector;
