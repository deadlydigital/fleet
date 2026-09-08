-- ============================================================================
-- 014_monthly_credit.sql  —  the third ceiling, and the one that knows what
--                            month it is
--
-- Spec: specs/approval-surface.md §6 ceiling 2, and §6.1, which made all three
-- a precondition for installing fleet-runner.timer. Two were built in 013.
-- This is the third, and until it existed the honest description of the system
-- was the one §6.1 writes down: no ceiling at all, the human having been
-- removed and the constraint not yet built.
--
-- THE POOL IS NOT READABLE FROM THIS HOST, AND THAT IS THE WHOLE DESIGN
--
-- There is no credential here that can ask Anthropic what is left. This is the
-- same shape as the AWS figure in 012 §5: `cost-discipline` carries a hard
-- number, nothing on this box can read it, and the brief therefore carries it
-- as a STANDING UNCOMPUTED CLAIM rather than substituting `infra_costs` and
-- presenting fleet's own record as the biller's.
--
-- A ceiling cannot end there. A brief that cannot compute a figure prints
-- UNCOMPUTED and the reader supplies the judgement. A ceiling that cannot read
-- its limit has no reader to fall back on -- it is being consulted precisely
-- because nobody is watching -- so it must REFUSE. Those are the two honest
-- answers to the same missing number, and which one is right depends on what
-- the thing is for.
--
-- So the pool figure is a RECORDED HUMAN READING, in a table, carrying where it
-- came from and when it was read. Not a default. Not a constant in a function.
-- Not zero. When no reading exists for the current month, every consumer of
-- this file refuses, and says which month it wanted and where to get it.
--
-- WHY THE POOL IS DATA AND THE CAPS IN 013 ARE FUNCTIONS
--
-- 013 argues that a cap belongs in an IMMUTABLE function because "a cap that
-- can be raised without a migration will be raised on the morning something
-- needs longer". That argument is right for a POLICY -- five is a choice about
-- how much autonomy to grant -- and wrong for a READING. The pool is not a
-- decision anybody makes; it is a fact about an account that changes every
-- month by design. Freezing it in a function would mean a migration every
-- month, and a migration that is due monthly is a migration that gets
-- rubber-stamped.
--
-- The policy is still in the constraints, where 013 put it: that a reading must
-- exist, must name its source, must say when it was READ rather than when it
-- was typed, and may not be written by the identity that spends against it.
--
-- COMMITTED IS MEASURED AT max_cost_gbp, NOT AT AN ESTIMATE
--
-- §6 proposed refusing when `SUM(est_cost_gbp)` of the batch exceeds what is
-- left. The measured data says an estimate is the wrong instrument. Of eight
-- settled task runs on this host, two -- tasks 3 and 7 -- settled at exactly
-- £3.0000, which is their `max_cost_gbp` to the penny. That is not what they
-- cost; it is `settle_model_budget()` refusing an actual above the reservation
-- and settling at the bound, with the true figure recorded in a note. A
-- ceiling built on the mean of numbers that are themselves clipped at the cap
-- would under-count exactly the runs that matter.
--
-- So an open task is counted at the most it may spend, which is the only
-- number about it that is not a guess.
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

-- ============================================================ 1. THE READING

CREATE TABLE IF NOT EXISTS model_credit_pool (
    -- One reading per month, keyed by the first of it.
    period_month date PRIMARY KEY
                 CHECK (period_month = date_trunc('month', period_month)::date),

    pool_gbp     numeric(10,2) NOT NULL CHECK (pool_gbp >= 0),

    -- WHERE THE NUMBER CAME FROM, in words, NOT NULL and not blank. Same
    -- discipline as protected_path_floor.rationale and brief_claims.source,
    -- and here for a sharper reason: this is the only figure in the system
    -- that no process can re-derive. If its provenance is lost there is
    -- nothing to check it against, and a number nobody can check is a number
    -- somebody will eventually raise.
    source       text NOT NULL CHECK (length(btrim(source)) > 0),

    -- WHEN THE HUMAN READ IT, which is not when the row was written. The same
    -- separation as brief_claims.as_of against brief_runs.generated_at, and as
    -- candidate_batches.source_sha against generated_at: a figure attributable
    -- to "September" is attributable to a morning.
    read_at      timestamptz NOT NULL CHECK (read_at <= now()),

    recorded_by  text NOT NULL DEFAULT current_user,
    recorded_at  timestamptz NOT NULL DEFAULT now(),
    note         text
);

COMMENT ON TABLE model_credit_pool IS
  'A human reading of the monthly model credit pool. Nothing on this host can '
  'derive it, so it is recorded rather than computed, and its absence makes '
  'every ceiling that depends on it refuse rather than assume.';
COMMENT ON COLUMN model_credit_pool.read_at IS
  'When the figure was READ from the provider, not when this row was written.';

-- ============================================================ 2. COMMITTED

--: Everything this month's pool is already spoken for, in three parts that do
--: not overlap:
--:
--:   settled    model_calls this month. What was actually billed, including
--:              detector calls -- they draw on the same pool, and a ceiling
--:              that counted only task spend would describe something other
--:              than the account.
--:   held       reservations in flight that belong to NO task. A task's own
--:              reservation is exactly its max_cost_gbp (runs_task_budget
--:              refuses more, _reserve() asks for precisely that), so counting
--:              the task below already covers it; counting both would
--:              double-charge every running task.
--:   open       QUEUED and RUNNING tasks, at max_cost_gbp each. Money promised
--:              and not yet spent. WITHOUT THIS the ceiling is blind in the one
--:              window that matters: five tasks approved and not yet claimed
--:              have no model_calls and no reservations, so a pool checked
--:              against spend alone would happily approve five more.
--:
--: A task queued in one month and run in the next is counted against the month
--: it is sitting in. That is deliberate and it is the conservative direction:
--: the ceiling over-counts rather than letting an approval through on the
--: strength of a month boundary.
CREATE OR REPLACE FUNCTION fleet_month_committed_gbp() RETURNS numeric
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT
        (SELECT coalesce(sum(mc.marginal_cost_gbp), 0)
           FROM public.model_calls mc
          WHERE mc.started_at >= date_trunc('month', now()))
      + (SELECT coalesce(sum(br.estimate_gbp), 0)
           FROM public.budget_reservations br
           JOIN public.runs r ON r.id = br.run_id
          WHERE br.status = 'HELD' AND r.task_id IS NULL)
      + (SELECT coalesce(sum(t.max_cost_gbp), 0)
           FROM public.tasks t
          WHERE t.status IN ('QUEUED', 'RUNNING'));
$$;

-- ============================================================ 3. THE ANSWER

--: The month's credit position, or a refusal to state one.
--:
--: status is COMPUTED or UNCOMPUTED, and an UNCOMPUTED row carries a reason and
--: NO numbers -- the same rule brief_claims enforces in a CHECK constraint, for
--: the same reason: a renderer is one refactor away from dropping a field, and
--: a caller is one `coalesce(remaining, 0)` away from turning "I do not know"
--: into "nothing left" or, far worse, into "plenty".
--:
--: Returning NULL for remaining_gbp rather than 0 is the load-bearing choice.
--: Zero is a number. Every arithmetic comparison against it succeeds and
--: silently means something. NULL makes `NEW.max_cost_gbp > remaining` neither
--: true nor false, so a caller that forgets to check the status gets a refusal
--: it did not write instead of an approval it did not mean.
CREATE OR REPLACE FUNCTION fleet_month_credit()
RETURNS TABLE (period_month date, status text, pool_gbp numeric,
               source text, read_at timestamptz,
               committed_gbp numeric, remaining_gbp numeric,
               uncomputed_reason text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE m date := date_trunc('month', now())::date;
        p public.model_credit_pool;
        c numeric := public.fleet_month_committed_gbp();
BEGIN
    SELECT * INTO p FROM public.model_credit_pool WHERE model_credit_pool.period_month = m;

    IF NOT FOUND THEN
        RETURN QUERY SELECT m, 'UNCOMPUTED'::text, NULL::numeric, NULL::text,
               NULL::timestamptz, c, NULL::numeric,
               ('no credit pool reading recorded for ' || to_char(m, 'YYYY-MM')
                || '. Nothing on this host can read the provider balance, so '
                || 'the figure is recorded by hand and its absence is a '
                || 'refusal rather than an assumption. Record one as '
                || 'fleet_admin: INSERT INTO model_credit_pool (period_month, '
                || 'pool_gbp, source, read_at) VALUES (''' || m
                || ''', <gbp>, ''where you read it'', <when you read it>);')::text;
        RETURN;
    END IF;

    RETURN QUERY SELECT m, 'COMPUTED'::text, p.pool_gbp, p.source, p.read_at,
           c, p.pool_gbp - c, NULL::text;
END; $$;

-- ============================================================ 4. THE CEILING

-- ON `tasks`, FOR THE REASON 013 GIVES FOR THE QUEUE DEPTH.
--
-- "On the table rather than in the surface, because the surface is not the only
-- thing that could ever insert a task and a ceiling that only one caller
-- respects is a convention, not a ceiling." That argument is unchanged here,
-- and it has already been tested: the net-refunds code task was inserted
-- directly, bypassing console/approve.py entirely, because approve.py only
-- makes draft-spec tasks. A ceiling living in approve.py would not have been
-- consulted at all.
--
-- Per row rather than per batch, which is what makes a batch work without any
-- batch logic: approve_batch() inserts its tasks in ONE transaction, so the
-- second insert sees the first, the fifth sees four, and the one that crosses
-- the line takes the whole batch down with it.
CREATE OR REPLACE FUNCTION enforce_credit_ceiling() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE k record;
BEGIN
    IF NEW.status <> 'QUEUED' THEN RETURN NEW; END IF;

    SELECT * INTO k FROM fleet_month_credit();

    IF k.status = 'UNCOMPUTED' THEN
        RAISE EXCEPTION 'monthly credit is unknown, so nothing may be queued: %',
                        k.uncomputed_reason
            USING HINT = 'a ceiling that cannot read its limit refuses. The '
                         'brief prints UNCOMPUTED because a reader supplies the '
                         'judgement; nobody is reading at 03:00.';
    END IF;

    IF NEW.max_cost_gbp > k.remaining_gbp THEN
        RAISE EXCEPTION 'monthly credit: £% remains of the £% pool for % '
                        '(£% already committed), and this task may spend £%',
                        round(k.remaining_gbp, 2), k.pool_gbp,
                        to_char(k.period_month, 'YYYY-MM'),
                        round(k.committed_gbp, 2), NEW.max_cost_gbp
            USING HINT = 'the pool does not roll over, so this is a refusal to '
                         'spend next month''s work on this month''s queue. Let '
                         'tasks drain, or record a new reading if the pool has '
                         'actually changed.';
    END IF;

    RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS tasks_credit_ceiling ON tasks;
CREATE TRIGGER tasks_credit_ceiling BEFORE INSERT ON tasks
    FOR EACH ROW EXECUTE FUNCTION enforce_credit_ceiling();

-- ============================================================ 5. OWNERSHIP

-- SECURITY DEFINER, so the ceiling can read what it must without every
-- inserting identity holding SELECT on the billing tables. fleet_console can
-- queue a task and still cannot read model_calls, which is the separation 012
-- §4 keeps between spending and reading spend.
ALTER FUNCTION fleet_month_committed_gbp() OWNER TO fleet_owner;
ALTER FUNCTION fleet_month_credit()        OWNER TO fleet_owner;
ALTER FUNCTION enforce_credit_ceiling()    OWNER TO fleet_owner;

-- What those definer functions read, and nothing else -- the note 003 carries
-- for GRANT SELECT ON tasks TO fleet_owner. budget_reservations and model_calls
-- are already granted to fleet_owner by 001.
GRANT SELECT ON public.model_credit_pool TO fleet_owner;

-- ============================================================ 6. GRANTS

REVOKE ALL ON model_credit_pool FROM PUBLIC;

-- READ, for everything that must show the position or refuse against it.
GRANT SELECT ON model_credit_pool TO fleet_console, fleet_console_reader;
GRANT SELECT ON model_credit_pool TO fleet_detector;

-- WRITE: fleet_admin, AND NOT fleet_console. The absence is the invariant.
--
-- fleet_console is the identity that approves a batch and queues the tasks. If
-- it could also write the pool figure, the ceiling would be a number the
-- spending identity sets for itself -- the same shape as a runner that could
-- mark its own branch MERGED, which 003 §5 refuses, and as a producer that
-- could pre-approve its own candidate, which 013 §3 refuses.
--
-- Raising this ceiling should require reaching for a different credential. It
-- is not a migration, because a monthly reading is not a policy change; it is
-- a deliberate step outside the surface that spends the money.
GRANT SELECT, INSERT, UPDATE, DELETE ON model_credit_pool TO fleet_admin;

-- Functions are EXECUTE TO PUBLIC by default. The two readers are safe to
-- expose -- they are the position, which the console page prints -- but the
-- trigger function is not something any caller should invoke directly.
REVOKE ALL ON FUNCTION enforce_credit_ceiling() FROM PUBLIC;
