-- ============================================================================
-- 038_a_verified_branch_can_be_adopted.sql
--
-- NOT APPLIED. Apply as the identity that owns `tasks` and
-- `enforce_task_transition` (listmonk). Nothing on this host holds it.
--
-- A FAILED task whose branch is GREEN can be moved to READY_FOR_REVIEW instead
-- of being rebuilt. One new edge, and a precondition that makes it safe.
--
-- WHY, AND IT COST £15.06 TO LEARN. Task 69 ran four times. Run 44 produced a
-- branch -- fleet/task-69.3 -- that passed all six of its contract's checks,
-- new_test_bites.sh included, and was refused only by max_test_diff_lines at a
-- value that has since been retired. That branch was, and is, correct. It
-- could not be reached: task_transitions had no FAILED -> READY_FOR_REVIEW
-- edge, so the only way back in was FAILED -> QUEUED, and QUEUED means the
-- agent writes the change again from the spec.
--
-- IT DOES NOT WRITE THE SAME THING. Four runs, identical spec, identical base
-- commit, and the test came out 377, 606, 439, 385 lines. Run 45 -- the rebuild
-- of run 44's work -- cleared the size gate and then failed ruff on one new
-- I001 in the test file. £3.32 to replace a verified branch with a broken one.
-- A retry here is a re-roll, not a retry, and a second draw is as likely to be
-- worse as better.
--
-- WHAT THE PRECONDITION IS, AND WHAT IT DELIBERATELY IS NOT
--
-- The edge requires a RECORDED VERIFICATION that was green. Not a status, not
-- an inference, not `result = PASS`:
--
--   NOT the run's status. FAILED is what every one of these rows says, and it
--   is the reason the edge is being used.
--
--   NOT payload->>'result'. That is `boundary_clean AND verification.passed`,
--   so it is FAIL for exactly the branch this exists to adopt. Run 44's result
--   is FAIL and its six checks are green; those are different sentences and
--   only the second is being asked about.
--
--   THE CHECKS THEMSELVES, read back out of the payload and judged by
--   runner/verify.py's own rules, which the payload carries every field for.
--   A check passes if it was not unresolved and not undecided, and either was
--   skipped or exited 0 without timing out. The verification passes if every
--   check passed AND AT LEAST ONE ACTUALLY RAN -- the second half is
--   Verification.passed's own, and it is what stops a payload of six skips
--   from reading as proof.
--
-- THE RUNS WHERE NOTHING WAS PROVEN ARE EXACTLY THE ONES THIS MUST REFUSE, and
-- until this morning they were most of them. A boundary violation used to
-- return before verification, so runs 41 and 43 carry
-- `verification_skipped: boundary violation` and an empty checks array. Those
-- rows are indistinguishable from a green run BY STATUS -- all three are
-- FAILED -- and completely distinguishable by payload. That is the whole
-- reason the precondition reads the payload.
--
-- WHAT IS NOT CHECKED HERE, BECAUSE THIS FUNCTION CANNOT: GIT.
--
-- Two facts matter and neither is in the database. That the branch tip IS the
-- commit that was verified, and that the base has not moved since -- green
-- against 871f165d is not green against whatever main becomes. Both are asked
-- of the tree by console/adopt.py before it issues the UPDATE, because the
-- tree is the thing neither the row nor anybody editing it can talk out of.
-- The same discipline as paired_paths.py and new_test_bites.sh.
--
-- And console/app.py's accept() is the backstop: it re-runs the contract's
-- verification against the base AS IT STANDS at merge time, before merging,
-- for every branch. An adopted branch is checked exactly as any other is, so
-- the worst a stale adoption can do is arrive at a refusal it would have
-- reached anyway.
-- ============================================================================

BEGIN;

-- The edge. fleet_console, like every other by-hand move: the runner produces
-- branches and must not be able to promote its own failures.
INSERT INTO task_transitions (from_status, to_status, required_role, note)
VALUES ('FAILED', 'READY_FOR_REVIEW', 'fleet_console',
        'adopted: a branch whose recorded checks were green, refused by a '
        'boundary rule rather than by anything wrong with it')
ON CONFLICT (from_status, to_status) DO UPDATE
    SET required_role = EXCLUDED.required_role, note = EXCLUDED.note;

CREATE OR REPLACE FUNCTION public.enforce_task_transition()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE req text;
BEGIN
    IF NEW.status = OLD.status THEN RETURN NEW; END IF;

    SELECT required_role INTO req FROM task_transitions
    WHERE from_status = OLD.status AND to_status = NEW.status;

    IF req IS NULL THEN
        RAISE EXCEPTION 'task % may not move % -> %', OLD.id, OLD.status, NEW.status;
    END IF;
    IF NOT pg_has_role(current_user, req, 'MEMBER') THEN
        RAISE EXCEPTION '% may not move task % -> % (requires %)',
            current_user, OLD.status, NEW.status, req;
    END IF;

    -- A branch is what this track produces. Claiming it is ready without one
    -- is the one lie the status column could otherwise tell.
    IF NEW.status = 'READY_FOR_REVIEW' THEN
        IF NEW.branch_name IS NULL THEN
            RAISE EXCEPTION 'task % cannot be ready for review without a branch',
                OLD.id;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM runs WHERE task_id = OLD.id) THEN
            RAISE EXCEPTION 'task % cannot be ready for review without a run',
                OLD.id;
        END IF;
    END IF;

    -- 038: ADOPTION. Coming from FAILED, a recorded green verification is the
    -- entire justification, so it is required here rather than trusted to the
    -- caller. Judged by runner/verify.py's rules, on the payload's own fields.
    IF OLD.status = 'FAILED' AND NEW.status = 'READY_FOR_REVIEW' THEN
        IF NOT EXISTS (
            SELECT 1
              FROM run_steps s
              JOIN runs r ON r.id = s.run_id
             WHERE r.task_id = OLD.id
               AND s.step_type = 'VERIFICATION_RUN'
               -- Verification.ran: the checks were not skipped wholesale.
               AND s.payload->>'verification_skipped' IS NULL
               AND jsonb_array_length(
                       COALESCE(s.payload->'checks', '[]'::jsonb)) > 0
               -- Verification.passed, second half: something looked at the
               -- tree. Six skips establish nothing and must not read as proof.
               AND EXISTS (
                   SELECT 1 FROM jsonb_array_elements(s.payload->'checks') c
                    WHERE c->>'skipped_reason' IS NULL
                      AND c->>'unresolved_reason' IS NULL
                      AND c->>'undecided_reason' IS NULL)
               -- Verification.passed, first half: no check failed. Check.passed
               -- in reverse -- unresolved and undecided are failures however
               -- they exited, a skip is not, and anything that ran must have
               -- exited 0 without timing out.
               AND NOT EXISTS (
                   SELECT 1 FROM jsonb_array_elements(s.payload->'checks') c
                    WHERE c->>'unresolved_reason' IS NOT NULL
                       OR c->>'undecided_reason' IS NOT NULL
                       OR (c->>'skipped_reason' IS NULL
                           AND (c->>'exit_code' IS DISTINCT FROM '0'
                                OR COALESCE((c->>'timed_out')::boolean, false))))
               -- The boundary refusal must have been about SIZE. A run that
               -- touched a protected path cannot have its checks believed --
               -- the suite is on that list -- and today such a run never
               -- reaches verification at all. Asserted anyway: this edge must
               -- not silently widen if that ordering is ever revisited.
               AND COALESCE(s.payload->'boundary_violations'->'protected',
                            '{}'::jsonb) = '{}'::jsonb
               AND COALESCE(jsonb_array_length(
                       COALESCE(s.payload->'boundary_violations'->'outside_writable',
                                '[]'::jsonb)), 0) = 0
        ) THEN
            RAISE EXCEPTION
                'task % has no run whose recorded checks were green, so there '
                'is nothing to adopt. A run refused before its checks opened '
                'proved nothing about its branch, and that is most of them.',
                OLD.id;
        END IF;
    END IF;

    RETURN NEW;
END; $function$;

DO $$
DECLARE ok boolean;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM task_transitions
                    WHERE from_status = 'FAILED'
                      AND to_status = 'READY_FOR_REVIEW') THEN
        RAISE EXCEPTION '038: the adoption edge was not added';
    END IF;

    SELECT required_role = 'fleet_console' INTO ok FROM task_transitions
     WHERE from_status = 'FAILED' AND to_status = 'READY_FOR_REVIEW';
    IF NOT ok THEN
        RAISE EXCEPTION '038: adoption must be the console''s, not the '
                        'runner''s -- a runner that can adopt can promote its '
                        'own failures';
    END IF;

    -- The edge it must NOT have created: nothing else may reach
    -- READY_FOR_REVIEW, and RUNNING -> READY_FOR_REVIEW stays the runner's.
    SELECT required_role = 'fleet_task_runner' INTO ok FROM task_transitions
     WHERE from_status = 'RUNNING' AND to_status = 'READY_FOR_REVIEW';
    IF NOT ok THEN
        RAISE EXCEPTION '038: the runner''s own path to READY_FOR_REVIEW was '
                        'disturbed';
    END IF;
END $$;

COMMIT;
