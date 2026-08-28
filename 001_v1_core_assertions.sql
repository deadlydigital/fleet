\set ON_ERROR_STOP on
-- NOTE: `SELECT 1/0 WHERE <cond>` does NOT work as an assertion in Postgres.
-- The division is constant-folded at plan time and raises regardless of the
-- predicate, so such an assertion always fails. Use DO ... RAISE instead.

DO $$ BEGIN IF EXISTS (
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname='public'
      AND ((p.proname='coverage_horizon_valid'  AND p.pronargs <> 6)
        OR (p.proname='subject_horizon_covered' AND p.pronargs <> 8)))
THEN RAISE EXCEPTION 'A1 FAIL: legacy overload present'; END IF;
RAISE NOTICE 'A1 pass  no legacy overloads'; END $$;

DO $$ BEGIN IF EXISTS (
    SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname='public'
      AND p.proname IN ('coverage_horizon_valid','subject_horizon_covered')
      AND p.pronargdefaults <> 0)
THEN RAISE EXCEPTION 'A2 FAIL: default on a horizon predicate'; END IF;
RAISE NOTICE 'A2 pass  no defaults on horizon predicates'; END $$;

DO $$ BEGIN IF NOT (
    SELECT bool_and(d LIKE '%coverage_horizon_valid%'
                AND d LIKE '%subject_horizon_covered%'
                AND d LIKE '%subject_identity_stable%')
    FROM (SELECT pg_get_functiondef(p::regprocedure) AS d
          FROM unnest(ARRAY['resolve_cleared_issues()',
                            'execute_due_outcome_checks()']) p) x)
THEN RAISE EXCEPTION 'A3 FAIL: a verdict function is missing a predicate'; END IF;
RAISE NOTICE 'A3 pass  all three predicates in both verdict functions'; END $$;

DO $$ BEGIN IF NOT (
    pg_get_functiondef('resolve_cleared_issues()'::regprocedure) LIKE '%judge_at%'
AND pg_get_functiondef('execute_due_outcome_checks()'::regprocedure) LIKE '%judge_at%')
THEN RAISE EXCEPTION 'A4 FAIL: judge_at not captured'; END IF;
RAISE NOTICE 'A4 pass  judge_at captured in both'; END $$;

DO $$ BEGIN IF EXISTS (
    SELECT 1 FROM unnest(ARRAY['resolve_cleared_issues()',
                               'execute_due_outcome_checks()']) p,
    LATERAL regexp_matches(pg_get_functiondef(p::regprocedure),
        '(coverage_horizon_valid|subject_horizon_covered)\s*\(([^;]*)\)', 'g') AS m
    WHERE m[2] !~ 'judge_at')
THEN RAISE EXCEPTION 'A5 FAIL: a maturity predicate call omits judge_at'; END IF;
RAISE NOTICE 'A5 pass  judge_at passed to every maturity-sensitive call'; END $$;

DO $$ BEGIN IF EXISTS (
    SELECT 1 FROM unnest(ARRAY['resolve_cleared_issues()',
                               'execute_due_outcome_checks()']) p
    WHERE pg_get_functiondef(p::regprocedure) ~
          '(coverage_horizon_valid|subject_horizon_covered)\s*\([^;]*now\(\)')
THEN RAISE EXCEPTION 'A5b FAIL: now() passed into a maturity predicate'; END IF;
RAISE NOTICE 'A5b pass  no now() inside those calls'; END $$;

DO $$ BEGIN
IF to_regprocedure('covering_runs_since(text,integer,text,text,text,timestamptz)')
   IS NOT NULL
THEN RAISE EXCEPTION 'A6 FAIL: covering_runs_since still exists'; END IF;
IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname='public' AND p.proname='resolve_issue_manually')
THEN RAISE EXCEPTION 'A6 FAIL: resolve_issue_manually still exists'; END IF;
RAISE NOTICE 'A6 pass  removed APIs absent'; END $$;

DO $$
DECLARE bad text;
BEGIN
  SELECT string_agg(r, ', ') INTO bad FROM unnest(ARRAY[
      'fleet_agent','fleet_detector','fleet_verifier','fleet_deployer',
      'fleet_evaluator','fleet_console','fleet_model_gateway']) r
  WHERE pg_has_role(r, 'fleet_owner', 'MEMBER');
  IF bad IS NOT NULL THEN
    RAISE EXCEPTION 'A7 FAIL: runtime principals reach fleet_owner: %', bad;
  END IF;
  RAISE NOTICE 'A7 pass  no runtime principal reaches fleet_owner';
END $$;

DO $$
DECLARE bad text;
BEGIN
  SELECT string_agg(p.proname, ', ') INTO bad
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public'
    AND 'timestamptz'::regtype = ANY (p.proargtypes)
    AND p.proname NOT IN ('coverage_horizon_valid','subject_horizon_covered',
                          'subject_identity_stable','expected_slot_range',
                          'open_scheduled_run','purge_observations',
                          'bump_issue_key_version');
  IF bad IS NOT NULL THEN
    RAISE EXCEPTION 'A8 FAIL: workflow function accepts a timestamp: %', bad;
  END IF;
  RAISE NOTICE 'A8 pass  no workflow function accepts an effective time';
END $$;

\echo 'ALL ASSERTIONS PASSED'
