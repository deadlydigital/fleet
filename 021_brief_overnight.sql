-- ============================================================================
-- 021_brief_overnight.sql  —  a section for what the fleet did while nobody
--                             was watching
--
-- specs/unattended-operation.md §4. The brief is 19 descriptive counts and
-- says outright that it "carries no judgement until there are thresholds worth
-- judging against". That is right for an attended system and wrong for an
-- unattended one: a brief of counts cannot tell you a bad night happened.
--
-- OVERNIGHT is not judgement and does not reopen the LOOKS_WRONG argument.
-- Every row in it is a fact with a source, exactly like a CHANGED row. What
-- makes it a different section is WHAT IT IS ABOUT: CHANGED reports how the
-- world's numbers moved, OVERNIGHT reports what the fleet itself DID -- which
-- task merged, which failed and why, what it cost, and whether production
-- still matches main.
--
-- It renders FIRST because it is the only section a reader must not miss, and
-- because on most mornings it is three lines and the answer is "nothing to do".
--
-- WHY A MIGRATION AND NOT A RENDERER CHANGE
--
-- brief_claims.section carries a CHECK, and 012 put it there so that a section
-- is a vocabulary rather than a string a caller invents. Adding to that
-- vocabulary is a schema decision, which is the property that constraint
-- exists to create.
--
-- The uncomputed pairing holds unchanged: section='UNCOMPUTED' iff
-- status='UNCOMPUTED', so an OVERNIGHT row that could not be computed is
-- reported in the uncomputed list like any other. A night the brief could not
-- read is not a quiet night.
-- ============================================================================

ALTER TABLE brief_claims DROP CONSTRAINT IF EXISTS brief_claims_section_check;

ALTER TABLE brief_claims
  ADD CONSTRAINT brief_claims_section_check
  CHECK (section IN ('OVERNIGHT','CHANGED','LOOKS_WRONG','UNCOMPUTED'));
