\set ON_ERROR_STOP on
-- Assertions for 003_tasks.sql, runnable against a deployed database.
-- The pytest suite proves the behaviour on a throwaway cluster; this proves
-- the deployed grants, triggers and data are the ones that behaviour was
-- proved on.
--
-- As in 001 and 002: `SELECT 1/0 WHERE <cond>` is not an assertion, because
-- the division is constant-folded at plan time. DO ... RAISE, always.

-- ---- the separation this track rests on -----------------------------------

DO $$ DECLARE bad text; BEGIN
    SELECT string_agg(r.rolname, ', ') INTO bad
    FROM pg_roles r
    WHERE r.rolname IN ('fleet_agent','fleet_verifier','fleet_deployer',
                        'fleet_console','fleet_evaluator')
      AND pg_has_role('fleet_task_runner', r.oid, 'MEMBER');
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'C1 FAIL: fleet_task_runner is a member of %', bad;
    END IF;
RAISE NOTICE 'C1 pass  the runner proposes nothing, certifies nothing, deploys nothing'; END $$;

DO $$ BEGIN IF EXISTS (
    SELECT 1 FROM task_transitions
    WHERE to_status IN ('MERGED','REJECTED','REWORK','ABANDONED')
      AND required_role <> 'fleet_console')
THEN RAISE EXCEPTION 'C2 FAIL: a reviewed state is reachable by something other than the console'; END IF;
IF EXISTS (SELECT 1 FROM task_transitions
           WHERE required_role = 'fleet_task_runner'
             AND to_status NOT IN ('RUNNING','READY_FOR_REVIEW','FAILED','QUEUED'))
THEN RAISE EXCEPTION 'C3 FAIL: the runner can reach a state it should not'; END IF;
RAISE NOTICE 'C2 pass  every reviewed state requires the console';
RAISE NOTICE 'C3 pass  the runner reaches only machine states'; END $$;

-- The whole track in one assertion: nothing here can deploy.
DO $$ BEGIN IF EXISTS (
    SELECT 1 FROM task_transitions WHERE to_status IN ('DEPLOYED','MERGING'))
THEN RAISE EXCEPTION 'C4 FAIL: the task state machine can reach a deploying state'; END IF;
IF has_table_privilege('fleet_task_runner', 'public.tasks'::regclass, 'INSERT')
THEN RAISE EXCEPTION 'C4 FAIL: the runner can write its own queue'; END IF;
IF has_table_privilege('fleet_task_runner', 'public.tasks'::regclass, 'DELETE')
THEN RAISE EXCEPTION 'C4 FAIL: the runner can delete tasks'; END IF;
RAISE NOTICE 'C4 pass  no deploy state, and the queue is written by a person'; END $$;

-- ---- the floor ------------------------------------------------------------

DO $$ DECLARE n int; BEGIN
    SELECT count(*) INTO n FROM protected_path_floor
    WHERE repo = 'deadly-digital-platform';
    IF n = 0 THEN
        RAISE EXCEPTION 'C5 FAIL: no protected path floor for deadly-digital-platform';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM protected_path_floor
                   WHERE repo='deadly-digital-platform' AND glob='api/tests/**') THEN
        RAISE EXCEPTION 'C5 FAIL: the test suite is not in the floor';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM protected_path_floor
                   WHERE repo='deadly-digital-platform' AND glob='api/alembic/**') THEN
        RAISE EXCEPTION 'C5 FAIL: migrations are not in the floor';
    END IF;
RAISE NOTICE 'C5 pass  tests and migrations are floor entries, not contract etiquette (% globs)', n; END $$;

DO $$ BEGIN IF EXISTS (
    SELECT 1 FROM protected_path_floor WHERE length(btrim(rationale)) = 0)
THEN RAISE EXCEPTION 'C6 FAIL: a floor entry has no rationale'; END IF;
RAISE NOTICE 'C6 pass  every protected path says why it is protected'; END $$;

DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
    WHERE c.relname='tasks' AND t.tgname='tasks_contract_floor'
      AND (t.tgtype & 4) <> 0 AND (t.tgtype & 16) <> 0)
THEN RAISE EXCEPTION 'C7 FAIL: the floor is not checked on both insert and update'; END IF;
RAISE NOTICE 'C7 pass  a contract that does not protect the floor cannot be stored'; END $$;

-- ---- the boundary cannot move while work is inside it ---------------------

DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
    WHERE c.relname='tasks' AND t.tgname IN ('tasks_immutable','tasks_transition'))
THEN RAISE EXCEPTION 'C8 FAIL: the task guards are missing'; END IF;
IF NOT (pg_get_functiondef('guard_task_immutability()'::regprocedure)
        LIKE '%acceptance_contract%')
THEN RAISE EXCEPTION 'C8 FAIL: immutability does not cover the contract'; END IF;
RAISE NOTICE 'C8 pass  the contract is frozen once the task leaves QUEUED'; END $$;

-- ---- one origin per run ---------------------------------------------------

DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'runs_one_origin_ck')
THEN RAISE EXCEPTION 'C9 FAIL: a run need not name an origin'; END IF;
IF EXISTS (SELECT 1 FROM runs WHERE (issue_id IS NULL) = (task_id IS NULL))
THEN RAISE EXCEPTION 'C9 FAIL: a run names both origins or neither'; END IF;
RAISE NOTICE 'C9 pass  every run names exactly one of an issue and a task'; END $$;

DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE indexname = 'runs_one_active_per_task')
THEN RAISE EXCEPTION 'C10 FAIL: two runs may be active on one task'; END IF;
RAISE NOTICE 'C10 pass  one active run per task'; END $$;

-- ---- the wall clock -------------------------------------------------------

DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid
    WHERE c.relname = 'tasks'
      AND pg_get_constraintdef(con.oid) LIKE '%timeout_seconds%')
THEN RAISE EXCEPTION 'C11 FAIL: timeout_seconds is unbounded'; END IF;
IF EXISTS (SELECT 1 FROM tasks WHERE timeout_seconds IS NULL)
THEN RAISE EXCEPTION 'C11 FAIL: a task exists with no wall-clock cap'; END IF;
RAISE NOTICE 'C11 pass  every task carries a bounded wall-clock cap'; END $$;

-- ---- budget ---------------------------------------------------------------

DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
    WHERE c.relname='runs' AND t.tgname='runs_task_budget')
THEN RAISE EXCEPTION 'C12 FAIL: a task run may carry any spend limit it likes'; END IF;
IF EXISTS (SELECT 1 FROM runs r JOIN tasks t ON t.id = r.task_id
           WHERE r.spend_limit_gbp > t.max_cost_gbp)
THEN RAISE EXCEPTION 'C12 FAIL: a run outspends its task'; END IF;
RAISE NOTICE 'C12 pass  a run cannot carry more budget than its task authorised'; END $$;

-- ---- claiming -------------------------------------------------------------

DO $$ BEGIN IF NOT (
    pg_get_functiondef('claim_task(text)'::regprocedure) LIKE '%SKIP LOCKED%')
THEN RAISE EXCEPTION 'C13 FAIL: claiming does not use SKIP LOCKED'; END IF;
IF (SELECT prosecdef FROM pg_proc WHERE oid = 'claim_task(text)'::regprocedure)
THEN RAISE EXCEPTION 'C13 FAIL: claim_task is SECURITY DEFINER and so bypasses the transition check'; END IF;
RAISE NOTICE 'C13 pass  claiming is SKIP LOCKED and runs as the caller'; END $$;

DO $$ BEGIN IF NOT (
    pg_get_functiondef('rework_task(bigint,text)'::regprocedure) LIKE '%spec_md ||%')
THEN RAISE EXCEPTION 'C14 FAIL: rework does not append its note to the spec'; END IF;
IF has_function_privilege('fleet_task_runner', 'rework_task(bigint,text)', 'EXECUTE')
THEN RAISE EXCEPTION 'C14 FAIL: the runner can rework its own task'; END IF;
RAISE NOTICE 'C14 pass  rework appends, and only the console may call it'; END $$;

DO $$ BEGIN RAISE NOTICE '--- 003 assertions complete ---'; END $$;
