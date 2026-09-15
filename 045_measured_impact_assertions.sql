\set ON_ERROR_STOP on
-- Assertions for 045_measured_impact.sql.
--
-- Each builds a real candidate row and lets the constraint answer. The theme:
-- a figure that cannot be CHECKED BY A READER is worse than no figure, because
-- nothing downstream re-executes this column. `probes` and `premise` are run
-- against the tree and a stale one fails; a stale millisecond is indis-
-- tinguishable from a fresh one except by the `dataset` and `as_of` this
-- refuses to let a producer omit.
--
-- Rows are inserted and deleted inside the same function, on 030's pattern, so
-- the assertions leave the pool as they found it.

CREATE OR REPLACE FUNCTION pg_temp.q_batch() RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE bid bigint; BEGIN
    SELECT id INTO bid FROM candidate_batches
     WHERE note = '045 assertions: a fixture, not a batch';
    IF bid IS NULL THEN
        INSERT INTO candidate_batches (source_document, source_sha, source_repo,
                                       note)
        VALUES ('research/candidates-dashboard-remaining-2026-09-14.md',
                'c1deb33', 'fleet',
                '045 assertions: a fixture, not a batch')
        RETURNING id INTO bid;
    END IF;
    RETURN bid;
END; $$;

CREATE OR REPLACE FUNCTION pg_temp.q_insert(p_title text, p_impact jsonb)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE cid bigint; BEGIN
    INSERT INTO candidates (batch_id, title, rationale, repo, measured_impact)
    VALUES (pg_temp.q_batch(), p_title, 'a rationale', 'deadly-digital-platform',
            p_impact)
    RETURNING id INTO cid;
    DELETE FROM candidates WHERE id = cid;
END; $$;

-- ---------------------------------------------------------------- Q1
-- c66's real figure, in the shape this column is for. If this row cannot be
-- written, the column does not do the job it was added for.
DO $$ BEGIN
    PERFORM pg_temp.q_insert('Q1', jsonb_build_object(
        'value', 619, 'unit', 'ms',
        'what', 'the top_products statement, per dashboard request',
        'dataset', 'tenant 166, dashboard at a 30-day window, median of three '
                   'warm passes on a quiet box',
        'as_of', '2026-09-14'));
RAISE NOTICE 'Q1 pass  a well-formed figure inserts'; END $$;

-- ---------------------------------------------------------------- Q2
-- No figure at all. Every one of the 23 rows open when this landed is this
-- row, and refusing them would have replaced a ranker that will not choose
-- with a pool holding nothing to choose from. NULL sorts last; it does not
-- gate. See 045's header.
DO $$ BEGIN
    PERFORM pg_temp.q_insert('Q2', NULL);
RAISE NOTICE 'Q2 pass  a row with no figure is unaffected'; END $$;

-- ---------------------------------------------------------------- Q3
-- A number with no dataset. This is the one that matters most. `619 ms` with
-- nothing naming the tenant, the window or the conditions is unfalsifiable,
-- and task 102's requirement 5 states the rule this borrows: an identity claim
-- with no named dataset is the claim task 100 was made to avoid.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q3', jsonb_build_object(
            'value', 619, 'unit', 'ms', 'what', 'top_products',
            'as_of', '2026-09-14'));
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q3 FAIL: a figure with no named dataset was accepted, '
                        'and nothing downstream re-executes this column';
    END IF;
RAISE NOTICE 'Q3 pass  a figure with no named dataset is refused'; END $$;

-- ---------------------------------------------------------------- Q4
-- A number with no date. A figure that cannot be told from a stale one is the
-- standing defect this fleet keeps rediscovering.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q4', jsonb_build_object(
            'value', 619, 'unit', 'ms', 'what', 'top_products',
            'dataset', 'tenant 166 at 30 days'));
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q4 FAIL: an undated figure was accepted';
    END IF;
RAISE NOTICE 'Q4 pass  an undated figure is refused'; END $$;

-- ---------------------------------------------------------------- Q5
-- A date that is not one. `as_of: recently` satisfies a non-empty test and
-- tells a reader nothing, so the form is checked rather than the presence.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q5', jsonb_build_object(
            'value', 619, 'unit', 'ms', 'what', 'top_products',
            'dataset', 'tenant 166 at 30 days', 'as_of', 'recently'));
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q5 FAIL: as_of accepted a value that is not a date';
    END IF;
RAISE NOTICE 'Q5 pass  as_of must be an ISO date'; END $$;

-- ---------------------------------------------------------------- Q6
-- A unit outside the vocabulary. c66's OTHER true figure is 4,546,466 rows
-- scanned, and it is not comparable with c67's 89 ms. A ranker handed both
-- would order them anyway and print a sentence saying it had. Adding a second
-- unit is a migration that has to say how the two compare.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q6', jsonb_build_object(
            'value', 4546466, 'unit', 'rows',
            'what', 'order_items scanned by top_products',
            'dataset', 'tenant 166 at 30 days', 'as_of', '2026-09-14'));
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q6 FAIL: a unit outside the closed vocabulary was '
                        'accepted, so the ranker would compare rows with ms';
    END IF;
RAISE NOTICE 'Q6 pass  the unit vocabulary is closed'; END $$;

-- ---------------------------------------------------------------- Q7
-- Zero. Not a measurement of impact -- a statement that there is none, which
-- is a row that should not have been filed. Refused so it cannot sort ABOVE
-- the NULL rows it is worth less than.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q7', jsonb_build_object(
            'value', 0, 'unit', 'ms', 'what', 'nothing measurable',
            'dataset', 'tenant 166 at 30 days', 'as_of', '2026-09-14'));
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q7 FAIL: a zero figure was accepted';
    END IF;
RAISE NOTICE 'Q7 pass  zero is not an impact'; END $$;

-- ---------------------------------------------------------------- Q8
-- A value that is a string. `"619"` sorts as text and would put 89 above 619.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        PERFORM pg_temp.q_insert('Q8', jsonb_build_object(
            'value', '619', 'unit', 'ms', 'what', 'top_products',
            'dataset', 'tenant 166 at 30 days', 'as_of', '2026-09-14'));
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'Q8 FAIL: a string value was accepted, and "89" sorts '
                        'above "619"';
    END IF;
RAISE NOTICE 'Q8 pass  the value must be a number'; END $$;

-- ---------------------------------------------------------------- Q9
-- The pool is as it was found: the fixture batch holds no rows.
DO $$ DECLARE n int; BEGIN
    SELECT count(*) INTO n FROM candidates
     WHERE batch_id = pg_temp.q_batch();
    IF n <> 0 THEN
        RAISE EXCEPTION 'Q9 FAIL: % assertion row(s) were left behind', n;
    END IF;
RAISE NOTICE 'Q9 pass  the assertions left no rows in the pool'; END $$;
