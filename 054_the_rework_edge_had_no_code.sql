-- ============================================================================
-- 054_the_rework_edge_had_no_code.sql
--
-- NOT APPLIED BY ANYTHING AUTOMATIC. Apply as the owner (the listmonk
-- identity), as every migration here is.
--
-- WHAT THIS IS FOR
--
-- 003 wrote two transitions and nothing ever implemented them:
--
--   ('READY_FOR_REVIEW', 'REWORK', 'fleet_console', 'you sent it back')
--   ('REWORK',           'QUEUED', 'fleet_console', 'requeued with feedback')
--
-- There is no other caller of REWORK in the repository -- no console module,
-- no runner path, no CLI. The edge was reachable only by writing the UPDATEs
-- by hand, and on 22 Sep 2026 that is what happened, to two tasks, and it
-- destroyed both:
--
--     build: task 137: FAILED -- UniqueViolation: duplicate key value
--            violates unique constraint "runs_one_active_per_task"
--
-- A task at READY_FOR_REVIEW has a run at AWAITING_HUMAN. Moving the task to
-- QUEUED leaves that run holding the slot `runs_one_active_per_task` reserves,
-- so the next claim cannot open a run -- and it fails AFTER `claim_task()` has
-- spent the attempt. Task 137 reached 3/3 with its branch_name cleared without
-- an agent ever having run.
--
-- 008 already knew. `reclaim_stale_task` closes the slot-holding run before it
-- requeues and states the reason: "Without this the requeue below succeeds and
-- the next tick dies on the unique index instead, which is how this presented
-- the first time." It could do that because it runs as `fleet_task_runner`,
-- which holds column-level UPDATE on `runs`. `fleet_console`, which owns both
-- of the transitions above, holds none -- so the one identity permitted to
-- send a task back is the one identity that cannot close its run.
--
-- WHY A GRANT AND NOT A DEFINER FUNCTION
--
-- 008 refused SECURITY DEFINER here for a reason that still holds: "A definer
-- function would run as the owner and satisfy enforce_task_transition()'s role
-- check no matter who called it, which would make the state machine
-- advisory." A definer function that closed runs would let any caller past the
-- role check on the way through. The grant keeps the state machine real.
--
-- WHY THESE TWO COLUMNS AND NOT `UPDATE ON runs`
--
-- `fleet_task_runner` holds UPDATE on exactly (status, completed_at, reason,
-- peak_memory_mib, unjudged_reason). The console needs the first two and
-- nothing else: it is ending a run, not describing one. `reason` is
-- deliberately withheld, so a rework cannot rewrite what the run said about
-- itself -- "verified, branch ready" stays on the row it belongs to.
--
-- `committed_gbp`, `final_outcome`, `human_attention_seconds` and the token
-- columns stay unreachable to the console, which is the partition 014 and 048
-- rest on: the console may not touch the ledger.
--
-- Target: PostgreSQL 13+ (RDS 15.17), applied with the listmonk identity.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

GRANT UPDATE (status, completed_at) ON runs TO fleet_console;

COMMENT ON INDEX runs_one_active_per_task IS
  'One live run per task. Whatever moves a task OUT of a state that owns a '
  'run must close that run first, or the next claim dies here after '
  'claim_task() has already spent the attempt -- see 008 reclaim_stale_task '
  'and console/rework.py. Cost the fleet task 137''s last attempt, 22 Sep 2026.';

-- ===================================================== ASSERTIONS

DO $$
BEGIN
    IF NOT has_column_privilege('fleet_console', 'runs', 'status', 'UPDATE') THEN
        RAISE EXCEPTION '054: fleet_console cannot close a run''s status';
    END IF;
    IF NOT has_column_privilege('fleet_console', 'runs', 'completed_at', 'UPDATE') THEN
        RAISE EXCEPTION '054: fleet_console cannot stamp a run''s completed_at';
    END IF;

    -- The withholding is the point, so it is asserted rather than assumed.
    IF has_column_privilege('fleet_console', 'runs', 'reason', 'UPDATE') THEN
        RAISE EXCEPTION '054: fleet_console may not rewrite a run''s reason';
    END IF;
    IF has_column_privilege('fleet_console', 'runs', 'committed_gbp', 'UPDATE') THEN
        RAISE EXCEPTION '054: fleet_console reached the ledger';
    END IF;
    IF has_table_privilege('fleet_console', 'runs', 'INSERT') THEN
        RAISE EXCEPTION '054: fleet_console may not open a run';
    END IF;
    IF has_table_privilege('fleet_console', 'runs', 'DELETE') THEN
        RAISE EXCEPTION '054: fleet_console may not delete a run';
    END IF;

    -- And the edge this exists to make usable is still there.
    IF NOT EXISTS (SELECT 1 FROM task_transitions
                    WHERE from_status='READY_FOR_REVIEW' AND to_status='REWORK')
       OR NOT EXISTS (SELECT 1 FROM task_transitions
                       WHERE from_status='REWORK' AND to_status='QUEUED') THEN
        RAISE EXCEPTION '054: the rework edge is gone; this grant has no caller';
    END IF;
END $$;

COMMIT;
