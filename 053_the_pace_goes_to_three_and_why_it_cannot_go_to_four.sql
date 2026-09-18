-- ============================================================================
-- 053_the_pace_goes_to_three_and_why_it_cannot_go_to_four.sql
--
-- NOT APPLIED. Apply as `listmonk`, which owns the ceiling functions.
--
-- 044 raised the pace to 2, wrote its argument into a table, and said what it
-- would take to move it again:
--
--     "THE TABLE ABOVE IS NOW THE ONE TO ANSWER. Raising this again is another
--      migration, and the numbers to beat are these."
--
-- This answers that table. It also reports that HALF OF IT HAS STOPPED
-- MEANING ANYTHING, and that the pace is not the dial it was taken for.
--
-- WHAT DIED IN 044'S TABLE
--
-- Its right-hand column was `nights of credit`, and 050 removed the money term
-- from `_cut` entirely: the pool auto-reloads, nothing is billed, and
-- `fleet_month_credit()` is now printed as "notional, governs nothing". So the
-- column that made 2 "where the two columns meet" describes no constraint. The
-- live constraint is 049's window -- output tokens against a target that
-- resets on Sunday -- and it is measured below rather than asserted, because
-- this file must not assert a reading that changes hourly.
--
-- THE READING ON 18 Sep 2026, 10:50 UTC:
--
--     target     2,500,000 output tokens/week (set by eamonn, 17 Sep)
--     committed  1,554,028
--     remaining    945,972          window resets Sunday 20 Sep
--
-- Every task carries max_output_tokens = 100,000 (the column default; all 90
-- rows in `tasks` hold exactly that), and each approval queues ONE draft-spec
-- task which, on merge, queues its code task. So a pace of 3 commits 300,000
-- tonight and 600,000 across the pair -- against 945,972 with two days to run.
-- The window has room for this and would not have room for much more.
--
-- AND NOW THE PART THAT IS NOT ABOUT CEILINGS AT ALL
--
-- The pace was never what rationed this pool, and the table 044 asked for
-- cannot be written in 044's shape. Measured against the live pool this
-- morning, by forcing `_cut` and calling `plan()`, which writes nothing:
--
--     per_night | approves | why
--     ----------+----------+------------------------------------------------
--         1     |    0     | refuses: c71 and c72 indistinguishable
--         2     |    0     | refuses: c72 and c77 indistinguishable  <- TODAY
--         3     |    3     | takes 71, 72, 77
--         4     |    0     | refuses: c73 and c74 indistinguishable
--         5     |    0     | refuses: c74 and c75 indistinguishable
--         6     |    0     | refuses: c75 and c78 indistinguishable
--         7     |    7     | takes all of them
--
-- THAT IS NOT A CEILING CURVE. The seven eligible rows collapse into two
-- equivalence classes under rank_v4 -- every one of the five keys agrees
-- inside each class:
--
--     A = {71, 72, 77}   create, data-present, weekly, 0 prior, no impact
--     B = {73, 74, 75, 78} create, no-figure,  weekly, 0 prior, no impact
--
-- §2.3 refuses when nothing separates the last row taken from the first row
-- below the line. So the sweep approves if and only if the cut lands ON A
-- CLASS BOUNDARY, and every value that lands inside a class approves nothing
-- at all. 3 is where A ends. 7 is where B ends and is unreachable:
-- fleet_max_approval_batch() is 5, and 044's own assertion (below, kept)
-- requires max_queued >= 2 x pace, which at 8 caps the pace at 4.
--
-- SO 3 IS NOT "MORE THROUGHPUT". It is the only reachable value that ships
-- anything, and it ships class A exactly. Tomorrow, with a different pool, 3
-- may well land mid-class and refuse -- and that will not be a regression in
-- this number.
--
-- THE REAL CONSTRAINT, NAMED SO THE NEXT MIGRATION IS NOT ANOTHER GUESS AT
-- THIS NUMBER: the producer is emitting rows that rank_v4 cannot tell apart.
-- Seven candidates, five keys, two distinct key-tuples. `measured_impact` is
-- NULL on all seven, so key 5 -- the key 045 added precisely to break these
-- ties -- has never once had anything to read. Populating it, or adding a
-- sixth key, raises throughput at every pace. Moving the pace does not.
--
-- WHAT IT GIVES UP, on 044's precedent of saying so plainly: a bad night is
-- now three draft-spec tasks rather than two. draft_spec remains on
-- console/automerge.py's NEVER_UNATTENDED, so the output is still markdown on
-- a local branch no auto-merge will touch, and `console/undo.py` is still one
-- command and still only complete before the runner claims the task.
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

BEGIN;

CREATE OR REPLACE FUNCTION public.fleet_autoapprove_per_night()
 RETURNS integer
 LANGUAGE sql
 IMMUTABLE
AS $function$ SELECT 3 $function$;

-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF fleet_autoapprove_per_night() <> 3 THEN
        RAISE EXCEPTION '053: the pace is %, not 3',
            fleet_autoapprove_per_night();
    END IF;

    -- 044'S TWO ASSERTIONS, KEPT VERBATIM IN INTENT. They are the reason this
    -- file stops at 3 rather than reaching for the 7 that would drain class B
    -- as well: max_queued = 8 caps the pace at 4, and max_approval_batch = 5
    -- caps the cut regardless of the pace. Both would have to move first, and
    -- each is its own argument.
    IF fleet_max_approval_batch() < fleet_autoapprove_per_night() THEN
        RAISE EXCEPTION
            '053: the pace (%) is above max_approval_batch (%), so the pace '
            'is no longer the thing that binds and the argument in this file '
            'is about the wrong number',
            fleet_autoapprove_per_night(), fleet_max_approval_batch();
    END IF;
    IF fleet_max_queued_tasks() < 2 * fleet_autoapprove_per_night() THEN
        RAISE EXCEPTION
            '053: max_queued_tasks (%) leaves no room for a night at pace %, '
            'counting the spec task and the code task each approval makes',
            fleet_max_queued_tasks(), fleet_autoapprove_per_night();
    END IF;

    RAISE NOTICE '053: the pace is 3. It is the only reachable cut that lands '
                 'on a rank_v4 class boundary in the pool as it stands; see '
                 'the header, and 045 for the key that would make this a '
                 'throughput question rather than an alignment one.';
END $$;

COMMIT;
