\set ON_ERROR_STOP on
-- Assertions for 010_decision_log.sql, run against the deployed database.
-- These check what the design REFUSES, because that is the half that cannot
-- be established by using the feature and finding it works.

-- ---- J1: the log exists, and did not land on 002's table -------------------
DO $$ BEGIN
    IF to_regclass('public.decision_log') IS NULL THEN
        RAISE EXCEPTION 'J1 FAIL: there is no decision log, so nothing links a '
                        'recommendation to a choice to a result';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'decisions' AND column_name = 'reason_code') THEN
        RAISE EXCEPTION 'J1 FAIL: 002''s decisions table has been altered; the '
                        'two logs answer different questions and must stay apart';
    END IF;
RAISE NOTICE 'J1 pass  the log exists beside 002''s decisions, not instead of it'; END $$;

-- ---- J2: reason is NOT NULL on every row, rejections included --------------
--
-- The single most important constraint in the file. A rejection with no reason
-- is the one record this table exists to keep.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name = 'decision_log' AND column_name = 'reason'
                  AND is_nullable = 'YES') THEN
        RAISE EXCEPTION 'J2 FAIL: reason is nullable, so a rejection can be '
                        'recorded with no reason -- which is the record this '
                        'table exists to keep';
    END IF;
RAISE NOTICE 'J2 pass  every decision carries a reason'; END $$;

-- ---- J3: there is nowhere to type an outcome ------------------------------
DO $$ DECLARE bad text; BEGIN
    SELECT string_agg(column_name, ', ') INTO bad
      FROM information_schema.columns
     WHERE table_name = 'decision_log'
       AND column_name IN ('outcome','task_status','task_outcome','issue_outcome',
                           'issue_status','total_cost_gbp','cost_gbp','runs_total',
                           'attempts_to_green','worked','executed','succeeded',
                           'resolved','outcome_note');
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'J3 FAIL: decision_log carries outcome columns (%). An '
                        'outcome someone can type is an outcome someone will '
                        'type from memory', bad;
    END IF;
RAISE NOTICE 'J3 pass  outcomes have no column to be hand-typed into'; END $$;

-- ---- J4: and they are derived instead --------------------------------------
DO $$ DECLARE missing text; BEGIN
    IF to_regclass('public.decision_outcomes') IS NULL THEN
        RAISE EXCEPTION 'J4 FAIL: outcomes are neither stored nor derived';
    END IF;
    SELECT string_agg(c, ', ') INTO missing FROM unnest(ARRAY[
        'task_status','task_outcome','total_cost_gbp','attempts_to_green',
        'issue_status','issue_outcome','reopened_since_decision']) c
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'decision_outcomes' AND column_name = c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'J4 FAIL: decision_outcomes does not derive %', missing;
    END IF;
RAISE NOTICE 'J4 pass  every outcome field is recomputed from current state'; END $$;

-- ---- J5: the view reads as the caller, not as its owner --------------------
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_class
                    WHERE relname = 'decision_outcomes'
                      AND reloptions @> ARRAY['security_invoker=true']) THEN
        RAISE EXCEPTION 'J5 FAIL: decision_outcomes is not security_invoker, so '
                        'anyone granted it reads tasks, runs and issues through '
                        'the view owner rather than their own grants';
    END IF;
RAISE NOTICE 'J5 pass  the view carries no privileges of its own'; END $$;

-- ---- J6: only the console may record one -----------------------------------
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                    WHERE tgname = 'decision_log_authority'
                      AND tgrelid = 'public.decision_log'::regclass) THEN
        RAISE EXCEPTION 'J6 FAIL: nothing restricts who may record a decision';
    END IF;
    IF has_table_privilege('fleet_proposer','public.decision_log','INSERT')
    OR has_table_privilege('fleet_task_runner','public.decision_log','INSERT') THEN
        RAISE EXCEPTION 'J6 FAIL: a layer that is decided ABOUT can record the '
                        'decision on itself';
    END IF;
    IF NOT has_table_privilege('fleet_console','public.decision_log','INSERT') THEN
        RAISE EXCEPTION 'J6 FAIL: the console cannot record a decision';
    END IF;
RAISE NOTICE 'J6 pass  the console decides; the proposer and runner cannot'; END $$;

-- ---- J7: a settled decision cannot be revised or deleted -------------------
DO $$ BEGIN
    IF has_table_privilege('fleet_console','public.decision_log','UPDATE')
    OR has_table_privilege('fleet_console','public.decision_log','DELETE') THEN
        RAISE EXCEPTION 'J7 FAIL: the console can rewrite what it decided';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                    WHERE tgname = 'decision_log_immutable'
                      AND tgrelid = 'public.decision_log'::regclass) THEN
        RAISE EXCEPTION 'J7 FAIL: nothing freezes a recorded decision';
    END IF;
RAISE NOTICE 'J7 pass  a decision is a record of a moment and stays one'; END $$;

-- ---- J8: the proposal cycle still cannot see how it is graded --------------
--
-- 004 gave the console its own read identity precisely so that widening the
-- reader would not hand the proposer sight of `decisions`. The same applies
-- here and is easier to get wrong, because this table looks like general
-- operational state rather than a grade.
DO $$ BEGIN
    IF has_table_privilege('fleet_detector_reader','public.decision_log','SELECT') THEN
        RAISE EXCEPTION 'J8 FAIL: the proposal layer can read the decisions '
                        'made about its own output';
    END IF;
    IF NOT has_table_privilege('fleet_console_reader','public.decision_log','SELECT') THEN
        RAISE EXCEPTION 'J8 FAIL: the console page cannot render the log';
    END IF;
    IF has_table_privilege('fleet_console_reader','public.decision_log','INSERT') THEN
        RAISE EXCEPTION 'J8 FAIL: the read-only console can record a decision';
    END IF;
RAISE NOTICE 'J8 pass  the console reads it; the layer it grades does not'; END $$;

-- ---- J9: backfilled rows are distinguishable, and own the sentinels --------
DO $$ DECLARE bad int; BEGIN
    SELECT count(*) INTO bad FROM decision_log
     WHERE origin = 'BACKFILLED' AND confidence <> 'INFERRED';
    IF bad > 0 THEN
        RAISE EXCEPTION 'J9 FAIL: % backfilled rows claim stated confidence', bad;
    END IF;
    SELECT count(*) INTO bad FROM decision_log
     WHERE origin = 'RECORDED' AND (reason = 'UNRECORDED' OR decided_by = 'UNRECORDED');
    IF bad > 0 THEN
        RAISE EXCEPTION 'J9 FAIL: % live rows use the backfill sentinel, which '
                        'is how a NOT NULL reason becomes decorative', bad;
    END IF;
RAISE NOTICE 'J9 pass  reconstructed rows say so and cannot pass for recorded'; END $$;

-- ---- J10: one log, not one per product -------------------------------------
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
                  AND c.relname LIKE 'decision\_log\_%') THEN
        RAISE EXCEPTION 'J10 FAIL: the log has been split by product, which '
                        'makes the cross-product question unanswerable';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'decision_log' AND column_name = 'product') THEN
        RAISE EXCEPTION 'J10 FAIL: decisions do not name a product';
    END IF;
RAISE NOTICE 'J10 pass  product is a column and there is one log'; END $$;

DO $$ BEGIN RAISE NOTICE '--- 010 assertions complete ---'; END $$;
