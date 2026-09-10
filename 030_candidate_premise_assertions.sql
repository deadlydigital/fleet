\set ON_ERROR_STOP on
-- Assertions for 030_candidate_premise.sql.
--
-- Each builds a real candidate row and lets the constraint answer. The theme
-- is narrower than 025's: a premise that cannot be READ is worse than no
-- premise, because rank.py would carry it to the approval and find nothing to
-- execute -- and "nothing to execute" reads, in every log line downstream,
-- exactly like "it held".

CREATE OR REPLACE FUNCTION pg_temp.q_batch() RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE bid bigint; BEGIN
    SELECT id INTO bid FROM candidate_batches
     WHERE note = '030 assertions: a fixture, not a batch';
    IF bid IS NULL THEN
        INSERT INTO candidate_batches (source_document, source_sha, source_repo,
                                       note)
        VALUES ('specs/metorik-gap.md', 'b198634', 'fleet',
                '030 assertions: a fixture, not a batch')
        RETURNING id INTO bid;
    END IF;
    RETURN bid;
END; $$;

CREATE OR REPLACE FUNCTION pg_temp.q_insert(p_title text, p_premise jsonb)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE cid bigint; BEGIN
    INSERT INTO candidates (batch_id, title, rationale, repo, premise)
    VALUES (pg_temp.q_batch(), p_title, 'a rationale', 'deadly-digital-platform',
            coalesce(p_premise, '[]'::jsonb))
    RETURNING id INTO cid;
    DELETE FROM candidates WHERE id = cid;
END; $$;

-- ---------------------------------------------------------------- Q1
-- The premise candidate 38 should have carried, and the shape this key is for.
DO $$ BEGIN
    PERFORM pg_temp.q_insert('Q1', jsonb_build_array(jsonb_build_object(
        'claim', 'the order table renders payment_method, billing_country and '
                 'coupon_code as their own columns',
        'probe', jsonb_build_object('grep_count', jsonb_build_object(
            'glob', 'platform/app/(dashboard)/analytics/orders/page.tsx',
            'pattern', 'key: ''payment_method''', 'expected', 1)))));
RAISE NOTICE 'Q1 pass  a well-formed premise inserts'; END $$;

-- ---------------------------------------------------------------- Q2
-- A row with no premise at all still loads. Candidates 12-41 predate this key
-- and this table is the record of what was emitted, not of what the rule
-- became. What refuses a NEW block omitting it is candidate_block_shape.py.
DO $$ BEGIN
    PERFORM pg_temp.q_insert('Q2', NULL);
RAISE NOTICE 'Q2 pass  a row with no premise is unaffected'; END $$;

-- ---------------------------------------------------------------- Q3
-- A claim with no probe. This is candidate 38 exactly: the sentence was in the
-- rationale and nothing could re-execute it.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q3', jsonb_build_array(jsonb_build_object(
            'claim', 'the values are on screen and inert')));
    EXCEPTION WHEN raise_exception THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q3 FAIL: a premise with no probe was accepted, which '
                        'is the sentence in the rationale with nothing behind it';
    END IF;
RAISE NOTICE 'Q3 pass  a claim with no probe is refused'; END $$;

-- ---------------------------------------------------------------- Q4
-- A probe with no claim in words. The predicate alone cannot be reviewed: the
-- open question is whether it tests the claim or something adjacent, and that
-- question needs the claim written down.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q4', jsonb_build_array(jsonb_build_object(
            'claim', '   ',
            'probe', jsonb_build_object('path_exists', 'platform/x.tsx'))));
    EXCEPTION WHEN raise_exception THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q4 FAIL: a premise with a blank claim was accepted';
    END IF;
RAISE NOTICE 'Q4 pass  a probe with no claim in words is refused'; END $$;

-- ---------------------------------------------------------------- Q5
-- Two predicates in one entry. run_probe() dispatches on the single key of a
-- probe object; a two-key probe would have one of them executed and the other
-- silently ignored, which is the half-checked premise this key exists to stop.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q5', jsonb_build_array(jsonb_build_object(
            'claim', 'two things at once',
            'probe', jsonb_build_object('path_exists', 'platform/x.tsx',
                                        'path_absent', 'platform/y.tsx'))));
    EXCEPTION WHEN raise_exception THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q5 FAIL: a two-predicate probe was accepted, and one '
                        'of the two would never be run';
    END IF;
RAISE NOTICE 'Q5 pass  a probe carrying two predicates is refused'; END $$;

-- ---------------------------------------------------------------- Q6
-- Not an array. jsonb_array_elements() raises on a scalar, so without the
-- is-array constraint the shape check would fail at INSERT with a type error
-- rather than with a sentence about premises.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q6', '"a sentence"'::jsonb);
    EXCEPTION WHEN raise_exception OR invalid_parameter_value
                 OR check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q6 FAIL: a non-array premise was accepted';
    END IF;
RAISE NOTICE 'Q6 pass  a premise that is not an array is refused'; END $$;

-- ---------------------------------------------------------------- Q7
-- 025's probes rule must still hold: this migration adds a column beside it
-- and does not replace anything, so the neighbour is re-asserted rather than
-- assumed.
DO $$ DECLARE ok bool := false; cid bigint; BEGIN
    BEGIN
        INSERT INTO candidates (batch_id, title, rationale, repo, probes)
        VALUES (pg_temp.q_batch(), 'Q7', 'a rationale',
                'deadly-digital-platform', '"not an array"'::jsonb)
        RETURNING id INTO cid;
        DELETE FROM candidates WHERE id = cid;
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q7 FAIL: 025s probes-is-array rule did not survive 030';
    END IF;
RAISE NOTICE 'Q7 pass  025s probes rule is untouched'; END $$;
