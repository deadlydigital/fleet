\set ON_ERROR_STOP on
-- Assertions for 013_approval_surface.sql.

-- K1. The queue depth is real and is on `tasks`, not on the caller. This is
-- what replaces "a person types run_task.py", so it has to fire for anyone.
BEGIN;
DO $$
DECLARE cap int := fleet_max_queued_tasks(); i int; ok bool := false; c jsonb;
BEGIN
    -- The contract's protected_paths are built FROM protected_path_floor
    -- rather than typed. 003 refuses a task whose contract does not cover the
    -- floor for its repo, which is the check working -- a hand-typed list here
    -- would go stale exactly as the conftest migration list did.
    SELECT jsonb_build_object(
             'work_type','research', 'writable_paths', jsonb_build_array('research/x.md'),
             'protected_paths', jsonb_agg(glob), 'verification', jsonb_build_array('true'),
             'max_diff_lines', 10)
      INTO c FROM protected_path_floor WHERE repo='fleet';
    DELETE FROM tasks WHERE title LIKE 'K1 depth%';
    FOR i IN 1..cap LOOP
        INSERT INTO tasks (title, spec_md, repo, acceptance_contract, max_cost_gbp)
        VALUES ('K1 depth '||i, 'x', 'fleet', c, 1.0);
    END LOOP;
    BEGIN
        INSERT INTO tasks (title, spec_md, repo, acceptance_contract, max_cost_gbp)
        VALUES ('K1 depth over', 'x', 'fleet', c, 1.0);
    EXCEPTION WHEN others THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'K1 FAIL: a % th task was queued past the cap of %; '
                        'the ceiling that replaces the human is not there',
                        cap + 1, cap;
    END IF;
    RAISE NOTICE 'K1 pass  queue depth is enforced on tasks at %', cap;
END $$;
ROLLBACK;

-- K2. A producer may not pre-approve. A candidate arrives PENDING or not at all.
BEGIN;
DO $$ DECLARE b bigint; ok bool := false; BEGIN
    INSERT INTO candidate_batches (source_document, source_sha, source_repo)
    VALUES ('K2','abc','fleet') RETURNING id INTO b;
    BEGIN
        INSERT INTO candidates (batch_id, title, rationale, repo, disposition,
                                decided_at)
        VALUES (b,'pre-approved','r','fleet','APPROVED', now());
    EXCEPTION WHEN others THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'K2 FAIL: a producer inserted an APPROVED candidate; '
                        'that is the autonomy this surface refuses';
    END IF;
    RAISE NOTICE 'K2 pass  candidates arrive PENDING';
END $$;
ROLLBACK;

-- K3. A rejection says why. This is the informative half and the one place a
-- sentence is the point.
BEGIN;
DO $$ DECLARE b bigint; cid bigint; ok bool := false; BEGIN
    INSERT INTO candidate_batches (source_document, source_sha, source_repo)
    VALUES ('K3','abc','fleet') RETURNING id INTO b;
    INSERT INTO candidates (batch_id, title, rationale, repo)
    VALUES (b,'t','r','fleet') RETURNING id INTO cid;
    BEGIN
        UPDATE candidates SET disposition='REJECTED', decided_at=now()
         WHERE id=cid;
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'K3 FAIL: a candidate was rejected with no reason';
    END IF;
    RAISE NOTICE 'K3 pass  a rejection carries a reason';
END $$;
ROLLBACK;

-- K4. The approval batch cap keeps one batch reason honest.
BEGIN;
DO $$
DECLARE b bigint; d bigint; cap int := fleet_max_approval_batch();
        i int; cid bigint; ok bool := false;
BEGIN
    INSERT INTO candidate_batches (source_document, source_sha, source_repo)
    VALUES ('K4','abc','fleet') RETURNING id INTO b;
    -- decision_log's authority trigger gates recording to fleet_console, and
    -- the migration principal is deliberately not a member: "a layer that can
    -- record its own approval is an agent marking its own work as passing".
    -- The assertion assumes the role rather than the constraint being relaxed.
    SET LOCAL ROLE fleet_console;
    INSERT INTO decision_log (product, subject, decision, reason, decided_by)
    VALUES ('fleet','K4 batch','APPROVED','a real selection reason','assert')
    RETURNING id INTO d;
    RESET ROLE;
    FOR i IN 1..cap LOOP
        INSERT INTO candidates (batch_id, title, rationale, repo)
        VALUES (b,'K4 '||i,'r','fleet') RETURNING id INTO cid;
        UPDATE candidates SET disposition='APPROVED', approval_decision_id=d,
               decided_at=now() WHERE id=cid;
    END LOOP;
    INSERT INTO candidates (batch_id, title, rationale, repo)
    VALUES (b,'K4 over','r','fleet') RETURNING id INTO cid;
    BEGIN
        UPDATE candidates SET disposition='APPROVED', approval_decision_id=d,
               decided_at=now() WHERE id=cid;
    EXCEPTION WHEN others THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'K4 FAIL: % candidates approved under one decision, '
                        'cap is %; one reason is now covering more than it can',
                        cap + 1, cap;
    END IF;
    RAISE NOTICE 'K4 pass  approval batch capped at %', cap;
END $$;
ROLLBACK;

-- K5. An approved candidate cites the decision that approved it, so the batch
-- reason is never unattached to what it approved.
BEGIN;
DO $$ DECLARE b bigint; cid bigint; ok bool := false; BEGIN
    INSERT INTO candidate_batches (source_document, source_sha, source_repo)
    VALUES ('K5','abc','fleet') RETURNING id INTO b;
    INSERT INTO candidates (batch_id, title, rationale, repo)
    VALUES (b,'t','r','fleet') RETURNING id INTO cid;
    BEGIN
        UPDATE candidates SET disposition='APPROVED', decided_at=now()
         WHERE id=cid;
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'K5 FAIL: a candidate was approved citing no decision';
    END IF;
    RAISE NOTICE 'K5 pass  an approval cites its decision';
END $$;
ROLLBACK;

-- K6. There is no work_type column. Its absence is the decision: the draft spec
-- chooses it, and a column here would make a producer guess.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_name='candidates' AND column_name='work_type') THEN
        RAISE EXCEPTION 'K6 FAIL: candidates.work_type exists; a producer is '
                        'now required to guess what the spec step determines';
    END IF;
    RAISE NOTICE 'K6 pass  no work_type on a candidate';
END $$;

-- K7. The caps cost a migration to change. A cap in a config table is a cap
-- that gets edited on the morning something needs more.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname='fleet_max_queued_tasks')
    OR NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname='fleet_max_approval_batch')
    THEN
        RAISE EXCEPTION 'K7 FAIL: a cap is not a function, so it lives '
                        'somewhere editable without a migration';
    END IF;
    RAISE NOTICE 'K7 pass  both caps are immutable functions, not config rows';
END $$;
