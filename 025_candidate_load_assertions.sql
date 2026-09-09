\set ON_ERROR_STOP on
-- Assertions for 025_candidate_load.sql.
--
-- Each inserts a real candidate row and lets the constraint answer. The theme
-- of every refusal below is the same one: a HALF-LOADED row must be
-- impossible, because the whole reason this migration exists is that fields
-- the producer emitted were silently dropped at the load and nothing noticed
-- for two batches.

-- A batch to hang the rows off. Its own row is the fixture, not a reading.
CREATE OR REPLACE FUNCTION pg_temp.q_batch() RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE bid bigint; BEGIN
    SELECT id INTO bid FROM candidate_batches
     WHERE note = '025 assertions: a fixture, not a batch';
    IF bid IS NULL THEN
        INSERT INTO candidate_batches (source_document, source_sha, source_repo,
                                       note)
        VALUES ('specs/metorik-gap.md', 'b198634', 'fleet',
                '025 assertions: a fixture, not a batch')
        RETURNING id INTO bid;
    END IF;
    RETURN bid;
END; $$;

CREATE OR REPLACE FUNCTION pg_temp.q_insert(
        p_title text, p_band text, p_signal jsonb, p_probes jsonb)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE cid bigint; BEGIN
    INSERT INTO candidates (batch_id, title, rationale, repo, band, hib_signal,
                            probes)
    VALUES (pg_temp.q_batch(), p_title,
            'a rationale long enough to clear the twelve-word floor the shape '
            'check applies to the block it came from', 'fleet',
            p_band, p_signal, coalesce(p_probes, '[]'::jsonb))
    RETURNING id INTO cid;
    DELETE FROM candidates WHERE id = cid;
END; $$;

-- ---------------------------------------------------------------- Q1
-- The shape batch 9 actually emits, end to end.
DO $$ BEGIN
    PERFORM pg_temp.q_insert(
        'Q1', 'daily',
        jsonb_build_object(
            'value', 'payment_method populated on 2,782,530 of 2,844,177 orders',
            'as_of', '2026-08-28',
            'source', 'specs/metorik-gap.md'),
        jsonb_build_array(
            jsonb_build_object('path_exists', 'api/analytics/routes/orders.py'),
            jsonb_build_object('grep_count', jsonb_build_object(
                'glob', 'platform/app/api/analytics/orders/route.ts',
                'pattern', 'payment_method', 'expected', 0))));
RAISE NOTICE 'Q1 pass  a fully loaded candidate inserts'; END $$;

-- ---------------------------------------------------------------- Q2
-- NULL band, NULL signal, no probes: EXACTLY the row a hand-load produces, and
-- it must stay insertable. Candidates 12 through 28 are this shape and this
-- table is the record of how they arrived. The rule that stops one of these
-- being auto-approved is a gate in console/rank.py, not a constraint here --
-- a constraint would make the history unrepresentable.
DO $$ BEGIN
    PERFORM pg_temp.q_insert('Q2', NULL, NULL, NULL);
RAISE NOTICE 'Q2 pass  a hand-loaded row with none of the three still inserts'; END $$;

-- ---------------------------------------------------------------- Q3
-- A band the vocabulary does not contain. The loader derives this from a free-
-- text heading, so the failure mode is a document that changes its wording --
-- and the answer to that is an error at the load, not a row that ranks wrongly
-- every night afterwards.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q3', 'Daily', NULL, NULL);
    EXCEPTION WHEN check_violation THEN ok := true; END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q3 FAIL: band is case-sensitive by design and '
                        '''Daily'' was accepted; the loader lower-cases, and a '
                        'column that accepts both stores two spellings of one '
                        'fact';
    END IF;
RAISE NOTICE 'Q3 pass  a band outside the vocabulary is refused'; END $$;

-- ---------------------------------------------------------------- Q4
-- The half-signal, and it is the one that matters. A value with no as_of is a
-- population figure of unknown age, and the age is the thing that decides
-- whether it can be leaned on -- which is why candidate_block_shape.py already
-- requires both on the producer side. The column enforces the same pair.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert(
            'Q4', 'daily',
            jsonb_build_object('value', 'refund_total non-zero on 1 of 2,844,177'),
            NULL);
    EXCEPTION WHEN check_violation THEN ok := true; END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q4 FAIL: an hib_signal with no as_of was accepted, '
                        'and an undated population figure reads as a current one';
    END IF;
RAISE NOTICE 'Q4 pass  an hib_signal missing as_of is refused'; END $$;

-- ---------------------------------------------------------------- Q5
-- The other half: an as_of with no value.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert(
            'Q5', 'daily', jsonb_build_object('as_of', '2026-08-28'), NULL);
    EXCEPTION WHEN check_violation THEN ok := true; END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q5 FAIL: an hib_signal with no value was accepted';
    END IF;
RAISE NOTICE 'Q5 pass  an hib_signal missing value is refused'; END $$;

-- ---------------------------------------------------------------- Q6
-- An empty-string value satisfies "the key is present" and states nothing. The
-- constraint btrims, so whitespace is not a signal either.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert(
            'Q6', 'daily',
            jsonb_build_object('value', '   ', 'as_of', '2026-08-28'), NULL);
    EXCEPTION WHEN check_violation THEN ok := true; END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q6 FAIL: a blank hib_signal value was accepted, which '
                        'is a signal that is present and says nothing';
    END IF;
RAISE NOTICE 'Q6 pass  a blank hib_signal value is refused'; END $$;

-- ---------------------------------------------------------------- Q7
-- probes is a LIST of predicates. An object is what a hand-written INSERT
-- produces when somebody stores one probe rather than a list of one, and
-- rank.py iterates it.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert(
            'Q7', 'daily', NULL,
            jsonb_build_object('path_exists', 'api/analytics/routes/orders.py'));
    EXCEPTION WHEN check_violation THEN ok := true; END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q7 FAIL: a probes value that is not an array was accepted';
    END IF;
RAISE NOTICE 'Q7 pass  probes must be an array'; END $$;

-- ---------------------------------------------------------------- Q8
-- probes is NOT NULL with a default, so the rows already in the table got '[]'
-- rather than NULL when this migration ran. rank.py's gate reads `len(probes)`
-- and a NULL here would be a crash on the hand-loaded history.
DO $$ DECLARE n int; BEGIN
    SELECT count(*) INTO n FROM candidates WHERE probes IS NULL;
    IF n > 0 THEN
        RAISE EXCEPTION 'Q8 FAIL: % candidate row(s) have a NULL probes', n;
    END IF;
RAISE NOTICE 'Q8 pass  every existing row has a probes list, empty or otherwise'; END $$;

-- ---------------------------------------------------------------- Q9
-- 013's invariant survives: a candidate still arrives PENDING, and none of the
-- three columns added here is a way around that trigger.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        INSERT INTO candidates (batch_id, title, rationale, repo, band,
                                disposition, decided_at)
        VALUES (pg_temp.q_batch(), 'Q9', 'a rationale long enough to clear the '
                'twelve-word floor the shape check applies', 'fleet', 'daily',
                'APPROVED', now());
    EXCEPTION WHEN raise_exception OR check_violation THEN ok := true; END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q9 FAIL: 013s arrive-PENDING trigger did not survive 025';
    END IF;
RAISE NOTICE 'Q9 pass  a candidate still arrives PENDING'; END $$;

DELETE FROM candidate_batches WHERE note = '025 assertions: a fixture, not a batch';
