\set ON_ERROR_STOP on
-- Assertions for 002_proposals.sql, runnable against a deployed database.
-- The pytest suite proves the behaviour on a throwaway cluster; this proves
-- the deployed grants and triggers are the ones the behaviour was proved on.
--
-- As in 001: `SELECT 1/0 WHERE <cond>` is not an assertion, because the
-- division is constant-folded at plan time. DO ... RAISE, always.

DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgname = 'proposals_require_evidence'
      AND tgconstraint <> 0 AND tgdeferrable AND tginitdeferred)
THEN RAISE EXCEPTION 'B1 FAIL: the evidence check is not a deferred constraint trigger'; END IF;
RAISE NOTICE 'B1 pass  evidence is checked at commit, not at insert'; END $$;

DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgname = 'proposal_evidence_last_row'
      AND tgconstraint <> 0 AND tgdeferrable)
THEN RAISE EXCEPTION 'B2 FAIL: deleting the last evidence row is unchecked'; END IF;
RAISE NOTICE 'B2 pass  retention cannot strand a proposal without evidence'; END $$;

DO $$ BEGIN IF NOT (
    pg_get_functiondef('enforce_decision_authority()'::regprocedure)
        LIKE '%fleet_console%')
THEN RAISE EXCEPTION 'B3 FAIL: decision authority does not name fleet_console'; END IF;
IF pg_get_functiondef('enforce_decision_authority()'::regprocedure)
       LIKE '%fleet_proposer%'
THEN RAISE EXCEPTION 'B3 FAIL: the proposer appears in the decision authority list'; END IF;
RAISE NOTICE 'B3 pass  only fleet_console may decide, and the proposer is not in the list'; END $$;

DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
    WHERE c.relname = 'decisions' AND t.tgname = 'decisions_authority'
      AND (t.tgtype & 4) <> 0 AND (t.tgtype & 16) <> 0)
THEN RAISE EXCEPTION 'B4 FAIL: decision authority does not cover both INSERT and UPDATE'; END IF;
RAISE NOTICE 'B4 pass  authority is checked on insert and on update'; END $$;

-- The proposer writes and does not read. The single permitted read is
-- proposals.id, which INSERT ... RETURNING id requires.
DO $$ DECLARE leak text; BEGIN
    SELECT string_agg(c.relname, ', ') INTO leak
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
      AND has_table_privilege('fleet_proposer', c.oid, 'SELECT');
    IF leak IS NOT NULL THEN
        RAISE EXCEPTION 'B5 FAIL: fleet_proposer holds table-level SELECT on %', leak;
    END IF;
    IF NOT has_column_privilege('fleet_proposer', 'public.proposals'::regclass,
                                'id', 'SELECT') THEN
        RAISE EXCEPTION 'B5 FAIL: fleet_proposer cannot read proposals.id and '
                        'so cannot attach evidence';
    END IF;
    IF has_column_privilege('fleet_proposer', 'public.proposals'::regclass,
                            'title', 'SELECT') THEN
        RAISE EXCEPTION 'B5 FAIL: fleet_proposer can read proposal bodies';
    END IF;
RAISE NOTICE 'B5 pass  the proposer reads proposals.id and nothing else'; END $$;

DO $$ DECLARE leak text; BEGIN
    SELECT string_agg(format('%s:%s', c.relname, p.priv), ', ') INTO leak
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
         unnest(ARRAY['INSERT','UPDATE','DELETE','TRUNCATE']) AS p(priv)
    WHERE n.nspname = 'public' AND c.relkind = 'r'
      AND has_table_privilege('fleet_detector_reader', c.oid, p.priv);
    IF leak IS NOT NULL THEN
        RAISE EXCEPTION 'B6 FAIL: fleet_detector_reader can write: %', leak;
    END IF;
RAISE NOTICE 'B6 pass  the read-only role is read-only'; END $$;

DO $$ BEGIN
    IF has_table_privilege('fleet_detector_reader', 'public.decisions', 'SELECT') THEN
        RAISE EXCEPTION 'B7 FAIL: the layer can read its own marks';
    END IF;
    IF NOT has_table_privilege('fleet_detector_reader', 'public.proposals', 'SELECT') THEN
        RAISE EXCEPTION 'B7 FAIL: the layer cannot read its own past output, so a '
                        'daily cycle cannot suppress what it said yesterday';
    END IF;
RAISE NOTICE 'B7 pass  the layer sees what it said, not how it was graded'; END $$;

DO $$ DECLARE leak text; BEGIN
    SELECT string_agg(r.rolname, ', ') INTO leak
    FROM pg_roles r
    WHERE r.rolname LIKE 'fleet\_%'
      AND NOT r.rolsuper
      -- Members of fleet_console are supposed to be able to; that is what
      -- membership means. What must not exist is a route in from anywhere else.
      AND NOT pg_has_role(r.oid, 'fleet_console', 'MEMBER')
      AND has_table_privilege(r.oid, 'public.decisions', 'INSERT');
    IF leak IS NOT NULL THEN
        RAISE EXCEPTION 'B8 FAIL: % may insert decisions without holding '
                        'fleet_console', leak;
    END IF;
RAISE NOTICE 'B8 pass  the only route to a decision is fleet_console membership'; END $$;

DO $$ DECLARE leak text; BEGIN
    SELECT string_agg(c.relname, ', ') INTO leak
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
         unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) AS p(priv)
    WHERE n.nspname = 'public'
      AND c.relname IN ('proposals','proposal_evidence','decisions')
      AND has_table_privilege('public', c.oid, p.priv);
    IF leak IS NOT NULL THEN
        RAISE EXCEPTION 'B9 FAIL: PUBLIC holds privileges on %', leak;
    END IF;
RAISE NOTICE 'B9 pass  nothing is granted to PUBLIC'; END $$;

DO $$ BEGIN IF NOT (
    pg_get_functiondef('enforce_cycle_cardinality()'::regprocedure) ~ 'n >= 5')
THEN RAISE EXCEPTION 'B10 FAIL: the five-item cap is not in the trigger'; END IF;
RAISE NOTICE 'B10 pass  the cap is five and lives in the database'; END $$;

DO $$
DECLARE actual text[];
BEGIN
    SELECT array_agg(e.enumlabel ORDER BY e.enumsortorder) INTO actual
    FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid
    WHERE t.typname = 'decision_reason_code';
    IF actual <> ARRAY['ALREADY_KNOWN','WRONG_PRIORITY','TOO_EXPENSIVE',
                       'BAD_REASONING','MISSING_CONTEXT','NOT_MY_CALL',
                       'DISAGREE_WITH_PREMISE'] THEN
        RAISE EXCEPTION 'B11 FAIL: reason codes are %', actual;
    END IF;
RAISE NOTICE 'B11 pass  the reason codes are the seven declared'; END $$;

DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'proposals_observation_no_estimate_ck')
THEN RAISE EXCEPTION 'B12 FAIL: an observation may carry an effort estimate'; END IF;
RAISE NOTICE 'B12 pass  an observation cannot arrive dressed as advice'; END $$;

-- 001 must be untouched. These are the objects 002 has no business changing.
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'observation_verdicts_authority')
THEN RAISE EXCEPTION 'B13 FAIL: track 1 verdict authority is missing'; END IF;
IF (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind = 'r') < 19
THEN RAISE EXCEPTION 'B13 FAIL: fewer tables than 001 and 002 together create'; END IF;
RAISE NOTICE 'B13 pass  track 1''s objects are still there'; END $$;
