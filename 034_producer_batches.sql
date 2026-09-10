-- ============================================================================
-- 034_producer_batches.sql  —  only a producer batch supersedes a candidate
--
-- NOT APPLIED. Apply as the identity that owns `candidate_batches`.
--
-- console/rank.py gate 2 holds every candidate that is not in the newest
-- batch, on a stated argument: "the newer batch re-verified these claims
-- against a later sha". On 10 Sep 2026 that argument was false about the
-- batch doing the holding, and the whole pool was shut because of it.
--
--     batch  8   specs/metorik-gap.md            read by hand by a person
--     batch  9   research/candidates-...-09.md   produced by task 34
--     batch 10   research/candidates-...-10.md   produced by task 50
--     batch 11   drafts/order-filters-frontend.md  ONE CANDIDATE, BY HAND
--                and its own note says "NOT A PRODUCER BATCH"
--     batch 12   specs/metorik-gap.md            a leaked test fixture
--
-- Gate 2 took `max(batch_id) FROM candidates`, which is 11, so twenty real
-- candidates from batches 8 to 10 were all reported as superseded -- by one
-- hand-written row about §2.5 of a draft, which re-verified nothing. The
-- first live auto-approve would have approved nothing and the morning would
-- have read "the ranker approved nothing", which is indistinguishable from
-- the ranker working.
--
-- WHY A COLUMN AND NOT A HEURISTIC. `generated_by` does not separate them --
-- batches 10 and 11 were both written by fleet_console_login -- and
-- `source_document` would mean matching on a filename pattern, which is the
-- prose-scraping that research_document_shape.py measured and rejected.
--
-- WHY IT IS DERIVED AND NOT PASSED IN. A flag on the loader that somebody
-- forgets makes a real producer batch stop counting, and the pool jams again
-- with no error -- the same silent failure by a new route. So it is looked up
-- from the run that ADDED the document: PATCH_PROPOSED carries
-- `files_changed`, and a document no task added has no producer, which is the
-- true answer for batches 8 and 12.
--
-- AND THE WORK TYPE IS PART OF THE DERIVATION, WHICH IT LOOKED LIKE IT NEED
-- NOT BE. "The task that added this document" attributes batch 11 to TASK 52
-- -- the draft-spec run that wrote drafts/order-filters-frontend.md -- so the
-- hand-made batch counts as a producer batch and nothing changes. Measured
-- before this file was applied rather than after. `runs.work_type` must be
-- `candidate_producer`: a draft-spec run adding a document is not a producer
-- re-verifying a gap list, and only the second is what gate 2 means.
--
-- WHAT THIS CHANGES ON THIS HOST: the newest producer batch becomes 10, so
-- its eight rows reach the later gates. Seven are then held by gates 5 and 6
-- (work no single contract can do), leaving ONE eligible candidate. That is
-- the intended size for a mechanism that has never fired.
--
-- APPLY WITH, as the identity that owns the table:
--     psql -v ON_ERROR_STOP=1 -d fleet -f 034_producer_batches.sql
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE candidate_batches
    ADD COLUMN IF NOT EXISTS produced_by_task_id bigint
        REFERENCES tasks(id) ON DELETE SET NULL;

COMMENT ON COLUMN candidate_batches.produced_by_task_id IS
  'The candidate_producer task whose run ADDED source_document, or NULL when '
  'no task did -- a batch read from a gap list by hand, one written from a '
  'draft, or a test fixture. console/rank.py gate 2 supersedes a candidate '
  'only against a batch that has one, because "a newer batch re-verified '
  'these claims against a later sha" is true of a producer run and of '
  'nothing else. Derived from run_steps rather than passed to the loader: a '
  'flag somebody forgets jams the pool with no error.';

-- ---- backfill, from the runs that added the documents ---------------------
--
-- The same derivation console/load_candidates.py now performs at load time,
-- run once over the batches that predate the column. A document no task
-- added stays NULL, which is the true answer and not a gap.
UPDATE candidate_batches b
   SET produced_by_task_id = (
       SELECT r.task_id
         FROM run_steps s JOIN runs r ON r.id = s.run_id
        WHERE s.step_type = 'PATCH_PROPOSED'
          AND r.work_type = 'candidate_producer'
          AND s.payload->'files_changed' ? b.source_document
        ORDER BY r.id DESC LIMIT 1)
 WHERE b.produced_by_task_id IS NULL;

DO $$
DECLARE producer_batches int; hand_batches int;
BEGIN
    SELECT count(*) FILTER (WHERE produced_by_task_id IS NOT NULL),
           count(*) FILTER (WHERE produced_by_task_id IS NULL)
      INTO producer_batches, hand_batches
      FROM candidate_batches;

    -- NOT an assertion on the numbers. This file is applied to the fleet
    -- database and to a test template built from every migration with no
    -- rows in it, and a count that is right for one is wrong for the other.
    -- What must hold in both is that the backfill did not invent a link.
    IF EXISTS (SELECT 1 FROM candidate_batches b
                WHERE b.produced_by_task_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM run_steps s JOIN runs r ON r.id = s.run_id
                       WHERE r.task_id = b.produced_by_task_id
                         AND s.step_type = 'PATCH_PROPOSED'
                         AND r.work_type = 'candidate_producer'
                         AND s.payload->'files_changed' ? b.source_document))
    THEN
        RAISE EXCEPTION
            '034: a batch names a producer whose run did not add its '
            'source_document';
    END IF;

    RAISE NOTICE '034: % producer batch(es), % without a producing run.',
                 producer_batches, hand_batches;
END $$;

GRANT SELECT ON candidate_batches TO fleet_console_reader;

COMMIT;
