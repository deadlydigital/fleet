\set ON_ERROR_STOP on
-- Assertions for 024_paired_paths.sql.
--
-- Each builds a real task row and lets the trigger answer, and each of the
-- refusals below is a shape that would otherwise produce a check that cannot
-- fail -- which is the failure mode this key was added with rather than a
-- tidiness rule.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM model_credit_pool
                    WHERE period_month = date_trunc('month', now())::date) THEN
        INSERT INTO model_credit_pool (period_month, pool_gbp, source, read_at)
        VALUES (date_trunc('month', now())::date, 500.00,
                '024 assertions: a fixture, not a reading', now());
        RAISE NOTICE 'Q0 seed  recorded a fixture credit pool so tasks can be inserted';
    END IF;
END $$;

-- A contract that is legal apart from whatever each case below breaks.
CREATE OR REPLACE FUNCTION pg_temp.q_contract(p_paired jsonb) RETURNS jsonb
LANGUAGE sql AS $$
    SELECT jsonb_build_object(
        'work_type','dd_frontend',
        'writable_paths', jsonb_build_array(
            'platform/app/api/analytics/dashboard/**',
            'platform/app/(dashboard)/analytics/page.tsx'),
        'protected_paths', (SELECT jsonb_agg(glob) FROM protected_path_floor
                             WHERE repo = 'deadly-digital-platform'))
      || CASE WHEN p_paired IS NULL THEN '{}'::jsonb
              ELSE jsonb_build_object('paired_paths', p_paired) END;
$$;

CREATE OR REPLACE FUNCTION pg_temp.q_insert(p_title text, p_paired jsonb)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE tid bigint; BEGIN
    INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                       max_cost_gbp, timeout_seconds)
    VALUES (p_title, 'x', 'deadly-digital-platform', 'main',
            pg_temp.q_contract(p_paired), 1.00, 600)
    RETURNING id INTO tid;
    DELETE FROM tasks WHERE id = tid;
END; $$;

-- ---------------------------------------------------------------- Q1
-- The pair task 28's spec asked for, and the reason the key exists.
DO $$ BEGIN
    PERFORM pg_temp.q_insert('Q1', jsonb_build_array(jsonb_build_object(
        'why', 'the proxy widening and the label must land together',
        'paths', jsonb_build_array(
            'platform/app/api/analytics/dashboard/route.ts',
            'platform/app/(dashboard)/analytics/page.tsx'))));
RAISE NOTICE 'Q1 pass  a well-formed pair inside writable_paths inserts'; END $$;

-- ---------------------------------------------------------------- Q2
-- A contract with no paired_paths at all is unaffected: this key adds a rule
-- for contracts that use it and changes nothing for the ones that do not.
DO $$ BEGIN
    PERFORM pg_temp.q_insert('Q2', NULL);
RAISE NOTICE 'Q2 pass  a contract with no paired_paths is unaffected'; END $$;

-- ---------------------------------------------------------------- Q3
-- The check-that-cannot-fail: a path the task may not write is never in the
-- diff, so "both or neither" is satisfied by writing neither, forever, green.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q3', jsonb_build_array(jsonb_build_object(
            'why', 'looks right, and the second path is not writable',
            'paths', jsonb_build_array(
                'platform/app/api/analytics/dashboard/route.ts',
                'platform/components/analytics/TimeSeriesChart.tsx'))));
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%not inside any writable path%' THEN ok := true; END IF;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q3 FAIL: a pair naming an unwritable path was accepted';
    END IF;
RAISE NOTICE 'Q3 pass  a pair reaching outside writable_paths is refused'; END $$;

-- ---------------------------------------------------------------- Q4
-- A group of one pairs nothing.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q4', jsonb_build_array(jsonb_build_object(
            'why', 'a group of one',
            'paths', jsonb_build_array(
                'platform/app/api/analytics/dashboard/route.ts'))));
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%fewer than two paths%' THEN ok := true; END IF;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q4 FAIL: a one-path group was accepted, and it pairs nothing';
    END IF;
RAISE NOTICE 'Q4 pass  a group of fewer than two paths is refused'; END $$;

-- ---------------------------------------------------------------- Q5
-- No `why`. The refusal is what the agent reads; without one it is told that
-- something is wrong and not what to do about it, and what it does then is
-- drop one of the two files.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q5', jsonb_build_array(jsonb_build_object(
            'paths', jsonb_build_array(
                'platform/app/api/analytics/dashboard/route.ts',
                'platform/app/(dashboard)/analytics/page.tsx'))));
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%has no why%' THEN ok := true; END IF;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q5 FAIL: a group with no why was accepted';
    END IF;
RAISE NOTICE 'Q5 pass  a group with no why is refused'; END $$;

-- ---------------------------------------------------------------- Q6
-- 020 must still hold: this migration replaced the whole function, so its
-- earlier rules are re-asserted here rather than assumed.
DO $$ DECLARE ok bool := false; tid bigint; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    BEGIN
        INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                           max_cost_gbp, timeout_seconds)
        VALUES ('Q6', 'x', 'deadly-digital-platform', 'main',
                jsonb_build_object(
                  'work_type','dd_frontend',
                  'writable_paths', jsonb_build_array(
                      'platform/app/(dashboard)/analytics/page.tsx'),
                  'protected_paths', floor_globs,
                  'creatable_paths', jsonb_build_array('platform/scripts/**')),
                1.00, 600)
        RETURNING id INTO tid;
        DELETE FROM tasks WHERE id = tid;
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%creatable_paths must narrow protected_paths%'
        THEN ok := true; END IF;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q6 FAIL: 020s creatable_paths rule did not survive 024';
    END IF;
RAISE NOTICE 'Q6 pass  020s rule survives the function replacement'; END $$;

-- ---------------------------------------------------------------- Q7
-- And 023's, for the same reason.
DO $$ DECLARE ok bool := false; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    BEGIN
        INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                           max_cost_gbp, timeout_seconds)
        VALUES ('Q7', 'x', 'deadly-digital-platform', 'main',
                jsonb_build_object(
                  'work_type','dd_frontend',
                  'writable_paths', jsonb_build_array('platform/lib/**'),
                  'protected_paths', floor_globs),
                1.00, 600);
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%writes where the floor forbids%'
        OR SQLERRM LIKE '%self-contradictory%' THEN ok := true; END IF;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q7 FAIL: 023s platform floor did not survive 024';
    END IF;
RAISE NOTICE 'Q7 pass  023s floor survives the function replacement'; END $$;
