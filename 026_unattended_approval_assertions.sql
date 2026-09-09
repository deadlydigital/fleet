\set ON_ERROR_STOP on
-- Assertions for 026_unattended_approval.sql.
--
-- Two themes. The record must not be able to exist without its working -- a
-- machine that writes a reason and no mechanics is 010's UNRECORDED problem
-- arriving by a new route. And the 60% stop must actually bite on the
-- unattended path while leaving the 100% ceiling alone for a person, because
-- specs/unattended-operation.md §5.1 set it two weeks ago and nothing built it.

-- ---------------------------------------------------------------- Q1
-- A console decision needs no mechanics. Every row written before this
-- migration is this shape, and they must all still be legal.
DO $$ DECLARE did bigint; BEGIN
    INSERT INTO decision_log (product, subject, decision, reason, decided_by)
    VALUES ('fleet', 'Q1 a person ticked this', 'APPROVED',
            'because a person read it and said so', 'q1')
    RETURNING id INTO did;
    IF (SELECT decided_via FROM decision_log WHERE id = did) <> 'console' THEN
        RAISE EXCEPTION 'Q1 FAIL: decided_via did not default to console';
    END IF;
    DELETE FROM decision_log WHERE id = did;
RAISE NOTICE 'Q1 pass  a console decision defaults correctly and needs no mechanics'; END $$;

-- ---------------------------------------------------------------- Q2
-- THE ONE THAT MATTERS. An unattended decision with no mechanics is refused.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        INSERT INTO decision_log (product, subject, decision, reason,
                                  decided_by, decided_via)
        VALUES ('fleet', 'Q2 nobody watched this', 'APPROVED',
                'Approved 1 of 12 open candidates (rank_v1).', 'dd_console_login',
                'unattended');
    EXCEPTION WHEN check_violation THEN ok := true; END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q2 FAIL: an unattended approval with no mechanics was '
                        'accepted. reason is NOT NULL on every row here, so a '
                        'machine writing prose into it with nothing to check '
                        'the prose against is exactly how 010s UNRECORDED '
                        'problem comes back';
    END IF;
RAISE NOTICE 'Q2 pass  an unattended decision with no mechanics is refused'; END $$;

-- ---------------------------------------------------------------- Q3
-- An EMPTY object is not mechanics. It satisfies "not null" and shows nothing,
-- which is the same defect as ten paraphrases of "yes" in `reason`.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        INSERT INTO decision_log (product, subject, decision, reason,
                                  decided_by, decided_via, mechanics)
        VALUES ('fleet', 'Q3', 'APPROVED', 'a reason', 'dd_console_login',
                'unattended', '{}'::jsonb);
    EXCEPTION WHEN check_violation THEN ok := true; END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q3 FAIL: an empty mechanics object was accepted';
    END IF;
RAISE NOTICE 'Q3 pass  an empty mechanics object is not mechanics'; END $$;

-- ---------------------------------------------------------------- Q4
-- The shape an auto-approval actually writes.
DO $$ DECLARE did bigint; BEGIN
    INSERT INTO decision_log (product, subject, decision, reason, decided_by,
                              decided_via, mechanics)
    VALUES ('fleet', 'Q4 approve 1 candidate', 'APPROVED',
            'Candidate 20 is the highest of the three whose probes show the API '
            'already returns the value and the frontend drops it.',
            'dd_console_login', 'unattended',
            jsonb_build_object(
                'rank_version', 1,
                'platform_sha', '6fd8ddd',
                'probes', jsonb_build_object('run', 32, 'held', 32),
                'ranked', jsonb_build_array(
                    jsonb_build_object('candidate_id', 20, 'keys',
                                       jsonb_build_array(0, 0, 20))),
                'cut_line', 1,
                'held', jsonb_build_array(
                    jsonb_build_object('candidate_id', 21, 'rule', 'path_overlap')),
                'credit', jsonb_build_object('pool', 158.00, 'committed', 18.91)))
    RETURNING id INTO did;
    DELETE FROM decision_log WHERE id = did;
RAISE NOTICE 'Q4 pass  a full unattended record inserts'; END $$;

-- ---------------------------------------------------------------- Q5
-- mechanics is an OBJECT. An array is what a caller produces when it stores
-- the ranked list alone and drops everything that explains it.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        INSERT INTO decision_log (product, subject, decision, reason,
                                  decided_by, decided_via, mechanics)
        VALUES ('fleet', 'Q5', 'APPROVED', 'a reason', 'dd_console_login',
                'unattended', '[1,2,3]'::jsonb);
    EXCEPTION WHEN check_violation THEN ok := true; END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q5 FAIL: a mechanics array was accepted';
    END IF;
RAISE NOTICE 'Q5 pass  mechanics must be an object'; END $$;

-- ---------------------------------------------------------------- Q6
-- decided_via has a closed vocabulary, and it is decide.py's.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        INSERT INTO decision_log (product, subject, decision, reason,
                                  decided_by, decided_via, mechanics)
        VALUES ('fleet', 'Q6', 'APPROVED', 'a reason', 'x', 'auto',
                '{"rank_version": 1}'::jsonb);
    EXCEPTION WHEN check_violation THEN ok := true; END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q6 FAIL: decided_via ''auto'' was accepted. A reader '
                        'who sees ''auto'' asks which automation; the word is '
                        '''unattended'' in both tables that carry it';
    END IF;
RAISE NOTICE 'Q6 pass  decided_via refuses a word outside the vocabulary'; END $$;

-- ---------------------------------------------------------------- Q7
-- 010's sentinel rule survives: UNRECORDED is for backfilled rows only, and
-- nothing added here lets a live row claim it.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        INSERT INTO decision_log (product, subject, decision, reason,
                                  decided_by, decided_via, mechanics)
        VALUES ('fleet', 'Q7', 'APPROVED', 'UNRECORDED', 'dd_console_login',
                'unattended', '{"rank_version": 1}'::jsonb);
    EXCEPTION WHEN check_violation THEN ok := true; END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q7 FAIL: a live unattended row claimed UNRECORDED';
    END IF;
RAISE NOTICE 'Q7 pass  010s UNRECORDED sentinel is still backfill-only'; END $$;

-- ---------------------------------------------------------------- Q8
-- The pace is 1, and it is a function so raising it costs a migration.
DO $$ DECLARE n int; BEGIN
    SELECT fleet_autoapprove_per_night() INTO n;
    IF n <> 1 THEN
        RAISE EXCEPTION 'Q8 FAIL: the pace is %, and specs/unattended-'
                        'operation.md §8 costed 1', n;
    END IF;
RAISE NOTICE 'Q8 pass  the pace is one chain a night'; END $$;

-- ---------------------------------------------------------------- Q9
-- THE 60% STOP EXISTS AND IS BELOW THE 100% CEILING.
--
-- The defect this replaces was not a wrong number, it was an ABSENT one: the
-- spec said 60% and approve.py checked 100%, and nothing compared the two.
DO $$ DECLARE k record; want numeric; BEGIN
    IF NOT EXISTS (SELECT 1 FROM model_credit_pool
                    WHERE period_month = date_trunc('month', now())::date) THEN
        INSERT INTO model_credit_pool (period_month, pool_gbp, source, read_at)
        VALUES (date_trunc('month', now())::date, 158.00,
                '026 assertions: a fixture, not a reading', now());
    END IF;
    SELECT * INTO k FROM fleet_month_credit();
    IF k.status <> 'COMPUTED' THEN
        RAISE EXCEPTION 'Q9 FAIL: the fixture pool did not compute';
    END IF;
    want := (k.pool_gbp * 0.60) - k.committed_gbp;
    IF k.autonomous_remaining_gbp IS DISTINCT FROM want THEN
        RAISE EXCEPTION 'Q9 FAIL: autonomous_remaining_gbp is %, expected %',
                        k.autonomous_remaining_gbp, want;
    END IF;
    IF k.autonomous_remaining_gbp >= k.remaining_gbp THEN
        RAISE EXCEPTION 'Q9 FAIL: the unattended line (%) is not below the '
                        'human ceiling (%). "Leaving £63 for work a person '
                        'chooses" requires the person to have the larger number',
                        k.autonomous_remaining_gbp, k.remaining_gbp;
    END IF;
RAISE NOTICE 'Q9 pass  the 60%% stop exists and sits below the 100%% ceiling'; END $$;

-- ---------------------------------------------------------------- Q10
-- UNCOMPUTED carries NO numbers, and the new column obeys that rule. A caller
-- one coalesce() away from reading "I do not know" as "plenty" is the failure
-- 014 built this shape to prevent, and an appended column is exactly where it
-- would come back.
DO $$ DECLARE k record; m date := date_trunc('month', now())::date;
             saved model_credit_pool; BEGIN
    SELECT * INTO saved FROM model_credit_pool WHERE period_month = m;
    DELETE FROM model_credit_pool WHERE period_month = m;

    SELECT * INTO k FROM fleet_month_credit();
    IF k.status <> 'UNCOMPUTED' THEN
        RAISE EXCEPTION 'Q10 FAIL: expected UNCOMPUTED with no pool row';
    END IF;
    IF k.autonomous_remaining_gbp IS NOT NULL THEN
        RAISE EXCEPTION 'Q10 FAIL: autonomous_remaining_gbp is % on an '
                        'UNCOMPUTED row; it must be NULL, never 0',
                        k.autonomous_remaining_gbp;
    END IF;

    IF saved.period_month IS NOT NULL THEN
        INSERT INTO model_credit_pool
        SELECT saved.*;
    END IF;
RAISE NOTICE 'Q10 pass  an UNCOMPUTED position states no autonomous figure'; END $$;

-- ---------------------------------------------------------------- Q11
-- 014's credit ceiling still fires. fleet_month_credit() was DROPped and
-- recreated in this migration, and enforce_credit_ceiling() calls it -- so this
-- asserts the trigger survived a change to the function underneath it rather
-- than being silently left pointing at nothing.
DO $$ DECLARE ok bool := false; m date := date_trunc('month', now())::date;
             saved model_credit_pool; BEGIN
    SELECT * INTO saved FROM model_credit_pool WHERE period_month = m;
    DELETE FROM model_credit_pool WHERE period_month = m;
    INSERT INTO model_credit_pool (period_month, pool_gbp, source, read_at)
    VALUES (m, 0.01, '026 assertions: a fixture, not a reading', now());

    BEGIN
        INSERT INTO tasks (title, spec_md, repo, base_branch,
                           acceptance_contract, max_cost_gbp, timeout_seconds)
        VALUES ('Q11', 'x', 'fleet', 'master',
                jsonb_build_object(
                    'work_type','draft_spec',
                    'writable_paths', jsonb_build_array('drafts/**'),
                    'protected_paths', (SELECT jsonb_agg(glob)
                                          FROM protected_path_floor
                                         WHERE repo = 'fleet')),
                2.00, 600);
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM LIKE '%monthly credit%' THEN ok := true; END IF;
    END;

    DELETE FROM model_credit_pool WHERE period_month = m;
    IF saved.period_month IS NOT NULL THEN
        INSERT INTO model_credit_pool SELECT saved.*;
    END IF;

    IF NOT ok THEN
        RAISE EXCEPTION 'Q11 FAIL: 014s credit ceiling did not fire after '
                        'fleet_month_credit() was recreated';
    END IF;
RAISE NOTICE 'Q11 pass  014s credit ceiling survives the function being replaced'; END $$;
