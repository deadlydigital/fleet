-- ============================================================================
-- 047_the_evidence_reader_can_see_order_items.sql
--
-- Apply as `listmonk`, which owns the analytics schemas. THIS RUNS AGAINST THE
-- `deadly_digital` DATABASE, not `fleet`.
--
-- NAMED `dd_047_` AND NOT `047_`, and the first draft of this file got that
-- wrong. tests/conftest.py builds the fleet test template by globbing
-- `[0-9][0-9][0-9]_*.sql` at the project root and applying every match, so a
-- dd-database file numbered into that sequence is handed to the wrong database
-- and takes the entire suite down with it. The `dd_` prefix keeps the sequence
-- hint -- this belongs beside 047 in time -- while staying out of a glob that
-- means "a fleet migration". The grant is auditable here rather than living
-- only in somebody's shell history, which was the point of numbering it.
--
-- ============================================================================
-- WHY
-- ============================================================================
--
-- `runner/evidence.py` runs a contract's `evidence_queries` as one of two
-- read-only roles, and the only one that can reach the analytics schemas is
-- `dd_detector_login`. Measured 15 Sep 2026, that role holds SELECT on:
--
--     analytics_1.orders                  analytics_2.orders
--     analytics_1.reconciliation_manifests analytics_2.reconciliation_manifests
--     public.orders  public.tenants  public.utm_source_alias
--
-- and on nothing else. `order_items` is absent, and not merely unreadable:
-- with no privilege at all the role cannot see the table in
-- information_schema. Asked directly it answers
--
--     ERROR:  permission denied for table order_items
--
-- research/top-products-index-pricing.md (task 105) is an index pricing for
-- `top_products`, which is a GROUP BY over `order_items` joined to `orders`.
-- Its gate A2 -- does hypopg honour the INCLUDE clause -- needs only catalog
-- access and RAN: 101 MB bare against 361 MB covering, so hypopg 1.4.2 honours
-- it. Its gates A and B are `EXPLAIN` over the real statement and cannot run
-- at all without this grant.
--
-- So specs/auto-approval.md §9.16 named half the problem. It proposed putting
-- `evidence_queries` on `research.yaml` and that would have produced a pack of
-- permission errors: the queries would have been declared and the role still
-- could not have answered them. §9.16 did not see it because task 57's
-- research was about `orders`, which the role can already read.
--
-- ============================================================================
-- WHAT IS GRANTED, AND WHAT IS DELIBERATELY NOT
-- ============================================================================
--
-- SELECT on `order_items` in the tenant schemas that exist, and nothing else.
-- No INSERT, no UPDATE, no DELETE, no ownership, no other table. The role is
-- the evidence pack's reader and the pack is read-only by construction
-- (`runner/evidence.py` sets `conn.read_only = True`), so anything beyond
-- SELECT would be a privilege nothing can use.
--
-- ENUMERATED, NOT `ALL TABLES IN SCHEMA`. A blanket grant would silently pick
-- up every table added later, which is how a reader ends up holding a
-- privilege nobody decided to give it. Two schemas exist today; a third will
-- need a line here, and needing a line is the point.
--
-- NO DEFAULT PRIVILEGES for the same reason. `ALTER DEFAULT PRIVILEGES` would
-- make future tables readable by this role automatically, and the decision to
-- expose a new table to the evidence pack should be taken when the table is
-- created rather than inherited from a decision taken today.
-- ============================================================================

\set ON_ERROR_STOP on

GRANT SELECT ON analytics_1.order_items TO dd_detector_login;
GRANT SELECT ON analytics_2.order_items TO dd_detector_login;

-- ----------------------------------------------------------------------------
-- What this file claims.
DO $$
DECLARE missing text;
BEGIN
    SELECT string_agg(s, ', ') INTO missing FROM (
        SELECT s FROM unnest(ARRAY['analytics_1','analytics_2']) s
         WHERE NOT has_table_privilege('dd_detector_login',
                                       s || '.order_items', 'SELECT')
    ) x;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION '047: dd_detector_login still cannot read order_items in %',
            missing;
    END IF;

    -- And nothing beyond SELECT arrived with it.
    SELECT string_agg(privilege_type, ', ') INTO missing
      FROM information_schema.table_privileges
     WHERE grantee = 'dd_detector_login'
       AND table_name = 'order_items'
       AND privilege_type <> 'SELECT';
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION '047: dd_detector_login holds % on order_items, and the '
                        'evidence pack is read-only by construction', missing;
    END IF;

    RAISE NOTICE '047 ok  the evidence reader can SELECT order_items, and only SELECT';
END $$;
