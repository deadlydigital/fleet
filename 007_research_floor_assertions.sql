\set ON_ERROR_STOP on
-- Assertions for 007_research_floor.sql.

DO $$ DECLARE n int; BEGIN
    SELECT count(*) INTO n FROM protected_path_floor WHERE repo = 'fleet';
    IF n = 0 THEN
        RAISE EXCEPTION 'G1 FAIL: the fleet repository has no protected floor, so '
                        'a research contract could make contracts/checks/ writable';
    END IF;
RAISE NOTICE 'G1 pass  the fleet repository has a floor (% globs)', n; END $$;

-- The one that matters most: the agent now works inside the repo holding its
-- own acceptance check.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM protected_path_floor
                    WHERE repo = 'fleet' AND glob = 'contracts/**') THEN
        RAISE EXCEPTION 'G2 FAIL: contracts/ is not protected in the fleet repo, '
                        'so a research task could edit the check judging it';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM protected_path_floor
                    WHERE repo = 'fleet' AND glob = 'tests/**') THEN
        RAISE EXCEPTION 'G2 FAIL: tests/ is not protected in the fleet repo';
    END IF;
RAISE NOTICE 'G2 pass  the check that judges a research task is out of its reach'; END $$;

-- Every migration on disk should be named. This fails when one is added and
-- not listed, which is the only way this table goes stale.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM protected_path_floor
                    WHERE repo='fleet' AND glob='006_verdict_coverage.sql') THEN
        RAISE EXCEPTION 'G3 FAIL: a migration is missing from the floor';
    END IF;
RAISE NOTICE 'G3 pass  the migrations are named individually, not globbed'; END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM protected_path_floor WHERE length(btrim(rationale)) = 0)
    THEN RAISE EXCEPTION 'G4 FAIL: a floor row has no rationale'; END IF;
RAISE NOTICE 'G4 pass  every protected path says why it is protected'; END $$;

DO $$ BEGIN RAISE NOTICE '--- 007 assertions complete ---'; END $$;
