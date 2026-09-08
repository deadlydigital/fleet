\set ON_ERROR_STOP on
-- Assertions for 014_monthly_credit.sql.
--
-- Every one of these is about the same property from a different side: the
-- ceiling refuses when it cannot read, and refuses when it can read and the
-- answer is no. A ceiling only ever fails by permitting, so permitting is what
-- these try to make it do.

-- L1. THE ONE THAT MATTERS. With no reading for the current month, nothing may
-- be queued at all. Not "assume the pool is large", not "assume zero and let
-- free tasks through" -- refuse, and say which month and where to get it.
BEGIN;
DO $$
DECLARE c jsonb; ok bool := false; msg text;
BEGIN
    SELECT jsonb_build_object(
             'work_type','research', 'writable_paths', jsonb_build_array('research/x.md'),
             'protected_paths', jsonb_agg(glob), 'verification', jsonb_build_array('true'),
             'max_diff_lines', 10)
      INTO c FROM protected_path_floor WHERE repo='fleet';
    DELETE FROM model_credit_pool WHERE period_month = date_trunc('month', now())::date;
    BEGIN
        INSERT INTO tasks (title, spec_md, repo, acceptance_contract, max_cost_gbp)
        VALUES ('L1 no reading', 'x', 'fleet', c, 0.01);
    EXCEPTION WHEN others THEN ok := true; msg := SQLERRM;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'L1 FAIL: a task was queued with no credit reading for '
                        'this month. The ceiling assumed a number it could not '
                        'read, which is the failure 012 section 5 refuses for '
                        'the AWS figure and this file refuses for the pool';
    END IF;
    IF msg NOT LIKE '%credit is unknown%' THEN
        RAISE EXCEPTION 'L1 FAIL: refused, but not for the stated reason: %', msg;
    END IF;
    RAISE NOTICE 'L1 pass  no reading means nothing queues';
END $$;
ROLLBACK;

-- L2. An UNCOMPUTED answer carries a reason and NO numbers. The pool and the
-- remaining figure are NULL rather than 0, because 0 is a number and every
-- comparison against it quietly succeeds.
BEGIN;
DO $$ DECLARE k record; BEGIN
    DELETE FROM model_credit_pool WHERE period_month = date_trunc('month', now())::date;
    SELECT * INTO k FROM fleet_month_credit();
    IF k.status <> 'UNCOMPUTED' THEN
        RAISE EXCEPTION 'L2 FAIL: no reading exists but the answer is %', k.status;
    END IF;
    IF k.pool_gbp IS NOT NULL OR k.remaining_gbp IS NOT NULL THEN
        RAISE EXCEPTION 'L2 FAIL: an UNCOMPUTED position carries figures '
                        '(pool %, remaining %); a caller comparing against '
                        'those gets an answer nobody computed',
                        k.pool_gbp, k.remaining_gbp;
    END IF;
    IF k.uncomputed_reason IS NULL OR length(btrim(k.uncomputed_reason)) = 0 THEN
        RAISE EXCEPTION 'L2 FAIL: UNCOMPUTED with no reason';
    END IF;
    -- committed is still computable and still reported: what is unknown is the
    -- pool, not the spend, and conflating the two would hide a real figure.
    IF k.committed_gbp IS NULL THEN
        RAISE EXCEPTION 'L2 FAIL: committed is derivable and was not reported';
    END IF;
    RAISE NOTICE 'L2 pass  UNCOMPUTED means a reason and no numbers';
END $$;
ROLLBACK;

-- L3. With a reading, a task inside the remaining credit queues and one outside
-- it does not. The boundary, from both sides, in one transaction.
BEGIN;
DO $$
DECLARE c jsonb; k record; ok bool := false; headroom numeric;
BEGIN
    SELECT jsonb_build_object(
             'work_type','research', 'writable_paths', jsonb_build_array('research/x.md'),
             'protected_paths', jsonb_agg(glob), 'verification', jsonb_build_array('true'),
             'max_diff_lines', 10)
      INTO c FROM protected_path_floor WHERE repo='fleet';
    DELETE FROM model_credit_pool WHERE period_month = date_trunc('month', now())::date;
    -- A pool exactly 10.00 above what is already committed, so the arithmetic
    -- below is about this assertion and not about the host's history.
    INSERT INTO model_credit_pool (period_month, pool_gbp, source, read_at)
    VALUES (date_trunc('month', now())::date,
            fleet_month_committed_gbp() + 10.00,
            'L3 assertion, not a real reading', now());

    SELECT * INTO k FROM fleet_month_credit();
    IF k.status <> 'COMPUTED' THEN
        RAISE EXCEPTION 'L3 FAIL: a reading exists and the answer is still %', k.status;
    END IF;
    headroom := k.remaining_gbp;
    IF round(headroom, 2) <> 10.00 THEN
        RAISE EXCEPTION 'L3 FAIL: remaining is % with 10.00 of headroom set up; '
                        'committed is not being measured as this file claims',
                        headroom;
    END IF;

    INSERT INTO tasks (title, spec_md, repo, acceptance_contract, max_cost_gbp)
    VALUES ('L3 inside', 'x', 'fleet', c, 9.00);

    BEGIN
        INSERT INTO tasks (title, spec_md, repo, acceptance_contract, max_cost_gbp)
        VALUES ('L3 outside', 'x', 'fleet', c, 9.00);
    EXCEPTION WHEN others THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'L3 FAIL: two 9.00 tasks queued against 10.00 of '
                        'credit. The first task is not being counted as '
                        'committed, so a batch can outspend the pool one row '
                        'at a time';
    END IF;
    RAISE NOTICE 'L3 pass  the ceiling holds across rows in one transaction';
END $$;
ROLLBACK;

-- L4. A QUEUED task that has never run is counted. This is the window the
-- ceiling exists for: five approved tasks have no model_calls and no
-- reservations, and a pool checked against spend alone would approve five more.
BEGIN;
DO $$
DECLARE c jsonb; before numeric; after numeric;
BEGIN
    SELECT jsonb_build_object(
             'work_type','research', 'writable_paths', jsonb_build_array('research/x.md'),
             'protected_paths', jsonb_agg(glob), 'verification', jsonb_build_array('true'),
             'max_diff_lines', 10)
      INTO c FROM protected_path_floor WHERE repo='fleet';
    DELETE FROM model_credit_pool WHERE period_month = date_trunc('month', now())::date;
    INSERT INTO model_credit_pool (period_month, pool_gbp, source, read_at)
    VALUES (date_trunc('month', now())::date,
            fleet_month_committed_gbp() + 100.00,
            'L4 assertion, not a real reading', now());

    before := fleet_month_committed_gbp();
    INSERT INTO tasks (title, spec_md, repo, acceptance_contract, max_cost_gbp)
    VALUES ('L4 queued', 'x', 'fleet', c, 2.50);
    after := fleet_month_committed_gbp();

    IF round(after - before, 2) <> 2.50 THEN
        RAISE EXCEPTION 'L4 FAIL: queueing a 2.50 task moved committed by %; '
                        'promised money is invisible until it is spent, which '
                        'is exactly too late', round(after - before, 2);
    END IF;
    RAISE NOTICE 'L4 pass  a queued task is committed money';
END $$;
ROLLBACK;

-- L5. The identity that spends may not write the ceiling it spends against.
-- Same rule as a runner that cannot set MERGED and a producer that cannot
-- pre-approve.
DO $$ BEGIN
    IF has_table_privilege('fleet_console', 'model_credit_pool', 'INSERT')
    OR has_table_privilege('fleet_console', 'model_credit_pool', 'UPDATE') THEN
        RAISE EXCEPTION 'L5 FAIL: fleet_console can write model_credit_pool, so '
                        'the ceiling is a number the spending identity sets for '
                        'itself';
    END IF;
    IF NOT has_table_privilege('fleet_console', 'model_credit_pool', 'SELECT') THEN
        RAISE EXCEPTION 'L5 FAIL: fleet_console cannot READ the pool, so the '
                        'surface cannot refuse a batch with a reason';
    END IF;
    IF NOT has_table_privilege('fleet_admin', 'model_credit_pool', 'INSERT') THEN
        RAISE EXCEPTION 'L5 FAIL: no identity can record a reading at all';
    END IF;
    RAISE NOTICE 'L5 pass  reading the pool and writing it are different identities';
END $$;

-- L6. A reading must say where it came from. The pool is the one figure in this
-- system that no process can re-derive, so provenance is the only check there
-- is on it.
BEGIN;
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        INSERT INTO model_credit_pool (period_month, pool_gbp, source, read_at)
        VALUES (date_trunc('month', now())::date + interval '1 month',
                100.00, '   ', now());
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'L6 FAIL: a pool figure was recorded with no source';
    END IF;
    RAISE NOTICE 'L6 pass  a reading names where it was read';
END $$;
ROLLBACK;
