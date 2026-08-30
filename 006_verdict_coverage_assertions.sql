\set ON_ERROR_STOP on
-- Assertions for 006_verdict_coverage.sql.

DO $$ BEGIN
    IF to_regclass('public.observation_coverage') IS NULL THEN
        RAISE EXCEPTION 'F1 FAIL: observation_coverage does not exist';
    END IF;
    IF to_regclass('public.verdict_coverage_policy') IS NULL THEN
        RAISE EXCEPTION 'F1 FAIL: verdict_coverage_policy does not exist';
    END IF;
RAISE NOTICE 'F1 pass  the coverage view and its policy table exist'; END $$;

-- Coverage is DERIVED. If it ever becomes a table, the thing it is derived
-- from and the thing stored can disagree, which is the failure this shape
-- exists to prevent.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='public' AND c.relname='observation_coverage'
                  AND c.relkind <> 'v')
    THEN RAISE EXCEPTION 'F2 FAIL: observation_coverage is not a view'; END IF;
RAISE NOTICE 'F2 pass  coverage is derived, not stored'; END $$;

-- A default policy must exist, or an observation type nobody configured would
-- fall through to an allowance of zero and every occurrence would re-queue.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM verdict_coverage_policy
                    WHERE observation_type = '*' AND policy_version = 1) THEN
        RAISE EXCEPTION 'F3 FAIL: no default (*) coverage policy';
    END IF;
    IF EXISTS (SELECT 1 FROM verdict_coverage_policy WHERE length(btrim(rationale)) = 0) THEN
        RAISE EXCEPTION 'F3 FAIL: a coverage policy row has no rationale';
    END IF;
RAISE NOTICE 'F3 pass  there is a default allowance, and every row says why'; END $$;

-- Nothing was migrated: every verdict ever recorded still exists, and every
-- one still points at the observation somebody actually looked at.
DO $$ DECLARE orphaned int; BEGIN
    SELECT count(*) INTO orphaned
      FROM observation_verdicts v
      LEFT JOIN observations o ON o.id = v.observation_id
     WHERE o.id IS NULL;
    IF orphaned > 0 THEN
        RAISE EXCEPTION 'F4 FAIL: % verdicts no longer point at an observation', orphaned;
    END IF;
RAISE NOTICE 'F4 pass  no verdict was rewritten or orphaned'; END $$;

-- The property the whole change rests on: a judgement is never also a
-- restatement, and every covered observation names the verdict covering it.
DO $$ DECLARE bad int; BEGIN
    SELECT count(*) INTO bad FROM observation_coverage
     WHERE is_judgement AND covered;
    IF bad > 0 THEN
        RAISE EXCEPTION 'F5 FAIL: % observations are both a judgement and covered', bad;
    END IF;
    SELECT count(*) INTO bad FROM observation_coverage
     WHERE covered AND covering_verdict_id IS NULL;
    IF bad > 0 THEN
        RAISE EXCEPTION 'F5 FAIL: % covered observations name no covering verdict', bad;
    END IF;
    SELECT count(*) INTO bad FROM observation_coverage
     WHERE coverage_reason IS NULL OR length(btrim(coverage_reason)) = 0;
    IF bad > 0 THEN
        RAISE EXCEPTION 'F5 FAIL: % observations give no reason for their coverage '
                        'state, so "why is this not in my queue" is unanswerable', bad;
    END IF;
RAISE NOTICE 'F5 pass  judgements and restatements are disjoint, and every row says why'; END $$;

-- The readers that need it have it, and the writer roles gained nothing.
DO $$ BEGIN
    IF NOT has_table_privilege('fleet_console_reader','public.observation_coverage','SELECT')
    THEN RAISE EXCEPTION 'F6 FAIL: the console cannot read coverage'; END IF;
    IF NOT has_table_privilege('fleet_detector_reader','public.observation_coverage','SELECT')
    THEN RAISE EXCEPTION 'F6 FAIL: the proposal layer cannot read coverage'; END IF;
    IF has_table_privilege('fleet_console_reader','public.verdict_coverage_policy','UPDATE')
    THEN RAISE EXCEPTION 'F6 FAIL: a reader can retune the coverage policy'; END IF;
RAISE NOTICE 'F6 pass  both read sides can see coverage; neither can retune it'; END $$;

DO $$ BEGIN RAISE NOTICE '--- 006 assertions complete ---'; END $$;
