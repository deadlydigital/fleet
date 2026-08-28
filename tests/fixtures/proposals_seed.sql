-- Track 2's test principals, with exactly the production grants and nothing
-- else. Three logins because the design is three roles: the layer reads as
-- one, writes as another, and cannot decide at all. A test suite that used a
-- single superuser connection would pass while the real separation was
-- broken.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_test_proposer') THEN
    CREATE ROLE fleet_test_proposer LOGIN PASSWORD 'fleet_test_proposer';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_test_reader') THEN
    CREATE ROLE fleet_test_reader LOGIN PASSWORD 'fleet_test_reader';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_test_console') THEN
    CREATE ROLE fleet_test_console LOGIN PASSWORD 'fleet_test_console';
  END IF;
END $$;

GRANT fleet_proposer        TO fleet_test_proposer;
GRANT fleet_detector_reader TO fleet_test_reader;
GRANT fleet_console         TO fleet_test_console;
