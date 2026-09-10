-- ============================================================================
-- 029_autoapprove_pace.sql  —  the pace stops being bound by the pool and
--                              starts being bound by the night
--
-- 026 set fleet_autoapprove_per_night() to 1 and costed it against the £158
-- pool: "1 spec/night, £4.20 with the code task, 33 nights". That table asked
-- the right question for the loop as it was, where a person queued the code
-- task by hand and the pace was really about how much reading they would do.
--
-- WHAT CHANGED. console/autoqueue.py queues the code task when a draft spec is
-- accepted, so a feature is now TWO RUNNER FIRES that must happen in order,
-- with a merge between them. The money stopped being the constraint and the
-- NIGHT became it.
--
-- THE ARITHMETIC, MEASURED ON THIS HOST RATHER THAN ESTIMATED
--
--     runner fires        9   02:00-04:40, every 20 min, ONE TASK PER FIRE
--                             (run_task.py: "One task per tick. Serial.")
--     before automerge    5   02:00, 02:20, 02:40, 03:00, 03:20
--     after               4   03:40, 04:00, 04:20, 04:40
--
--     a feature           2 runs, and the code task CANNOT EXIST until the
--                         draft merges -- so the two runs fall either side of
--                         automerge, and the post-automerge fires bind.
--
--     measured cost       draft spec  £1.76 / 373s   (task 54)
--                         code task   £2.18 / 424s   (task 53)
--                         a feature   £3.94 / ~13 min of run time
--
-- FOUR CEILINGS, AND WHICH ONE BINDS
--
--     post-automerge fires      4   <- binds
--     queue depth (013)         5   drafts still queued PLUS code tasks
--                                   queued at 03:30, in one number
--     max_approval_batch (013)  5
--     60% credit line           16 features total at £3.94, from £61.85
--
-- The pool allows about sixteen features and the night allows four. The pool
-- has not been the constraint since autoqueue landed, and setting the pace
-- from it would queue work that cannot run.
--
-- WHY 3 AND NOT 4. Four uses every post-automerge fire and takes the queue to
-- its depth at 03:30 -- and a task that reclaims, or a draft that runs slow
-- enough to still be queued when its siblings' code tasks arrive, pushes the
-- INSERT past `fleet_max_queued_tasks()` and autoqueue is REFUSED. That
-- failure leaves a merged draft with no work queued, which is the one state in
-- this loop where nothing is wrong and nothing happens either. Three leaves a
-- fire spare on each side and two slots of queue headroom.
--
-- WHAT WOULD MOVE IT. Not more money. `fleet-automerge.timer` fires ONCE, at
-- 03:30, which was right when it was a nightly sweep and is now a stall in the
-- middle of the chain -- its own comment argues only that it must not fire
-- BEFORE the runner starts. Moving it onto the runner's cadence makes the
-- bound 9 fires / 2 runs = 4, and lets a feature finish in one night instead
-- of two. Raising `fleet_max_queued_tasks()` past 5 is what would then let it
-- go higher. Both are migrations, deliberately.
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION fleet_autoapprove_per_night() RETURNS int
LANGUAGE sql IMMUTABLE AS $$ SELECT 3 $$;

COMMENT ON FUNCTION fleet_autoapprove_per_night() IS
  'specs/auto-approval.md §2.4, revised by 029. Three chains a night, bound by '
  'the four runner fires that follow automerge and by the queue depth -- NOT '
  'by the pool, which allows about sixteen. A feature is two runs either side '
  'of a merge since console/autoqueue.py; the night is the constraint and the '
  'money is not. Raising it is a migration, deliberately.';
