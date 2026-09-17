-- ============================================================================
-- 049_the_window_is_a_rate_and_it_resets_on_sunday.sql
--
-- NOT APPLIED BY ANYTHING AUTOMATIC, AND NOT SAFE TO APPLY EMPTY. Apply as the
-- owner, WITH a target row in the same transaction -- see THE ONE THING THIS
-- FILE WILL NOT DECIDE, below. Applying it with no target stops the fleet.
--
-- WHAT 014 MEASURED, AND WHAT IS ACTUALLY SCARCE
--
-- 014 built a monthly ceiling over `model_credit_pool`, a hand-read figure for
-- the provider's credit balance, and refused a task whose `max_cost_gbp`
-- exceeded what was left. Every part of that describes an account nobody
-- holds:
--
--   THE POOL DOES NOT DEPLETE. The balance auto-reloads, so a reading of it
--   is a snapshot of a float and not a measure of what remains. 014's own
--   defence -- "the pool is not a decision anybody makes; it is a fact about
--   an account that changes every month by design" -- inverts.
--
--   NOTHING IS BILLED. The runs authenticate against a Claude Max
--   subscription with usage credits OFF and a zero balance. 048 records what
--   `marginal_cost_gbp` is: accurate list price, and notional.
--
--   THE PERIOD IS WRONG TOO. The plan's window resets on SUNDAY. A monthly
--   ceiling cannot see a weekly limit at all, and would let a week's work be
--   spent in three days without noticing.
--
-- So the constraint is a RATE against a window that resets, in a unit the
-- provider meters rather than one it invoices. This file counts OUTPUT
-- TOKENS. That choice is measured: over the 95 runs 048 backfilled, output is
-- the class that tracks work done, while 96.8% of prompt volume is cache
-- reads that grow with conversation length whether or not anything is
-- achieved.
--
-- WHY THIS GATES THE CLAIM AND NOT THE QUEUE
--
-- 014 refused at INSERT, which is the right place for money: an approval
-- commits spend. A window is different. Work that is queued costs nothing
-- until it runs, and the failure this exists to prevent is a run that STARTS
-- with too little window left to finish -- the provider refuses mid-task, the
-- agent stops where it stands, and the branch is a half-finished diff nobody
-- can review.
--
-- That failure is now survivable rather than free: runner/agent.py classifies
-- a usage-window refusal as could-not-run and the task is requeued with its
-- attempt handed back. Survivable is not cheap. The run still burns wall
-- clock, a worktree and a slot in the tick, and the work is thrown away. So
-- the claim is where the question is asked.
--
-- COUNTED AT THE CEILING, WHICH IS 014'S ARGUMENT WITH THE CURRENCY CHANGED
--
-- "Money promised and not yet spent. WITHOUT THIS the ceiling is blind in the
-- one window that matters: five tasks approved and not yet claimed have no
-- model_calls and no reservations, so a pool checked against spend alone
-- would happily approve five more." The same hole exists here and is the same
-- size: five claimed-and-running tasks have written no model_calls yet, and a
-- window checked against settled output alone would admit five more.
--
-- An open task is therefore counted at `max_output_tokens`, the most it may
-- produce, which is the only number about it that is not a guess.
--
-- WHY THE PER-TASK CEILING IS A BACKSTOP AND NOT A BUDGET
--
-- `max_output_tokens` defaults to 100,000, which is 1.37x the largest run on
-- record (72,932) and will almost never fire. That is deliberate, and it is
-- the opposite of what `max_cost_gbp` did.
--
-- Size predicts failure: past ~40k output tokens a run fails about 60% of the
-- time against a 37% baseline. It does not predict it well enough to act on.
-- Tested against all 95 runs, a 45k ceiling would have stopped 9 failing runs
-- and destroyed 5 verified ones; at 40k, 12 and 8. A cap there is a coin flip
-- on real work, so the size signal is SURFACED while a run is in flight --
-- runner/agent.NOTABLE_OUTPUT_TOKENS -- and fired on by nothing.
--
-- The old cap was mis-sized in the same direction and did fire: 4 of 95 runs
-- settled exactly at `max_cost_gbp`, and decision 102 records one of those
-- four, task 118's £6.00, as the cap deleting the work rather than refusing
-- it.
--
-- THE ONE THING THIS FILE WILL NOT DECIDE
--
-- The number. `output_tokens_per_week` is a POLICY -- 013's argument, which
-- 014 explicitly declined for a reading and which applies now that the figure
-- is chosen rather than observed: "a cap that can be raised without a
-- migration will be raised on the morning something needs longer."
--
-- Nothing on this host can derive it. The plan's allowance is not published
-- in tokens, `/usage` is computed from local session history, and the share
-- attributed to Claude Code includes interactive sessions as well as the
-- fleet. What IS measured is the fleet's own pace:
--
--     week of 2026-09-07    53 runs    1,540,651 output tokens
--     week of 2026-09-14    35 runs    1,027,366 output tokens   (3 days)
--
-- Supply the row when you apply this, in the same transaction:
--
--     INSERT INTO model_window_target
--         (output_tokens_per_week, set_by, effective_from, rationale)
--     VALUES (2000000, 'eamonn', now(), 'about a 30% headroom over the
--             53-run week of 7 Sep; revisit once a full week has run under it');
--
-- Target: PostgreSQL 15+, same floor as 014.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- ===================================================== 1. THE WINDOW

--: SUNDAY, NOT MONDAY. `date_trunc('week', ...)` is ISO and starts Monday;
--: the plan resets on Sunday, and a ceiling measuring a different seven days
--: from the provider is a ceiling that is wrong twice a week.
CREATE OR REPLACE FUNCTION fleet_window_start() RETURNS timestamptz
LANGUAGE sql STABLE AS $$
    SELECT date_trunc('week', now() + interval '1 day') - interval '1 day';
$$;

COMMENT ON FUNCTION fleet_window_start() IS
  'Start of the current usage window. Sunday, matching the plan reset -- not '
  'date_trunc(week) which is Monday. See 049.';

-- ===================================================== 2. THE TARGET

CREATE TABLE IF NOT EXISTS model_window_target (
    id                     bigserial PRIMARY KEY,
    output_tokens_per_week bigint NOT NULL CHECK (output_tokens_per_week > 0),

    -- PROVENANCE FOR A DECISION, NOT FOR A READING. 014 carried `source` and
    -- `read_at` because the pool was a figure somebody looked up. This is a
    -- figure somebody CHOSE, so the columns that matter are who chose it and
    -- from when it applies.
    set_by                 text NOT NULL CHECK (length(btrim(set_by)) > 0),
    effective_from         timestamptz NOT NULL,

    -- NOT NULL and not blank, for 014's sharper reason: this is the only
    -- number in the system nothing can re-derive, so if its reasoning is lost
    -- there is nothing to check it against, and a number nobody can check is
    -- a number somebody will eventually raise.
    rationale              text NOT NULL CHECK (length(btrim(rationale)) > 0),

    recorded_by            text NOT NULL DEFAULT current_user,
    recorded_at            timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE model_window_target IS
  'The fleet''s self-imposed output-token budget per usage window. A POLICY, '
  'not a reading: nothing on this host can see the plan''s allowance. Rows '
  'are append-only in practice -- record a new one rather than editing.';

-- ===================================================== 3. THE PER-TASK CEILING

ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS max_output_tokens int NOT NULL DEFAULT 100000
        CHECK (max_output_tokens > 0);

COMMENT ON COLUMN tasks.max_output_tokens IS
  'The most output this task may produce; a runaway backstop, deliberately '
  'above the largest run on record (72,932). It is what an open task is '
  'counted at, and it is not a budget -- see 049 on why a ceiling at p90 '
  'would destroy as much work as it saved.';

-- ===================================================== 4. THE POSITION

--: Settled + open, and the two do not overlap: a RUNNING task has written no
--: model_call yet (the runner settles once, at the end), so counting it at
--: its ceiling and counting its output would not double-count today -- but
--: the settle lands inside the same window, so the row is excluded by
--: `completed_at IS NULL` rather than by hoping the ordering holds.
CREATE OR REPLACE FUNCTION fleet_window_committed_tokens() RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT
        (SELECT coalesce(sum(mc.completion_tokens), 0)
           FROM public.model_calls mc
          WHERE mc.started_at >= public.fleet_window_start())
      + (SELECT coalesce(sum(t.max_output_tokens), 0)
           FROM public.tasks t
          WHERE t.status IN ('QUEUED', 'RUNNING'));
$$;

--: UNCOMPUTED carries a reason and NO numbers, for the reason 014 states and
--: which is load-bearing here too: a caller one `coalesce(remaining, 0)` away
--: from turning "I do not know" into "nothing left" is bad; one that turns it
--: into "plenty" is worse.
CREATE OR REPLACE FUNCTION fleet_window_position()
RETURNS TABLE (window_start timestamptz, status text,
               target_tokens bigint, set_by text, effective_from timestamptz,
               committed_tokens bigint, remaining_tokens bigint,
               uncomputed_reason text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE w timestamptz := public.fleet_window_start();
        t public.model_window_target;
        c bigint := public.fleet_window_committed_tokens();
BEGIN
    SELECT * INTO t FROM public.model_window_target
     WHERE model_window_target.effective_from <= now()
     ORDER BY model_window_target.effective_from DESC,
              model_window_target.id DESC
     LIMIT 1;

    IF NOT FOUND THEN
        RETURN QUERY SELECT w, 'UNCOMPUTED'::text, NULL::bigint, NULL::text,
               NULL::timestamptz, c, NULL::bigint,
               ('no output-token target is in effect. Nothing on this host '
                || 'can derive the plan''s allowance, so the figure is a '
                || 'policy somebody sets and its absence is a refusal rather '
                || 'than an assumption. Record one as a member of '
                || 'fleet_admin -- NOT as fleet_console, which holds SELECT '
                || 'here and nothing more: INSERT INTO model_window_target '
                || '(output_tokens_per_week, set_by, effective_from, '
                || 'rationale) VALUES (<tokens>, ''<who>'', now(), '
                || '''<why>'');')::text;
        RETURN;
    END IF;

    RETURN QUERY SELECT w, 'COMPUTED'::text, t.output_tokens_per_week,
           t.set_by, t.effective_from, c,
           t.output_tokens_per_week - c, NULL::text;
END; $$;

-- ===================================================== 5. ADMISSION

--: SECURITY DEFINER for the reason 014 gives: "so the ceiling can read what
--: it must without every inserting identity holding SELECT on the billing
--: tables. fleet_console can queue a task and still cannot read model_calls."
--: The trigger below runs as the CLAIMING identity, so every table it needs
--: is read through here instead.
CREATE OR REPLACE FUNCTION fleet_window_admission_load(p_task_id bigint)
RETURNS TABLE (settled bigint, in_flight bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT
        (SELECT coalesce(sum(mc.completion_tokens), 0)
           FROM public.model_calls mc
          WHERE mc.started_at >= public.fleet_window_start()),
        (SELECT coalesce(sum(t.max_output_tokens), 0)
           FROM public.tasks t
          WHERE t.status = 'RUNNING' AND t.id <> p_task_id);
$$;

-- ON THE TABLE, for 013's reason that 014 quotes: "the surface is not the only
-- thing that could ever insert a task and a ceiling that only one caller
-- respects is a convention, not a ceiling". The runner claims with an UPDATE,
-- so that is where this sits.
CREATE OR REPLACE FUNCTION enforce_window_admission() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE k record; settled bigint; in_flight bigint;
BEGIN
    IF NEW.status <> 'RUNNING' OR OLD.status = 'RUNNING' THEN
        RETURN NEW;
    END IF;

    SELECT * INTO k FROM fleet_window_position();

    IF k.status = 'UNCOMPUTED' THEN
        RAISE EXCEPTION 'the usage window is unknown, so nothing may be claimed: %',
                        k.uncomputed_reason
            USING HINT = 'a ceiling that cannot read its limit refuses. '
                         'Nobody is reading at 03:00.';
    END IF;

    -- THE GATE ASKS A NARROWER QUESTION THAN THE READOUT REPORTS, and the
    -- difference is deliberate.
    --
    -- `fleet_window_position()` counts QUEUED tasks at their ceiling, which
    -- is 014's argument and the right shape for a POSITION: a backlog is
    -- work the window will have to absorb, and a reader who cannot see it is
    -- blind in the window that matters.
    --
    -- The GATE must not use that number. A backlog larger than the window
    -- would make `remaining` negative and refuse every claim -- including the
    -- first, so a queue of ten against room for five would run none instead
    -- of five. Queued work consumes nothing until it is claimed.
    --
    -- So admission asks only what is already irreversible: output already
    -- settled this window, plus what the tasks ALREADY RUNNING may still
    -- produce, plus this one.
    SELECT a.settled, a.in_flight INTO settled, in_flight
      FROM fleet_window_admission_load(NEW.id) a;

    IF settled + in_flight + NEW.max_output_tokens > k.target_tokens THEN
        RAISE EXCEPTION 'usage window: % of the % target is already settled '
                        'and % is in flight for the window that began %, so '
                        'this task''s % would cross it',
                        settled, k.target_tokens, in_flight, k.window_start,
                        NEW.max_output_tokens
            USING HINT = 'the window resets on Sunday and does not roll over. '
                         'Let the queue drain, lower the task''s '
                         'max_output_tokens, or record a new target.';
    END IF;

    RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS tasks_window_admission ON tasks;
CREATE TRIGGER tasks_window_admission BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION enforce_window_admission();

-- ===================================================== 6. OWNERSHIP

ALTER FUNCTION fleet_window_committed_tokens() OWNER TO fleet_owner;
ALTER FUNCTION fleet_window_admission_load(bigint) OWNER TO fleet_owner;
ALTER FUNCTION fleet_window_position()         OWNER TO fleet_owner;
ALTER FUNCTION enforce_window_admission()      OWNER TO fleet_owner;

-- What the definer functions read, and nothing else -- the note 014 carries
-- for the same grant on model_credit_pool. Without it every definer read of
-- this table fails for the identity that owns the function rather than for
-- the one that called it, which reads as a permissions bug in the caller.
GRANT SELECT ON model_window_target TO fleet_owner;

GRANT SELECT ON model_window_target TO fleet_console, fleet_console_reader;
GRANT SELECT ON model_window_target TO fleet_detector;

-- WRITE: fleet_admin, AND NOT fleet_console. The absence is the invariant, and
-- it matters more than it did in 014. That file could argue the pool was a
-- reading rather than a decision; this is a decision, so a surface that could
-- set its own ceiling would be setting its own budget.
GRANT SELECT, INSERT ON model_window_target TO fleet_admin;
GRANT USAGE, SELECT ON SEQUENCE model_window_target_id_seq TO fleet_admin;

REVOKE ALL ON FUNCTION enforce_window_admission() FROM PUBLIC;

COMMIT;
