\set ON_ERROR_STOP on
-- Assertions for 011_proposal_product.sql.

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='proposals' AND column_name='product'
                      AND is_nullable='NO') THEN
        RAISE EXCEPTION 'K1 FAIL: proposals.product is missing or nullable, so '
                        'a proposal can exist without saying what it is about';
    END IF;
RAISE NOTICE 'K1 pass  every proposal names a product'; END $$;

-- `area` is kept and not repurposed. Two of its spellings are detector keys,
-- and renaming it would make the historical rows lie about which they held.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='proposals' AND column_name='area') THEN
        RAISE EXCEPTION 'K2 FAIL: area was removed or renamed; the rows that '
                        'held a detector key in it no longer say so';
    END IF;
RAISE NOTICE 'K2 pass  area is kept beside product, not replaced by it'; END $$;

DO $$ DECLARE bad int; BEGIN
    SELECT count(*) INTO bad FROM proposals WHERE btrim(product) = '';
    IF bad > 0 THEN
        RAISE EXCEPTION 'K3 FAIL: % proposals carry a blank product', bad;
    END IF;
RAISE NOTICE 'K3 pass  no proposal carries a blank product'; END $$;

-- The proposal layer still cannot read how it is graded. 011 adds a column to
-- a table fleet_detector_reader can read; that must not have widened anything.
DO $$ BEGIN
    IF has_table_privilege('fleet_detector_reader','public.decisions','SELECT')
    OR has_table_privilege('fleet_detector_reader','public.decision_log','SELECT')
    THEN RAISE EXCEPTION 'K4 FAIL: the proposal layer can read its own grades';
    END IF;
RAISE NOTICE 'K4 pass  the layer sees what it said, not how it was graded'; END $$;

DO $$ BEGIN RAISE NOTICE '--- 011 assertions complete ---'; END $$;
