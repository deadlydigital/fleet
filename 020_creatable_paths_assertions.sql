\set ON_ERROR_STOP on
-- Assertions for 020_creatable_paths.sql. Assumes 017's credit-pool seed.

DO $$ DECLARE ok bool := false; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    BEGIN
        INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                           max_cost_gbp, timeout_seconds)
        VALUES ('C1', 'x', 'deadly-digital-platform', 'main',
                jsonb_build_object(
                  'work_type','dd_api',
                  'writable_paths', jsonb_build_array('api/analytics/routes/orders.py'),
                  'protected_paths', floor_globs,
                  'creatable_paths', jsonb_build_array('**')),
                1.00, 600);
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%must narrow protected_paths%' THEN ok := true; END IF;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'C1 FAIL: creatable_paths ** was accepted';
    END IF;
RAISE NOTICE 'C1 pass  a creatable glob outside every protected one is refused'; END $$;

DO $$ DECLARE tid bigint; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                       max_cost_gbp, timeout_seconds)
    VALUES ('C2', 'x', 'deadly-digital-platform', 'main',
            jsonb_build_object(
              'work_type','dd_api',
              'writable_paths', jsonb_build_array('api/analytics/routes/orders.py'),
              'protected_paths', floor_globs,
              'creatable_paths', jsonb_build_array('api/tests/analytics/test_fleet_*.py')),
            1.00, 600)
    RETURNING id INTO tid;
    DELETE FROM tasks WHERE id = tid;
RAISE NOTICE 'C2 pass  a creatable glob inside api/tests/** is accepted'; END $$;

DO $$ DECLARE tid bigint; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                       max_cost_gbp, timeout_seconds)
    VALUES ('C3', 'x', 'deadly-digital-platform', 'main',
            jsonb_build_object(
              'work_type','dd_api',
              'writable_paths', jsonb_build_array('api/analytics/routes/orders.py'),
              'protected_paths', floor_globs),
            1.00, 600)
    RETURNING id INTO tid;
    DELETE FROM tasks WHERE id = tid;
RAISE NOTICE 'C3 pass  a contract with no creatable_paths at all still inserts'; END $$;
