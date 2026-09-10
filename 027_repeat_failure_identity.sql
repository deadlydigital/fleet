-- ============================================================================
-- 027_repeat_failure_identity.sql  —  the repeat-failure ceiling counts a
--                                     QUANTITY THAT NO LONGER RESETS
--
-- specs/auto-approval.md §9.2, which recorded this as a finding and did not
-- fix it. The first live dry run proved it, and it is a safety-control defect
-- rather than a tuning question: the ceiling could never fire.
--
-- WHAT 022 COUNTED, AND WHY IT COUNTED ZERO
--
-- `candidate_prior_failures(title, repo)` was exact-match on the TITLE, and
-- 022's own header says why it had to be: "Candidates carry no stable key
-- across batches -- deliberately, because a batch two weeks old is a new batch
-- and rows are never updated in place." That is true of the ROW. It is not
-- true of the WORK, and the two were conflated.
--
--     c14  "Coupon and discount performance report"          batch 8, task 23
--                                                            FAILED  -> 1
--     c28  "Coupon and discount performance report, over a
--           column that is already populated"                batch 9  -> 0
--
-- Same row of the same findings document, re-verified eleven days apart and
-- retitled by the producer on the way through. The stop fires at 2. Every one
-- of batch 9's nine candidates scored 0, and the counter restarts at 0 every
-- time the producer runs -- which specs/approval-surface.md §7 REQUIRES it to
-- do, because "a candidate that reappears is a signal" and the producer is
-- forbidden to deduplicate. So this was not a ceiling set too high. It was a
-- ceiling on a quantity that is reset before it can accumulate.
--
-- THE IDENTITY THIS USES, AND WHY IT IS NOT THE TITLE
--
-- A candidate is one ROW OF A FINDINGS DOCUMENT. `candidates.evidence` already
-- carries the document, the sha it was read at, and the section heading the
-- row came from -- required by contracts/checks/candidate_block_shape.py and
-- already mined for `band` by console/load_candidates.band_of(). That triple
-- is a structured, deterministic identity that the producer does not get to
-- rewrite, because it is a citation of somebody else's document rather than
-- prose of its own.
--
-- console/work_key.py resolves it: the section heading, band prefix stripped
-- and slugged, matched against the table rows of the cited document AT THE SHA
-- THE CANDIDATE CITES. Both spellings above resolve to one row --
--
--     coupon-and-discount-performance-usage-discount-total-orders-aov-with-without
--
-- -- and so do the four other repeat pairs in the pool. It is derived in
-- Python and STORED here, not computed in SQL, because resolving it means
-- reading a document out of git and no database function may shell out.
--
-- NULL IS ALLOWED AND MEANS "no key could be derived", never "no repeat".
-- candidate_work_identity() falls back to 022's (title, repo) for such a row,
-- so this migration is never WEAKER than what it replaces -- it is 022 plus
-- the rows 022 could not see.
--
-- WHAT ELSE WAS WRONG: `tasks.status = 'FAILED'` IS NOT AN OUTCOME
--
-- §9.2 measured it and §9.3 explains it. Three of this host's six FAILED tasks
-- failed their acceptance check and three passed it and were recorded FAILED
-- anyway -- task 21, whose draft was promoted at abf4856; task 34, whose block
-- became batch 9; and task 49, whose branch is pushed and verified. A task
-- that fails AFTER verification writes no reason anywhere, so `tasks.status`
-- alone cannot tell an unsuccessful attempt from a successful one recorded
-- badly. The last VERIFICATION_RUN step can, and it is the same evidence §9.2
-- used to establish the miscount.
--
-- The threshold is unchanged at 2 and lives where it always did, in
-- console/approve.py. This migration changes WHAT IS COUNTED, not how many.
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

-- ============================================================ 1. THE KEY

-- ADDITIVE AND APPEND-ONLY IN SPIRIT: a nullable column, written once per row
-- by the loader, and by a one-time backfill that only ever fills NULLs. No
-- candidate row is rewritten to manufacture a count, and no decision_log row
-- is touched by anything here.
ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS work_key text;

DO $$ BEGIN
    ALTER TABLE candidates ADD CONSTRAINT candidates_work_key_nonempty_ck
        CHECK (work_key IS NULL OR length(btrim(work_key)) > 0);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON COLUMN candidates.work_key IS
  'The findings-document row this candidate is, as '
  '<repo>::<document>#<kind>:<slug>, derived by console/work_key.py at load '
  'time from evidence[].document, evidence[].sha and evidence[].section. It '
  'is what makes a repeat visible across batches, candidate ids and retitles: '
  'the producer may not deduplicate and rewrites its titles every run, so the '
  'title is not an identity. NULL means no key could be derived from the '
  'evidence -- candidate_work_identity() then falls back to 022''s '
  '(title, repo), which is never weaker than what it replaced.';

-- Not unique, and it must not be: two candidates with the same key IS the
-- repetition, and the whole point is to be able to count it.
CREATE INDEX IF NOT EXISTS candidates_work_key_idx
    ON candidates (work_key) WHERE work_key IS NOT NULL;

-- ============================================================ 2. IDENTITY

-- One string per candidate, so the count below is an equality join rather than
-- a comparison with rules in it. The fallback is inside this function and not
-- at the call site, because a caller that forgets it counts zero and says
-- nothing -- which is the failure this migration exists to end.
CREATE OR REPLACE FUNCTION candidate_work_identity(p_candidate_id bigint)
RETURNS text
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT coalesce(c.work_key,
                    'title::' || c.repo || '#' || lower(btrim(c.title)))
      FROM candidates c
     WHERE c.id = p_candidate_id;
$$;

COMMENT ON FUNCTION candidate_work_identity(bigint) IS
  'What work this candidate IS, for the repeat-failure ceiling: the stored '
  'work_key, or 022''s (title, repo) when none could be derived. Two '
  'candidates with the same value are the same underlying work regardless of '
  'batch, candidate id or title.';

-- ============================================================ 3. OUTCOME

-- The verdict of the acceptance check the task was contracted against, or NULL
-- if it never reached one. Read from the LAST VERIFICATION_RUN step of the
-- last run, because a reclaimed task can have more than one run and the
-- question is how the final attempt ended.
CREATE OR REPLACE FUNCTION task_verification_result(p_task_id bigint)
RETURNS text
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT s.payload ->> 'result'
      FROM runs r
      JOIN run_steps s ON s.run_id = r.id
     WHERE r.task_id = p_task_id
       AND s.step_type = 'VERIFICATION_RUN'
     ORDER BY r.id DESC, s.sequence DESC
     LIMIT 1;
$$;

COMMENT ON FUNCTION task_verification_result(bigint) IS
  'PASS or FAIL from the last VERIFICATION_RUN on the task''s last run, or '
  'NULL if it never reached verification. specs/auto-approval.md §9.3: a task '
  'that fails after passing its check records nothing else anywhere, so this '
  'is the only structured account of whether the work product met its '
  'contract.';

-- WHAT THE CEILING IS COUNTING, FROZEN IN ONE PREDICATE.
--
--     an unsuccessful attempt is a task in a terminal FAILED state whose
--     acceptance verification did not record PASS
--
-- The two halves are separate facts and this is the line between them:
--
--     task 21  FAILED  verification PASS  draft promoted at abf4856   NOT counted
--     task 34  FAILED  verification PASS  block became batch 9        NOT counted
--     task 49  FAILED  verification PASS  branch pushed, unmerged     NOT counted
--     task 23  FAILED  verification FAIL  draft_spec_shape.py exit 1  COUNTED
--     task 24  FAILED  verification FAIL  draft_spec_shape.py exit 1  COUNTED
--     task 25  FAILED  verification FAIL  draft_spec_shape.py exit 1  COUNTED
--
-- A FAILED task that never reached verification COUNTS. It produced nothing,
-- which is the plainest kind of unsuccessful attempt, and treating a missing
-- verdict as a pass would let a task that died before it was checked buy the
-- next one.
--
-- THE STATE SET IS 022'S, UNCHANGED. Only 'FAILED'. ABANDONED is an operator
-- withdrawing a task rather than an attempt at the work, and REJECTED is a
-- person's review verdict, which is a different judgement with a different
-- ceiling behind it. Widening this set would change how much the stop catches,
-- and this migration is about counting the right ATTEMPTS, not more states.
CREATE OR REPLACE FUNCTION task_was_unsuccessful_attempt(p_task_id bigint)
RETURNS boolean
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT t.status = 'FAILED'
       AND coalesce(task_verification_result(t.id), 'NONE') <> 'PASS'
      FROM tasks t
     WHERE t.id = p_task_id;
$$;

COMMENT ON FUNCTION task_was_unsuccessful_attempt(bigint) IS
  'FAILED, and its acceptance verification did not say PASS. Three of this '
  'host''s six FAILED tasks passed verification and produced accepted '
  'artefacts (21, 34, 49); counting those would be the ceiling over-counting '
  'while it under-counts real repeats. A FAILED task that never reached '
  'verification counts: it produced nothing.';

-- ============================================================ 4. THE COUNT

-- 022's function keyed on (title, repo) and is REPLACED rather than left
-- beside this one. Two functions answering "how many times has this failed"
-- is the drift console/load_candidates.py's header refuses for the probe
-- vocabulary, and the losing answer here is a ceiling that silently reads 0.
DROP FUNCTION IF EXISTS candidate_prior_failures(text, text);

CREATE OR REPLACE FUNCTION candidate_prior_failures(p_candidate_id bigint)
RETURNS int
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT count(DISTINCT t.id)::int
      FROM candidates c
      JOIN tasks t
        ON t.id = c.spec_task_id OR t.id = c.work_task_id
     WHERE candidate_work_identity(c.id)
         = candidate_work_identity(p_candidate_id)
       AND task_was_unsuccessful_attempt(t.id);
$$;

COMMENT ON FUNCTION candidate_prior_failures(bigint) IS
  'How many unsuccessful attempts materially the same work has already had, '
  'across every batch, candidate id and retitle. DISTINCT on the task, so one '
  'task reachable from two candidates counts once and a candidate refused by '
  'the dedupe gate cannot double it. Both task columns count: a spec task '
  'failing means the spec could not be written and a work task failing means '
  'it could not be built, and either is a failure of this work. Two is where '
  'a repeat stops being bad luck -- console/approve.py.REPEAT_FAILURE_STOP.';

-- ============================================================ 5. GRANTS
--
-- fleet_console_reader gains nothing it did not have: 004 already grants it
-- SELECT on runs and run_steps and 013 on candidates, and these functions are
-- SECURITY INVOKER, so they read exactly what the caller could read anyway.
-- Named explicitly because console/autoapprove.plan() now calls
-- candidate_prior_failures on the READ-ONLY connection -- the dry run has to
-- evaluate the same predicate the real run enforces, or it is a second
-- implementation that agrees with it only until somebody edits one.
GRANT EXECUTE ON FUNCTION candidate_work_identity(bigint)
    TO fleet_console, fleet_console_reader;
GRANT EXECUTE ON FUNCTION task_verification_result(bigint)
    TO fleet_console, fleet_console_reader;
GRANT EXECUTE ON FUNCTION task_was_unsuccessful_attempt(bigint)
    TO fleet_console, fleet_console_reader;
GRANT EXECUTE ON FUNCTION candidate_prior_failures(bigint)
    TO fleet_console, fleet_console_reader;
