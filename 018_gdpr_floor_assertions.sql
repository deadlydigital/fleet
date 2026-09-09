\set ON_ERROR_STOP on
-- Assertions for 018_gdpr_floor.sql.
--
-- 017's assertions seed a credit pool if the month has none; this file assumes
-- 017's has run, because they are applied in order. If it is run alone against
-- a bare schema, G2 will fail on the credit ceiling rather than on the floor.

-- ---------------------------------------------------------------- G1
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM protected_path_floor
                    WHERE repo = 'deadly-digital-platform'
                      AND glob = 'api/analytics/services/gdpr.py') THEN
        RAISE EXCEPTION 'G1 FAIL: erasure is not on the floor';
    END IF;
RAISE NOTICE 'G1 pass  api/analytics/services/gdpr.py is on the floor'; END $$;

-- ---------------------------------------------------------------- G2
-- The refusal, exercised: a contract making erasure writable cannot create a
-- task, even when it lists every floor glob in protected_paths.
DO $$ DECLARE ok bool := false; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    BEGIN
        INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                           max_cost_gbp, timeout_seconds)
        VALUES ('G2', 'x', 'deadly-digital-platform', 'main',
                jsonb_build_object(
                  'work_type','dd_api',
                  'writable_paths', jsonb_build_array('api/analytics/services/gdpr.py'),
                  'protected_paths', floor_globs),
                1.00, 600);
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%gdpr%' THEN ok := true; END IF;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'G2 FAIL: a task writing the erasure module was accepted';
    END IF;
RAISE NOTICE 'G2 pass  a task that would write erasure code is refused'; END $$;

-- ---------------------------------------------------------------- G3
-- And the neighbours are still reachable: flooring erasure must not quietly
-- take the rest of the analytics services with it.
DO $$ DECLARE tid bigint; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                       max_cost_gbp, timeout_seconds)
    VALUES ('G3', 'x', 'deadly-digital-platform', 'main',
            jsonb_build_object(
              'work_type','dd_api',
              'writable_paths', jsonb_build_array(
                  'api/analytics/services/analytics_engine.py',
                  'api/analytics/services/order_query.py'),
              'protected_paths', floor_globs),
            1.00, 600)
    RETURNING id INTO tid;
    DELETE FROM tasks WHERE id = tid;
RAISE NOTICE 'G3 pass  the rest of api/analytics/services is still writable'; END $$;
