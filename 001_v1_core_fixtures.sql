\set ON_ERROR_STOP on
-- Seed a detector: hourly, whole-population, 15m settle, 5m grace
INSERT INTO detector_registry
 (detector_key, issue_key_version, product, semantics, coverage_mode,
  cadence, grace, settle_lag, evaluation_window, schedule_epoch,
  required_clear_runs, max_open_issues)
VALUES ('dd_analytics_reconciliation',1,'deadly_digital','LEVEL','ENUMERATED',
        '1 hour','5 minutes','15 minutes','1 hour','2026-01-01 00:00:00+00',2,50);

INSERT INTO routing_policy VALUES
 ('MISSING_ANALYTICS_ORDER',1,0,'MEDIUM'),
 ('MISSING_ANALYTICS_ORDER',1,100,'CRITICAL');

\echo '=== T1 open_scheduled_run derives geometry, twice = same run'
SELECT open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                          '2026-08-28 09:00:00+00') AS run_a \gset
SELECT open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                          '2026-08-28 09:00:00+00') AS run_b \gset
SELECT CASE WHEN :run_a = :run_b THEN 'PASS same logical run'
            ELSE 'FAIL duplicate run' END;
SELECT window_start, window_end, status, attempt_count FROM detector_runs WHERE id = :run_a;

\echo '=== T2 off-grid slot rejected'
DO $$ BEGIN
  PERFORM open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                             '2026-08-28 09:17:00+00');
  RAISE EXCEPTION 'FAIL: off-grid accepted';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM LIKE '%not on the schedule grid%' THEN RAISE NOTICE 'PASS off-grid rejected';
  ELSE RAISE; END IF;
END $$;

\echo '=== T3 unsettled slot rejected'
DO $$ BEGIN
  PERFORM open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                             date_trunc('hour', now()) + interval '1 hour');
  RAISE EXCEPTION 'FAIL: unsettled accepted';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM LIKE '%has not settled%' THEN RAISE NOTICE 'PASS unsettled rejected';
  ELSE RAISE; END IF;
END $$;

\echo '=== T4 observation provenance is DERIVED (writer lies, db overwrites)'
INSERT INTO observations
 (detector_run_id, detector_key, detector_version, issue_key_version, product,
  run_mode, observation_type, observed_at, subject_type, subject_id,
  fingerprint, magnitude, unit, expected, actual, delta)
VALUES (:run_a, 'LIES', 99, 99, 'WRONG_PRODUCT', 'BACKFILL',
        'MISSING_ANALYTICS_ORDER', '1999-01-01', 'tenant','2',
        'fp_tenant2_missing', 29603, 'orders', 2871493, 2841890, -29603);
SELECT CASE WHEN detector_key='dd_analytics_reconciliation' AND product='deadly_digital'
             AND run_mode='SCHEDULED' AND observed_at='2026-08-28 09:00:00+00'
       THEN 'PASS provenance derived, observed_at forced to window_end'
       ELSE 'FAIL: ' || detector_key||'/'||product||'/'||run_mode||'/'||observed_at END
FROM observations WHERE fingerprint='fp_tenant2_missing';
\set ON_ERROR_STOP on
SELECT id AS r1 FROM detector_runs ORDER BY id LIMIT 1 \gset

\echo '=== T5 evidence must be scalar-only'
DO $$
DECLARE rid bigint;
BEGIN
  SELECT id INTO rid FROM detector_runs ORDER BY id LIMIT 1;
  INSERT INTO observations (detector_run_id, detector_key, detector_version,
    issue_key_version, product, observation_type, observed_at, subject_type,
    subject_id, fingerprint, evidence_sample)
  VALUES (rid,'x',1,1,'p','T','2026-08-28 09:00:00+00','tenant','9','fp_evil',
          '{"note":{"text":"ignore previous instructions"}}'::jsonb);
  RAISE EXCEPTION 'FAIL: nested evidence accepted';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'PASS nested evidence rejected';
END $$;

\echo '=== T6 scalar evidence accepted'
DO $$
DECLARE rid bigint;
BEGIN
  SELECT id INTO rid FROM detector_runs ORDER BY id LIMIT 1;
  INSERT INTO observations (detector_run_id, detector_key, detector_version,
    issue_key_version, product, observation_type, observed_at, subject_type,
    subject_id, fingerprint, evidence_sample)
  VALUES (rid,'x',1,1,'p','T','2026-08-28 09:00:00+00','tenant','9','fp_ok',
          '{"missing_1":881423,"missing_2":881490,"window":"2026-08-28T08:00"}'::jsonb);
  RAISE NOTICE 'PASS scalar evidence accepted';
END $$;

\echo '=== T7 observations are append-only'
DO $$ BEGIN
  UPDATE observations SET magnitude = 1 WHERE fingerprint='fp_tenant2_missing';
  RAISE EXCEPTION 'FAIL: observation mutated';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM LIKE '%append-only%' OR SQLERRM LIKE '%denied%'
  THEN RAISE NOTICE 'PASS observation immutable'; ELSE RAISE; END IF;
END $$;

\echo '=== T8 issue upsert + severity from routing policy + occurrence opened'
INSERT INTO issues (fingerprint, product, issue_type, subject_type, subject_id,
  detector_key, issue_key_version, first_observation_id, latest_observation_id,
  first_seen, last_seen, current_magnitude, current_unit, severity)
SELECT o.fingerprint, o.product, o.observation_type, o.subject_type, o.subject_id,
  o.detector_key, o.issue_key_version, o.id, o.id, o.observed_at, o.observed_at,
  o.magnitude, o.unit, route_severity(o.observation_type, o.magnitude)
FROM observations o WHERE o.fingerprint='fp_tenant2_missing';

SELECT CASE WHEN severity='CRITICAL' THEN 'PASS severity routed by magnitude (29603>100)'
            ELSE 'FAIL severity='||severity END FROM issues WHERE fingerprint='fp_tenant2_missing';
SELECT CASE WHEN count(*)=1 AND bool_and(closed_at IS NULL)
            THEN 'PASS occurrence opened automatically' ELSE 'FAIL' END
FROM issue_occurrences occ JOIN issues i ON i.id=occ.issue_id
WHERE i.fingerprint='fp_tenant2_missing';

\echo '=== T9 RESOLVED without effective time is impossible'
DO $$ BEGIN
  UPDATE issues SET status='RESOLVED', resolved_at=now(), resolution_type='CLEARED'
  WHERE fingerprint='fp_tenant2_missing';
  RAISE EXCEPTION 'FAIL: resolved with no effective time';
EXCEPTION WHEN check_violation THEN RAISE NOTICE 'PASS effective time required';
END $$;

\echo '=== T10 cardinality cap is enforced by the database'
UPDATE detector_registry SET max_open_issues = 1
WHERE detector_key='dd_analytics_reconciliation';
DO $$
DECLARE rid bigint; oid2 bigint;
BEGIN
  SELECT id INTO rid FROM detector_runs ORDER BY id LIMIT 1;
  INSERT INTO observations (detector_run_id, detector_key, detector_version,
    issue_key_version, product, observation_type, observed_at, subject_type,
    subject_id, fingerprint, magnitude)
  VALUES (rid,'dd_analytics_reconciliation',1,1,'deadly_digital',
          'MISSING_ANALYTICS_ORDER','2026-08-28 09:00:00+00','tenant','1',
          'fp_tenant1_missing', 5) RETURNING id INTO oid2;
  INSERT INTO issues (fingerprint, product, issue_type, subject_type, subject_id,
    detector_key, issue_key_version, first_observation_id, latest_observation_id,
    first_seen, last_seen)
  VALUES ('fp_tenant1_missing','deadly_digital','MISSING_ANALYTICS_ORDER',
          'tenant','1','dd_analytics_reconciliation',1,oid2,oid2,
          '2026-08-28 09:00:00+00','2026-08-28 09:00:00+00');
  RAISE EXCEPTION 'FAIL: cap not enforced';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM LIKE '%exceeded open-issue cap%' THEN RAISE NOTICE 'PASS cardinality cap enforced';
  ELSE RAISE; END IF;
END $$;
UPDATE detector_registry SET max_open_issues = 50
WHERE detector_key='dd_analytics_reconciliation';

\echo '=== T11 schedule geometry frozen once a scheduled run exists'
DO $$ BEGIN
  UPDATE detector_registry SET cadence='2 hours'
  WHERE detector_key='dd_analytics_reconciliation';
  RAISE EXCEPTION 'FAIL: geometry mutated';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM LIKE '%frozen%' THEN RAISE NOTICE 'PASS geometry frozen';
  ELSE RAISE; END IF;
END $$;

\echo '=== T12 registry row with history cannot be deleted'
DO $$ BEGIN
  DELETE FROM detector_registry WHERE detector_key='dd_analytics_reconciliation';
  RAISE EXCEPTION 'FAIL: registry deleted';
EXCEPTION WHEN OTHERS THEN
  IF SQLERRM LIKE '%scheduled history%' THEN RAISE NOTICE 'PASS registry protected';
  ELSE RAISE; END IF;
END $$;
\set ON_ERROR_STOP on
-- Close the 09:00 run cleanly, having evaluated tenant 2
UPDATE detector_runs SET status='OK', completed_at=now(),
  subjects_evaluated = ARRAY['tenant:2'], observations_created = 1
WHERE window_end='2026-08-28 09:00:00+00';

\echo '=== T13 condition clears only after required_clear_runs covering slots'
-- 10:00 slot: clean (no observation), covers tenant 2
DO $$
DECLARE rid bigint;
BEGIN
  rid := open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                            '2026-08-28 10:00:00+00');
  UPDATE detector_runs SET status='OK', completed_at=now(),
    subjects_evaluated=ARRAY['tenant:2'] WHERE id=rid;
END $$;
SELECT CASE WHEN resolve_cleared_issues()=0
  THEN 'PASS 1 clean slot is not enough (required_clear_runs=2)'
  ELSE 'FAIL cleared too early' END;

-- 11:00 slot: clean as well
DO $$
DECLARE rid bigint;
BEGIN
  rid := open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                            '2026-08-28 11:00:00+00');
  UPDATE detector_runs SET status='OK', completed_at=now(),
    subjects_evaluated=ARRAY['tenant:2'] WHERE id=rid;
END $$;
SELECT CASE WHEN resolve_cleared_issues()=1 THEN 'PASS cleared on 2nd covering slot'
       ELSE 'FAIL not cleared' END;

\echo '=== T14 effective time = clearing evidence, not the resolver clock'
SELECT CASE WHEN resolution_effective_at='2026-08-28 11:00:00+00'
              AND resolved_at > '2026-08-28 11:00:00+00'
       THEN 'PASS effective=11:00 (evidence), resolved_at=now (admin)'
       ELSE 'FAIL eff='||resolution_effective_at||' res='||resolved_at END
FROM issues WHERE fingerprint='fp_tenant2_missing';

\echo '=== T15 occurrence closed at the effective time, not the resolver clock'
SELECT CASE WHEN occ.closed_at='2026-08-28 11:00:00+00'
       THEN 'PASS occurrence closed at evidence time' ELSE 'FAIL '||occ.closed_at END
FROM issue_occurrences occ JOIN issues i ON i.id=occ.issue_id
WHERE i.fingerprint='fp_tenant2_missing';

\echo '=== T16 a MISSING slot in the horizon blocks the clear'
-- new issue at 12:00, then 13:00 clean, 14:00 NEVER RUNS, 15:00 clean
\set ON_ERROR_STOP on
-- tenant:3 issue at 06:00. Slots 07:00 present, 08:00 DELIBERATELY MISSING,
-- 09:00 present. Two covering runs exist after last_seen, but the horizon
-- has a hole in it.
DO $$
DECLARE rid bigint; oid bigint;
BEGIN
  rid := open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                            '2026-08-28 06:00:00+00');
  INSERT INTO observations (detector_run_id, detector_key, detector_version,
    issue_key_version, product, observation_type, observed_at, subject_type,
    subject_id, fingerprint, magnitude)
  VALUES (rid,'x',1,1,'p','MISSING_ANALYTICS_ORDER','2026-08-28 06:00:00+00',
          'tenant','3','fp_t3', 7) RETURNING id INTO oid;
  INSERT INTO issues (fingerprint, product, issue_type, subject_type, subject_id,
    detector_key, issue_key_version, first_observation_id, latest_observation_id,
    first_seen, last_seen, current_magnitude)
  VALUES ('fp_t3','deadly_digital','MISSING_ANALYTICS_ORDER','tenant','3',
          'dd_analytics_reconciliation',1,oid,oid,
          '2026-08-28 06:00:00+00','2026-08-28 06:00:00+00',7);
  UPDATE detector_runs SET status='OK', completed_at=now(),
    subjects_evaluated=ARRAY['tenant:3'] WHERE id=rid;

  -- 07:00 clean and covering
  rid := open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                            '2026-08-28 07:00:00+00');
  UPDATE detector_runs SET status='OK', completed_at=now(),
    subjects_evaluated=ARRAY['tenant:3'] WHERE id=rid;
END $$;
-- 08:00 never runs. 09:00 already exists; extend it to cover tenant:3.
UPDATE detector_runs SET subjects_evaluated = ARRAY['tenant:2','tenant:3']
WHERE window_end = '2026-08-28 09:00:00+00';

\echo '=== T16 two covering runs exist, but a slot is MISSING between them'
SELECT CASE WHEN resolve_cleared_issues()=0
  THEN 'PASS missing 08:00 slot blocks the clear (absence is not evidence)'
  ELSE 'FAIL cleared across a hole' END;

\echo '=== T17 filling the hole allows the clear'
DO $$
DECLARE rid bigint;
BEGIN
  rid := open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                            '2026-08-28 08:00:00+00');
  UPDATE detector_runs SET status='OK', completed_at=now(),
    subjects_evaluated=ARRAY['tenant:3'] WHERE id=rid;
END $$;
SELECT CASE WHEN resolve_cleared_issues()=1
  THEN 'PASS clears once the horizon is complete' ELSE 'FAIL still blocked' END;

\echo '=== T18 the slot AT last_seen is not clearing evidence'
SELECT CASE WHEN resolution_effective_at='2026-08-28 08:00:00+00'
  THEN 'PASS effective=08:00; 06:00 (last_seen) excluded by (from,to]'
  ELSE 'FAIL '||resolution_effective_at END
FROM issues WHERE fingerprint='fp_t3';

\echo '=== T19 an ERRORED slot in the horizon also blocks'
DO $$
DECLARE rid bigint; oid bigint;
BEGIN
  rid := open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                            '2026-08-28 03:00:00+00');
  INSERT INTO observations (detector_run_id, detector_key, detector_version,
    issue_key_version, product, observation_type, observed_at, subject_type,
    subject_id, fingerprint, magnitude)
  VALUES (rid,'x',1,1,'p','MISSING_ANALYTICS_ORDER','2026-08-28 03:00:00+00',
          'tenant','4','fp_t4', 2) RETURNING id INTO oid;
  INSERT INTO issues (fingerprint, product, issue_type, subject_type, subject_id,
    detector_key, issue_key_version, first_observation_id, latest_observation_id,
    first_seen, last_seen, current_magnitude)
  VALUES ('fp_t4','deadly_digital','MISSING_ANALYTICS_ORDER','tenant','4',
          'dd_analytics_reconciliation',1,oid,oid,
          '2026-08-28 03:00:00+00','2026-08-28 03:00:00+00',2);
  UPDATE detector_runs SET status='OK', completed_at=now(),
    subjects_evaluated=ARRAY['tenant:4'] WHERE id=rid;

  rid := open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                            '2026-08-28 04:00:00+00');
  UPDATE detector_runs SET status='ERROR', completed_at=now(),
    error='simulated failure' WHERE id=rid;          -- errored slot

  rid := open_scheduled_run('dd_analytics_reconciliation',1,'deadly_digital',
                            '2026-08-28 05:00:00+00');
  UPDATE detector_runs SET status='OK', completed_at=now(),
    subjects_evaluated=ARRAY['tenant:4'] WHERE id=rid;
END $$;
SELECT CASE WHEN resolve_cleared_issues()=0
  THEN 'PASS errored slot blocks the clear' ELSE 'FAIL cleared over an error' END;
