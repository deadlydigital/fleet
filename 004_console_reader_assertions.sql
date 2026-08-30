\set ON_ERROR_STOP on
-- Assertions for 004_console_reader.sql, runnable against a deployed database.
--
-- The console's whole safety argument is "it holds a credential that cannot
-- write". That is one sentence and four ways to be wrong, so it is four
-- assertions rather than a comment.
--
-- As in 001, 002 and 003: DO ... RAISE, never `SELECT 1/0 WHERE <cond>`.

DO $$ DECLARE leak text; BEGIN
    SELECT string_agg(format('%s on %s', p.priv, c.relname), ', ')
      INTO leak
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace,
         unnest(ARRAY['INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) AS p(priv)
    WHERE n.nspname = 'public' AND c.relkind IN ('r','p')
      AND has_table_privilege('fleet_console_reader', c.oid, p.priv);
    IF leak IS NOT NULL THEN
        RAISE EXCEPTION 'D1 FAIL: fleet_console_reader holds % ', leak;
    END IF;
RAISE NOTICE 'D1 pass  the console reader holds no write privilege on any table'; END $$;

DO $$ DECLARE bad text; BEGIN
    SELECT string_agg(g.rolname, ', ') INTO bad
    FROM pg_auth_members m
    JOIN pg_roles g ON g.oid = m.roleid
    JOIN pg_roles r ON r.oid = m.member
    WHERE r.rolname = 'fleet_console_reader';
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'D2 FAIL: fleet_console_reader is a member of %, and '
                        'inherits whatever that role can do', bad;
    END IF;
RAISE NOTICE 'D2 pass  the console reader is a member of nothing'; END $$;

-- The console must be able to render all three pages. A missing SELECT here
-- is a page that 500s at 8am, which is the failure this whole thing exists to
-- avoid.
DO $$
DECLARE t text; missing text := '';
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'tasks','runs','run_steps','budget_reservations','model_calls',
        'detector_registry','detector_runs','observations','issues',
        'issue_occurrences','observation_verdicts','scheduled_checks',
        'proposals','proposal_evidence','decisions','routing_policy']
    LOOP
        IF NOT has_table_privilege('fleet_console_reader',
                                   format('public.%I', t)::regclass, 'SELECT') THEN
            missing := missing || t || ' ';
        END IF;
    END LOOP;
    IF missing <> '' THEN
        RAISE EXCEPTION 'D3 FAIL: the console cannot read %', missing;
    END IF;
RAISE NOTICE 'D3 pass  the console can read every table its three pages need'; END $$;

-- The separation that made a new role necessary rather than a widened one.
DO $$ BEGIN
    IF has_table_privilege('fleet_detector_reader', 'public.decisions', 'SELECT') THEN
        RAISE EXCEPTION 'D4 FAIL: the proposal layer can now read decisions -- '
                        '004 widened the wrong role';
    END IF;
    IF NOT has_table_privilege('fleet_console_reader', 'public.decisions', 'SELECT') THEN
        RAISE EXCEPTION 'D4 FAIL: the console cannot read decisions';
    END IF;
RAISE NOTICE 'D4 pass  the console reads decisions and the proposal layer still does not'; END $$;

DO $$ BEGIN RAISE NOTICE '--- 004 assertions complete ---'; END $$;
