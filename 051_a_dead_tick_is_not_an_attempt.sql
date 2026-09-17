-- ============================================================================
-- 051_a_dead_tick_is_not_an_attempt.sql
--
-- NOT APPLIED BY ANYTHING AUTOMATIC. Apply as the owner: it replaces
-- reclaim_stale_task(), which 009 owns, and adds a column to task_reclaims.
--
-- WHAT HAPPENED, 17 SEP 2026
--
-- Task 123 was claimed at 12:46:09, its tick died, and reclaim recovered it at
-- 13:31:16 -- correctly, and into FAILED at attempts 1/1. Nothing about the
-- task had been judged. No agent had finished, no boundary had been checked,
-- no verification had run. The row now reads FAILED over work nobody looked
-- at, which is exactly the state specs/auto-approval.md 9.6 exists to stop:
-- "a task reading FAILED over code in production is the defect".
--
-- `claim_task()` spends the attempt up front, and 009's comment states the
-- consequence plainly -- "Does not touch attempts -- claim_task() already
-- counted this try". That is true and it is the bug: the try did not happen.
--
-- THE SAME ARGUMENT AS THE WINDOW REFUSAL, one layer over
--
-- runner/verify.py separates a check that FAILED from a check that COULD NOT
-- RUN -- "a check that cannot write is not a check that failed". 048's commit
-- applied that to an agent the provider refused. This applies it to a tick
-- that died: in all three the work was never attempted, so the run is not
-- evidence about the task and must not spend its budget of tries.
--
-- WHY THE REFUND IS BOUNDED, WHICH THE OTHER TWO DID NOT NEED
--
-- A window refusal is transient by construction: the window resets on Sunday,
-- so retrying is guaranteed to become possible. A dead tick is not. A task
-- that reliably kills the tick around it -- an OOM on a pathological repo, a
-- worktree the filesystem will not give up -- would be refunded forever and
-- retried forever, and an unbounded retry is how a small failure becomes a
-- total one.
--
-- So the refund has a ceiling, and past it the attempt stands. Two deaths are
-- an accident; the third is a property of the task. This is 027's
-- repeat-failure argument in a different currency: the same work failing the
-- same way repeatedly IS evidence, even when no single instance was.
--
-- The count comes from `task_reclaims`, which 009 built to make exactly this
-- visible -- "a silent overnight retry, made visible". It was recording the
-- history this decision needs before there was a decision to make.
--
-- WHAT THE ROW SAYS AFTERWARDS
--
-- `attempts` in task_reclaims stays the DEAD TICK'S count, pre-refund, because
-- that is what the column has always meant and a reader comparing rows across
-- time should not have to know which side of this migration each one fell.
-- The new `attempt_refunded` says what was done about it. A reclaim that did
-- not refund because the ceiling was reached is distinguishable from one that
-- did, which is the question a person asks when a task fails twice.
--
-- Target: PostgreSQL 15+.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- ===================================================== 1. THE CEILING

-- IMMUTABLE AND IN A FUNCTION, on 013's argument, which applies because this
-- is a POLICY and not a reading: "a cap that can be raised without a migration
-- will be raised on the morning something needs longer". Two is a choice about
-- how much accident to absorb before concluding the task is the problem.
CREATE OR REPLACE FUNCTION fleet_reclaim_refund_ceiling() RETURNS int
LANGUAGE sql IMMUTABLE AS $$ SELECT 2 $$;

COMMENT ON FUNCTION fleet_reclaim_refund_ceiling() IS
  'How many dead ticks a task may have its attempt refunded for before the '
  'deaths count against it. Past this the tick dying repeatedly is evidence '
  'about the task rather than about the tick. See 051.';

-- ===================================================== 2. THE RECORD

ALTER TABLE task_reclaims
    ADD COLUMN IF NOT EXISTS attempt_refunded boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN task_reclaims.attempt_refunded IS
  'Whether this reclaim handed the attempt back. False on rows written before '
  '051, and false after it when fleet_reclaim_refund_ceiling() was already '
  'reached -- the two are different and the column is how to tell.';

COMMENT ON COLUMN task_reclaims.attempts IS
  'The DEAD TICK''S attempt count, before any refund 051 applies. Unchanged in '
  'meaning across 051 deliberately: a reader comparing rows over time should '
  'not have to know which side of the migration each one fell on.';

-- ===================================================== 3. THE FUNCTION

-- Replaces 009's, which replaced 008's. The only change is the refund and its
-- ceiling; every other line is 009's and is repeated rather than patched
-- because CREATE OR REPLACE takes a whole body and a diff nobody can see is a
-- diff nobody can review.
CREATE OR REPLACE FUNCTION reclaim_stale_task(p_task_id bigint,
                                              p_grace interval DEFAULT interval '15 minutes')
RETURNS text
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE t public.tasks; deadline timestamptz; open_runs int; last_run bigint;
        result text; prior int; refunded boolean := false; dead_attempts int;
BEGIN
    IF p_grace < interval '5 minutes' THEN
        RAISE EXCEPTION 'refusing to reclaim with a grace under five minutes: '
                        'a live tick would be reclaimed out from under itself';
    END IF;

    SELECT * INTO t FROM public.tasks WHERE id = p_task_id FOR UPDATE;
    IF NOT FOUND THEN RETURN 'no_such_task'; END IF;
    IF t.status <> 'RUNNING' THEN RETURN 'not_running'; END IF;

    deadline := coalesce(t.claimed_at, t.created_at)
                + make_interval(secs => t.timeout_seconds) + p_grace;
    IF now() < deadline THEN
        RETURN 'still_live';
    END IF;

    SELECT id INTO last_run FROM public.runs
     WHERE task_id = p_task_id ORDER BY id DESC LIMIT 1;

    UPDATE public.runs
       SET status = 'FAILED', completed_at = now()
     WHERE task_id = p_task_id AND status IN ('ACTIVE', 'AWAITING_HUMAN');
    GET DIAGNOSTICS open_runs = ROW_COUNT;

    -- THE REFUND. Counted BEFORE this reclaim's own row is written below, so
    -- `prior` is the number of deaths already survived and the ceiling means
    -- what it says.
    dead_attempts := t.attempts;
    SELECT count(*) INTO prior FROM public.task_reclaims
     WHERE task_id = p_task_id;

    IF prior < public.fleet_reclaim_refund_ceiling() THEN
        UPDATE public.tasks
           SET attempts = greatest(attempts - 1, 0)
         WHERE id = p_task_id
        RETURNING attempts INTO t.attempts;
        refunded := true;
    END IF;

    IF t.attempts >= t.max_attempts THEN
        UPDATE public.tasks SET status = 'FAILED', completed_at = now()
         WHERE id = p_task_id;
        result := 'failed';
    ELSE
        UPDATE public.tasks
           SET status = 'QUEUED', claimed_at = NULL, completed_at = NULL
         WHERE id = p_task_id;
        result := 'requeued';
    END IF;

    INSERT INTO public.task_reclaims
        (task_id, run_id, outcome, dead_claimed_at, stale_for, grace,
         timeout_seconds, attempts, max_attempts, open_runs_closed,
         attempt_refunded)
    VALUES (p_task_id, last_run, result, t.claimed_at, now() - deadline, p_grace,
            t.timeout_seconds, dead_attempts, t.max_attempts, open_runs,
            refunded);

    RETURN result;
END; $$;

COMMENT ON FUNCTION reclaim_stale_task(bigint, interval) IS
  'Recover a task whose tick died: close the ACTIVE run holding the '
  'one-per-task slot, hand the attempt back (up to '
  'fleet_reclaim_refund_ceiling() times, since a tick that died judged '
  'nothing), then requeue below max_attempts or FAIL at it.';

COMMIT;
