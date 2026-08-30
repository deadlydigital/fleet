\set ON_ERROR_STOP on
-- Assertions for 005_console_decisions.sql.
--
-- E1 is the specific fix. E2 is the general one: it fails for ANY role
-- step_authority names that cannot read it, so the next step type added with
-- a new role cannot repeat this.

DO $$ BEGIN
    IF NOT has_table_privilege('fleet_console', 'public.step_authority', 'SELECT') THEN
        RAISE EXCEPTION 'E1 FAIL: fleet_console cannot read step_authority, so '
                        'enforce_step_authority() raises a permission error '
                        'instead of its own message and HUMAN_DECISION is '
                        'unreachable by the only role permitted to write it';
    END IF;
RAISE NOTICE 'E1 pass  the console can record the verdict 001 designed for it'; END $$;

DO $$ DECLARE blind text; BEGIN
    SELECT string_agg(DISTINCT sa.required_role, ', ') INTO blind
      FROM step_authority sa
     WHERE NOT has_table_privilege(sa.required_role, 'public.step_authority', 'SELECT');
    IF blind IS NOT NULL THEN
        RAISE EXCEPTION 'E2 FAIL: % are named by step_authority but cannot read '
                        'it, so the trigger that governs them fails on the '
                        'wrong error', blind;
    END IF;
RAISE NOTICE 'E2 pass  every role step_authority names can read step_authority'; END $$;

-- The console gained exactly two writes and no more. In particular it did not
-- gain the ability to deploy, which is the one thing this track promises.
DO $$ BEGIN
    IF has_table_privilege('fleet_console', 'public.detector_runs', 'INSERT')
       OR has_table_privilege('fleet_console', 'public.observations', 'INSERT') THEN
        RAISE EXCEPTION 'E3 FAIL: the console can write track 1 evidence';
    END IF;
    IF pg_has_role('fleet_console', 'fleet_deployer', 'MEMBER') THEN
        RAISE EXCEPTION 'E3 FAIL: the console is a member of fleet_deployer';
    END IF;
RAISE NOTICE 'E3 pass  the console may decide, and may not deploy or fabricate evidence'; END $$;

DO $$ BEGIN RAISE NOTICE '--- 005 assertions complete ---'; END $$;
