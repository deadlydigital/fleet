\set ON_ERROR_STOP on
-- Assertions for 023_platform_floor.sql.
--
-- Same shape as 017's: every one of these builds a real task row and lets the
-- trigger answer. A floor asserted by SELECTing the table only proves the rows
-- are there; the property is that a task cannot be written, and that is what is
-- exercised.
--
-- 014's credit ceiling refuses any INSERT into tasks when the month has no
-- recorded pool reading, so a bare schema cannot exercise the floor at all. One
-- is recorded here if absent, because these assertions are about the FLOOR and
-- a refusal from a different ceiling would read as a floor failure.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM model_credit_pool
                    WHERE period_month = date_trunc('month', now())::date) THEN
        INSERT INTO model_credit_pool (period_month, pool_gbp, source, read_at)
        VALUES (date_trunc('month', now())::date, 500.00,
                '023 assertions: a fixture, not a reading', now());
        RAISE NOTICE 'P0 seed  recorded a fixture credit pool so tasks can be inserted';
    END IF;
END $$;

-- ---------------------------------------------------------------- P1
DO $$ DECLARE n int; BEGIN
    SELECT count(*) INTO n FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform' AND glob LIKE 'platform/%'
       AND glob NOT IN ('platform/__tests__/**', 'platform/vitest.config.ts',
                        'platform/playwright.config.ts');
    IF n <> 25 THEN
        RAISE EXCEPTION 'P1 FAIL: the platform surface is % of 25 globs on the floor', n;
    END IF;
RAISE NOTICE 'P1 pass  the platform surface is on the floor (25 globs)'; END $$;

-- ---------------------------------------------------------------- P2
-- The refusal this file exists for: the retired contract's writable set.
-- platform/app/** reaches auth, billing, campaigns, gdpr and the rest, and it
-- is refused even though every floor glob is protected -- because the two
-- halves of enforce_contract_floor() are separate and this is the second one.
DO $$ DECLARE rule text := ''; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    BEGIN
        INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                           max_cost_gbp, timeout_seconds)
        VALUES ('P2', 'x', 'deadly-digital-platform', 'main',
                jsonb_build_object(
                  'work_type','dd_frontend',
                  'writable_paths', jsonb_build_array(
                      'platform/app/**', 'platform/components/**', 'platform/lib/**'),
                  'protected_paths', floor_globs),
                1.00, 600);
    EXCEPTION WHEN raise_exception THEN
        -- WHICH rule caught it is recorded rather than glossed. On an INSERT
        -- the clash rule fires first and always will: the floored globs are in
        -- protected_paths, so a writable glob that reaches one overlaps one.
        -- The floor half is unreachable here by construction, which is why P6
        -- exists and why this notice does not claim to be the floor.
        IF SQLERRM LIKE '%writes where the floor forbids%' THEN rule := 'the floor';
        ELSIF SQLERRM LIKE '%self-contradictory%' THEN rule := 'the clash rule';
        END IF;
    END;
    IF rule = '' THEN
        RAISE EXCEPTION 'P2 FAIL: the retired wide frontend contract was accepted, '
                        'and it reaches auth, billing, email and erasure';
    END IF;
RAISE NOTICE 'P2 pass  platform/app,components,lib writable is refused by %', rule; END $$;

-- ---------------------------------------------------------------- P3
-- The one a path list would miss. middleware.ts is not under app/, components/
-- or lib/, so a contract can be scrupulous about those three trees and still
-- leave the file that decides which requests reach an authenticated route.
DO $$ DECLARE ok bool := false; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform' AND glob <> 'platform/middleware.ts';
    BEGIN
        INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                           max_cost_gbp, timeout_seconds)
        VALUES ('P3', 'x', 'deadly-digital-platform', 'main',
                jsonb_build_object(
                  'work_type','dd_frontend',
                  'writable_paths', jsonb_build_array(
                      'platform/app/(dashboard)/analytics/orders/**'),
                  'protected_paths', floor_globs),
                1.00, 600);
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%does not protect%platform/middleware.ts%' THEN ok := true; END IF;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'P3 FAIL: a contract that leaves platform/middleware.ts '
                        'unprotected was accepted';
    END IF;
RAISE NOTICE 'P3 pass  a contract that leaves middleware.ts unprotected is refused'; END $$;

-- ---------------------------------------------------------------- P4
-- 017's E3, at the frontend: the intervention surface sits INSIDE the analytics
-- tree, so the obvious analytics glob must be refused for reaching it. This is
-- the assertion that makes enumeration in dd-analytics-frontend.yaml a
-- consequence of the floor rather than a style choice somebody can revise.
DO $$ DECLARE rule text := ''; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    BEGIN
        INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                           max_cost_gbp, timeout_seconds)
        VALUES ('P4', 'x', 'deadly-digital-platform', 'main',
                jsonb_build_object(
                  'work_type','dd_frontend',
                  'writable_paths', jsonb_build_array(
                      'platform/app/api/analytics/**',
                      'platform/app/(dashboard)/analytics/**'),
                  'protected_paths', floor_globs),
                1.00, 600);
    EXCEPTION WHEN raise_exception THEN
        -- As in P2: on an INSERT the clash rule answers first. Either way the
        -- glob is refused, and refused BECAUSE of the intervention globs 023
        -- adds -- without them this contract inserts, which is what P5 shows.
        IF SQLERRM LIKE '%writes where the floor forbids%' THEN rule := 'the floor';
        ELSIF SQLERRM LIKE '%self-contradictory%' THEN rule := 'the clash rule';
        END IF;
    END;
    IF rule = '' THEN
        RAISE EXCEPTION 'P4 FAIL: a wide analytics glob was accepted, and it reaches '
                        'the intervention surface';
    END IF;
RAISE NOTICE 'P4 pass  a wide analytics glob is refused by % for reaching interventions', rule; END $$;

-- ---------------------------------------------------------------- P5
-- The work this posture exists to allow must still insert: the enumerated
-- analytics directories, a named component, and one creatable test file.
DO $$ DECLARE tid bigint; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                       max_cost_gbp, timeout_seconds)
    VALUES ('P5', 'x', 'deadly-digital-platform', 'main',
            jsonb_build_object(
              'work_type','dd_frontend',
              'writable_paths', jsonb_build_array(
                  'platform/app/api/analytics/dashboard/**',
                  'platform/app/api/analytics/orders/**',
                  'platform/app/api/analytics/revenue/**',
                  'platform/app/(dashboard)/analytics/page.tsx',
                  'platform/app/(dashboard)/analytics/orders/**',
                  'platform/components/analytics/DateRangePicker.tsx'),
              'protected_paths', floor_globs,
              'creatable_paths', jsonb_build_array(
                  'platform/__tests__/unit/analytics/test_fleet_*.tsx')),
            1.00, 600)
    RETURNING id INTO tid;
    DELETE FROM tasks WHERE id = tid;
RAISE NOTICE 'P5 pass  the enumerated analytics frontend contract still inserts'; END $$;

-- ---------------------------------------------------------------- P6
-- The half that must not be waived when the floor moves under work already in
-- flight. 017's E5 established that a task whose contract predates the floor
-- may still change status; E6 established that it may not if its writable paths
-- reach the floor. This is E6 for the globs 023 adds, and it is the concrete
-- danger: a task queued under the retired frontend contract before this ran.
DO $$ DECLARE tid bigint; ok bool := false; old_floor jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO old_floor FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform' AND glob NOT LIKE 'platform/app/%'
       AND glob NOT LIKE 'platform/lib/%' AND glob <> 'platform/middleware.ts';

    ALTER TABLE tasks DISABLE TRIGGER tasks_contract_floor;
    INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                       max_cost_gbp, timeout_seconds, status)
    VALUES ('P6', 'x', 'deadly-digital-platform', 'main',
            jsonb_build_object(
              'work_type','dd_frontend',
              'writable_paths', jsonb_build_array('platform/app/**'),
              'protected_paths', old_floor),
            1.00, 600, 'QUEUED')
    RETURNING id INTO tid;
    ALTER TABLE tasks ENABLE TRIGGER tasks_contract_floor;

    BEGIN
        UPDATE tasks SET status = 'RUNNING', claimed_at = now(), attempts = 1
         WHERE id = tid;
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%writes where the floor forbids%' THEN ok := true; END IF;
    END;
    ALTER TABLE tasks DISABLE TRIGGER tasks_contract_floor;
    DELETE FROM tasks WHERE id = tid;
    ALTER TABLE tasks ENABLE TRIGGER tasks_contract_floor;

    IF NOT ok THEN
        RAISE EXCEPTION 'P6 FAIL: a task queued under the retired frontend contract '
                        'was allowed to start after the floor moved';
    END IF;
RAISE NOTICE 'P6 pass  a stale wide frontend contract cannot start after the floor moved'; END $$;
