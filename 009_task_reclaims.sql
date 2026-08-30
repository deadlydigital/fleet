-- ============================================================================
-- 009_task_reclaims.sql  —  a silent overnight retry, made visible
--
-- Reclaiming now happens at the start of every tick rather than only when an
-- operator runs it. That closes the stuck-task hole without anyone noticing
-- one, and it opens a different one: a task can be retried at 03:00 and the
-- only trace by morning is that `attempts` reads 2 instead of 1. "Why did
-- this run twice" becomes a question answerable by inference, which is the
-- failure this codebase keeps finding.
--
-- WHY THIS IS STORED RATHER THAN DERIVED
--
-- The instinct everywhere else here is to derive: the runner derives its
-- diff, the console derives its diff, observation_coverage derives coverage
-- from verdicts. A stored answer can disagree with the facts it came from.
--
-- A reclaim cannot be derived, because the act destroys its own evidence.
-- Requeueing sets `claimed_at` to NULL -- the one field that said how long the
-- dead tick had been running -- and `runs` carries no error column to hold a
-- reason. After a reclaim there is nothing left to compute an answer from.
-- That is the test: coverage was derivable from rows that still exist, this is
-- not, so this is a table.
--
-- WRITTEN BY THE FUNCTION, not by the caller. A record the caller is trusted
-- to write is a record that is missing exactly when the caller crashed, which
-- is the circumstance this exists to document.
--
-- Target: PostgreSQL 13+ (RDS 15.17), applied with the listmonk identity.
-- ============================================================================

CREATE TABLE task_reclaims (
    id                bigserial PRIMARY KEY,
    task_id           bigint      NOT NULL REFERENCES tasks(id),
    run_id            bigint      REFERENCES runs(id),
    reclaimed_at      timestamptz NOT NULL DEFAULT now(),
    reclaimed_by      text        NOT NULL DEFAULT current_user,
    outcome           text        NOT NULL CHECK (outcome IN ('requeued','failed')),

    -- The dead tick, as it was. claimed_at is copied here because the requeue
    -- is about to null it, and stale_for is stored rather than recomputed for
    -- the same reason: both are gone a statement later.
    dead_claimed_at   timestamptz,
    stale_for         interval    NOT NULL,
    grace             interval    NOT NULL,
    timeout_seconds   int         NOT NULL,

    attempts          int         NOT NULL,
    max_attempts      int         NOT NULL,
    open_runs_closed  int         NOT NULL DEFAULT 0,

    -- Filled in by the caller after the fact: removing a worktree is
    -- filesystem work no trigger can do, so the database records that a
    -- reclaim happened and the runner records what it cleaned up.
    worktree_removed  text,
    branch_kept       text
);

CREATE INDEX task_reclaims_task_idx ON task_reclaims (task_id, reclaimed_at DESC);

COMMENT ON TABLE task_reclaims IS
  'One row per recovered tick. Stored, not derived: requeueing nulls '
  'claimed_at, so after a reclaim there is nothing left to compute it from.';

-- ============================================================ THE FUNCTION
--
-- Unchanged except that it now records what it did, in the same transaction
-- that does it. A reclaim that happened and left no row would be the silent
-- retry this migration exists to prevent.
CREATE OR REPLACE FUNCTION reclaim_stale_task(
        p_task_id bigint,
        p_grace interval DEFAULT interval '15 minutes')
RETURNS text
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE t public.tasks; deadline timestamptz; open_runs int; last_run bigint;
        result text;
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
         timeout_seconds, attempts, max_attempts, open_runs_closed)
    VALUES (p_task_id, last_run, result, t.claimed_at, now() - deadline, p_grace,
            t.timeout_seconds, t.attempts, t.max_attempts, open_runs);

    RETURN result;
END; $$;

-- What the runner cleaned up, attached after the fact. Only the most recent
-- reclaim of a task can be annotated: an older one is settled history.
CREATE FUNCTION note_reclaim_cleanup(p_task_id bigint, p_worktree text,
                                     p_branch text)
RETURNS void
LANGUAGE sql SET search_path = pg_catalog, public AS $$
    UPDATE public.task_reclaims SET worktree_removed = p_worktree,
                                    branch_kept = p_branch
     WHERE id = (SELECT id FROM public.task_reclaims
                  WHERE task_id = p_task_id ORDER BY reclaimed_at DESC, id DESC
                  LIMIT 1);
$$;

-- ============================================================ GRANTS

REVOKE ALL ON task_reclaims FROM PUBLIC;
REVOKE ALL ON FUNCTION note_reclaim_cleanup(bigint, text, text) FROM PUBLIC;

-- The runner reclaims, so the runner writes the record. It may then attach
-- what it cleaned up on the filesystem -- and ONLY that. Column-level, the way
-- 001 grants UPDATE (status, completed_at) on runs: a reclaim is a fact about
-- what happened, and the outcome, the timings and the attempt counts are not
-- the runner's to revise afterwards.
GRANT SELECT, INSERT ON task_reclaims TO fleet_task_runner;
GRANT UPDATE (worktree_removed, branch_kept) ON task_reclaims TO fleet_task_runner;
GRANT USAGE, SELECT ON SEQUENCE task_reclaims_id_seq TO fleet_task_runner;
GRANT EXECUTE ON FUNCTION note_reclaim_cleanup(bigint, text, text) TO fleet_task_runner;

-- Both read sides: the console shows it, and track 2 may one day want to
-- notice that a task is being retried nightly and never finishing.
GRANT SELECT ON task_reclaims TO fleet_console_reader, fleet_console,
      fleet_detector_reader;
