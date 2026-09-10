-- ============================================================================
-- 030_candidate_premise.sql  —  the claim the work RESTS ON, not the gap it
--                               fills, and it is re-executed at the approval
--
-- specs/auto-approval.md §9.9.1. Candidate 38 said, in its own rationale,
-- "the Payment, Country and Coupon values in the table are inert". They were
-- not in the table. The order page rendered five columns -- wc_order_id,
-- created_at, billing_email, status, total -- and had never rendered those
-- three.
--
-- The candidate carried four probes and every one of them held:
--
--     path_exists  platform/app/(dashboard)/analytics/orders/page.tsx
--     grep_count   aria-label="Filter by payment method"          = 1
--     grep_count   onClick={() => setPaymentMethod                = 0
--     grep_count   payment_method: str = Query (api)              = 1
--
-- Read them again against the sentence they were meant to establish. Three say
-- THE WORK IS NEEDED AND NOT DONE -- the filter box exists, nothing wires a
-- cell to it, the API accepts the parameter. One says the file exists. None of
-- them says the value is ON SCREEN, which is the thing that had to be true for
-- "make the cell set the filter" to be a few lines of work rather than a table
-- redesign.
--
-- It cost £2.25 and a run, and the agent -- correctly, on the facts in front of
-- it -- added three columns to the order table that no spec asked for.
-- candidate_block_shape.py's own header had already named this exact limit:
-- "nor whether a candidate's probes test the claim it actually made rather
-- than something adjacent."
--
-- ============================================================================
-- WHY A SEPARATE COLUMN AND NOT ONE MORE ENTRY IN `probes`
-- ============================================================================
--
-- Two reasons, and the second is mechanical.
--
-- THEY ARE DIFFERENT CLAIMS. `probes` say what is MISSING -- they are how a
-- producer shows the gap is real and still open. A premise says what must
-- ALREADY BE TRUE for the work to be the work described. Nothing stops a
-- producer writing a presence probe today, and c38's second and fourth are
-- exactly that; what nothing did was make it write down the sentence its own
-- rationale rested on and then check it. A key that must be filled in is a
-- question that must be answered.
--
-- AND KEY 1 IS READ OFF `probes`. console/rank.py's work_class() classifies a
-- candidate as create / modify / api-present by looking at the probe list.
-- Premises are overwhelmingly presence assertions about the platform, so
-- folding them in would move rows between classes for a reason that has
-- nothing to do with what the work does. Key 1 classifies the WORK; the
-- premise describes the GROUND. Separate columns keep that separation true
-- rather than remembered.
--
-- ============================================================================
-- WHAT THE DATABASE CHECKS, AND WHAT IT DELIBERATELY LEAVES ALONE
-- ============================================================================
--
-- It checks that a premise entry can be READ: an object, a non-empty `claim`,
-- and a `probe` object. It does NOT check the probe's kind against the
-- vocabulary, because the vocabulary lives in exactly one place --
-- PROBE_KINDS in contracts/checks/candidate_block_shape.py, beside the
-- run_probe() that dispatches on it -- and a copy here would be a second
-- vocabulary that accepts what the executor cannot run, one edit later. 025
-- made the same choice for `probes` and it was right.
--
-- DEFAULT '[]' IS FOR THE ROWS ALREADY HERE, on 025's argument and with 025's
-- caveat. Candidates 12-28 were hand-loaded and 29-41 predate this key, so
-- they carry an empty list, and an empty list must never read as "the premise
-- held". console/rank.py records the distinction on the decision --
-- premise: {declared: 0} is "nobody stated one", not "one was checked" -- and
-- contracts/checks/candidate_block_shape.py refuses a NEW block that omits it.
-- The producer contract governs what may be EMITTED; this table is the record
-- of what was, including the batches emitted before the rule existed.
-- ============================================================================

ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS premise jsonb NOT NULL DEFAULT '[]'::jsonb;

DO $$ BEGIN
    ALTER TABLE candidates ADD CONSTRAINT candidates_premise_is_array_ck
        CHECK (jsonb_typeof(premise) = 'array');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Every entry readable: a claim in words, and a probe to re-execute it with.
-- The claim is required in PROSE as well as in predicate form because the two
-- are checked by different readers -- the predicate by rank.py at 01:30, the
-- sentence by whoever reads the decision afterwards and asks whether the
-- predicate tests the claim or something adjacent. That question is the one
-- this key exists for and no machine can answer it.
--
-- A TRIGGER RATHER THAN A CHECK, and not by preference: a CHECK constraint may
-- not contain a subquery, and per-element validation of a jsonb array needs
-- one. 024_paired_paths.sql validates its groups the same way for the same
-- reason. The cost is that the failure arrives as raise_exception rather than
-- check_violation, which is what 030_candidate_premise_assertions.sql catches.
CREATE OR REPLACE FUNCTION enforce_candidate_premise_shape() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE bad text;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.premise IS NOT DISTINCT FROM OLD.premise THEN
        RETURN NEW;
    END IF;

    SELECT string_agg(msg, '; ')
      INTO bad
    FROM (
        SELECT CASE
                 WHEN jsonb_typeof(e) <> 'object'
                   THEN 'a premise entry is not a mapping of claim and probe'
                 WHEN coalesce(btrim(e->>'claim'), '') = ''
                   THEN 'a premise entry has no claim in words, and the '
                        'sentence is what a reader checks the predicate against'
                 WHEN jsonb_typeof(e->'probe') <> 'object'
                   THEN 'a premise entry has no probe, so nothing can '
                        're-execute it -- which is the rationale sentence that '
                        'cost candidate 38 a run'
                 WHEN (SELECT count(*) FROM jsonb_object_keys(e->'probe')) <> 1
                   THEN 'a premise entry has a probe that is not exactly one '
                        'predicate, so one of them would never be run'
               END AS msg
        FROM jsonb_array_elements(coalesce(NEW.premise, '[]'::jsonb)) g(e)
    ) s
    WHERE msg IS NOT NULL;

    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'candidate premise is malformed: %', bad;
    END IF;
    RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS candidates_premise_shape ON candidates;
CREATE TRIGGER candidates_premise_shape
    BEFORE INSERT OR UPDATE ON candidates
    FOR EACH ROW EXECUTE FUNCTION enforce_candidate_premise_shape();

COMMENT ON COLUMN candidates.premise IS
  'What must ALREADY be true for this work to be the work described, as '
  '{claim, probe} pairs: the sentence in words and the same sentence as a '
  're-executable predicate. Distinct from `probes`, which say what is MISSING. '
  'console/rank.py re-executes these at the sha it is about to spend money '
  'against. An EMPTY list is a row that predates the key, and it means nobody '
  'stated a premise -- never that one was checked.';
