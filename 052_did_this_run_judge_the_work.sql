-- ============================================================================
-- 052_did_this_run_judge_the_work.sql
--
-- NOT APPLIED BY ANYTHING AUTOMATIC. Apply as the owner: it adds a column to
-- `runs` and redefines fleet_reclaim_refund_ceiling().
--
-- THE THIRD INSTANCE IN ONE DAY, AND THE REASON THIS FILE IS ABOUT THE
-- QUESTION RATHER THAN THE CASE
--
-- Three times on 17 Sep 2026 a run that judged nothing about a task was
-- recorded as the task failing:
--
--   1. THE PROVIDER REFUSED. The plan's usage window was spent, the agent
--      never started, and the run arrived as a generic non-zero exit. Fixed
--      in runner/agent.classify_could_not_run().
--
--   2. THE TICK DIED. Task 123: claimed 12:46, no agent, reclaimed into
--      FAILED at 1/1. Fixed in 051 by refunding the attempt.
--
--   3. THE AGENT REFUSED ON INSTRUCTION. Task 125: its spec carries a section
--      headed READ THIS BEFORE QUEUEING IT, telling the agent to stop and
--      explain rather than edit the protected suite that would refuse the
--      change. The agent did exactly that -- 64 seconds, no diff, a reply
--      saying why -- and `change.empty` recorded "the agent changed nothing"
--      and FAILED at 1/1. The most correct behaviour available to it was
--      scored identically to giving up.
--
-- Each was found by tripping over it, and each was fixed on its own. That is
-- the pattern worth naming: there was never a single place asking "did this
-- run judge the work at all", so the answer was re-derived, differently, at
-- three sites.
--
-- WHAT CONSOLIDATES, AND WHAT CANNOT
--
-- Two of the three are the same question asked of a live runner, and they
-- consolidate into one predicate: runner/cycle._judged_the_work(). The
-- provider refusing and the agent refusing are both "this process is here,
-- and it has nothing to say about the task".
--
-- The dead tick cannot join them, and the reason is structural rather than an
-- omission: there is no process left to ask. Nothing is running, so the
-- question has to be asked later, by something else, from the outside -- which
-- is what reclaim_stale_task() is. A design that insisted on one site would
-- have to invent a process to host it.
--
-- So: two sites, not three, and not one. What this file makes common is the
-- CONSEQUENCE rather than the detection -- one ceiling, one column, one
-- sentence about what an unjudged run means -- so the next instance is a new
-- detector feeding an existing answer instead of a fourth invention.
--
-- WHY IT IS BOUNDED, AND WHY THE WINDOW REFUSAL IS NOT
--
-- 051 states the case for a ceiling on the dead tick: a task that reliably
-- kills its tick would be refunded forever. An agent that refuses on
-- instruction is the same shape -- if the precondition is never met it refuses
-- every time, and each refusal costs a run, a worktree and wall clock.
--
-- The window refusal is genuinely different and is deliberately NOT bounded:
-- 049's admission control refuses the CLAIM, so no run starts and nothing is
-- spent. That is a task waiting, not a task looping, and the window resets on
-- Sunday whether anything retries or not.
--
-- Target: PostgreSQL 15+.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- ===================================================== 1. THE RECORD

-- WHY A COLUMN AND NOT A PREFIX ON `reason`. The runner writes a sentence
-- there for a person to read, and counting rows by matching the front of a
-- human sentence makes that sentence load-bearing: the next person to improve
-- the wording silently changes what the ceiling counts. Asked of a column
-- instead, the wording stays free.
ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS unjudged_reason text;

COMMENT ON COLUMN runs.unjudged_reason IS
  'Set when the run reached its end without judging the task at all -- the '
  'provider refused before the agent started, or the agent refused on the '
  'spec''s own instruction. NULL means the run is evidence about the task, '
  'including when it failed. A dead tick has no runner to set it and is '
  'recorded in task_reclaims instead. See 052.';

-- ===================================================== 2. THE CEILING

-- ONE NUMBER FOR BOTH CONSEQUENCES. 051 named this
-- fleet_reclaim_refund_ceiling() when the dead tick was the only case; the
-- agent refusing needs the same bound for the same reason, and two knobs that
-- must be changed together are one knob somebody will change half of.
CREATE OR REPLACE FUNCTION fleet_unjudged_refund_ceiling() RETURNS int
LANGUAGE sql IMMUTABLE AS $$ SELECT 2 $$;

COMMENT ON FUNCTION fleet_unjudged_refund_ceiling() IS
  'How many runs that judged nothing a task may be forgiven before they count '
  'against it. Past this, a task whose runs keep judging nothing is telling '
  'you something about the task. See 052.';

-- Kept, and now a view onto the one number rather than a second one. 051's
-- tests and reclaim_stale_task() both name it.
CREATE OR REPLACE FUNCTION fleet_reclaim_refund_ceiling() RETURNS int
LANGUAGE sql IMMUTABLE AS $$ SELECT public.fleet_unjudged_refund_ceiling() $$;

COMMENT ON FUNCTION fleet_reclaim_refund_ceiling() IS
  'Superseded by fleet_unjudged_refund_ceiling(), which it now returns. Kept '
  'because 051 named it and reclaim_stale_task() calls it. See 052.';

-- ===================================================== 3. THE COUNT

--: How many runs of this task judged nothing. The ceiling's input, asked of
--: the column rather than of a sentence.
CREATE OR REPLACE FUNCTION fleet_task_unjudged_runs(p_task_id bigint)
RETURNS int
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT count(*)::int FROM public.runs
     WHERE task_id = p_task_id AND unjudged_reason IS NOT NULL;
$$;

ALTER FUNCTION fleet_task_unjudged_runs(bigint) OWNER TO fleet_owner;
GRANT EXECUTE ON FUNCTION fleet_task_unjudged_runs(bigint) TO fleet_task_runner;

GRANT UPDATE (unjudged_reason) ON runs TO fleet_task_runner;

COMMIT;
