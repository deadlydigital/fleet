-- ============================================================================
-- 032_pace_and_depth.sql  —  the count stops binding, so the money can
--
-- 029 set fleet_autoapprove_per_night() to 3 and costed it against a loop
-- where a person read every draft and accepted it by hand. That stopped being
-- true on 10 Sep 2026: `draft_spec` came off console/automerge's
-- NEVER_UNATTENDED and fleet-automerge came off --dry-run, so a draft merges
-- at 03:30 and its code task is queued by console/autoqueue.py without anyone
-- present.
--
-- With the human step gone the pace should be bound by what the night can run
-- and by what the pool can pay for, in that order. 3 is bound by neither: it
-- is a number chosen against a constraint that no longer exists, and it
-- leaves a post-automerge runner fire idle every night.
--
-- WHAT THE NIGHT CAN RUN, COUNTED
--
--     runner fires        9   02:00-04:40, every 20 min, ONE TASK PER FIRE
--                             (run_task.py: "One task per tick. Serial.")
--     before automerge    5   02:00, 02:20, 02:40, 03:00, 03:20
--     after               4   03:40, 04:00, 04:20, 04:40
--
--     a feature           2 runs, either side of the 03:30 merge -- the code
--                         task cannot exist until the draft merges
--
--     so the night allows FOUR, and the pace becomes four.
--
-- THE DEPTH HAS TO MOVE WITH IT, AND APPLYING ONE WITHOUT THE OTHER IS THE
-- FAILURE THIS FILE EXISTS TO AVOID
--
-- 029 gave the reason and understated it. Its words were that a reclaim or a
-- slow draft "pushes the INSERT past fleet_max_queued_tasks() and autoqueue
-- is REFUSED". Counted against enforce_queue_depth() as it actually is -- it
-- counts `status = 'QUEUED'` only, RUNNING does not count, and it refuses at
-- `n >= cap` -- the steady state never reaches 5:
--
--     01:30   4 drafts inserted, n = 0,1,2,3          within a cap of 5
--     03:30   k drafts merged -> k code tasks, and
--             the 4-k unfinished ones are RUNNING or
--             READY_FOR_REVIEW, so n peaks at 4       within a cap of 5
--
-- The real overflow is CARRY-OVER. Eight runs fill eight of nine fires, so a
-- single slow run or one reclaim leaves a task QUEUED when the window closes
-- at 04:40. Two of those and the next night dies:
--
--     01:30   2 left QUEUED from last night
--             draft inserts see n = 2, 3, 4, and then 5 >= 5  REFUSED
--
-- And it is refused inside approve_batch's one transaction, so it is not one
-- row that fails -- it is the WHOLE NIGHT'S APPROVAL, and the morning reads
-- "the ranker approved nothing" for a reason that has nothing to do with the
-- ranking.
--
-- WHY 8 AND NOT 6. Eight is one full night in flight: 4 carried over plus 4
-- inserted at 03:30 gives n = 4,5,6,7 on those inserts, which is exactly
-- within a cap of 8 and exactly outside a cap of 7. It is a bound, not a
-- guess: a cap that fits the worst legitimate night and refuses the night
-- after a genuinely saturated one.
--
-- THIS DOES NOT WIDEN THE RUNNER WINDOW, AND THAT IS A DECISION
--
-- 029 notes that moving fleet-automerge onto the runner's cadence lifts the
-- bound. It is not done here. Tonight is the first live fleet-autoapprove and
-- the first live fleet-automerge; neither has ever fired for real, and
-- nothing reads a spec at any point. Learning how both behave at four times
-- the rate, in the dark, is not a thing to buy with a timer edit. Two nights
-- at four first.
--
-- WHAT IT COSTS, MEASURED ON THIS HOST RATHER THAN ESTIMATED
--
--     clean feature   GBP 3.94   (n=3: 3.94, 3.88, 4.01 -- candidates 12,
--                                 29, 38, spec run plus code run)
--     shipped feature GBP 5.92   (GBP 11.83 across those three chains, two of
--                                 which merged by machine; task 55 failed
--                                 verification and was merged by hand)
--
-- THE SECOND FIGURE IS THE ONE TO PLAN WITH. 029 used 3.94 and that is the
-- cost of a feature that goes right the first time. A ceiling costed against
-- the happy path is a ceiling that refuses in the middle of a bad week.
--
--     four a night    GBP 23.66 at 5.92
--     20 candidates   GBP 118.30, which is five nights
--
-- AND IT IS ONLY SAFE ABOVE A POOL OF ABOUT GBP 250
--
-- fleet_month_credit() holds unattended work to
-- `pool_gbp * fleet_autonomous_pool_fraction() - committed`, which is 0.60
-- today. At the pool of GBP 158.00 read on 8 Sep that is GBP 62.61 of
-- headroom -- about ten shipped features, so four a night walks into the 60%
-- line partway through the third night and stops mid-list.
--
--     pool needed to clear 20 = (118.30 + 32.19) / 0.60 = GBP 250.82
--
-- So raising the pace WITHOUT raising the pool moves which ceiling binds and
-- does not buy anything. The pool is a reading of reality and is not set by a
-- migration; record it as the identity that owns the table, e.g.
--
--     UPDATE model_credit_pool
--        SET pool_gbp = 270.00,
--            source = 'console.anthropic.com billing, read by hand',
--            read_at = now(), recorded_by = current_user, recorded_at = now()
--      WHERE period_month = date_trunc('month', now())::date;
--
-- GBP 270 leaves about two features of slack over the 250.82 the list needs,
-- against a mechanism that has never run live.
--
-- TIMING. fleet-autoapprove.timer fires at 01:30. Applied after that, this
-- takes effect the following night.
--
-- APPLY WITH, as the identity that owns these functions:
--     psql -v ON_ERROR_STOP=1 -d fleet -f 032_pace_and_depth.sql
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

CREATE OR REPLACE FUNCTION fleet_autoapprove_per_night() RETURNS int
LANGUAGE sql IMMUTABLE AS $$ SELECT 4 $$;

COMMENT ON FUNCTION fleet_autoapprove_per_night() IS
  'specs/auto-approval.md §2.4, revised by 029 and again by 032. Four chains '
  'a night: the number of runner fires that follow the 03:30 merge, which is '
  'what the night allows once a feature is two unattended runs either side of '
  'it. 029 said three because a fourth overflowed a queue depth of 5 on any '
  'night with carry-over; 032 raises the depth to 8 in the same change, and '
  'applying one without the other is the failure both files describe. NOT '
  'bound by the pool, which allows about ten shipped features at the reading '
  'of 8 Sep -- that ceiling binds on the third night and is raised by '
  'recording a larger pool, not by a migration.';

CREATE OR REPLACE FUNCTION fleet_max_queued_tasks() RETURNS int
LANGUAGE sql IMMUTABLE AS $$ SELECT 8 $$;

COMMENT ON FUNCTION fleet_max_queued_tasks() IS
  'specs/approval-surface.md §6.1, revised by 032. One full night in flight: '
  'four drafts approved at 01:30 plus four code tasks queued at 03:30. Sized '
  'against enforce_queue_depth(), which counts QUEUED only and refuses at '
  'n >= cap, so the worst legitimate night inserts against n = 4,5,6,7 and a '
  'cap of 7 would refuse it. The refusal happens inside approve_batch''s one '
  'transaction, so what a too-small cap costs is the whole night''s approval '
  'and a morning that reads "the ranker approved nothing" for a reason that '
  'has nothing to do with the ranking.';

-- ---------------------------------------------------------------- assertions
--
-- Checked here rather than in a sibling _assertions.sql because both of these
-- are one-line functions and the thing worth asserting is the RELATIONSHIP
-- between them, which no single file owns. A depth below twice the pace is
-- the state 029 was in, and it fails silently in the direction nobody
-- watches: the night approves nothing and looks like a quiet night.
DO $$
DECLARE pace int := fleet_autoapprove_per_night();
        depth int := fleet_max_queued_tasks();
BEGIN
    IF pace <> 4 THEN
        RAISE EXCEPTION '032: pace is %, expected 4', pace;
    END IF;
    IF depth <> 8 THEN
        RAISE EXCEPTION '032: depth is %, expected 8', depth;
    END IF;
    IF depth < 2 * pace THEN
        RAISE EXCEPTION
            '032: depth % is below twice the pace % -- a night with carry-'
            'over will refuse the whole batch inside approve_batch', depth, pace;
    END IF;
    IF pace > 4 THEN
        RAISE EXCEPTION
            '032: a pace above 4 needs more runner fires after the 03:30 '
            'merge than fleet-runner.timer provides (9 fires, 4 of them '
            'after). Widen the window first, deliberately.';
    END IF;
    RAISE NOTICE '032: pace 4, depth 8, and depth >= 2 * pace.';
END $$;

COMMIT;
