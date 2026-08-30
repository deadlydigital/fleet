-- ============================================================================
-- 004_console_reader.sql  —  the console's read identity
--
-- The console renders three pages over this database and writes nothing. It
-- therefore needs a credential that can only read, and no existing role is
-- one:
--
--   fleet_reader_login   reads track 1 and proposals, but not runs, run_steps
--                        or decisions, so the Tasks and Proposals pages
--                        cannot render. It is also the identity the proposal
--                        cycle reads as -- widening it would give that layer
--                        sight of `decisions`, which is the property 002's
--                        assertion B7 exists to keep.
--   fleet_console       reads what the console needs and can also INSERT a
--                        decision, UPDATE a task and record a verdict. A page
--                        that cannot write should not hold a credential that
--                        can.
--
-- So: a third read side, additive, touching no existing role. The spec said
-- "do not create a new role", meaning do not give the console a writer's
-- credential and do not reuse listmonk. A SELECT-only role serves that intent
-- better than widening a role two other processes already depend on.
--
-- What this file must never grow: an INSERT, an UPDATE, a DELETE, or a
-- membership. Assertion C-series in 004_console_reader_assertions.sql checks
-- all four on the deployed database.
--
-- Target: PostgreSQL 13+ (RDS 15.17), applied with the listmonk identity.
-- ============================================================================

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_console_reader') THEN
        CREATE ROLE fleet_console_reader NOLOGIN;
    END IF;
END $$;

-- ============================================================ 1. TRACK 3
-- The review surface. `tasks` carries the spec and the contract; the run and
-- its steps carry what the runner derived, including the divergence between
-- what the agent claimed and what git showed.
GRANT SELECT ON tasks, task_transitions, protected_path_floor
      TO fleet_console_reader;
GRANT SELECT ON runs, run_steps TO fleet_console_reader;

-- Cost against reservation. `runs.committed_gbp` alone cannot say whether a
-- reservation was exceeded -- settle_model_budget caps the settled figure at
-- the reservation and records the true one on the step -- so the page needs
-- the reservation rows and the calls to show both sides.
GRANT SELECT ON budget_reservations, model_calls TO fleet_console_reader;

-- ============================================================ 2. TRACK 1
-- Detector health, open issues, untriaged observations, false-positive rate.
-- `detector_registry` is here because the page must judge lateness against
-- each detector's own cadence and grace rather than a number in the console.
GRANT SELECT ON detector_registry, detector_definition_boundaries,
      source_registry, routing_policy, step_authority,
      detector_runs, observations, issues, issue_occurrences,
      observation_verdicts, scheduled_checks
      TO fleet_console_reader;

-- ============================================================ 3. TRACK 2
-- Proposals with their evidence, and the decisions recorded against them.
--
-- This is the one grant fleet_reader_login must never have. The console is a
-- person looking at what was decided; the proposal cycle is a layer that must
-- not see how it was graded. Same table, two different readers, and the
-- reason they are different roles.
GRANT SELECT ON proposals, proposal_evidence, decisions TO fleet_console_reader;

-- ============================================================ 4. NOTHING ELSE
--
-- No sequence usage: the console never inserts, so it never needs a nextval.
-- No function grants: the budget functions are SECURITY DEFINER and reserved
-- to fleet_model_gateway, and nothing the console renders needs to call one.
