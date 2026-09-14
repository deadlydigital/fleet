-- ============================================================================
-- 044_the_pace_goes_to_two.sql
--
-- NOT APPLIED. Apply as `listmonk`, which owns the ceiling functions.
--
-- specs/auto-approval.md §2.4 decided 1, wrote the two numbers it was chosen
-- over into a table beside it, and said plainly what it would take to change:
--
--     "Raising it is a migration -- one line, one commit -- and this table is
--      the argument that has to be answered to justify one, not a menu."
--
-- THIS IS THE ANSWER TO THAT TABLE. The original was priced against GBP139.09
-- remaining and a pool nobody had measured the drain rate of. Tonight, against
-- GBP44.06 on the unattended line and the pool as it stands after 043 retires
-- the rows the tree has already answered:
--
--     per_night | eligible rows | nights to drain | nights of credit
--     ----------+---------------+-----------------+------------------
--         1     |       5       |        5        |       10
--         2     |       5       |        3        |        5
--         4     |       5       |        2        |        2
--
-- 2 IS WHERE THE TWO COLUMNS MEET. At 1 the credit outlives the pool twice
-- over and a person reads a brief every morning for a working week to spend
-- money that is sitting there. At 4 the credit is the binding constraint and
-- runs out mid-week, which is the failure §5.1's line exists to prevent --
-- and 4 was `depth-fill`, chosen for a night, not a pace.
--
-- WHAT IT GIVES UP, SAID PLAINLY. Every ceiling under this one now binds
-- twice as often: max_approval_batch is 5, queue_room is 8, and the
-- repeat-failure stop is a per-candidate rule that does not know about pace.
-- A bad night is twice as expensive, and the thing that makes a bad night
-- cheap is still `console/undo.py`, still one command, and still only
-- complete before the runner claims the task.
--
-- AND IT MULTIPLIES WHATEVER ELSE IS WRONG, which on the night this was
-- written is not hypothetical: the gate fixes earlier the same evening made
-- candidate 66 reachable for the first time -- a row asking to PRICE an index
-- before writing a migration -- so the first night at the new pace is also
-- the first night the migration contract is reachable unattended. That is an
-- argument for watching the first two nights, not for the pace being wrong.
--
-- THE TABLE ABOVE IS NOW THE ONE TO ANSWER. Raising this again is another
-- migration, and the numbers to beat are these.
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

BEGIN;

CREATE OR REPLACE FUNCTION public.fleet_autoapprove_per_night()
 RETURNS integer
 LANGUAGE sql
 IMMUTABLE
AS $function$ SELECT 2 $function$;

-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF fleet_autoapprove_per_night() <> 2 THEN
        RAISE EXCEPTION '044: the pace is %, not 2',
            fleet_autoapprove_per_night();
    END IF;

    -- The ceilings this one is meant to stay under. If either has moved, the
    -- table in the header was priced against a system that no longer exists.
    IF fleet_max_approval_batch() < fleet_autoapprove_per_night() THEN
        RAISE EXCEPTION
            '044: the pace (%) is above max_approval_batch (%), so the pace '
            'is no longer the thing that binds and the argument in this file '
            'is about the wrong number',
            fleet_autoapprove_per_night(), fleet_max_approval_batch();
    END IF;
    IF fleet_max_queued_tasks() < 2 * fleet_autoapprove_per_night() THEN
        RAISE EXCEPTION
            '044: max_queued_tasks (%) leaves no room for a night at pace %, '
            'counting the spec task and the code task each approval makes',
            fleet_max_queued_tasks(), fleet_autoapprove_per_night();
    END IF;

    RAISE NOTICE '044: the pace is 2. specs/auto-approval.md 2.4 carries the '
                 'table this answered.';
END $$;

COMMIT;
