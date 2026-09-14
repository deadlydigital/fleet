-- ============================================================================
-- 042_a_check_that_fails_on_the_base_is_not_evidence.sql
--
-- NOT APPLIED. Apply as `listmonk`, which owns run_steps and is a member of
-- fleet_owner, which owns enforce_task_transition(). This file needs both.
--
-- WHAT 038 CANNOT TELL APART. Adoption requires a recorded green verification,
-- judged on the payload's own fields. That is the right rule for the case it
-- was written for -- a gate refused a branch on a threshold, the checks were
-- green, take the branch -- and it has no answer at all for the case where a
-- CHECK is what was wrong.
--
-- MEASURED, NOT REASONED. Task 100 on 14 Sep 2026: a 68-line query rewrite in
-- analytics_engine.py, five of six checks green, boundary clean, branch tip
-- equal to the recorded patch sha, base unmoved. The sixth check failed on
-- `tests/analytics/test_migrations.py::TestHalfMigratedSchema::
-- test_apply_executes_only_the_missing_steps`, asserting `22 == 21` against a
-- hand-maintained step tally that migration 0014 had moved by one. The branch
-- touches no migration and no test_migrations.py. Checked out on its own, the
-- base fails that test identically, in 1.87s.
--
-- So the recorded FAIL was true about the tree and false about the branch, and
-- 038 had no way to say so. The two available answers were both bad: re-queue
-- the task, paying a rebuild to discard a good branch and maybe get a worse
-- one; or hand-edit the row past a trigger written to stop exactly that.
--
-- THE RULE, SAID ONCE: a check that fails identically on the base is not
-- evidence about the branch.
--
-- THE DATABASE CANNOT RUN PYTEST, so it does not try. console/adopt.py re-runs
-- the failing command in a throwaway clone AT THE BASE COMMIT THE RUN
-- RECORDED, and writes what happened as a BASE_CHECK_RUN step against that
-- same run. This function then asks whether such a step exists and agrees with
-- the failure it excuses. Evidence is produced outside and judged inside,
-- which is how 040 and 041 already work.
--
-- WHY THIS IS SAFE TO WIDEN AT ALL, which is the question worth asking of any
-- relaxation to an adoption gate: adoption does not merge. It moves a task to
-- READY_FOR_REVIEW, and console/reverify.py then runs the WHOLE contract
-- against the actual merged tree before anything is accepted -- where a green
-- result is required outright and no corroboration is consulted. A wrong
-- corroboration therefore costs a human a review, not a bad merge. If that
-- ordering is ever revisited, this file must be revisited with it.
--
-- WHAT IT DELIBERATELY DOES NOT EXCUSE:
--   * unresolved and undecided checks, which stay unconditional failures --
--     a check that could not run establishes nothing at either end;
--   * a timeout, at either end. A timeout corroborated by a timeout is how a
--     busy box adopts a branch nobody judged;
--   * a check green in the run and failing at the base, which is not a thing
--     this asks about: only a non-zero exit is ever excused;
--   * anything about WHY the two failed. The exit codes match and both tails
--     are recorded for the human who accepts. Equal exit codes are not equal
--     causes, and pytest exits 1 for any failure at all. That gap is the
--     reverify pass's to close, and it does.
--
-- HOW THIS FILE WAS WRITTEN: `pg_get_functiondef` of the running function,
-- with ONE conjunct inserted, one RAISE message extended, and every other line
-- asserted unchanged by the script that produced it. Five migrations now
-- redefine this function. See principles.md, "Rebuild a function body from the
-- live definition".
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

BEGIN;

-- The step type this rule reads. Added to the enumeration rather than left to
-- convention: an evidence type the CHECK constraint rejects is an evidence
-- type that silently cannot be written.
ALTER TABLE run_steps DROP CONSTRAINT run_steps_step_type_check;
ALTER TABLE run_steps ADD CONSTRAINT run_steps_step_type_check
    CHECK (step_type = ANY (ARRAY[
        'EVIDENCE_COLLECTED'::text, 'HYPOTHESIS_RECORDED'::text,
        'PATCH_PROPOSED'::text, 'VERIFICATION_RUN'::text,
        'HUMAN_DECISION'::text, 'DEPLOYED'::text, 'ROLLED_BACK'::text,
        'BASE_CHECK_RUN'::text]));

-- WHO MAY WRITE IT: the console, not the verifier.
--
-- Every other check result in this table is written by fleet_verifier,
-- because every other one is a VERDICT ABOUT A BRANCH and the verifier is the
-- identity that is allowed to reach one. This is not that. It is a
-- measurement of the BASE, taken by console/adopt.py at a human's request,
-- and it decides nothing on its own -- enforce_task_transition() above is
-- what judges it. Handing it to fleet_verifier would mean the console needed
-- the verifier's credentials to ask a question about a commit that is
-- already merged.
INSERT INTO step_authority (step_type, required_role)
VALUES ('BASE_CHECK_RUN', 'fleet_console')
ON CONFLICT (step_type) DO UPDATE SET required_role = EXCLUDED.required_role;

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
                                OR COALESCE((c->>'timed_out')::boolean, false))
                           -- 042: UNLESS THE SAME COMMAND FAILS THE SAME WAY
                           -- ON THE BASE. A check that fails identically
                           -- without the branch applied is not evidence about
                           -- the branch. The evidence is a BASE_CHECK_RUN step
                           -- recorded against the same run by
                           -- console/adopt.py, which re-ran the command in a
                           -- throwaway clone AT THE BASE THIS RUN RECORDED --
                           -- not at whatever the base is now, which is a
                           -- different question and is asked in git.
                           --
                           -- Narrow on purpose. It excuses a check that RAN
                           -- and exited non-zero, and nothing else: unresolved
                           -- and undecided stay unconditional failures above,
                           -- and a timeout is excused by nothing, because a
                           -- timeout corroborated by a timeout is how a busy
                           -- box adopts a branch nobody judged.
                           AND NOT EXISTS (
                               SELECT 1
                                 FROM run_steps b,
                                      jsonb_array_elements(
                                          COALESCE(b.payload->'checks',
                                                   '[]'::jsonb)) bc
                                WHERE b.run_id = s.run_id
                                  AND b.step_type = 'BASE_CHECK_RUN'
                                  AND b.payload->>'base_commit_sha'
                                      = s.payload->>'base_commit_sha'
                                  AND bc->>'command' = c->>'command'
                                  AND bc->>'exit_code' = c->>'exit_code'
                                  AND c->>'exit_code' IS DISTINCT FROM '0'
                                  AND NOT COALESCE(
                                      (c->>'timed_out')::boolean, false)
                                  AND NOT COALESCE(
                                      (bc->>'timed_out')::boolean, false)
                                  AND bc->>'skipped_reason' IS NULL
                                  AND bc->>'unresolved_reason' IS NULL
                                  AND bc->>'undecided_reason' IS NULL)))
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
                'proved nothing about its branch, and that is most of them. '
                'If a check fails on the base too, corroborate it first: '
                'python -m console.adopt --task % --branch <branch> --corroborate-base.',
                OLD.id, OLD.id;
        END IF;
    END IF;

    RETURN NEW;
END; $function$;


-- ----------------------------------------------------------------------------
-- What this file claims, asserted here rather than left to the suite.
DO $$
DECLARE def text;
BEGIN
    SELECT pg_get_functiondef('public.enforce_task_transition'::regproc)
      INTO def;

    IF position('BASE_CHECK_RUN' in def) = 0 THEN
        RAISE EXCEPTION '042: the corroboration clause was not installed';
    END IF;

    -- 040 started from an old copy of a function four migrations had edited
    -- and silently deleted three of their checks. Every earlier rule in this
    -- function is named here so that cannot happen quietly again.
    IF position('may not move' in def) = 0
       OR position('without a branch' in def) = 0
       OR position('without a run' in def) = 0
       OR position('nothing to adopt' in def) = 0 THEN
        RAISE EXCEPTION
            '042: an earlier migration''s check is missing from the function '
            'this file rebuilt. Do not apply it; re-read the live definition.';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM task_transitions
         WHERE from_status = 'FAILED' AND to_status = 'READY_FOR_REVIEW'
           AND required_role = 'fleet_console') THEN
        RAISE EXCEPTION '042: 038''s adoption edge is not where it was left';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM step_authority
         WHERE step_type = 'BASE_CHECK_RUN'
           AND required_role = 'fleet_console') THEN
        RAISE EXCEPTION
            '042: nothing may write BASE_CHECK_RUN, so the evidence this '
            'file judges could never be recorded';
    END IF;

    -- Read rather than probed. A trial INSERT would have to satisfy `sequence`
    -- and `actor` first, and a violation of either would arrive here wearing
    -- this constraint's name.
    IF (SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conname = 'run_steps_step_type_check') NOT LIKE '%BASE_CHECK_RUN%'
    THEN
        RAISE EXCEPTION
            '042: run_steps still rejects BASE_CHECK_RUN as a step type';
    END IF;

    RAISE NOTICE
        '042: a check that fails identically on the base is no longer '
        'evidence against the branch.';
END $$;

COMMIT;
