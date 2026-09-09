-- ============================================================================
-- 026_unattended_approval.sql  —  the record an unattended approval leaves,
--                                 and the two ceilings it consults
--
-- Spec: specs/auto-approval.md §2.4 and §3, approved 9 Sep 2026.
--
-- THE RECORD COMES BEFORE THE THING THAT WRITES IT
--
-- specs/unattended-operation.md §9's principle: the brief was built before
-- autonomy, because the brief is how autonomy is watched. Same ordering here.
-- `decision_log` learns to hold what a machine decision rested on in this
-- migration; console/rank.py and console/autoapprove.py are what fill it, and
-- they land after.
--
-- WHY `decision_log` AND NOT `run_steps`
--
-- console/decide.py already has this vocabulary and this constraint, in
-- `run_steps.payload`. That column belongs to a TASK VERDICT -- a merge, a
-- rejection, something with a run behind it. An approval is not a run step: it
-- happens before any task exists, and the thing it decides is which candidate
-- becomes a task at all. So the vocabulary is reused verbatim and the location
-- is not. Same three words, same constraint, other table.
--
-- Target: PostgreSQL 15+, same floor as 013 and 014.
-- ============================================================================

\set ON_ERROR_STOP on

-- ============================================================ 1. THE PACE

--: The most candidates auto-approval may tick in one night.
--:
--: NOT THE QUEUE DEPTH. specs/unattended-operation.md §8 costs three paces
--: against the £158 pool and chooses ONE CHAIN A NIGHT at £4.20, rejecting two
--: as "exceeds the pool on day 19". Approving up to the queue depth is four
--: tonight -- £8.00 of draft specs, £16.80 if each one's code task follows --
--: which is the pace §8 rejected, twice over.
--:
--: What each setting costs, against £139.09 remaining on 9 Sep 2026:
--:
--:     per_night   specs/night   with code tasks   nights of pool
--:     1  (this)   £2.00         £4.20             33
--:     2           £4.00         £8.40             16
--:     4           £8.00         £16.80            8
--:
--: The other two rows are written down here because a cap whose alternatives
--: are not beside it reads as the only number anyone considered.
--:
--: In the database with the other ceilings, on 013's precedent: "a cap that can
--: be raised without a migration will be raised on the morning something needs
--: longer." The effective number is
--: min(per_night, max_approval_batch, max_queued - queued_now), so 013's
--: ceilings still bind above this one.
CREATE OR REPLACE FUNCTION fleet_autoapprove_per_night() RETURNS int
LANGUAGE sql IMMUTABLE AS $$ SELECT 1 $$;

COMMENT ON FUNCTION fleet_autoapprove_per_night() IS
  'specs/auto-approval.md §2.4. One chain a night, which is '
  'specs/unattended-operation.md §8''s costed answer and not the queue depth. '
  'Raising it is a migration, deliberately.';

-- ============================================================ 2. THE 60% STOP

--: The share of the month's pool the UNATTENDED path may reach.
--:
--: specs/unattended-operation.md §5.1 set this and nothing built it: "At 60%
--: the fleet stops queuing and the brief says why, leaving £63 for work a
--: person chooses." console/approve.py checks `wanted > remaining_gbp`, which
--: is the 100% ceiling, and there was no 60% stop anywhere.
--:
--: It was specified for exactly the situation auto-approval creates: a ceiling
--: consulted when nobody is reading. A person keeps the 100% ceiling -- that is
--: what "leaving £63 for work a person chooses" MEANS, and a stop that applied
--: to both would not leave the £63 for anybody, it would just lower the pool.
CREATE OR REPLACE FUNCTION fleet_autonomous_pool_fraction() RETURNS numeric
LANGUAGE sql IMMUTABLE AS $$ SELECT 0.60::numeric $$;

COMMENT ON FUNCTION fleet_autonomous_pool_fraction() IS
  'specs/unattended-operation.md §5.1. The unattended path stops at 60% of the '
  'pool; a person keeps the 100% ceiling. Not a second pool -- a lower line on '
  'the same one.';

-- fleet_month_credit() GAINS A COLUMN, so it is dropped and recreated:
-- CREATE OR REPLACE cannot change a function's return type. Every caller reads
-- it as `SELECT *` into a dict row or a record -- console/queries.py,
-- console/approve.py, brief/pass_.py, brief/notify.py, enforce_credit_ceiling()
-- -- so a column appended at the END is transparent to all of them. Appended
-- and not inserted, for that reason.
--
-- enforce_credit_ceiling() calls this function and is NOT dropped with it:
-- plpgsql resolves its body at runtime, so the trigger keeps working and picks
-- up the new shape on its next call. That is also why the DROP does not need
-- CASCADE, and must not have one -- CASCADE here would take the ceiling with
-- it and leave the trigger silently absent, which is the failure this whole
-- file exists to make less likely.
DROP FUNCTION IF EXISTS fleet_month_credit();

--: The month's credit position, or a refusal to state one.
--:
--: status is COMPUTED or UNCOMPUTED, and an UNCOMPUTED row carries a reason and
--: NO numbers. Unchanged from 014, and `autonomous_remaining_gbp` obeys the same
--: rule: NULL when the position is unknown, never 0. 014 states why and it is
--: the load-bearing choice here too -- a caller one `coalesce(remaining, 0)`
--: away from turning "I do not know" into "nothing left" is bad; one that turns
--: it into "plenty" is worse.
--:
--: autonomous_remaining_gbp MAY BE NEGATIVE, and that is the signal rather than
--: an error. At £18.91 committed against a £158 pool the unattended line is
--: £94.80 and there is £75.89 of room; past 60% the figure goes negative and
--: the unattended path refuses while a person still has headroom. Clamping it
--: at zero would make "just at the line" and "well past it" the same reading,
--: and the brief prints this number.
CREATE FUNCTION fleet_month_credit()
RETURNS TABLE (period_month date, status text, pool_gbp numeric,
               source text, read_at timestamptz,
               committed_gbp numeric, remaining_gbp numeric,
               uncomputed_reason text, autonomous_remaining_gbp numeric)
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
                || 'refusal rather than an assumption. Record one with the '
                || 'migration identity, which owns this table, or as any '
                || 'member of fleet_admin -- NOT as fleet_console, which holds '
                || 'SELECT here and nothing more: INSERT INTO '
                || 'model_credit_pool (period_month, pool_gbp, source, '
                || 'read_at) VALUES (''' || m
                || ''', <gbp>, ''where you read it'', <when you read it>);')::text,
               NULL::numeric;
        RETURN;
    END IF;

    RETURN QUERY SELECT m, 'COMPUTED'::text, p.pool_gbp, p.source, p.read_at,
           c, p.pool_gbp - c, NULL::text,
           (p.pool_gbp * public.fleet_autonomous_pool_fraction()) - c;
END; $$;

-- SECURITY DEFINER, so the ceiling reads the billing tables without every
-- inserting identity holding SELECT on them. Restored because the DROP took
-- the ownership with it; 014 §5 is the argument.
ALTER FUNCTION fleet_month_credit() OWNER TO fleet_owner;

-- ============================================================ 3. THE RECORD

-- HOW THE DECISION WAS ARRIVED AT, in the vocabulary console/decide.py already
-- uses. "unattended" and not "auto", and decide.py says why in a sentence worth
-- repeating here because this is a different table and a reader may only find
-- one of them: "the word that matters is that NOBODY WAS WATCHING, not that a
-- machine did it. A reader who sees 'auto' asks which automation; a reader who
-- sees 'unattended' knows what to check."
--
-- DEFAULT 'console' so every existing row and every existing caller is
-- unchanged. 010's rows were all written through the console and the default
-- states that rather than leaving it to be inferred.
ALTER TABLE decision_log
    ADD COLUMN IF NOT EXISTS decided_via text NOT NULL DEFAULT 'console';

DO $$ BEGIN
    ALTER TABLE decision_log ADD CONSTRAINT decision_log_decided_via_ck
        CHECK (decided_via IN ('console','by_hand','unattended'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- WHAT THE DECISION RESTED ON. NULL for console rows: a person's reasons are
-- in `reason`, and an empty object there would be a claim that a machine
-- decided this.
ALTER TABLE decision_log
    ADD COLUMN IF NOT EXISTS mechanics jsonb;

DO $$ BEGIN
    ALTER TABLE decision_log ADD CONSTRAINT decision_log_mechanics_is_object_ck
        CHECK (mechanics IS NULL OR jsonb_typeof(mechanics) = 'object');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- THE CONSTRAINT, AND IT IS decide.py's RULE MOVED TO THE OTHER TABLE.
--
-- Same sentence, and it is worth carrying across verbatim: "an unattended
-- decision must carry its gates. A merge nobody watched, with no record of what
-- was checked, is unreviewable afterwards."
--
-- An approval nobody watched is the same shape. `reason` is NOT NULL on every
-- row of this table and 010 §4 is explicit that ten paraphrases of "yes"
-- satisfy the constraint while emptying the column -- so a machine writing
-- reasons is exactly where that failure arrives by a new route. This is what
-- makes it cost something: the row cannot exist unless the mechanics are there
-- to be read against the reason.
DO $$ BEGIN
    ALTER TABLE decision_log ADD CONSTRAINT decision_log_unattended_shows_its_work_ck
        CHECK (decided_via <> 'unattended'
               OR (mechanics IS NOT NULL AND mechanics <> '{}'::jsonb));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON COLUMN decision_log.decided_via IS
  'How the decision was arrived at, not who made it (decided_by) and not what '
  'was decided (decision). ''unattended'' means nobody was watching.';

COMMENT ON COLUMN decision_log.mechanics IS
  'What an unattended decision rested on: the rank version, the sha the probes '
  'were re-executed at, every key value, the cut line, the rule that held each '
  'row below it, and the credit reading. NULL on console rows. Required and '
  'non-empty on unattended ones -- a decision nobody watched that cannot show '
  'its work is unreviewable afterwards.';

-- ============================================================ 4. GRANTS

-- No new grants. 010 already gives fleet_console INSERT on decision_log and
-- fleet_console_reader and fleet_detector SELECT; columns added to a table
-- inherit its privileges.
--
-- fleet_console can therefore write decided_via='unattended'. That is
-- deliberate and it is not a hole: the same identity already writes every
-- console approval, and the column records WHICH of the two it was. A separate
-- identity for the unattended path would make the distinction a credential
-- rather than a claim -- worth doing if this outlives the parity push, and
-- specs/auto-approval.md §0 says it should not.
--
-- fleet_detector holds SELECT, which is what lets brief/pass_.py build
-- overnight.approvals without a new grant.
GRANT EXECUTE ON FUNCTION fleet_autoapprove_per_night() TO PUBLIC;
GRANT EXECUTE ON FUNCTION fleet_autonomous_pool_fraction() TO PUBLIC;
