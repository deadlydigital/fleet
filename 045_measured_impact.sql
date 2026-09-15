-- ============================================================================
-- 045_measured_impact.sql  —  the figure that says how much the work is worth,
--                             carried on the row instead of in a document
--
-- NOT APPLIED. Apply as `listmonk`, which owns the candidates table.
--
-- ============================================================================
-- WHAT THIS IS FOR
-- ============================================================================
--
-- console/rank.py orders the open pool on four keys and then refuses when none
-- of them separates the top two. That refusal is correct and it has now fired
-- 15 times. Four changes have each moved it rather than removed it:
--
--     5f58a54  the ranker and its refusal            (the pair was c20)
--     ef63f55  coverage as key 2
--     51337b6  supersession is about the work
--     c1deb33  prior failures as key 4               (the pair was c63/c64)
--
-- The last of those landed at about 20:38 on 14 Sep 2026. It separated c63 from
-- c64 -- c64 has one prior failure and dropped below it. The next sweep, at
-- 20:46, refused anyway, now naming c66 and c67. Eight minutes.
--
-- AND THE REASON IS WORSE THAN "THE TIE MOVED", which is how it first read.
-- Key 4 worked. What it revealed is that the tie is not a PAIR. Three rows --
-- c63, c66 and c67 -- carry sort keys [1, 1, 0, 0, id] that differ in nothing
-- but the id:
--
--     c63  Add a CSV export of the product performance report
--     c66  Price an index for top_products, which reads all 4.5M order items
--     c67  The dashboard runs one reconciliation query per manifest
--
-- The sweep refuses wherever the pace puts the cut INSIDE that group, so the
-- pair it names is a function of per_night and not of the pool. 044 took the
-- pace to 2 in the same half hour, which is why the sentence changed from
-- "63 and 64" to "66 and 67"; at a pace of 1 it would have named c63 and c66
-- and refused identically. A fifth key that only ever separated two rows would
-- be the fifth fix to move this rather than end it.
--
-- The three are identical on every column that orders anything: band daily,
-- PENDING, est_cost_gbp NULL, est_diff_lines NULL, no hib_signal coverage,
-- zero prior failures, and all three `modify`.
--
-- AND THEY ARE NOT REMOTELY ALIKE. research/candidates-dashboard-remaining-
-- 2026-09-14.md, the document both rows were loaded from, times them twenty
-- minutes before the load:
--
--                                        30 days     180 days
--     c66  top_products                   619 ms      1,251 ms
--     c67  36 x reconciliation breakdown   89 ms         96 ms
--
-- Seven to one, measured, written down, and invisible to the ranker because
-- the candidate row has nowhere to put it. That is what this column is.
--
-- It separates all three, not just the named pair: c66 at 619 ms, c67 at
-- 89 ms, and c63 -- a CSV export -- carrying no figure and sorting last, which
-- is the whole tied group ordered on what the work is worth.
--
-- ============================================================================
-- IT IS A CLAIM AND NOT A PROBE, AND THAT IS THE IMPORTANT SENTENCE
-- ============================================================================
--
-- `probes` and `premise` are re-executed. contracts/checks/
-- candidate_block_shape.py runs every one of them against the tree at HEAD,
-- and console/rank.py runs the premise again at the sha it is about to spend
-- money against. A candidate whose predicate stopped holding fails.
--
-- NOTHING CAN DO THAT TO A MILLISECOND FIGURE. The probe vocabulary is closed
-- -- path_exists, path_absent, grep_count -- evaluated with pathlib and re,
-- and nothing is shelled out, deliberately, so that a probe cannot become an
-- arbitrary command. A figure like `619 ms at a 30-day window` is not a
-- predicate over a source tree. It is a measurement somebody took on a running
-- system, and re-taking it needs a database, a tenant, a warm cache and a
-- clock. The producer has none of those: contracts/candidate-producer.yaml
-- grants no Bash on purpose.
--
-- So this column has exactly the epistemic standing of a `spec:` citation in
-- contracts/checks/spec_requirements_cited.py, and for the same reason. It
-- establishes THAT A FIGURE WAS STATED, ATTRIBUTABLE, beside a named dataset
-- and a date. It does not establish that the figure is right, that it was
-- measured rather than copied, or that it still holds. It converts a number
-- that lived in a document nobody reads at 01:30 into a number on the row,
-- in the decision record, and in the morning brief -- where a reader who can
-- judge it sees it.
--
-- Everything below is shape. NONE of it is verification, and no reader of this
-- column should take a non-NULL value as one.
--
-- ============================================================================
-- WHY THE UNIT VOCABULARY IS CLOSED, AND WHY IT HAS ONE MEMBER
-- ============================================================================
--
-- A sort key over mixed units is not a sort key. `619 ms` and `4,546,466 rows
-- scanned` are both true of c66 and only one of them can be compared with
-- c67's 89 ms. A producer free to name its own unit would hand the ranker two
-- numbers whose ratio means nothing, and the ranker -- being a ranker -- would
-- order them anyway and print a sentence saying it had.
--
-- `ms` is the only unit this fleet has ever actually measured a candidate in.
-- Every figure in every candidates- document under research/ is a latency in
-- milliseconds. So the vocabulary is closed at one member, which makes adding
-- a second an explicit migration that has to state HOW THE TWO COMPARE, rather
-- than a producer typing a word and a comparison happening silently.
--
-- The cost, stated: work whose value is real and is not a latency cannot state
-- a figure and sorts last among rows it ties with. That is the honest position
-- -- ranking on what is known -- and it is the same one console/rank.py's
-- header already takes about cost and about hib_signal.
--
-- ============================================================================
-- MEASURED NOW. NEVER PROJECTED.
-- ============================================================================
--
-- c67 is the case that makes this a rule rather than a preference. Its figure
-- today is 89 ms. Its ARGUMENT is growth: the loop runs once per manifest with
-- no window bound, the tenant holds 36 manifests, and a two-year store holds
-- about 730 -- so the same code is ~1.8 s on a page that is 1.71 s today. The
-- research document says exactly that, in those words.
--
-- A `measured_impact` that admitted the projection would rank c67 ABOVE c66 on
-- a number nobody has observed, and the producer that wrote it would have been
-- free to choose the horizon that won. console/rank.py already refuses to rank
-- hib_signal for the neighbouring reason -- "two of the four say opposite
-- things about whether the work is worth doing" and "no sort key extracts that
-- from a sentence."
--
-- So: the figure is what the system does now, on a dataset named in the row.
-- The growth argument stays in `rationale`, where a reader judges it, and it
-- is not diminished by being there -- it is the reason c67 gets built at all.
-- This column decides which of two tied rows goes first, not what is worth
-- doing.
--
-- ============================================================================
-- NULL IS A ROW WITH NO FIGURE, AND IT SORTS LAST RATHER THAN BEING REFUSED
-- ============================================================================
--
-- 030 made an absent premise INELIGIBLE, and recorded why it could not wait.
-- This is deliberately the weaker rule, because the populations are different.
-- All 23 rows in the open pool predate this column, and every one of them
-- would become unapprovable the moment it existed -- which would replace a
-- ranker that refuses to choose with a pool that has nothing to choose from.
--
-- NULL therefore means "no figure stated" and sorts below every row that has
-- one. It does not gate. contracts/checks/candidate_block_shape.py requires
-- the KEY on a new block and permits the value to be null, on hib_signal's
-- argument: "the document states no figure" is a fact, and it is not the same
-- fact as a figure that went missing at the load.
--
-- AND IT DOES NOT UNSTICK c66 AND c67. Both predate the column; both will be
-- NULL; both still tie. That pair is being separated by a recorded by_hand
-- decision naming 619 ms against 89 ms, because a backfill would put figures
-- into a batch whose own source document says "Batch 17 carries the
-- single-pass figures and is left as it was loaded -- a batch is the record of
-- what was measured when it was loaded, and there is no path that edits one,
-- correctly." There is no such path enforced in the database; there is only
-- everyone's restraint, and this migration is not the place to spend it.
-- ============================================================================

ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS measured_impact jsonb;

-- A CHECK and not a trigger: the value is ONE object, not an array, so no
-- subquery is needed and 030's reason for reaching for a trigger does not
-- apply. The failure arrives as check_violation, which is what the assertions
-- alongside this file catch.
--
-- `value`  a positive number. Zero is not a measurement of impact, it is a
--          statement that there is none, and such a row should not be filed.
-- `unit`   'ms'. See the header. A second member is a migration.
-- `what`   the statement or request the figure is OF, in words. `619 ms` with
--          nothing attached is not a figure a reader can check.
-- `dataset` the tenant, the window and the conditions. specs' requirement 5 on
--          task 102 put it best: an identity claim with no named dataset is
--          the claim task 100 was made to avoid. Same rule, same reason.
-- `as_of`  ISO date. A figure with no date cannot be told from a stale one,
--          and [[relayed-figures-are-undated]] is the standing lesson here.
DO $$ BEGIN
    ALTER TABLE candidates ADD CONSTRAINT candidates_measured_impact_shape_ck
        CHECK (
            measured_impact IS NULL
            OR (
                jsonb_typeof(measured_impact) = 'object'
                AND jsonb_typeof(measured_impact->'value') = 'number'
                AND (measured_impact->>'value')::numeric > 0
                AND measured_impact->>'unit' = 'ms'
                AND nullif(btrim(measured_impact->>'what'), '') IS NOT NULL
                AND nullif(btrim(measured_impact->>'dataset'), '') IS NOT NULL
                AND measured_impact->>'as_of' ~ '^\d{4}-\d{2}-\d{2}$'
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON COLUMN candidates.measured_impact IS
  'What this work is worth, MEASURED NOW and never projected: '
  '{value, unit, what, dataset, as_of}. console/rank.py reads it as key 5, '
  'below prior failures; NULL means no figure was stated and sorts last '
  'without gating. IT IS A CLAIM, NOT A PROBE -- nothing re-executes it, for '
  'the reason 045 gives at length: the probe vocabulary is a closed set of '
  'predicates over a source tree and a latency is not one. A non-NULL value '
  'establishes that a figure was stated against a named dataset on a stated '
  'date, and establishes nothing else.';
