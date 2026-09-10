-- ============================================================================
-- 028_hib_signal_coverage.sql  —  the one real discriminator in the pool, as
--                                 a number instead of a sentence
--
-- specs/auto-approval.md §2.2 and §11. 025 stored `hib_signal` as a SENTENCE
-- and refused to parse it, for a reason that is still right:
--
--     "refund_total non-zero on 1 of 2,844,177 orders"
--
-- is the signal on the net-revenue candidate and it is an argument AGAINST
-- building it. A ranker that scored "has a signal" as a positive would rank
-- that candidate UP on the strength of the fact that argues it down. 025 says
-- so, and says what the right second version is: "{metric, populated, total,
-- as_of} in the block, and the shape check enforcing it".
--
-- This is that second version, and it is being built now because the pool
-- proved it is needed. On 10 Sep 2026 the ranker approved nothing: c20 and c21
-- are both frontend-only and both Daily, so no key separated them and §2.3
-- refused. The two nights before that produced an answer only because the
-- overlap gate was hiding c21 and c22 behind queued task 49 -- an unrelated
-- task's queue state was doing the ranker's job by accident.
--
-- Coverage separates that exact pair, decisively, and in the direction a
-- person reached independently: decision_log 23 records that the net-revenue
-- arithmetic is not exercised by live data at all -- "net_revenue therefore
-- equals revenue in every window on every tenant today".
--
--     c20  payment_method   2,782,530 of 2,844,177   97.83%
--     c21  refund_total             1 of 2,844,177    0.0000352%
--
-- THE SENTENCE STAYS. `value` is still required and still printed verbatim in
-- the morning brief, because the numbers cannot carry what the sentence
-- carries and the reader who can judge it is the point. This ADDS a reading;
-- it does not replace one.
--
-- COVERAGE IS A REQUIRED KEY AND MAY BE NULL, which is the third time this
-- table has used that shape and for the third time it is the same argument:
-- "the signal is not a coverage figure" and "nobody considered whether it was"
-- are different facts, and only a required key keeps them apart. `hib_signal`
-- itself is required-and-nullable on that argument, and so is
-- `suggested_paths`. A qualitative signal -- "all seven RFM buckets populated
-- on tenant 2" -- is legitimate and carries `coverage: null`.
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

-- ============================================================ 1. THE FLOOR

--: The ratio below which a coverage figure reads as "the column is empty".
--:
--: MEASURED, NOT PICKED. Every population figure specs/metorik-gap.md states
--: about HIB's production data, sorted:
--:
--:     refund_total          0.0000352%  (        1 of 2,844,177)
--:     discount_total        5.1348070%  (  146,043 of 2,844,177)
--:     coupon_code           5.1380768%  (  146,136 of 2,844,177)
--:     utm_source           70.6952837%  (2,010,699 of 2,844,177)
--:     payment_method       97.8325189%  (2,782,530 of 2,844,177)
--:     billing_country      99.8543691%  (2,840,035 of 2,844,177)
--:
--: There is one gap in that list and it is four and a half orders of
--: magnitude wide. 1% sits inside it with 1,459x of margin below the nearest
--: real figure and 5.1x above the next one, so every threshold in
--: (0.0000352%, 5.13%) sorts this pool identically and the choice of 1% cannot
--: be what makes the ranking come out one way rather than another.
--:
--: That is the whole claim. It is NOT a claim that 1% is where a column stops
--: being worth reporting on in general -- nobody has measured that, and the
--: honest answer is that it depends on the report. In the database with the
--: other ceilings on 013's precedent: a number that can be changed without a
--: migration will be changed on the morning something needs it to be
--: different.
CREATE OR REPLACE FUNCTION fleet_hib_coverage_floor() RETURNS numeric
LANGUAGE sql IMMUTABLE AS $$ SELECT 0.01::numeric $$;

COMMENT ON FUNCTION fleet_hib_coverage_floor() IS
  'specs/auto-approval.md §11. Below this ratio a coverage figure is read as '
  '"the column is effectively empty", and a report over an empty column is '
  'not a feature -- specs/metorik-gap.md says so in its own words. Chosen '
  'inside a 1,459x gap in the real figures, so the exact value does not '
  'decide the order. Raising it is a migration, deliberately.';

-- ============================================================ 2. THE SHAPE

-- 025's constraint required `value` and `as_of` and permitted any other key,
-- so a `coverage` object could already be stored -- unvalidated. That is the
-- half-a-fact failure 025's own header names: "this constraint stops a HALF of
-- one being stored, because a signal whose age is unknown is the thing that
-- cannot be leaned on". A numerator with no denominator is the same defect,
-- and it is exactly what the source document writes:
--
--     "coupon_code populated on 146,136 orders"     <- of how many?
--
-- So: populated and total are BOTH present or BOTH absent, total is positive,
-- populated cannot exceed it, and the metric names what was counted. A
-- coverage object that cannot answer "of how many" is not a coverage figure.
DO $$ BEGIN
    ALTER TABLE candidates DROP CONSTRAINT candidates_hib_signal_shape_ck;
EXCEPTION WHEN undefined_object THEN NULL; END $$;

ALTER TABLE candidates ADD CONSTRAINT candidates_hib_signal_shape_ck CHECK (
    hib_signal IS NULL
    OR (jsonb_typeof(hib_signal) = 'object'
        AND nullif(btrim(hib_signal ->> 'value'), '') IS NOT NULL
        AND nullif(btrim(hib_signal ->> 'as_of'), '') IS NOT NULL
        AND (
            hib_signal -> 'coverage' IS NULL
            OR jsonb_typeof(hib_signal -> 'coverage') = 'null'
            OR (jsonb_typeof(hib_signal -> 'coverage') = 'object'
                AND nullif(btrim(hib_signal -> 'coverage' ->> 'metric'), '')
                    IS NOT NULL
                AND (hib_signal -> 'coverage' -> 'populated') IS NOT NULL
                AND (hib_signal -> 'coverage' -> 'total') IS NOT NULL
                AND jsonb_typeof(hib_signal -> 'coverage' -> 'populated')
                    = 'number'
                AND jsonb_typeof(hib_signal -> 'coverage' -> 'total') = 'number'
                AND (hib_signal -> 'coverage' ->> 'total')::numeric > 0
                AND (hib_signal -> 'coverage' ->> 'populated')::numeric >= 0
                AND (hib_signal -> 'coverage' ->> 'populated')::numeric
                    <= (hib_signal -> 'coverage' ->> 'total')::numeric))));

COMMENT ON COLUMN candidates.hib_signal IS
  'The figure from HIB''s own data, verbatim in `value`, plus an OPTIONAL '
  '`coverage` object {metric, populated, total} carrying the same fact as two '
  'numbers. The sentence is what the morning brief prints and what a person '
  'judges; the numbers are what specs/auto-approval.md §2.2 key 2 ranks on. '
  'coverage IS NULL means the signal is not a population figure -- "all seven '
  'RFM buckets populated" is a real signal and not a ratio -- which is a '
  'different fact from nobody having considered it, and the shape check '
  'requires the key for that reason. NULL hib_signal still means the source '
  'document declared no figure at all.';

-- ============================================================ 3. READING IT

-- The ratio, or NULL. In SQL as well as in console/rank.py because the console
-- and the brief want to SHOW it and neither should re-derive it from the
-- sentence -- which is the parse 025 refused and this migration exists to make
-- unnecessary.
CREATE OR REPLACE FUNCTION candidate_coverage_ratio(p_candidate_id bigint)
RETURNS numeric
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT (c.hib_signal -> 'coverage' ->> 'populated')::numeric
         / nullif((c.hib_signal -> 'coverage' ->> 'total')::numeric, 0)
      FROM candidates c
     WHERE c.id = p_candidate_id
       AND jsonb_typeof(c.hib_signal -> 'coverage') = 'object';
$$;

COMMENT ON FUNCTION candidate_coverage_ratio(bigint) IS
  'How much of the data this candidate would report on actually exists, or '
  'NULL where the signal is not a population figure. NULL is not zero: '
  '"the document stated no fraction" and "the column is empty" are the two '
  'facts specs/auto-approval.md §2.2 key 2 keeps apart.';

GRANT EXECUTE ON FUNCTION fleet_hib_coverage_floor()
    TO fleet_console, fleet_console_reader;
GRANT EXECUTE ON FUNCTION candidate_coverage_ratio(bigint)
    TO fleet_console, fleet_console_reader;
