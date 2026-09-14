-- ============================================================================
-- 039_the_loop_became_the_main_consumer.sql
--
-- NOT APPLIED. Apply as `listmonk`, which owns
-- fleet_autonomous_pool_fraction(). Nothing on this host holds it: the fleet
-- DSN connects as dd_detector_login, which may EXECUTE the function and may
-- not REPLACE it. That separation is 014 §6's and it is the right one -- the
-- identity that spends does not set the line it spends under.
--
-- THE UNATTENDED LINE MOVES FROM 60% OF THE POOL TO 85%. Nothing else moves.
--
-- WHY IT MOVES, AND THE REASON IS NOT "IT WAS IN THE WAY"
--
-- It was in the way. On 13 Sep 2026 the loop stopped on CREDIT with task 83
-- queued at GBP 6.00 against GBP 2.99 of autonomous credit, and chain.py's
-- `room < cost` is exactly the stop this line exists to cause. That is the
-- occasion and it is deliberately NOT the justification, because "the control
-- refused, so we raised the control" is how a ceiling stops meaning anything.
-- The same sentence would have raised it at 70%, at 90%, and at 100%.
--
-- THE JUSTIFICATION IS THAT THE THING THE RESERVE WAS FOR HAS MOVED.
--
-- §5.1 set 60% to leave "GBP 63 for work a person chooses". That number was
-- sized when a person chose most of the work and the unattended path was a
-- new mechanism that had never run live (029's words). Measured against the
-- month, as of 13 Sep 2026:
--
--     model_calls, month to date        GBP 129.002313   48 calls
--       of which purpose=task_runner_patch  GBP 129.002313   48 calls
--     held reservations, no task        GBP   0.00
--     QUEUED / RUNNING tasks            GBP  30.00        tasks 83-87
--     ------------------------------------------------
--     committed                         GBP 159.002313   of a GBP 270.00 pool
--
-- EVERY PENNY THE MONTH HAS SPENT WAS SPENT BY THE LOOP. Not most of it --
-- all of it. There is one purpose in model_calls this month and it is the
-- task runner writing patches. The GBP 108.00 held back by the 60% line is
-- not being reserved for a person who is choosing work; it is being reserved
-- against a pattern of use that the month's own billing says has stopped.
--
-- A reserve sized for a consumer that no longer consumes is not caution, it
-- is a misreading kept in force. THAT is what moves the line. If the split
-- goes back -- if a person starts choosing most of the work again -- the
-- reason given here expires and the line should come back down, by another
-- migration, with the same kind of measurement in front of it.
--
-- WHAT 85% BUYS AND WHAT IT COSTS, against GBP 159.002313 committed:
--
--     fraction   the line     autonomous room   reserved for a person
--     0.60 (was) GBP 162.00   GBP   2.997687    GBP 108.00
--     0.75       GBP 202.50   GBP  43.497687    GBP  67.50
--     0.85 (now) GBP 229.50   GBP  70.497687    GBP  40.50
--     0.95       GBP 256.50   GBP  97.497687    GBP  13.50
--     1.00       GBP 270.00   GBP 110.997687    GBP   0.00  <- not a line
--
-- 0.85 is chosen because the reserve it leaves is still a reserve. GBP 40.50
-- is six draft specs at 032's GBP 5.92 shipped-feature figure, or about ten
-- at the GBP 3.94 clean-feature figure -- a person who arrives mid-month with
-- something they want built can have it built. At 0.95 the reserve is GBP
-- 13.50, which is two features, and a reserve that cannot absorb one bad week
-- is a rounding error wearing a ceiling's name.
--
-- THE RESERVE SHRINKS IN ABSOLUTE TERMS AND THAT IS THE REAL COST: GBP 108.00
-- becomes GBP 40.50, which is less than §5.1's GBP 63 even though the pool is
-- larger than the GBP 158 §5.1 was written against. Stated plainly here
-- because the percentage hides it -- 15% of a bigger pool still reads as
-- "more room" to anyone who does not do the multiplication.
--
-- WHAT WAS CONSIDERED AND REFUSED: RECORDING A LARGER POOL. 032 notes that a
-- ceiling bound by the pool is "raised by recording a larger pool, not by a
-- migration", and that route was available -- one UPDATE and task 83 runs.
-- It is refused because `model_credit_pool.pool_gbp` is a READING of the
-- provider balance, recorded by hand with a `source` naming where it was
-- read. Writing a number there to create room is falsifying a measurement to
-- move a limit derived from it, and 014 §6 keeps that column away from the
-- spending identity precisely so that cannot happen quietly. The pool is what
-- the provider says. The fraction is what we choose. This changes the second.
--
-- WHAT DOES NOT MOVE
--
--   THE CEILING. enforce_credit_ceiling() refuses any INSERT whose
--   max_cost_gbp exceeds `remaining_gbp` -- pool minus committed, the 100%
--   line -- and that function, that trigger, and fleet_month_credit() are not
--   touched by this file. A person keeps the whole pool; the unattended path
--   keeps a line below it. Asserted below, both that the fraction is still
--   under 1 and that the trigger is still wired to the table.
--
--   THE REFUSAL. An UNCOMPUTED pool still yields NULL for every figure and
--   still stops everything: the trigger raises, chain.py returns CREDIT, and
--   autoapprove sets `autonomous_credit` to 0. None of that reads the
--   fraction. 026 Q10 owns the destructive test of that property and still
--   passes unchanged, because fleet_month_credit() is not redefined here --
--   which is also why this file needs no DROP and no owner restoration.
--
-- WHAT THIS BREAKS ELSEWHERE, all of it fixed in the same change:
--
--   026's Q9 computed its expectation as `pool * 0.60` and would fail on a
--   correctly moved line. It now reads the fraction function, so it asserts
--   what it is about -- that fleet_month_credit() applies the fraction, and
--   that the result sits below the human ceiling -- and this file pins the
--   VALUE. Each migration that moves the line pins its own.
--
--   tests/test_autoapprove.py inherited the fraction from the deployed
--   database instead of pinning it, which is the coupling 029 found for the
--   pace and _pool() fixed for the pool. The same fixture now pins all three.
--
--   Four sentences in Python named "60%" in printed output and docstrings.
--   They now name the line without naming a number that moves.
--
-- TIMING. fleet-autoapprove.timer fires at 01:30 and the runner fires through
-- the night; this takes effect on the next fire after it is applied. Applying
-- it mid-pass is safe -- the fraction is read fresh on every call and no
-- decision already recorded is reinterpreted.
--
-- APPLY WITH, as the identity that owns the function:
--     psql -v ON_ERROR_STOP=1 -d fleet -f 039_the_loop_became_the_main_consumer.sql
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

CREATE OR REPLACE FUNCTION fleet_autonomous_pool_fraction() RETURNS numeric
LANGUAGE sql IMMUTABLE AS $$ SELECT 0.85::numeric $$;

COMMENT ON FUNCTION fleet_autonomous_pool_fraction() IS
  'specs/unattended-operation.md §5.1, revised by 039. The unattended path '
  'stops at 85% of the pool; a person keeps the 100% ceiling. Not a second '
  'pool -- a lower line on the same one. 026 set 60% to leave GBP 63 for a '
  'person choosing work, when a person chose most of it. 039 moved it to 85% '
  'because the month''s billing showed every penny spent by the loop and none '
  'by anyone else, so the reserve was sized for a consumer that had stopped '
  'consuming. NOT moved because it refused a task -- it did, and that is the '
  'occasion rather than the reason. If a person is choosing the work again, '
  'the reason has expired and the line comes back down by migration.';

-- ---------------------------------------------------------------- assertions
--
-- In this file rather than a sibling _assertions.sql, on 032's precedent: the
-- thing worth asserting about a one-line function is its RELATIONSHIP to the
-- ceiling it sits under, and no single file owns that.
DO $$
DECLARE f numeric := fleet_autonomous_pool_fraction();
        k record;
        wired boolean;
BEGIN
    IF f <> 0.85 THEN
        RAISE EXCEPTION '039: the fraction is %, expected 0.85', f;
    END IF;

    -- THE CEILING SURVIVES, STRUCTURALLY. pool*f - c < pool - c for any pool
    -- above zero exactly when f < 1, so this one comparison is the whole of
    -- "a person keeps the larger number" -- independent of what the pool
    -- happens to read today, which a figure-based check would not be.
    IF f >= 1 THEN
        RAISE EXCEPTION
            '039: a fraction of % is not a line below the ceiling, it is the '
            'ceiling. The unattended path would reach everything a person '
            'can, and specs/unattended-operation.md §5.1 exists to stop that', f;
    END IF;
    IF f <= 0 THEN
        RAISE EXCEPTION
            '039: a fraction of % stops the unattended path completely. That '
            'may be wanted, but it is a different decision and should not '
            'arrive by arithmetic', f;
    END IF;

    -- THE CEILING SURVIVES, LITERALLY: the trigger is still on the table.
    -- Checked because this file is about loosening a limit, and the cheapest
    -- way for that to go wrong is for the OTHER limit to have quietly gone.
    SELECT EXISTS (SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
                    WHERE c.relname = 'tasks'
                      AND t.tgname = 'tasks_credit_ceiling'
                      AND NOT t.tgisinternal) INTO wired;
    IF NOT wired THEN
        RAISE EXCEPTION
            '039: tasks_credit_ceiling is not on tasks. The 100%% ceiling is '
            'what makes 85%% a line rather than a budget; do not raise one '
            'while the other is absent';
    END IF;

    -- AND ON THE LIVE POSITION, if there is one. Skipped rather than failed
    -- when the pool is UNCOMPUTED: that is a refusal, not a fault, and a
    -- migration that would not apply on a month nobody has read the balance
    -- for is a migration that forces the reading to be guessed.
    SELECT * INTO k FROM fleet_month_credit();
    IF k.status = 'COMPUTED' THEN
        IF k.autonomous_remaining_gbp >= k.remaining_gbp THEN
            RAISE EXCEPTION
                '039: the unattended line (%) is not below the human ceiling '
                '(%)', k.autonomous_remaining_gbp, k.remaining_gbp;
        END IF;
        RAISE NOTICE '039: fraction 0.85; unattended GBP % of GBP % remaining',
                     round(k.autonomous_remaining_gbp, 2),
                     round(k.remaining_gbp, 2);
    ELSE
        RAISE NOTICE '039: fraction 0.85; the pool is %, so there is no '
                     'position to check it against and nothing may be queued '
                     'anyway', k.status;
    END IF;
END $$;

COMMIT;
