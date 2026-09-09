\set ON_ERROR_STOP on
-- Assertions for 017_email_floor.sql.
--
-- Every one of these builds a real task row and lets the trigger answer. A
-- floor asserted by SELECTing the table only proves the rows are there; the
-- property is that a task cannot be written, and that is what is exercised.
--
-- 014's credit ceiling refuses any INSERT into tasks when the month has no
-- recorded pool reading, so a bare schema cannot exercise the floor at all.
-- One is recorded here if absent, because these assertions are about the
-- FLOOR and a refusal from a different ceiling would read as a floor failure.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM model_credit_pool
                    WHERE period_month = date_trunc('month', now())::date) THEN
        INSERT INTO model_credit_pool (period_month, pool_gbp, source, read_at)
        VALUES (date_trunc('month', now())::date, 500.00,
                '017 assertions: a fixture, not a reading', now());
        RAISE NOTICE 'E0 seed  recorded a fixture credit pool so tasks can be inserted';
    END IF;
END $$;

-- ---------------------------------------------------------------- E1
DO $$ DECLARE n int; BEGIN
    SELECT count(*) INTO n FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform'
       AND glob IN ('api/app.py', 'api/services/email_sender.py', 'api/worker.py',
                    'api/analytics/routes/interventions.py',
                    'api/analytics/services/trigger_router.py');
    IF n <> 5 THEN
        RAISE EXCEPTION 'E1 FAIL: the email surface is % of 5 globs on the floor', n;
    END IF;
RAISE NOTICE 'E1 pass  the email surface is on the floor (5 globs)'; END $$;

-- ---------------------------------------------------------------- E2
-- The refusal that is the point of the file: a contract that does not protect
-- api/app.py cannot create a task at all.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                           max_cost_gbp, timeout_seconds)
        VALUES ('E2', 'x', 'deadly-digital-platform', 'main',
                jsonb_build_object(
                  'work_type','dd_api',
                  'writable_paths', jsonb_build_array('api/analytics/routes/revenue.py'),
                  'protected_paths', jsonb_build_array('api/tests/**')),
                1.00, 600);
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%does not protect%api/app.py%' THEN ok := true; END IF;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'E2 FAIL: a contract that does not protect api/app.py was accepted';
    END IF;
RAISE NOTICE 'E2 pass  a contract that leaves api/app.py unprotected is refused'; END $$;

-- ---------------------------------------------------------------- E3
-- The one a path list would miss: trigger_router.py sits inside the analytics
-- tree, so a contract with the ordinary analytics globs writable must be
-- refused for reaching it.
DO $$ DECLARE ok bool := false; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    BEGIN
        INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                           max_cost_gbp, timeout_seconds)
        VALUES ('E3', 'x', 'deadly-digital-platform', 'main',
                jsonb_build_object(
                  'work_type','dd_api',
                  'writable_paths', jsonb_build_array('api/analytics/services/**'),
                  'protected_paths', floor_globs),
                1.00, 600);
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%trigger_router%' OR SQLERRM LIKE '%self-contradictory%'
        THEN ok := true; END IF;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'E3 FAIL: a contract writing api/analytics/services/** was '
                        'accepted, which reaches trigger_router.py';
    END IF;
RAISE NOTICE 'E3 pass  a wide analytics glob is refused for reaching trigger_router.py'; END $$;

-- ---------------------------------------------------------------- E4
-- The analytics work this posture exists to allow must still insert.
DO $$ DECLARE tid bigint; floor_globs jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO floor_globs FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform';
    INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                       max_cost_gbp, timeout_seconds)
    VALUES ('E4', 'x', 'deadly-digital-platform', 'main',
            jsonb_build_object(
              'work_type','dd_api',
              'writable_paths', jsonb_build_array(
                  'api/analytics/services/analytics_engine.py',
                  'api/analytics/routes/dashboard.py'),
              'protected_paths', floor_globs),
            1.00, 600)
    RETURNING id INTO tid;
    DELETE FROM tasks WHERE id = tid;
RAISE NOTICE 'E4 pass  an ordinary analytics task still inserts'; END $$;

-- ---------------------------------------------------------------- E5
-- The reason PART 1 exists: a task whose contract predates the floor must
-- still be able to change status, because its contract is frozen and its
-- writable paths do not reach the floor. Task 28 was in exactly this state.
DO $$ DECLARE tid bigint; old_floor jsonb; BEGIN
    -- A contract carrying only the ORIGINAL eight floor globs.
    SELECT jsonb_agg(glob) INTO old_floor FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform'
       AND glob NOT IN ('api/app.py','api/services/email_sender.py','api/worker.py',
                        'api/analytics/routes/interventions.py',
                        'api/analytics/services/trigger_router.py');

    -- Insert it past the floor by disabling the trigger, which is what
    -- "written before the floor moved" means.
    ALTER TABLE tasks DISABLE TRIGGER tasks_contract_floor;
    INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                       max_cost_gbp, timeout_seconds, status)
    VALUES ('E5', 'x', 'deadly-digital-platform', 'main',
            jsonb_build_object(
              'work_type','dd_api',
              'writable_paths', jsonb_build_array('api/analytics/routes/dashboard.py'),
              'protected_paths', old_floor),
            1.00, 600, 'QUEUED')
    RETURNING id INTO tid;
    ALTER TABLE tasks ENABLE TRIGGER tasks_contract_floor;

    -- The status transition must succeed: the contract is stale, the writable
    -- paths are safe, and the work is in flight.
    UPDATE tasks SET status = 'RUNNING', claimed_at = now(), attempts = 1
     WHERE id = tid;
    DELETE FROM tasks WHERE id = tid;
RAISE NOTICE 'E5 pass  an in-flight task with a pre-floor contract can still transition'; END $$;

-- ---------------------------------------------------------------- E6
-- And the half of E5 that must NOT be waived: a stale contract whose writable
-- paths DO reach the floor is refused even on a status change.
DO $$ DECLARE tid bigint; ok bool := false; old_floor jsonb; BEGIN
    SELECT jsonb_agg(glob) INTO old_floor FROM protected_path_floor
     WHERE repo = 'deadly-digital-platform'
       AND glob NOT IN ('api/app.py','api/services/email_sender.py','api/worker.py',
                        'api/analytics/routes/interventions.py',
                        'api/analytics/services/trigger_router.py');

    ALTER TABLE tasks DISABLE TRIGGER tasks_contract_floor;
    INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,
                       max_cost_gbp, timeout_seconds, status)
    VALUES ('E6', 'x', 'deadly-digital-platform', 'main',
            jsonb_build_object(
              'work_type','dd_api',
              'writable_paths', jsonb_build_array('api/app.py'),
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
        RAISE EXCEPTION 'E6 FAIL: a task with api/app.py writable was allowed to '
                        'transition because its contract predated the floor';
    END IF;
RAISE NOTICE 'E6 pass  a stale contract that writes a floored path is still refused'; END $$;
