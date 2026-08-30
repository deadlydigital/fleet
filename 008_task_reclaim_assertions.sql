\set ON_ERROR_STOP on
-- Assertions for 008_task_reclaim.sql.

DO $$ BEGIN
    IF to_regprocedure('reclaim_stale_task(bigint,interval)') IS NULL
       OR to_regprocedure('stale_tasks(interval)') IS NULL THEN
        RAISE EXCEPTION 'H1 FAIL: the reclaim path is missing';
    END IF;
RAISE NOTICE 'H1 pass  a stuck task can be reclaimed'; END $$;

-- SECURITY INVOKER, as claim_task is. A definer function would satisfy
-- enforce_task_transition()'s role check whoever called it.
DO $$ BEGIN
    IF (SELECT prosecdef FROM pg_proc
         WHERE oid = 'reclaim_stale_task(bigint,interval)'::regprocedure) THEN
        RAISE EXCEPTION 'H2 FAIL: reclaim_stale_task is SECURITY DEFINER and so '
                        'bypasses the transition check it should be subject to';
    END IF;
RAISE NOTICE 'H2 pass  reclaiming runs as the caller, so the state machine applies'; END $$;

-- Both halves carry the age floor. The acting one alone is not enough: the
-- caller removes a worktree before asking the database, so a listing function
-- that could name a live tick would get its worktree removed first.
DO $$ BEGIN
    IF pg_get_functiondef('reclaim_stale_task(bigint,interval)'::regprocedure)
       NOT LIKE '%5 minutes%' THEN
        RAISE EXCEPTION 'H3 FAIL: reclaim_stale_task has no minimum grace';
    END IF;
    IF pg_get_functiondef('stale_tasks(interval)'::regprocedure)
       NOT LIKE '%5 minutes%' THEN
        RAISE EXCEPTION 'H3 FAIL: stale_tasks can name a live tick, whose worktree '
                        'would then be removed before anything refused';
    END IF;
RAISE NOTICE 'H3 pass  neither half can act on, or name, a live tick'; END $$;

-- It must not touch attempts: claim_task already counted the try.
DO $$ BEGIN
    IF pg_get_functiondef('reclaim_stale_task(bigint,interval)'::regprocedure)
       LIKE '%attempts = attempts + 1%'
    OR pg_get_functiondef('reclaim_stale_task(bigint,interval)'::regprocedure)
       LIKE '%attempts + 1%' THEN
        RAISE EXCEPTION 'H4 FAIL: reclaim increments attempts, which claim_task '
                        'already did -- one try would be charged twice and a task '
                        'retired at half its allowance';
    END IF;
RAISE NOTICE 'H4 pass  reclaiming does not charge the attempt a second time'; END $$;

-- No task may be left RUNNING with a closed run, or QUEUED with an open one.
DO $$ DECLARE bad int; BEGIN
    SELECT count(*) INTO bad FROM tasks t
     WHERE t.status = 'QUEUED'
       AND EXISTS (SELECT 1 FROM runs r WHERE r.task_id = t.id
                     AND r.status IN ('ACTIVE','AWAITING_HUMAN'));
    IF bad > 0 THEN
        RAISE EXCEPTION 'H5 FAIL: % queued tasks still hold an open run, so the '
                        'next tick will die on runs_one_active_per_task', bad;
    END IF;
RAISE NOTICE 'H5 pass  no queued task is holding the one-active-per-task slot'; END $$;

DO $$ BEGIN
    IF has_function_privilege('fleet_console_reader',
                              'reclaim_stale_task(bigint,interval)', 'EXECUTE') THEN
        RAISE EXCEPTION 'H6 FAIL: the read-only console role can reclaim';
    END IF;
    IF NOT has_function_privilege('fleet_task_runner',
                                  'reclaim_stale_task(bigint,interval)', 'EXECUTE') THEN
        RAISE EXCEPTION 'H6 FAIL: the runner cannot reclaim';
    END IF;
RAISE NOTICE 'H6 pass  the runner reclaims; the read-only console cannot'; END $$;

DO $$ BEGIN RAISE NOTICE '--- 008 assertions complete ---'; END $$;
