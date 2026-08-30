-- ============================================================================
-- 008_task_reclaim.sql  —  a tick that died leaves a task nobody can retry
--
-- The runner claims a task, opens a run, and works. If the process dies --
-- killed, OOM, a terminal closed -- the task stays RUNNING and its run stays
-- ACTIVE forever. Nothing notices, because everything in track 3 is driven by
-- a tick that is no longer running.
--
-- It is worse than merely stuck. `runs_one_active_per_task` refuses a second
-- ACTIVE run on the same task, which is exactly right when two runners race
-- and exactly what blocks the retry afterwards: the abandoned run holds the
-- slot. Observed twice while building the research work type, each time
-- needing a hand-written UPDATE to recover.
--
-- This is the counterpart of reclaim_stale_detector_run(), which track 1 has
-- had since 001 for the same failure in the same shape.
--
-- WHAT IT DELIBERATELY DOES NOT DO: increment attempts.
--
-- `claim_task()` already did that at claim time. A killed tick has already
-- spent its attempt -- that is what makes attempts a count of tries rather
-- than a count of completions -- and incrementing again here would charge one
-- attempt twice and retire a task at half its allowance. So reclaim moves the
-- task and leaves the count alone. A task claimed once with max_attempts = 1
-- is therefore FAILED after a reclaim, which is correct: it was allowed one
-- try, it took it, and it died.
--
-- SECURITY INVOKER on purpose, as claim_task() is. A definer function would
-- run as the owner and satisfy enforce_task_transition()'s role check no
-- matter who called it, which would make the state machine advisory.
--
-- Target: PostgreSQL 13+ (RDS 15.17), applied with the listmonk identity.
-- ============================================================================

CREATE FUNCTION reclaim_stale_task(p_task_id bigint,
                                   p_grace interval DEFAULT interval '15 minutes')
RETURNS text
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE t public.tasks; deadline timestamptz; open_runs int;
BEGIN
    -- A grace that can be zero is a grace that will be zero on the morning
    -- somebody wants a stuck task back, and it would reclaim a tick that is
    -- still working. void_stale_reservations() refuses the same way.
    IF p_grace < interval '5 minutes' THEN
        RAISE EXCEPTION 'refusing to reclaim with a grace under five minutes: '
                        'a live tick would be reclaimed out from under itself';
    END IF;

    SELECT * INTO t FROM public.tasks WHERE id = p_task_id FOR UPDATE;
    IF NOT FOUND THEN RETURN 'no_such_task'; END IF;
    IF t.status <> 'RUNNING' THEN RETURN 'not_running'; END IF;

    -- The task's OWN wall clock plus a grace, not a constant. timeout_seconds
    -- is what the agent was given; the tick around it also has to create a
    -- worktree, take the evidence readings, verify and push, so the whole tick
    -- legitimately outlives the agent's cap. The grace is that margin, and it
    -- is the caller's to state.
    deadline := coalesce(t.claimed_at, t.created_at)
                + make_interval(secs => t.timeout_seconds) + p_grace;
    IF now() < deadline THEN
        RETURN 'still_live';
    END IF;

    -- Close the run that is holding the one-active-per-task slot. Without
    -- this the requeue below succeeds and the next tick dies on the unique
    -- index instead, which is how this presented the first time.
    UPDATE public.runs
       SET status = 'FAILED', completed_at = now()
     WHERE task_id = p_task_id AND status IN ('ACTIVE', 'AWAITING_HUMAN');
    GET DIAGNOSTICS open_runs = ROW_COUNT;

    IF t.attempts >= t.max_attempts THEN
        UPDATE public.tasks
           SET status = 'FAILED', completed_at = now()
         WHERE id = p_task_id;
        RETURN 'failed';
    END IF;

    UPDATE public.tasks
       SET status = 'QUEUED', claimed_at = NULL, completed_at = NULL
     WHERE id = p_task_id;
    RETURN 'requeued';
END; $$;

COMMENT ON FUNCTION reclaim_stale_task(bigint, interval) IS
  'Recover a task whose tick died: close the ACTIVE run holding the '
  'one-per-task slot, then requeue below max_attempts or FAIL at it. Does not '
  'touch attempts -- claim_task() already counted this try.';

-- Candidates, so a caller does not have to re-derive the deadline arithmetic
-- and get it subtly different from the function that acts on it.
-- The same five-minute floor as reclaim_stale_task, and not merely for
-- symmetry. The caller removes a worktree BEFORE asking the database to move
-- the task -- deliberately, so a crash between the two leaves a task still
-- RUNNING and reclaimable rather than QUEUED with its branch still checked
-- out. That ordering is only safe if this function cannot name a live tick.
-- Without the floor here, `stale_tasks(interval '0')` would list a working
-- run and its worktree would be removed out from under it before
-- reclaim_stale_task ever got the chance to refuse.
CREATE FUNCTION stale_tasks(p_grace interval DEFAULT interval '15 minutes')
RETURNS TABLE (task_id bigint, repo text, branch_name text, attempts int,
               max_attempts int, claimed_at timestamptz,
               stale_for interval, open_runs bigint)
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT t.id, t.repo, t.branch_name, t.attempts, t.max_attempts, t.claimed_at,
           now() - (coalesce(t.claimed_at, t.created_at)
                    + make_interval(secs => t.timeout_seconds) + p_grace),
           (SELECT count(*) FROM public.runs r
             WHERE r.task_id = t.id AND r.status IN ('ACTIVE','AWAITING_HUMAN'))
      FROM public.tasks t
     WHERE t.status = 'RUNNING'
       AND p_grace >= interval '5 minutes'
       AND now() >= coalesce(t.claimed_at, t.created_at)
                    + make_interval(secs => t.timeout_seconds) + p_grace
     ORDER BY t.id;
$$;

REVOKE ALL ON FUNCTION reclaim_stale_task(bigint, interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION stale_tasks(interval) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION reclaim_stale_task(bigint, interval) TO fleet_task_runner;
GRANT EXECUTE ON FUNCTION stale_tasks(interval)
      TO fleet_task_runner, fleet_console, fleet_console_reader;
