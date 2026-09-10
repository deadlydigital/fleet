\set ON_ERROR_STOP on
-- Assertions for 028_hib_signal_coverage.sql.
--
-- One theme: a coverage figure is a FRACTION or it is nothing. The failure
-- this guards is the one 025's constraint already guards for {value, as_of} --
-- half a fact stored as if it were whole. The source document writes
-- "coupon_code populated on 146,136 orders" and leaves the denominator two
-- sections away, so the half-stated shape is not hypothetical; it is what the
-- producer would copy.
--
-- Run against a built schema:  psql -f 028_hib_signal_coverage_assertions.sql

-- ---------------------------------------------------------------- helper
CREATE OR REPLACE FUNCTION pg_temp.q_sig(cov jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT jsonb_build_object('value', 'measured', 'as_of', '2026-08-28')
        || CASE WHEN cov IS NULL THEN '{}'::jsonb
                ELSE jsonb_build_object('coverage', cov) END;
$$;

CREATE OR REPLACE FUNCTION pg_temp.q_accepts(cov jsonb) RETURNS boolean
LANGUAGE plpgsql AS $$
DECLARE b bigint; ok boolean := true;
BEGIN
    INSERT INTO candidate_batches (source_document, source_sha, source_repo)
    VALUES ('Q', 'Qsha', 'fleet') RETURNING id INTO b;
    BEGIN
        INSERT INTO candidates (batch_id, title, rationale, repo, hib_signal)
        VALUES (b, 'Q', 'because the finding said so', 'fleet',
                pg_temp.q_sig(cov));
    EXCEPTION WHEN check_violation THEN ok := false; END;
    DELETE FROM candidates WHERE batch_id = b;
    DELETE FROM candidate_batches WHERE id = b;
    RETURN ok;
END $$;

-- ---------------------------------------------------------------- Q1
-- The floor is a measurement, not a preference, and it is where it can be
-- changed by a migration rather than by an afternoon.
DO $$ DECLARE f numeric := fleet_hib_coverage_floor(); BEGIN
    IF f <= 0 OR f >= 1 THEN
        RAISE EXCEPTION 'Q1 FAIL: the coverage floor is %, which is not a '
                        'ratio', f;
    END IF;
    -- It must sit inside the gap the real figures leave: above 1/2,844,177
    -- and below 146,043/2,844,177. Every value in that range sorts the live
    -- pool identically, which is the claim the comment in 028 makes.
    IF f <= 1.0 / 2844177 OR f >= 146043.0 / 2844177 THEN
        RAISE EXCEPTION 'Q1 FAIL: the floor % is outside the measured gap '
                        '(0.0000352%% .. 5.13%%), so the exact value now '
                        'decides the order and 028''s argument no longer '
                        'holds', f;
    END IF;
RAISE NOTICE 'Q1 pass  the coverage floor sits inside the measured gap'; END $$;

-- ---------------------------------------------------------------- Q2
-- No coverage key at all is legal AT THE DATABASE. The producer's check
-- requires it; the loader does not, because batch 9's committed document
-- predates the contract and refusing it would refuse to record what the
-- producer actually wrote.
DO $$ BEGIN
    IF NOT pg_temp.q_accepts(NULL) THEN
        RAISE EXCEPTION 'Q2 FAIL: a signal with no coverage key was refused, '
                        'which would make batch 9''s document unloadable';
    END IF;
RAISE NOTICE 'Q2 pass  an absent coverage key is legal at the database'; END $$;

-- ---------------------------------------------------------------- Q3
-- An explicit null is a real answer: "all seven RFM buckets populated" is a
-- signal and is not a ratio.
DO $$ BEGIN
    IF NOT pg_temp.q_accepts('null'::jsonb) THEN
        RAISE EXCEPTION 'Q3 FAIL: coverage: null was refused, and a signal '
                        'that is not a population figure is still a signal';
    END IF;
RAISE NOTICE 'Q3 pass  coverage: null is a real answer'; END $$;

-- ---------------------------------------------------------------- Q4
-- THE ONE THAT MATTERS. A numerator with no denominator is not a coverage
-- figure -- it is the shape the source document actually writes.
DO $$ BEGIN
    IF pg_temp.q_accepts('{"metric":"coupon_code","populated":146136}'::jsonb)
    THEN
        RAISE EXCEPTION 'Q4 FAIL: "populated on 146,136" was stored with no '
                        'denominator. It answers nothing without "of how '
                        'many", and it is exactly what specs/metorik-gap.md '
                        'writes';
    END IF;
    IF pg_temp.q_accepts('{"metric":"coupon_code","total":2844177}'::jsonb) THEN
        RAISE EXCEPTION 'Q4 FAIL: a denominator with no numerator was stored';
    END IF;
RAISE NOTICE 'Q4 pass  both numbers or neither'; END $$;

-- ---------------------------------------------------------------- Q5
-- A ratio that cannot say what it counted is a number nobody can check.
DO $$ BEGIN
    IF pg_temp.q_accepts('{"populated":1,"total":2844177}'::jsonb) THEN
        RAISE EXCEPTION 'Q5 FAIL: a coverage with no metric was stored';
    END IF;
RAISE NOTICE 'Q5 pass  a coverage names what it counted'; END $$;

-- ---------------------------------------------------------------- Q6
-- Arithmetic that is not a fraction of anything.
DO $$ BEGIN
    IF pg_temp.q_accepts('{"metric":"x","populated":0,"total":0}'::jsonb) THEN
        RAISE EXCEPTION 'Q6 FAIL: a zero denominator was stored, and a '
                        'denominator of zero is not a measurement';
    END IF;
    IF pg_temp.q_accepts('{"metric":"x","populated":9,"total":4}'::jsonb) THEN
        RAISE EXCEPTION 'Q6 FAIL: populated > total was stored';
    END IF;
    IF pg_temp.q_accepts('{"metric":"x","populated":"lots","total":4}'::jsonb)
    THEN
        RAISE EXCEPTION 'Q6 FAIL: a non-numeric numerator was stored';
    END IF;
RAISE NOTICE 'Q6 pass  a coverage is a fraction or it is refused'; END $$;

-- ---------------------------------------------------------------- Q7
-- The two real figures, read back as ratios, on either side of the floor.
DO $$
DECLARE b bigint; c20 bigint; c21 bigint; f numeric := fleet_hib_coverage_floor();
BEGIN
    INSERT INTO candidate_batches (source_document, source_sha, source_repo)
    VALUES ('Q7', 'Q7sha', 'fleet') RETURNING id INTO b;
    INSERT INTO candidates (batch_id, title, rationale, repo, hib_signal)
    VALUES (b, 'Q7 payment method', 'because the finding said so', 'fleet',
            pg_temp.q_sig('{"metric":"payment_method","populated":2782530,'
                          '"total":2844177}'::jsonb))
    RETURNING id INTO c20;
    INSERT INTO candidates (batch_id, title, rationale, repo, hib_signal)
    VALUES (b, 'Q7 refund total', 'because the finding said so', 'fleet',
            pg_temp.q_sig('{"metric":"refund_total","populated":1,'
                          '"total":2844177}'::jsonb))
    RETURNING id INTO c21;

    IF candidate_coverage_ratio(c20) <= f THEN
        RAISE EXCEPTION 'Q7 FAIL: payment_method reads % which is not above '
                        'the floor %', candidate_coverage_ratio(c20), f;
    END IF;
    IF candidate_coverage_ratio(c21) >= f THEN
        RAISE EXCEPTION 'Q7 FAIL: refund_total reads % which is not below the '
                        'floor %', candidate_coverage_ratio(c21), f;
    END IF;

    DELETE FROM candidates WHERE batch_id = b;
    DELETE FROM candidate_batches WHERE id = b;
RAISE NOTICE 'Q7 pass  c20 and c21 land on opposite sides of the floor'; END $$;

-- ---------------------------------------------------------------- Q8
-- NULL is not zero. A row with no coverage returns NULL from the ratio, and a
-- caller that coalesced it to 0 would rank "no figure stated" as "the column
-- is empty" -- which is the distinction the whole key rests on.
DO $$ DECLARE b bigint; c bigint; BEGIN
    INSERT INTO candidate_batches (source_document, source_sha, source_repo)
    VALUES ('Q8', 'Q8sha', 'fleet') RETURNING id INTO b;
    INSERT INTO candidates (batch_id, title, rationale, repo, hib_signal)
    VALUES (b, 'Q8', 'because the finding said so', 'fleet',
            pg_temp.q_sig('null'::jsonb)) RETURNING id INTO c;
    IF candidate_coverage_ratio(c) IS NOT NULL THEN
        RAISE EXCEPTION 'Q8 FAIL: a signal with no coverage reported a ratio '
                        'of %, and NULL is not zero',
                        candidate_coverage_ratio(c);
    END IF;
    DELETE FROM candidates WHERE id = c;
    DELETE FROM candidate_batches WHERE id = b;
RAISE NOTICE 'Q8 pass  no coverage reads as NULL, never as zero'; END $$;
