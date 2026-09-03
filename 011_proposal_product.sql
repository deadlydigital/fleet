-- ============================================================================
-- 011_proposal_product.sql  —  a proposal names its product
--
-- `proposals` had `area`, and `area` was doing two jobs. Three producers set
-- it to the product (`deadly_digital`); two set it to the detector key
-- (`dd_analytics_reconciliation`); one set it to the literal `fleet`. So it
-- could not be grouped on, filtered by, or joined to anything -- and
-- `decision_log.product`, which arrived in 010, had nothing to take a value
-- from when the decision cited a proposal.
--
-- A proposal that cannot say what it is about is incomplete, not
-- under-specified. So this column is NOT NULL rather than nullable-and-usually
-- -set: prompting for it at review time pushes the gap onto the reviewer every
-- morning, and inferring it from the evidence is a guess wearing a
-- derivation's clothes.
--
-- `area` is KEPT, unchanged, and not repurposed. Two of its five spellings are
-- detector keys, which are genuinely useful and are not products; renaming the
-- column would have made the historical rows lie about which of the two things
-- they held. Product is new and additive.
--
-- RUN ORDER. `proposer/findings.py` and `proposer/cycle.py` were changed to
-- write this column BEFORE this file was applied, so no cycle can run against
-- a NOT NULL column it does not populate. The proposer timer fires daily at
-- 07:30 and was 15 hours out when this was applied.
--
-- THE BACKFILL HAS TO STEP AROUND `proposals_immutable`, AND SAYS SO
--
-- `proposals` is append-only: 002 puts `reject_mutation()` on UPDATE and
-- DELETE, and unlike `observations` there is no fleet_admin escape for UPDATE
-- -- it is refused for every role including the owner. That is right for the
-- application and wrong for exactly one case, which is this one: a column
-- added by a migration has to be given a value by the same migration.
--
-- `ALTER TABLE ... DISABLE TRIGGER` is the right instrument because the
-- capability is already scoped correctly -- only the table owner can do it, and
-- the owner is the migration identity. It is re-enabled inside the same
-- transaction, so a failure anywhere in this file rolls the disable back with
-- everything else and cannot leave the table writable.
--
-- The first version of this file did not do this and failed on production
-- with `UPDATE on proposals denied for listmonk`. It passed the local
-- rehearsal because that database held no proposals, so the UPDATE never ran.
-- A migration whose backfill is only exercised when there is nothing to
-- backfill has not been exercised.
--
-- IDEMPOTENT, because it half-applied once. `ADD COLUMN IF NOT EXISTS` and
-- guarded constraint/index creation, so re-running it against the partially
-- migrated database completes it rather than erroring on step one.
--
-- Target: PostgreSQL 13+ (RDS 15.17), applied with the listmonk identity.
-- ============================================================================

BEGIN;

ALTER TABLE proposals ADD COLUMN IF NOT EXISTS product text;

-- ---- the backfill, which invents nothing -----------------------------------
--
-- There is exactly one proposal on the deployed database and it predates the
-- column. Rather than type a value for it, this takes the only product the
-- system has ever recorded -- and REFUSES if that is not exactly one, because
-- at that point there is a choice to be made and no rule here that could make
-- it. A default would file the row under a product nobody chose, which is the
-- same failure `fleet decision backfill` refuses for an unmapped repo.
ALTER TABLE proposals DISABLE TRIGGER proposals_immutable;

DO $$
DECLARE only_product text; n int; todo int;
BEGIN
    SELECT count(*) INTO todo FROM proposals WHERE product IS NULL;
    SELECT count(DISTINCT product) INTO n FROM issues;

    IF todo = 0 THEN
        RAISE NOTICE 'no proposals to backfill';
    ELSIF n = 1 THEN
        SELECT DISTINCT product INTO only_product FROM issues;
        UPDATE proposals SET product = only_product WHERE product IS NULL;
        RAISE NOTICE 'backfilled % proposal(s) to the only product on record: %',
            todo, only_product;
    ELSE
        RAISE EXCEPTION 'cannot backfill proposals.product: % distinct products '
                        'exist, so there is no unambiguous answer', n
            USING HINT = 'set proposals.product by hand for the existing rows, '
                         'then re-run this migration';
    END IF;
END $$;

ALTER TABLE proposals ENABLE TRIGGER proposals_immutable;

ALTER TABLE proposals ALTER COLUMN product SET NOT NULL;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'proposals_product_ck'
                      AND conrelid = 'public.proposals'::regclass) THEN
        ALTER TABLE proposals ADD CONSTRAINT proposals_product_ck
            CHECK (length(btrim(product)) > 0);
    END IF;
END $$;

COMMENT ON COLUMN proposals.product IS
  'What the proposal is about, in the same vocabulary as issues.product and '
  'decision_log.product. NOT NULL: a proposal that cannot name one is '
  'incomplete. Distinct from `area`, which is a detector key for two of the '
  'six producers.';

CREATE INDEX IF NOT EXISTS proposals_product_idx
    ON proposals (product, created_at DESC);

-- No new grants. `product` is a column on a table whose SELECT and INSERT
-- grants are already right: fleet_proposer inserts, fleet_console and
-- fleet_console_reader read, fleet_detector_reader reads its own past output.

COMMIT;
