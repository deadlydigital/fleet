\set ON_ERROR_STOP on
-- Assertions for 009_task_reclaims.sql.

DO $$ BEGIN
    IF to_regclass('public.task_reclaims') IS NULL THEN
        RAISE EXCEPTION 'I1 FAIL: reclaims are not recorded, so an automatic '
                        'overnight retry leaves nothing but an attempt count';
    END IF;
RAISE NOTICE 'I1 pass  a reclaim is recorded'; END $$;

-- Written by the function, in the same transaction. A record the caller is
-- trusted to write is missing exactly when the caller crashed.
DO $$ BEGIN
    IF pg_get_functiondef('reclaim_stale_task(bigint,interval)'::regprocedure)
       NOT LIKE '%INSERT INTO public.task_reclaims%' THEN
        RAISE EXCEPTION 'I2 FAIL: reclaim_stale_task does not write the record '
                        'itself, so a reclaim can happen without one';
    END IF;
RAISE NOTICE 'I2 pass  the function records what it did, not the caller'; END $$;

-- The evidence the requeue destroys, kept.
DO $$ DECLARE missing text; BEGIN
    SELECT string_agg(c, ', ') INTO missing FROM unnest(ARRAY[
        'dead_claimed_at','stale_for','grace','timeout_seconds','attempts',
        'max_attempts','outcome','open_runs_closed']) c
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name='task_reclaims' AND column_name=c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'I3 FAIL: task_reclaims does not keep %', missing;
    END IF;
RAISE NOTICE 'I3 pass  what the requeue erases is copied before it goes'; END $$;

-- The runner may attach what it cleaned up and revise nothing else.
DO $$ BEGIN
    IF has_table_privilege('fleet_task_runner','public.task_reclaims','DELETE') THEN
        RAISE EXCEPTION 'I4 FAIL: the runner can delete a reclaim record';
    END IF;
    IF has_column_privilege('fleet_task_runner','public.task_reclaims',
                            'outcome','UPDATE') THEN
        RAISE EXCEPTION 'I4 FAIL: the runner can rewrite a reclaim outcome';
    END IF;
    IF has_column_privilege('fleet_task_runner','public.task_reclaims',
                            'stale_for','UPDATE') THEN
        RAISE EXCEPTION 'I4 FAIL: the runner can rewrite how stale a tick was';
    END IF;
    IF NOT has_column_privilege('fleet_task_runner','public.task_reclaims',
                                'worktree_removed','UPDATE') THEN
        RAISE EXCEPTION 'I4 FAIL: the runner cannot record what it cleaned up';
    END IF;
RAISE NOTICE 'I4 pass  the runner notes its cleanup and revises nothing else'; END $$;

DO $$ BEGIN
    IF NOT has_table_privilege('fleet_console_reader','public.task_reclaims','SELECT')
    THEN RAISE EXCEPTION 'I5 FAIL: the console cannot show reclaims'; END IF;
    IF has_table_privilege('fleet_console_reader','public.task_reclaims','INSERT')
    THEN RAISE EXCEPTION 'I5 FAIL: the read-only console can write a reclaim'; END IF;
RAISE NOTICE 'I5 pass  the console shows reclaims and cannot invent one'; END $$;

-- Every recorded reclaim must name a task that exists and an outcome that is
-- one of the two the function can produce.
DO $$ DECLARE bad int; BEGIN
    SELECT count(*) INTO bad FROM task_reclaims r
     LEFT JOIN tasks t ON t.id = r.task_id WHERE t.id IS NULL;
    IF bad > 0 THEN
        RAISE EXCEPTION 'I6 FAIL: % reclaims name a task that does not exist', bad;
    END IF;
RAISE NOTICE 'I6 pass  every reclaim names a real task'; END $$;

DO $$ BEGIN RAISE NOTICE '--- 009 assertions complete ---'; END $$;
