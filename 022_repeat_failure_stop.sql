-- ============================================================================
-- 022_repeat_failure_stop.sql  —  a candidate that has failed twice stops
--                                 being approved on its own
--
-- specs/unattended-operation.md §5.2, CORRECTED. What that section proposed
-- was "a finding whose last two tasks both FAILED is not re-proposed", and it
-- does not fit this system in two ways:
--
--   1. THERE IS NO finding -> task LINK. Findings become `proposals`;
--      candidates come from a findings DOCUMENT read by the producer task, and
--      carry no finding_key. The proposer's 14-day suppression is about
--      proposals and never reaches a task.
--
--   2. THE PRODUCER MUST NOT DEDUPLICATE, and this is enforced rather than
--      asked: no Bash, no credential, one writable file, and a shape check
--      that refuses batch_id. specs/approval-surface.md §7 says why -- "a
--      candidate that reappears is a signal", and a producer that dropped
--      repeats would erase it. Suppressing at production would have broken a
--      designed property.
--
-- So the stop belongs at APPROVAL, which is the single path from a candidate
-- to a task, and it withholds only the AUTOMATIC approval. The candidate still
-- appears in the batch and a person can still tick it with a reason. The
-- signal survives; the money loop does not.
--
-- WHAT COUNTS AS "THE SAME CANDIDATE"
--
-- Candidates carry no stable key across batches -- deliberately, because a
-- batch two weeks old is a new batch and rows are never updated in place. So
-- identity is (title, repo), which is what a reader compares them by, and is
-- the same pair the surface already shows as a repetition.
--
-- Both task columns count. A candidate produces a spec task and later a work
-- task, and either failing is a failure of that candidate: the first means the
-- spec could not be written, the second that it could not be built.
-- ============================================================================

CREATE OR REPLACE FUNCTION candidate_prior_failures(p_title text, p_repo text)
RETURNS int
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT count(DISTINCT t.id)::int
      FROM candidates c
      JOIN tasks t
        ON t.id = c.spec_task_id OR t.id = c.work_task_id
     WHERE c.title = p_title
       AND c.repo  = p_repo
       AND t.status = 'FAILED';
$$;

COMMENT ON FUNCTION candidate_prior_failures(text, text) IS
  'How many FAILED tasks this candidate title has already produced in this '
  'repo, across every batch. Two is the point at which the approval surface '
  'stops approving it automatically -- see 022 and console/approve.py.';
