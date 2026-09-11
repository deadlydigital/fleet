-- ============================================================================
-- 035_a_run_records_what_it_cost_in_memory.sql
--          —  the number the ceiling in three unit files is supposed to clear
--
-- NOT APPLIED. Apply as the identity that owns `runs`.
--
-- 11 Sep 2026. fleet-runner, fleet-console and fleet-automerge were given one
-- memory ceiling -- 2G -- measured against the heaviest verification sequence
-- any contract declares: dd-analytics-frontend at 961 MiB, read from the
-- cgroup's memory.peak under each unit's real confinement.
--
-- THE RUNNER'S CEILING ALSO CAPS THE AGENT, AND THAT PEAK WAS NEVER MEASURED.
-- The other two units run verification and nothing else. The runner runs an
-- agent first -- a node process with a model session -- and then verifies. Its
-- ceiling was unset until that day, so no run has ever been near a limit and
-- nothing has ever recorded how close it came.
--
-- MemoryAccounting=yes IS NOT ENOUGH ON ITS OWN, and this migration exists
-- because checking that assumption is cheap and it was wrong:
--
--     $ systemctl show fleet-autoapprove.service -p MemoryPeak --value
--     [not set]
--
-- systemd drops MemoryPeak when the cgroup goes away, which for a Type=oneshot
-- unit is the moment it finishes. The number is readable only from INSIDE the
-- run, and only while it is still running. A unit whose peak can be read only
-- by a person who happened to be watching is a unit whose peak nobody knows --
-- which is the same shape as §9.6, where the run held what it knew and gave
-- the row none of it.
--
-- WHY ON `runs` AND NOT ON `tasks`, which is 033's argument unchanged: it is a
-- fact about an attempt, a task may have several, and a column on `tasks`
-- would hold the last one and overwrite the rest.
--
-- WHY NULLABLE. A host without cgroup v2, a delegated namespace, a missing
-- file: all mean "cannot say", and NULL is how this schema says that
-- everywhere else. A zero would be a measurement nobody took.
--
-- WHAT IT IS FOR: raising or lowering the ceiling on evidence. When several
-- runs have recorded a peak, `MEASURED_PEAK_MIB` in tests/test_unit_ceilings.py
-- can be moved to what the runner actually costs rather than to what
-- verification alone costs. Until then the runner's half of that number is an
-- inference, and it is written down as one.
--
-- APPLY WITH, as the identity that owns the table:
--     psql -v ON_ERROR_STOP=1 -d fleet -f 035_a_run_records_what_it_cost_in_memory.sql
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE runs ADD COLUMN IF NOT EXISTS peak_memory_mib integer;

COMMENT ON COLUMN runs.peak_memory_mib IS
  'High-water memory for this run''s whole cgroup, in MiB, read from '
  'memory.peak by runner/cycle.py at settle. Covers the agent AND the '
  'verification that follows it, which is what the unit''s MemoryMax has to '
  'hold. NULL means the host could not say -- no cgroup v2, or the file was '
  'not readable -- never that the run cost nothing. systemd''s own MemoryPeak '
  'is not an alternative: it is dropped when the cgroup goes away, which for '
  'a oneshot unit is the moment it finishes.';

-- The runner writes it, and only on its own rows. Same grant shape as 033's
-- `reason`: it is the runner's account of its own tick.
GRANT UPDATE (peak_memory_mib) ON runs TO fleet_task_runner;

DO $$
DECLARE has_col bool; has_grant bool;
BEGIN
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'runs'
                      AND column_name = 'peak_memory_mib')
      INTO has_col;
    IF NOT has_col THEN
        RAISE EXCEPTION '035: runs.peak_memory_mib was not created';
    END IF;

    SELECT has_column_privilege('fleet_task_runner', 'runs',
                                'peak_memory_mib', 'UPDATE')
      INTO has_grant;
    IF NOT has_grant THEN
        RAISE EXCEPTION '035: fleet_task_runner cannot write peak_memory_mib';
    END IF;

    -- The console reads it. It reads every other column of `runs` already,
    -- through fleet_console_reader, and a number nobody can display is a
    -- number nobody will look at.
    IF NOT has_column_privilege('fleet_console_reader', 'runs',
                                'peak_memory_mib', 'SELECT') THEN
        RAISE EXCEPTION '035: fleet_console_reader cannot read peak_memory_mib';
    END IF;
END $$;

COMMIT;
