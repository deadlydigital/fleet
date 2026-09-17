-- ============================================================================
-- 050_approval_bounds_the_queue_not_the_money.sql
--
-- NOT APPLIED BY ANYTHING AUTOMATIC. Apply as the owner: it drops a trigger on
-- `tasks`, which listmonk owns.
--
-- WHAT THIS IS FOR
--
-- 049 moved the resource ceiling to the claim, where a task's size is known.
-- It governs nothing, because 014's money ceiling is still upstream of it and
-- refuses first. On the night of 17 Sep 2026 the unattended approver reported
--
--     cut: 0, bound by autonomous_credit
--
-- with ten candidates eligible on merit and a queue of zero. The number that
-- bound it was minus GBP 20.52 of a pool that auto-reloads, on an account
-- where usage credits are off and the balance is zero. Nothing could have
-- been spent, and nothing was approved for two days on the strength of it.
--
-- THE HANDOFF, WHICH IS THE WHOLE POINT
--
--   APPROVAL bounds HOW MUCH WORK EXISTS.      per_night, max_approval_batch,
--                                              max_queued
--   THE CLAIM bounds HOW MUCH RUNS THIS WINDOW. 049's admission control
--
-- and depth becomes window consumption at the moment size becomes knowable.
-- A candidate has no size: `est_cost_gbp` is an estimate of a task that does
-- not exist yet, and on this fleet the spec is itself a task. The first
-- moment anything can be said about what a unit of work will consume is when
-- it is claimed and a contract, a spec and a ceiling exist to say it.
--
-- So the resource question is asked once, at the only point it can be
-- answered, and approval asks a different question entirely: is there room in
-- the queue, and is tonight's pace spent.
--
-- WHY THE MONEY TERM IS REMOVED AND NOT REPLACED
--
-- THE PREMISE FOR A RESOURCE TERM HERE IS GONE, NOT MIS-DENOMINATED. 014 put
-- the ceiling on INSERT because an approval COMMITTED spend -- a queued task
-- was money promised, counted at `max_cost_gbp` in
-- `fleet_month_committed_gbp()`. It is not now. A queued task consumes
-- nothing until it is claimed, and 049 gates the claim. This is not "swap
-- pounds for tokens in the same place"; there is no longer anything to
-- reserve at this point in the pipeline.
--
-- THE ARITHMETIC ALREADY ADMITTED IT. console/autoapprove._cut() computed
-- `int(autonomous_remaining_gbp // task_max_cost)`: a balance that describes
-- no account, divided by a flat contract default standing in for a size
-- nobody knows, to yield a count of tasks. Neither operand described
-- anything. A better divisor would not have fixed it.
--
-- DOUBLE-GATING HIDES THE BINDING CONSTRAINT RATHER THAN DOUBLING THE SAFETY.
-- With a resource term at both ends the stricter one wins and the other is
-- dead weight, and the log names the wrong one: `bound_by: autonomous_credit`
-- was true and useless, because it named a number that does not exist. Two
-- gates on one resource is not belt-and-braces. It is a place for the real
-- constraint to be somewhere other than where anybody is looking.
--
-- THERE WERE THREE MONEY GATES, NOT ONE, AND THAT IS ITSELF THE ARGUMENT
--
-- The first search found `autonomous_credit` in console/autoapprove._cut(),
-- which is what the night's log named. Removing it was not enough:
--
--   1. autoapprove._cut()        `int(autonomous_remaining_gbp //
--                                task_max_cost)` -- the term that bound the
--                                cut to 0 and the one the log reported.
--   2. approve.approve_batch()   refuses when the position is UNCOMPUTED, and
--                                when `task_max_cost * len(approve_ids)`
--                                exceeds `remaining_gbp`. On the SHARED path,
--                                so it gates the human and the machine alike.
--                                It had not fired yet only because GBP 19.98
--                                still covered two GBP 2.00 drafts -- and
--                                `committed_gbp` only grows, so it was days
--                                from firing for the same phantom reason.
--   3. tasks_credit_ceiling      the trigger on `tasks` (014).
--
-- Three gates on one resource, and the one that bound was the one nobody
-- would have looked at first. That is the double-gating argument made
-- concrete: each was individually defensible and together they made the
-- binding constraint unfindable. All three go.
--
-- WHERE THE 85% WENT, BECAUSE IT DID NOT GO ANYWHERE
--
-- This is the part a reader will otherwise conclude was lost.
--
-- 026 and 039 built `autonomous_remaining_gbp` to hold unattended approval to
-- a tighter line than a person: 85% of the pool, so the machine stops while a
-- human still has room. 039 asserts it -- "the unattended line is not below
-- the human ceiling" -- and that principle is not being dropped.
--
-- IT IS ALREADY EXPRESSED IN QUEUE UNITS, and was before this file.
-- `fleet_autoapprove_per_night()` is from 026, the unattended-approval
-- migration; it exists only to pace the machine. A person approving by hand
-- does not pass through `_cut()` at all, so every limit remaining in that
-- function is already an unattended-only limit. The tighter line survives as
-- the pace and the depth cap rather than as a fraction of a balance.
--
-- What is genuinely lost is the FRACTION as a tuning knob -- 0.85 of a number
-- that no longer means anything. If the unattended line should be tighter
-- than it is, the honest lever is now `fleet_autoapprove_per_night()` or
-- `fleet_max_queued_tasks()`, which bound the thing approval actually creates.
--
-- WHAT THIS DOES NOT DROP, AND WHY
--
-- `model_credit_pool`, `fleet_month_credit()` and `enforce_credit_ceiling()`
-- all stay. The pool is the contemporaneous record of what was read and when,
-- 026's and 039's assertions are written against the function, and a migration
-- that deletes the evidence for its own argument is worse than one that
-- leaves a function nothing calls. Only the WIRING goes.
--
-- 048 already relabelled `marginal_cost_gbp`, which is what
-- `fleet_month_committed_gbp()` sums: accurate list price, and notional.
--
-- TWO ASSERTIONS ARE RETIRED BY THIS FILE
--
--   039's DO block requires `tasks_credit_ceiling` to be wired -- "do not
--   raise one while the other is absent". That was correct about a world with
--   a money ceiling at both ends. It is now the thing being removed. 039 still
--   applies cleanly in sequence, because it runs before this file; a re-apply
--   of 039 ALONE, after this, would fail and should be read as this file
--   rather than as a fault.
--
--   026's Q11 asserts the ceiling still fires. Marked retired in
--   026_unattended_approval_assertions.sql, with a pointer here, because an
--   operator runs that file against the CURRENT schema and a check that is
--   deliberately false is an alarm that trains people to ignore alarms.
--
-- Target: PostgreSQL 15+.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

DROP TRIGGER IF EXISTS tasks_credit_ceiling ON tasks;

COMMENT ON FUNCTION enforce_credit_ceiling() IS
  'NOT WIRED since 050. Kept as the record of 014''s ceiling, not as a ceiling: '
  'the pool it reads auto-reloads, nothing is billed against it, and the '
  'resource question is now asked at the claim by 049 where a task''s size is '
  'known. Re-wiring this re-creates the state where the approver refused ten '
  'eligible candidates on minus GBP 20.52 of a balance that cannot be spent.';

COMMENT ON FUNCTION fleet_month_credit() IS
  'A reading nothing gates on, since 050. Still the contemporaneous record of '
  'what the pool was read at, and still what 026''s and 039''s assertions are '
  'written against. The live ceilings are fleet_autoapprove_per_night(), '
  'fleet_max_queued_tasks() and 049''s fleet_window_position().';

COMMIT;
