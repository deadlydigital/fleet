-- ============================================================================
-- 033_failed_runs_keep_what_they_knew.sql
--                     —  the column specs/auto-approval.md §9.6 asked for
--
-- NOT APPLIED. Apply as the identity that owns `runs`.
--
-- §9.6, recorded 10 Sep 2026 and unscheduled every time it was named:
-- "the FAILED path writes two columns and discards everything else the run
-- established". By the time runner/cycle.py settles a task it holds
-- `result.reason`, `result.branch`, the verification verdict and the boundary
-- result, and offers the row none of it.
--
-- FIVE READINGS SO FAR, AND THE FIFTH WAS THIS WEEK
--
--   21, 34, 49, 50   VERIFICATION_RUN = PASS, artefacts used or merged,
--                    tasks.status = FAILED, branch_name NULL
--   51               read as "the platform has no deploy script"; deploy.sh
--                    had been on main since that morning and run three times
--   34, 50           read as "the candidate producer is failing"; both
--                    produced the candidate documents that became batches 9
--                    and 10, and batch 10's nine rows are the pool
--   55, 49           read as failures of work that was merged by hand
--
-- The fifth cost a round trip: a question was put to the person who owns the
-- system on a premise the row supplied and they had to correct it. That is
-- the cheapest version of the failure and not a reason to think it is the
-- last.
--
-- WHY THE REASON GOES ON `runs` AND NOT ON `tasks`
--
-- It is a fact about an attempt. A task may have several, each stopping
-- somewhere different, and a single column on `tasks` would hold the last
-- one and silently overwrite the rest. Every reader that shows a task
-- already joins its latest run -- console/queries.py's TASK_LIST,
-- TASK_DETAIL and MORNING_* all take `ORDER BY id DESC LIMIT 1` -- so this is
-- reachable everywhere a status is displayed, without a join anybody has to
-- add.
--
-- WRITTEN ON EVERY SETTLE, not only on failure. A column that is NULL for
-- success and set for failure is a second encoding of `status`, and the first
-- reader to treat NULL as "fine" would be right until a failure forgot to
-- write it.
--
-- `branch_name` on the failed path is the other half and needs no schema:
-- it is one line in runner/cycle.py, and it writes the branch ONLY when git
-- says the ref exists. §9.6's own rule -- ask the tree, not the row -- and
-- necessary here rather than decorative: `result.branch` is assigned before
-- `worktree.create` runs, so a run that dies early holds a branch NAME for a
-- branch that was never cut. Writing that would be a new false statement of
-- exactly the kind this migration exists to end.
--
-- BLAST RADIUS, from §9.6, checked rather than assumed. Every reader that
-- ACTS on branch_name already gates on status: console/automerge.py selects
-- WHERE status = 'READY_FOR_REVIEW', console/app.py requires both, and
-- console/merge.py is reached only from a reviewed task. The rest display it.
-- So a branch recorded on a FAILED task is visible and inert, which is the
-- whole point: a person can see what the run left behind.
--
-- APPLY WITH, as the identity that owns the table:
--     psql -v ON_ERROR_STOP=1 -d fleet -f 033_failed_runs_keep_what_they_knew.sql
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE runs ADD COLUMN IF NOT EXISTS reason text;

COMMENT ON COLUMN runs.reason IS
  'Why this run ended, in a sentence, from runner/cycle.py''s TickResult. '
  'specs/auto-approval.md §9.6: the FAILED path used to write two columns '
  'and discard everything else the run established, so "verification failed", '
  '"could not be verified", a push that raised and an exception in the '
  'harness all left the same row. Written on every settle, success included: '
  'a column that is NULL for success is a second encoding of status.';

-- The runner writes it. Nothing else does, and nothing else should: it is the
-- runner's account of its own tick.
GRANT UPDATE (reason) ON runs TO fleet_task_runner;

DO $$
DECLARE has_col bool; has_grant bool;
BEGIN
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'runs' AND column_name = 'reason')
      INTO has_col;
    IF NOT has_col THEN
        RAISE EXCEPTION '033: runs.reason was not created';
    END IF;

    SELECT has_column_privilege('fleet_task_runner', 'runs', 'reason', 'UPDATE')
      INTO has_grant;
    IF NOT has_grant THEN
        RAISE EXCEPTION
            '033: fleet_task_runner cannot write runs.reason, so the runner '
            'would fail at exactly the moment it tried to record why it '
            'stopped -- which is the defect, arriving by a new route';
    END IF;

    -- The runner must already be able to write branch_name; 003 granted it
    -- for the success path and the failure path uses the same grant. Asserted
    -- because the other half of this fix depends on it and a missing grant
    -- would turn a settle into a traceback.
    IF NOT has_column_privilege('fleet_task_runner', 'tasks', 'branch_name',
                                'UPDATE') THEN
        RAISE EXCEPTION
            '033: fleet_task_runner cannot write tasks.branch_name';
    END IF;

    RAISE NOTICE '033: runs.reason exists and the runner may write it.';
END $$;

COMMIT;
