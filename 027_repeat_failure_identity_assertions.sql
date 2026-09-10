\set ON_ERROR_STOP on
-- Assertions for 027_repeat_failure_identity.sql.
--
-- Two themes, and they are the two directions the ceiling was wrong in at the
-- same time. It must SEE a repeat that arrives under a new candidate id, in a
-- new batch, under a new title -- because the producer is forbidden to
-- deduplicate and rewrites its titles every run. And it must NOT see one where
-- a task is recorded FAILED and produced an accepted artefact, which is three
-- of this host's six FAILED tasks.
--
-- Run against a built schema:  psql -f 027_repeat_failure_identity_assertions.sql

-- ---------------------------------------------------------------- Q1
-- The column exists, is nullable, and NULL is a legal state. Every candidate
-- row written before this migration has one, and they must all stay legal --
-- 027 falls back to (title, repo) for a NULL rather than counting nothing.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='candidates' AND column_name='work_key'
                      AND is_nullable='YES') THEN
        RAISE EXCEPTION 'Q1 FAIL: candidates.work_key is missing or NOT NULL';
    END IF;
RAISE NOTICE 'Q1 pass  work_key exists and NULL is legal'; END $$;

-- ---------------------------------------------------------------- Q2
-- An empty string is not a key. It would satisfy "not null" and identify
-- everything with everything, which is the same defect as ten paraphrases of
-- "yes" in decision_log.reason.
DO $$ DECLARE ok bool := false; b bigint; BEGIN
    INSERT INTO candidate_batches (source_document, source_sha, source_repo)
    VALUES ('Q2', 'Q2sha', 'fleet') RETURNING id INTO b;
    BEGIN
        INSERT INTO candidates (batch_id, title, rationale, repo, work_key)
        VALUES (b, 'Q2', 'because the finding said so', 'fleet', '   ');
    EXCEPTION WHEN check_violation THEN ok := true; END;
    DELETE FROM candidates WHERE batch_id = b;
    DELETE FROM candidate_batches WHERE id = b;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q2 FAIL: a blank work_key was accepted, and a blank '
                        'key identifies every candidate with every other one';
    END IF;
RAISE NOTICE 'Q2 pass  a blank work_key is refused'; END $$;

-- ---------------------------------------------------------------- Q3
-- 022's signature is GONE rather than left beside this one. Two functions
-- answering "how many times has this failed" is the drift the loader refuses
-- for the probe vocabulary, and here the losing answer silently reads 0.
DO $$ DECLARE n int; args text; BEGIN
    SELECT count(*) INTO n FROM pg_proc WHERE proname = 'candidate_prior_failures';
    IF n <> 1 THEN
        RAISE EXCEPTION 'Q3 FAIL: % candidate_prior_failures function(s) exist; '
                        'exactly one may, and the two-argument one counted a '
                        'title', n;
    END IF;
    SELECT pg_get_function_identity_arguments(oid) INTO args
      FROM pg_proc WHERE proname = 'candidate_prior_failures';
    IF args <> 'p_candidate_id bigint' THEN
        RAISE EXCEPTION 'Q3 FAIL: candidate_prior_failures takes (%), not a '
                        'candidate id', args;
    END IF;
RAISE NOTICE 'Q3 pass  one candidate_prior_failures, keyed on the candidate'; END $$;

-- ---------------------------------------------------------------- helper
-- A contract that satisfies 003's protected-path floor, BUILT FROM THE FLOOR
-- rather than typed. A literal here would go stale the first time a path is
-- floored, and these assertions would then start skipping instead of failing
-- -- which is the silent-pass shape the whole file exists to refuse.
CREATE OR REPLACE FUNCTION pg_temp.q_contract() RETURNS jsonb
LANGUAGE sql STABLE AS $$
    SELECT jsonb_build_object(
        'work_type', 'draft_spec',
        'writable_paths', jsonb_build_array('drafts/**'),
        'protected_paths', coalesce(
            (SELECT jsonb_agg(glob ORDER BY glob) FROM protected_path_floor
              WHERE repo = 'fleet'), '[]'::jsonb),
        'verification', jsonb_build_array('true'),
        'max_diff_lines', 400);
$$;

-- ---------------------------------------------------------------- Q4
-- THE ONE THAT MATTERS. Two candidates, two batches, two titles, one work key:
-- the earlier failure is counted against the later row. This is c14 and c28.
DO $$
DECLARE b1 bigint; b2 bigint; c1 bigint; c2 bigint; t bigint; r bigint; n int;
        key text := 'deadly-digital-platform::fleet/Q4.md#row:coupon-and-discount';
BEGIN
    INSERT INTO candidate_batches (source_document, source_sha, source_repo)
    VALUES ('Q4a', 'sha-a', 'fleet') RETURNING id INTO b1;
    INSERT INTO candidate_batches (source_document, source_sha, source_repo)
    VALUES ('Q4b', 'sha-b', 'fleet') RETURNING id INTO b2;

    INSERT INTO tasks (title, spec_md, repo, acceptance_contract, max_cost_gbp,
                       status)
    VALUES ('Q4 draft spec', 'spec', 'fleet', pg_temp.q_contract(), 2.00,
            'FAILED')
    RETURNING id INTO t;
    INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp,
                      status)
    VALUES (t, 'draft_spec', 1, 2.00, 'FAILED') RETURNING id INTO r;
    INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)
    VALUES (r, 1, 'VERIFICATION_RUN', 'fleet-runner/verifier',
            '{"result":"FAIL"}'::jsonb);

    INSERT INTO candidates (batch_id, title, rationale, repo, work_key)
    VALUES (b1, 'Coupon and discount performance report',
            'because the finding said so', 'deadly-digital-platform', key)
    RETURNING id INTO c1;
    UPDATE candidates SET spec_task_id = t WHERE id = c1;

    INSERT INTO candidates (batch_id, title, rationale, repo, work_key)
    VALUES (b2, 'Coupon and discount performance report, over a column that '
                'is already populated',
            'because the finding said so', 'deadly-digital-platform', key)
    RETURNING id INTO c2;

    n := candidate_prior_failures(c2);
    IF n <> 1 THEN
        RAISE EXCEPTION 'Q4 FAIL: the retitled candidate scores %, not 1. This '
                        'is the defect: a producer that must not deduplicate '
                        'supplies a fresh title every run, and a title-keyed '
                        'counter restarts at 0 before the stop at 2 can be '
                        'reached', n;
    END IF;

    DELETE FROM candidates WHERE id IN (c1, c2);
    DELETE FROM run_steps WHERE run_id = r;
    DELETE FROM runs WHERE id = r;
    DELETE FROM tasks WHERE id = t;
    DELETE FROM candidate_batches WHERE id IN (b1, b2);
RAISE NOTICE 'Q4 pass  a retitled repeat in a new batch is counted'; END $$;

-- ---------------------------------------------------------------- Q5
-- A FAILED task that PASSED its acceptance check is not an unsuccessful
-- attempt. Task 21's draft was promoted at abf4856 and task 34's block became
-- batch 9; both are FAILED rows. Counting them is the ceiling over-counting
-- while it under-counts, which is what §9.2 measured.
DO $$
DECLARE t bigint; r bigint;
BEGIN
    INSERT INTO tasks (title, spec_md, repo, acceptance_contract, max_cost_gbp,
                       status)
    VALUES ('Q5 draft spec', 'spec', 'fleet', pg_temp.q_contract(), 2.00,
            'FAILED')
    RETURNING id INTO t;
    INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp,
                      status)
    VALUES (t, 'draft_spec', 1, 2.00, 'FAILED') RETURNING id INTO r;
    INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)
    VALUES (r, 1, 'PATCH_PROPOSED', 'fleet-runner/agent',
            jsonb_build_object('patch_commit_sha', repeat('b', 40)));
    INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)
    VALUES (r, 2, 'VERIFICATION_RUN', 'fleet-runner/verifier',
            jsonb_build_object('result', 'PASS', 'boundary_clean', true,
                               'base_commit_sha', repeat('a', 40),
                               'patch_commit_sha', repeat('b', 40),
                               'suite_commit_sha', repeat('s', 40),
                               'contract_version', 1));

    IF task_verification_result(t) <> 'PASS' THEN
        RAISE EXCEPTION 'Q5 FAIL: the last VERIFICATION_RUN said PASS and '
                        'task_verification_result reports %',
                        task_verification_result(t);
    END IF;
    IF task_was_unsuccessful_attempt(t) THEN
        RAISE EXCEPTION 'Q5 FAIL: a FAILED task that passed verification was '
                        'counted as an unsuccessful attempt. Three of this '
                        'host''s six FAILED tasks are this shape and produced '
                        'accepted artefacts';
    END IF;

    DELETE FROM run_steps WHERE run_id = r;
    DELETE FROM runs WHERE id = r;
    DELETE FROM tasks WHERE id = t;
RAISE NOTICE 'Q5 pass  FAILED with a passing check is not an unsuccessful attempt'; END $$;

-- ---------------------------------------------------------------- Q6
-- A FAILED task that never reached verification IS one. It produced nothing,
-- and treating a missing verdict as a pass would let a task that died before
-- it was checked buy the next attempt.
DO $$
DECLARE t bigint;
BEGIN
    INSERT INTO tasks (title, spec_md, repo, acceptance_contract, max_cost_gbp,
                       status)
    VALUES ('Q6 draft spec', 'spec', 'fleet', pg_temp.q_contract(), 2.00,
            'FAILED')
    RETURNING id INTO t;
    IF task_verification_result(t) IS NOT NULL THEN
        RAISE EXCEPTION 'Q6 FAIL: a task with no run reported a verdict';
    END IF;
    IF NOT task_was_unsuccessful_attempt(t) THEN
        RAISE EXCEPTION 'Q6 FAIL: a FAILED task that never reached '
                        'verification was not counted; silence is not a pass';
    END IF;
    DELETE FROM tasks WHERE id = t;
RAISE NOTICE 'Q6 pass  a FAILED task with no verdict counts'; END $$;

-- ---------------------------------------------------------------- Q7
-- A NULL work_key falls back to (title, repo) -- 022's behaviour exactly --
-- so deploying this over a table where every row is NULL is never weaker than
-- what it replaces.
DO $$ DECLARE b bigint; c bigint; ident text; BEGIN
    INSERT INTO candidate_batches (source_document, source_sha, source_repo)
    VALUES ('Q7', 'Q7sha', 'fleet') RETURNING id INTO b;
    INSERT INTO candidates (batch_id, title, rationale, repo)
    VALUES (b, '  Q7 Unkeyed Work  ', 'because the finding said so', 'fleet')
    RETURNING id INTO c;
    ident := candidate_work_identity(c);
    IF ident <> 'title::fleet#q7 unkeyed work' THEN
        RAISE EXCEPTION 'Q7 FAIL: an unkeyed candidate identifies as %, which '
                        'is not 022''s (title, repo)', ident;
    END IF;
    DELETE FROM candidates WHERE id = c;
    DELETE FROM candidate_batches WHERE id = b;
RAISE NOTICE 'Q7 pass  a NULL work_key falls back to 022''s (title, repo)'; END $$;

-- ---------------------------------------------------------------- Q8
-- The console's READ-ONLY role can evaluate the ceiling. The dry run runs on
-- that credential, and a dry run that cannot ask the question is how this
-- defect stayed invisible for two batches.
DO $$ BEGIN
    IF NOT has_function_privilege('fleet_console_reader',
                                  'candidate_prior_failures(bigint)', 'EXECUTE')
    THEN
        RAISE EXCEPTION 'Q8 FAIL: the console reader cannot execute '
                        'candidate_prior_failures, so a dry run cannot show '
                        'whether the stop would fire';
    END IF;
RAISE NOTICE 'Q8 pass  the read-only console can evaluate the stop'; END $$;
