-- Track 3's test principals. The runner is a separate login from the console
-- because the whole track rests on the runner being unable to review its own
-- branch; a suite that drove both through one connection would pass while
-- that separation was broken.
--
-- fleet_test_agent and fleet_test_verifier exist for the same reason one step
-- further down: the identity that proposes a patch is not the identity that
-- certifies it, and 001's step_authority trigger is what enforces it.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_test_task_runner') THEN
    CREATE ROLE fleet_test_task_runner LOGIN PASSWORD 'fleet_test_task_runner';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_test_agent') THEN
    CREATE ROLE fleet_test_agent LOGIN PASSWORD 'fleet_test_agent';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_test_verifier') THEN
    CREATE ROLE fleet_test_verifier LOGIN PASSWORD 'fleet_test_verifier';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_test_model_gateway') THEN
    CREATE ROLE fleet_test_model_gateway LOGIN PASSWORD 'fleet_test_model_gateway';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_test_console_reader') THEN
    CREATE ROLE fleet_test_console_reader LOGIN PASSWORD 'fleet_test_console_reader';
  END IF;
END $$;

GRANT fleet_task_runner TO fleet_test_task_runner;
GRANT fleet_agent       TO fleet_test_agent;
GRANT fleet_verifier    TO fleet_test_verifier;
GRANT fleet_model_gateway TO fleet_test_model_gateway;
GRANT fleet_console_reader TO fleet_test_console_reader;

-- A credit pool reading, because 014 makes a task insert impossible without
-- one and almost every test in this suite inserts a task.
--
-- Large on purpose. Any test that wants the credit ceiling to BIND sets its own
-- pool figure; a template that sat near the line would make unrelated suites
-- fail with a credit error whenever somebody added a task to a fixture, which
-- is the least informative way for a ceiling to be discovered.
--
-- Two months, not one. The template is built once and reused, and a suite that
-- began on the last evening of a month would otherwise start failing at
-- midnight for a reason no test is about.
INSERT INTO model_credit_pool (period_month, pool_gbp, source, read_at)
VALUES (date_trunc('month', now())::date, 10000.00,
        'test fixture, not a reading of any real account', now()),
       ((date_trunc('month', now()) + interval '1 month')::date, 10000.00,
        'test fixture, not a reading of any real account', now())
ON CONFLICT (period_month) DO NOTHING;
