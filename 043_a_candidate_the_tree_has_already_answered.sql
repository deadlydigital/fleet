-- ============================================================================
-- 043_a_candidate_the_tree_has_already_answered.sql
--
-- NOT APPLIED. Apply as `listmonk`, which owns `candidates`.
--
-- THE POOL GREW AND NOTHING RETIRED. On 14 Sep 2026 the approval sweep
-- considered 24 candidates and approved none. Eight of the twenty held were
-- not blocked work -- they were FINISHED work:
--
--   c21  probe: page.tsx must not mention net_revenue -> found 18 matches
--   c22  probe: route.ts must not carry comparison_mode -> found 5
--   c23  probe: orders/export/route.ts must not exist -> it exists
--
-- Each of those probes was the producer's own statement of why the work was
-- needed, and the tree has since answered it. The gate reads that correctly
-- and reports `probes_failed`, which is true and is also the same word it
-- uses for a claim that was never right. So the rows are re-ranked and
-- re-refused every night, and a person reading "24 candidates" is reading a
-- third of it as a backlog when it is history.
--
-- A DISPOSITION RATHER THAN A GATE. Gate 1 already considers `PENDING` only,
-- so a retired row leaves the pool with no change to any gate.
--
-- WHY NOT `REJECTED`. It exists and it is a person's word: console/approve.py
-- refuses one without a sentence, because "rejections are the informative
-- half". A sweep writing REJECTED would erase the difference between "a person
-- judged this badly conceived" and "the tree got there first", which is the
-- same loss as the machine overruling a NOT_NOW -- and 038's neighbours exist
-- to stop exactly that confusion.
--
-- WHY NOT `NOT_NOW`. That is a person's veto, and specs/auto-approval.md §2.2
-- gate 1 says the machine does not overrule it. It would also be false: this
-- is not "later", it is "already".
--
-- WHAT WRITES IT. console/retire.py, and only for a candidate where EVERY
-- failing probe asserted ABSENCE and now finds PRESENCE -- `path_absent` on a
-- path that exists, or `grep_count` with `expected: 0` finding more. A probe
-- failing the other way (`expected 1, found 0`) means the ground MOVED, which
-- is a different fact and stays held for a person. c20 and c46 are in that
-- second class tonight, which is why this retires six rows and not eight.
--
-- `disposition_reason` IS REQUIRED FOR IT, in the trigger below rather than by
-- convention, on console/approve.py's argument about rejections: the sentence
-- is the point. For this disposition the sentence is the probe that answered
-- it, so a person reading the row a month later sees the evidence and not the
-- verdict.
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

BEGIN;

ALTER TABLE candidates DROP CONSTRAINT candidates_disposition_check;
ALTER TABLE candidates ADD CONSTRAINT candidates_disposition_check
    CHECK (disposition = ANY (ARRAY[
        'PENDING'::text, 'APPROVED'::text, 'NOT_NOW'::text,
        'REJECTED'::text, 'SHIPPED'::text]));

CREATE OR REPLACE FUNCTION public.enforce_shipped_has_evidence()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
    IF NEW.disposition = 'SHIPPED'
       AND COALESCE(btrim(NEW.disposition_reason), '') = '' THEN
        RAISE EXCEPTION
            'candidate % cannot be SHIPPED with no reason. The reason is the '
            'probe that answered it, and a retirement nobody can check is a '
            'row that vanished.', NEW.id;
    END IF;
    RETURN NEW;
END; $function$;

DROP TRIGGER IF EXISTS candidates_shipped_has_evidence ON candidates;
CREATE TRIGGER candidates_shipped_has_evidence
    BEFORE INSERT OR UPDATE ON candidates
    FOR EACH ROW EXECUTE FUNCTION public.enforce_shipped_has_evidence();

-- ----------------------------------------------------------------------------
DO $$
DECLARE n int;
BEGIN
    IF pg_get_constraintdef(
           (SELECT oid FROM pg_constraint
             WHERE conname = 'candidates_disposition_check')) NOT LIKE '%SHIPPED%'
    THEN
        RAISE EXCEPTION '043: candidates still rejects SHIPPED';
    END IF;

    -- The four that were there before are all still there. 040 deleted three
    -- migrations' checks by rebuilding a definition from an old copy; this
    -- names what it must not have dropped.
    SELECT count(*) INTO n
      FROM unnest(ARRAY['PENDING','APPROVED','NOT_NOW','REJECTED']) d
     WHERE pg_get_constraintdef(
               (SELECT oid FROM pg_constraint
                 WHERE conname = 'candidates_disposition_check')) LIKE '%' || d || '%';
    IF n <> 4 THEN
        RAISE EXCEPTION
            '043: % of the 4 existing dispositions survived the rewrite', n;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                    WHERE tgrelid = 'candidates'::regclass
                      AND tgname = 'candidates_shipped_has_evidence') THEN
        RAISE EXCEPTION '043: the evidence trigger was not installed';
    END IF;

    RAISE NOTICE
        '043: a candidate the tree has already answered can now be retired.';
END $$;

COMMIT;
