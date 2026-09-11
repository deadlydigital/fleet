-- ============================================================================
-- 037_a_candidate_may_need_more_than_one_task.sql
--                                      —  specs/auto-approval.md §12
--
-- NOT APPLIED. Apply as the identity that owns `tasks` and `candidates`.
--
-- Gate 6 holds six of the seven live candidates in the newest batch for
-- spanning two contracts, and the pool is therefore stopped rather than slow:
-- 19 open, 0 eligible on 11 Sep 2026. A draft spec produces ONE task under ONE
-- contract, so half the work would ship and nothing would queue the other --
-- which is what task 28 did.
--
-- A CHAIN IS A SET OF LINKS THAT MERGE TOGETHER OR NOT AT ALL.
--
-- The half-shipped state is not mitigated and not detected afterwards. It is
-- unrepresentable, because no link merges until every link has verified. If
-- the second half fails, the first was never merged and production never saw
-- either.
--
-- WHY THE LINKS DO NOT DEPEND ON EACH OTHER TO BUILD, WHICH IS WHAT MAKES
-- THIS SMALL
--
-- The two halves are coupled at RUNTIME and not at build time. Nothing under
-- platform/ imports from api/ -- checked, not assumed -- and a page reaches
-- the backend over HTTP:
--
--     const res = await fetch(`/api/analytics/dashboard?${params}`)
--
-- So the frontend half typechecks and its suite passes whether or not the
-- endpoint exists; it 404s at runtime, which is exactly the failure this
-- exists to prevent shipping. Each link therefore builds from the base branch
-- independently and verifies independently, and no link needs another's
-- branch as its base.
--
-- THAT EQUIVALENCE IS A PROPERTY OF THE SPLIT AND IS CHECKED RATHER THAN
-- ASSUMED. It holds only while the links touch disjoint paths: two links that
-- could write the same file would each verify against a tree without the
-- other's change, and neither run would be the tree that ships.
-- contracts/checks/draft_spec_shape.py refuses a draft whose blocks are not
-- pairwise disjoint, so the assumption is enforced where the split is made.
--
-- WHAT IS DELIBERATELY NOT HERE
--
-- No dependency column on `tasks`. A task does not depend on a task; a link
-- depends on its chain being complete, and keeping that off `tasks` is what
-- leaves `claim_task` untouched -- it still orders by (priority, id) over
-- QUEUED rows and knows nothing about chains.
--
-- No auto-resume. A chain whose link fails after another passed says something
-- about the SPLIT was wrong, and retrying the failed link against a held
-- sibling compounds a bad split rather than recovering from it. The candidate
-- returns to PENDING, the branches stay -- unmerged, unreferenced, cheap, and
-- evidence -- and it surfaces on the morning page as needing a person.
--
-- APPLY WITH, as the identity that owns the tables:
--     psql -v ON_ERROR_STOP=1 -d fleet -f 037_a_candidate_may_need_more_than_one_task.sql
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE IF NOT EXISTS task_chain (
    candidate_id   integer NOT NULL REFERENCES candidates (id),
    position       integer NOT NULL CHECK (position >= 1),
    contract_file  text    NOT NULL CHECK (length(btrim(contract_file)) > 0),
    declared_paths text[]  NOT NULL CHECK (cardinality(declared_paths) > 0),
    task_id        integer REFERENCES tasks (id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (candidate_id, position),
    -- One task belongs to at most one link. A task in two chains would be
    -- held by one and merged by the other.
    UNIQUE (task_id)
);

COMMENT ON TABLE task_chain IS
  'The ordered links one candidate was split into, because no single contract '
  'covers all its paths. specs/auto-approval.md §12. A link may not merge '
  'until every link in its chain has verified, so a half-shipped feature is '
  'unrepresentable rather than detected afterwards.';

COMMENT ON COLUMN task_chain.position IS
  'Merge order, 1-based. Used to sequence the merges and nothing else: the '
  'links do not depend on each other to build, because platform/ reaches api/ '
  'over HTTP and imports nothing from it.';

COMMENT ON COLUMN task_chain.declared_paths IS
  'What this link''s fleet-spec block declared. Recorded so the split can be '
  'read back without re-parsing the draft, and so the union can be checked '
  'against the candidate''s suggested paths.';

-- The console queues and decides; nothing else writes a chain.
GRANT SELECT, INSERT, UPDATE ON task_chain TO fleet_console;
GRANT SELECT ON task_chain TO fleet_console_reader, fleet_detector;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'task_chain') THEN
        RAISE EXCEPTION '037: task_chain was not created';
    END IF;

    IF NOT has_table_privilege('fleet_console', 'task_chain', 'INSERT') THEN
        RAISE EXCEPTION '037: fleet_console cannot write a chain';
    END IF;

    IF NOT has_table_privilege('fleet_console_reader', 'task_chain', 'SELECT') THEN
        RAISE EXCEPTION '037: the console cannot read a chain, so the morning '
                        'page could not show a half-failed one';
    END IF;

    -- The runner must not touch it. A runner that could edit its own chain
    -- could release the hold on its own sibling.
    IF has_table_privilege('fleet_task_runner', 'task_chain', 'UPDATE') THEN
        RAISE EXCEPTION '037: fleet_task_runner can write task_chain, which '
                        'lets a link release the hold on its own sibling';
    END IF;
END $$;

COMMIT;
