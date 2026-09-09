-- ============================================================================
-- 025_candidate_load.sql  —  the three fields the producer emits and the
--                            database has never held
--
-- Spec: specs/auto-approval.md §2.1, approved 9 Sep 2026.
--
-- WHAT IS BROKEN, AND IT IS NOT THE PRODUCER
--
-- contracts/checks/candidate_block_shape.py REQUIRES `hib_signal` on every
-- candidate and re-executes every `probes:` predicate against the tree before
-- a producer task may pass. The producer emits all three of these fields and
-- has done since batch 8. `candidate_batches.note` on batch 9 says what then
-- happens to them:
--
--     "Loaded by hand: there is no loader, and batch 8 was loaded the same
--      way."
--
-- A person retypes the title, the rationale and the paths into an INSERT, and
-- the band, the signal and the probes are dropped on the floor because there
-- is nowhere to put them. The loss is at the LOAD. This file makes the
-- somewhere, and console/load_candidates.py stops the retyping.
--
-- WHY THIS IS THE FIRST STEP OF AUTO-APPROVAL AND NOT A TIDY-UP
--
-- §2.2's ranking has four inputs. Two of them -- the probes and the signal --
-- do not reach the database at all today, and a third (the band) reaches it
-- only as a free-text prefix inside `evidence[].section`. A ranker built on
-- that is a ranker built on a string parse run every night, in the place that
-- cannot refuse a row. So the columns come first and the ranking comes after
-- them.
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

-- ============================================================ 1. band

-- DERIVED AT LOAD, STORED, AND NOT PARSED AT APPROVAL TIME.
--
-- The gap document groups its rows under headings that begin with a frequency
-- word -- "Daily — Order filtering: ...", "Rarely — Cross-store roll-up" -- and
-- the producer copies the heading verbatim into `evidence[].section`. That word
-- is the only statement anywhere of how often an agency would open the thing.
--
-- Parsing a free-text prefix is a thing to do ONCE, at the load, in the code
-- that is allowed to refuse the row -- not every night in the ranker, where a
-- heading that changes shape produces a silently unranked batch instead of an
-- error.
--
-- NULL IS ALLOWED AND MEANS "the section named no band". It is not "we could
-- not tell": contracts/checks/candidate_block_shape.py does not require the
-- section to start with a band, so a producer that legally omits one must
-- produce a row, and §2.2 sorts a NULL band last rather than gating on it.
-- specs/auto-approval.md §7.4 is the open question of whether the shape check
-- should start requiring it; until it does, this column records a convention,
-- and the loader refuses a section that carries a word it does not recognise
-- rather than storing NULL for it -- an unrecognised prefix is the convention
-- breaking, which is a different fact from a heading with no prefix at all.
ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS band text;

DO $$ BEGIN
    ALTER TABLE candidates ADD CONSTRAINT candidates_band_vocabulary_ck
        CHECK (band IS NULL OR band IN ('daily','weekly','monthly','rarely'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON COLUMN candidates.band IS
  'How often the source document says an agency would use this, lower-cased '
  'from the evidence section heading at LOAD time. NULL means the section '
  'named no band, never that a band was lost. One person''s estimate: nobody '
  'has asked an agency, which is why specs/auto-approval.md ranks it SECOND, '
  'below a re-executed measurement.';

-- ============================================================ 2. hib_signal

-- THE FIGURE FROM HIB'S OWN DATA, VERBATIM, AND DELIBERATELY NOT PARSED.
--
--     {value: "payment_method populated on 2,782,530 of 2,844,177 orders
--              (tenant 2)",
--      as_of: "2026-08-28",
--      source: "specs/metorik-gap.md"}
--
-- `value` is a SENTENCE and this column stores it as one. The temptation is to
-- split it into a numerator and a denominator so something can sort on it, and
-- §2.2 refuses that here for a reason worth keeping next to the column:
--
--     "refund_total non-zero on 1 of 2,844,177 orders"
--
-- is the signal on the net-revenue candidate, and it is an argument AGAINST
-- building it -- a net figure over refunds that were never captured is a
-- confident wrong number. A ranker that scored "has a signal" as a positive
-- would rank that candidate UP on the strength of the fact that argues it down.
-- No sort key gets that out of a sentence. So the signal is stored, carried
-- into the decision record, and PRINTED IN THE MORNING BRIEF beside every
-- approved row, in front of the one reader who can judge it. It does not rank.
--
-- Making it rankable is a producer-contract change -- {metric, populated,
-- total, as_of} in the block, and the shape check enforcing it -- and it is
-- the right second version, not this one.
--
-- NULL MEANS THE SOURCE DOCUMENT DECLARED NO FIGURE. The shape check requires
-- the KEY on every candidate and permits a null value, on the same argument
-- 013 makes for suggested_paths: "the producer did not consider it" and "the
-- producer considered it and found none" are different facts and only a
-- required key keeps them apart. The loader carries that distinction across;
-- this constraint stops a HALF of one being stored, because a signal whose age
-- is unknown is the thing that cannot be leaned on.
ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS hib_signal jsonb;

DO $$ BEGIN
    ALTER TABLE candidates ADD CONSTRAINT candidates_hib_signal_shape_ck
        CHECK (hib_signal IS NULL
               OR (jsonb_typeof(hib_signal) = 'object'
                   AND nullif(btrim(hib_signal ->> 'value'), '') IS NOT NULL
                   AND nullif(btrim(hib_signal ->> 'as_of'), '') IS NOT NULL));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON COLUMN candidates.hib_signal IS
  '{value, as_of, source} from the source document, verbatim. NULL means the '
  'document stated no figure. DISPLAYED, NEVER RANKED: the value is a sentence '
  'and two of them say opposite things about whether the work is worth doing.';

-- ============================================================ 3. probes

-- THE CLAIM, IN A FORM THAT CAN BE RE-EXECUTED.
--
-- The closed vocabulary of contracts/checks/candidate_block_shape.py, stored
-- exactly as emitted:
--
--     [{path_exists: api/analytics/routes/orders.py},
--      {grep_count: {glob: ..., pattern: ..., expected: 0}}]
--
-- The producer re-executed every one of these against the tree before the batch
-- could pass. That established the claim was true AT THE PRODUCER'S SHA -- the
-- rows on batch 9 were verified at platform 4619a76 -- and it says nothing
-- about the tree tonight. platform HEAD moves nightly. Storing the predicates
-- rather than the verdict is what lets the approval path run them AGAIN, at
-- the sha it is actually about to spend money against, which specs/auto-
-- approval.md §2.2 calls the most valuable of its four gates and the cheapest:
-- the code exists, it is pure pathlib and re, and nothing is shelled out.
--
-- DEFAULT '[]' IS FOR THE ROWS ALREADY HERE and it is not a free pass.
-- Candidates 12-28 were loaded by hand and carry no predicates, so they get an
-- empty list -- and an empty list must never satisfy "all probes held", which
-- is a check that cannot fail and is this codebase's recurring defect. The
-- gate in console/rank.py requires at least one probe and treats an empty list
-- as ineligible; the row stays PENDING and a person sees it. Not a NOT NULL
-- CHECK (length > 0) here, because that would make the hand-loaded history
-- unrepresentable and this table is the record of it.
ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS probes jsonb NOT NULL DEFAULT '[]'::jsonb;

DO $$ BEGIN
    ALTER TABLE candidates ADD CONSTRAINT candidates_probes_is_array_ck
        CHECK (jsonb_typeof(probes) = 'array');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

COMMENT ON COLUMN candidates.probes IS
  'The candidate''s claims about the repository as re-executable predicates, '
  'in candidate_block_shape.py''s closed vocabulary. An EMPTY list is a row '
  'that was hand-loaded before there was a loader, and it is not eligible for '
  'unattended approval: zero probes passing is a check that cannot fail.';

-- ============================================================ 4. GRANTS

-- No new grants. 013 already gives fleet_console INSERT and UPDATE on
-- candidates, fleet_console_reader and fleet_detector SELECT. Columns added to
-- a table inherit its privileges, so the loader (console) can write these and
-- the brief (detector) can read them.
--
-- AND THE INVARIANT 013 ENDS ON IS UNCHANGED: no producer identity gets
-- anything on `tasks`. A loader that writes candidate rows is still not a
-- thing that can create work; only the approval surface does that, and only
-- from a ticked row.
