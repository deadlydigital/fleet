-- ============================================================================
-- 046_an_unmet_obligation_is_not_a_broken_tree.sql
--
-- NOT APPLIED. Apply as `listmonk`, which owns enforce_task_transition().
--
-- 042 landed on 14 Sep 2026 and said: a check that fails IDENTICALLY on the
-- base is not evidence about the branch. It was right, and task 100 is the
-- case -- a hand-maintained migration tally that a commit on the base had
-- moved by one, on a branch that touched no migration and no test.
--
-- It matches on the COMMAND and the EXIT CODE, and compares nothing else.
-- console/adopt._corroboration_for() does the same, deliberately, because the
-- two must agree.
--
-- ============================================================================
-- WHAT THAT LET THROUGH, MEASURED THE FOLLOWING DAY
-- ============================================================================
--
-- contracts/checks/spec_requirements_cited.py reads `git diff BASE..HEAD` and
-- refuses a change that cites no requirement. corroborate() re-runs a failing
-- check in a clone AT THE BASE, with FLEET_BASE_SHA and FLEET_HEAD_SHA set to
-- the same commit. The diff is therefore EMPTY, nothing is cited, and it
-- fails -- every time, for every branch, whatever the branch did. Run against
-- the real task 102 spec at the real base it printed:
--
--     FAIL: 8 of 8 numbered requirement(s) are cited nowhere in this change.
--     EXIT=1
--
-- Branch side 1, base side 1, same command. Excused. Fed through
-- _verification_is_green with task 102's actual recorded payload, the branch
-- reads GREEN and adoptable.
--
-- THAT IS THE ONE CHECK THAT CAUGHT TASK 102. Five checks green over a
-- 530-line diff, including a 15.4-minute analytics suite, and this the only
-- thing in the path that noticed the branch had not proved the identity claim
-- its spec was written around. The rule built to rescue task 100 punched a
-- hole in it two days later.
--
-- ============================================================================
-- WHY NOT COMPARE THE OUTPUT
-- ============================================================================
--
-- The obvious fix, and it is wrong. Task 100s excused check printed
-- `FAIL: 1 of 43 files in tests/analytics failed` on the branch and
-- `1 of 42` at the base -- the branch had added a test file. The tails differ
-- by a factor of three in length. Requiring them to match would refuse the one
-- case this feature exists for, and no looser textual comparison is a rule
-- anybody could reason about later.
--
-- ============================================================================
-- THE DISCRIMINATOR IS A THIRD THING A REFUSAL CAN MEAN
-- ============================================================================
--
-- Until now a check said one of three things: it passed, the tree is wrong, or
-- nothing is known (unresolved, undecided). runner/verify.py adds the fourth,
-- as exit code 3:
--
--     THE BRANCH OWES AN OBLIGATION. The check ran, it has no complaint about
--     the tree, and something the branch was required to state is not there.
--
-- It still refuses -- verify.Check.passed is False, so nothing merges
-- unattended on an uncited requirement, and this trigger still counts it
-- against the branch through the ordinary non-zero clause. What it adds is
-- that the refusal can SAY WHAT IT IS ABOUT, and that this migration can name
-- the class that must never be corroborated.
--
-- An obligation is owed BY THE BRANCH. The base has no branch. So a base run
-- of such a check answers a question nobody asked, and answers it the same way
-- every time -- which is the definition of an excuse rather than evidence.
--
-- ============================================================================
-- WHAT THIS FILE CHANGES, AND IT IS FOUR LINES
-- ============================================================================
--
-- Two conditions inside 042's corroboration sub-clause: neither the branch
-- side nor the base side of a corroboration may carry `obligation_reason`.
-- Everything else in enforce_task_transition() is 042's text UNCHANGED --
-- this file was built by reading the LIVE function definition out of the
-- database and editing that, not by copying 042, for the reason 042 itself
-- records: 040 started from an old copy of a function four migrations had
-- edited and silently deleted three of their checks.
--
-- The assertions below name every earlier rule again, 042's list plus this
-- one, so the next rebuild cannot quietly drop any of them either.
--
-- ============================================================================
-- WHAT IT DELIBERATELY DOES NOT DO
-- ============================================================================
--
-- It does not create a path by which a person may adopt or merge a branch with
-- an outstanding obligation. That was proposed and is not built, because the
-- remedy for task 102 is not to wave it through: requirements 5 and 6 asked
-- for a measurement on production data, the agent has no shell to take one,
-- and the answer is to take the measurement or to change the spec -- not to
-- merge an unproven identity claim across three analytics endpoints. The
-- classification exists so a person is told THAT, instead of being told
-- "verification failed" about a diff that is fine.
-- ============================================================================

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
                                  AND bc->>'undecided_reason' IS NULL
                                  -- 046: AND NEITHER SIDE IS AN UNMET
                                  -- OBLIGATION. An obligation is owed BY THE
                                  -- BRANCH; the base has no branch and owes
                                  -- nothing, so a base run refuses such a
                                  -- check identically for every branch. That
                                  -- is an excuse, not evidence.
                                  --
                                  -- MEASURED, NOT FEARED. Run at the base on
                                  -- 15 Sep 2026,
                                  -- contracts/checks/spec_requirements_cited.py
                                  -- printed `FAIL: 8 of 8 numbered
                                  -- requirement(s) are cited nowhere` and
                                  -- exited 1 -- matching the branch's 1 and
                                  -- excusing itself, on any branch at all. It
                                  -- was the only check that noticed task 102
                                  -- had not proved its central claim.
                                  --
                                  -- The check now exits 2 there, which the
                                  -- three lines above already refuse. This is
                                  -- the same door from the other side, so a
                                  -- check that forgets the base-run rule is
                                  -- still not excusable on an obligation.
                                  AND bc->>'obligation_reason' IS NULL
                                  AND c->>'obligation_reason' IS NULL)))
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

    IF position('obligation_reason' in def) = 0 THEN
        RAISE EXCEPTION '046: the obligation clause was not installed';
    END IF;

    -- Both sides, not one. Excusing a branch obligation with a base
    -- obligation, or a base obligation excusing anything at all, are two
    -- separate doors and this file closes both.
    IF position('bc->>''obligation_reason'' IS NULL' in def) = 0
       OR position('c->>''obligation_reason'' IS NULL' in def) = 0 THEN
        RAISE EXCEPTION '046: only one side of the obligation rule is present';
    END IF;

    -- 042's list, carried forward verbatim and extended. 040 is why.
    IF position('BASE_CHECK_RUN' in def) = 0 THEN
        RAISE EXCEPTION '046: 042''s corroboration clause is missing from the '
                        'function this file rebuilt';
    END IF;
    IF position('may not move' in def) = 0
       OR position('without a branch' in def) = 0
       OR position('without a run' in def) = 0
       OR position('nothing to adopt' in def) = 0 THEN
        RAISE EXCEPTION
            '046: an earlier migration''s check is missing from the function '
            'this file rebuilt. Do not apply it; re-read the live definition.';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM task_transitions
         WHERE from_status = 'FAILED' AND to_status = 'READY_FOR_REVIEW'
           AND required_role = 'fleet_console') THEN
        RAISE EXCEPTION '046: 038''s adoption edge is not where it was left';
    END IF;

    RAISE NOTICE '046 ok  an unmet obligation cannot be corroborated, on '
                 'either side';
END $$;
