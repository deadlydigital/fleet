-- ============================================================================
-- 047_a_topic_key_is_not_an_identity.sql
--
-- NOT APPLIED BY ANYTHING AUTOMATIC. Apply as `listmonk`, which owns
-- candidate_work_identity().
--
-- THE CEILING AND THE RANKER DISAGREED ABOUT WHAT "THE SAME WORK" MEANS, AND
-- ONLY ONE OF THEM SAID SO OUT LOUD.
--
-- console/work_key.py returns two kinds of key. A `#row:` key is a RESOLUTION:
-- the cited heading was matched against the document and names exactly one
-- table row. A `#topic:` key is a FAILURE to resolve, kept as a string so the
-- reason survives: the heading named no single row, or the document could not
-- be read at that sha.
--
-- console/rank.py has always known the difference and acts on it::
--
--     ONLY `#row:` KEYS DEDUPLICATE. console/work_key.py returns a weaker
--     `topic:` key when a heading is ambiguous, and is explicit about which
--     way to fail [...] A topic key is stable only while the producer keeps
--     quoting the heading the same way, so it does not get to call two rows
--     the same work.
--
-- 027's candidate_work_identity() did not. It is coalesce(work_key, title
-- fallback) with no filter on kind, so a topic key IS the identity for the
-- repeat-failure ceiling. Two consumers, one column, opposite judgements.
--
-- ============================================================================
-- WHAT IT COST, MEASURED 16 SEP 2026
-- ============================================================================
--
-- Nothing yet, and that is luck rather than design. It became load-bearing the
-- day batch 16 landed.
--
-- Batches 8 to 15 were produced from specs/metorik-gap.md, where a section
-- heading names ONE row, so almost everything resolved to `#row:`. Batch 16 is
-- the first produced from research/metorik-report-classification-2026-09-15.md,
-- where a section heading is a GROUP over as many as eighteen rows. All ten of
-- its candidates key to `#topic:`. Candidates 69-74 -- six DIFFERENT reports,
-- an order-value histogram, an item-count histogram, a mean item count, a
-- day-of-week grouping, an hour-of-day grouping and a day-by-hour heatmap --
-- share the single key
--
--     deadly-digital-platform::fleet/research/...-2026-09-15.md#topic:orders-7-of-10
--
-- and candidates 77 and 78 share another. The ceiling in console/approve.py
-- fires at 2. So TWO failures among those six would have stopped the other
-- FOUR, none of which had ever been attempted, and the stop would have named a
-- work identity that is not work -- it is a section heading.
--
-- ============================================================================
-- WHY NOT FIX THE PRODUCER INSTEAD
-- ============================================================================
--
-- Because the producer cannot be fixed here, and it was tried before this was
-- written. Citing two evidence entries -- the group heading for band_of, the
-- row title for work_key -- returns NULL from derive(), which is weaker than
-- the topic key: it builds a key per citation and refuses when they differ,
-- on the same argument band_of makes about two bands. It cannot tell a group
-- from a row inside it, because document_rows() is a flat list of row slugs
-- with no section membership. Citing the row alone keys correctly and loses
-- the band, and a band-less candidate sorts last forever.
--
-- The document's shape is not wrong either. It preserves the catalogue's 17
-- groups on purpose, and the band lives in the group heading because
-- band_of reads it there.
--
-- So the key is right, the document is right, the producer is right, and the
-- ONE thing that was wrong is a consumer reading more into a key than the key
-- claims. That is what this changes, and it changes nothing else.
--
-- ============================================================================
-- WHAT THIS IS NOT
-- ============================================================================
--
-- NOT WEAKER THAN 027. 027 exists because the ceiling keyed on the TITLE and
-- the producer rewrites titles, so c14 and c28 -- one document row, eleven
-- days apart -- each scored 0 against a stop that fires at 2. Both of those
-- resolve to a `#row:` key and both still do. Every repeat 027 was built to
-- catch is a row key; topic keys were never the point, they are the residue.
--
-- NOT A CHANGE TO WHAT IS STORED. candidates.work_key keeps the topic key.
-- It is still the honest record of what could be derived, it is still what
-- console/autoapprove.py reports on, and throwing it away would destroy the
-- evidence that this situation exists. Only the IDENTITY derived from it moves.
--
-- NOT A CHANGE TO THE THRESHOLD, which is 2 and stays in console/approve.py.
--
-- Target: PostgreSQL 15+, same floor as 013 and 027.
-- ============================================================================

\set ON_ERROR_STOP on

CREATE OR REPLACE FUNCTION candidate_work_identity(p_candidate_id bigint)
RETURNS text
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT CASE
             WHEN c.work_key LIKE '%#row:%' THEN c.work_key
             ELSE 'title::' || c.repo || '#' || lower(btrim(c.title))
           END
      FROM candidates c
     WHERE c.id = p_candidate_id;
$$;

COMMENT ON FUNCTION candidate_work_identity(bigint) IS
  'What work this candidate IS, for the repeat-failure ceiling: the stored '
  'work_key ONLY when it resolved to a document row (#row:), else 022''s '
  '(title, repo). A #topic: key is a failure to resolve rather than an '
  'identity, and console/rank.py has always refused to deduplicate on one; '
  '047 makes the ceiling agree. Two candidates with the same value are the '
  'same underlying work regardless of batch, candidate id or title.';
