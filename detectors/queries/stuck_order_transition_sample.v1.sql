-- Up to five offending order ids, ordered so the evidence is stable across
-- runs. Ids only: no email, no name, no address, no total.
--
-- The predicate is character-for-character the one in
-- stuck_order_transition.v1.sql. If the two ever drift, the count and the ids
-- describe different sets of orders, and a detector whose two halves disagree
-- reports "84 stuck" beside a list naming something else with nothing to say
-- which half is lying. Same rule as RECONCILIATION-RUNS.md §3.2 makes binding
-- for the manifest descent, and the same reason.
--
-- No OFFSET 0 fence here, unlike missing_analytics_order_sample.v2. That one
-- needed it because its anti-join estimate was wrong by four orders of
-- magnitude; this is a single-table filter with no join to mis-estimate, and
-- the offenders are a few dozen rows in a table the planner already knows how
-- to scan. Adding a fence that buys nothing would be a cargo-culted hint.
SELECT o.wc_order_id AS offending_id
  FROM {analytics_schema}.orders o
 WHERE o.updated_at IS NULL
   AND (o.status IS NULL OR o.status = 'pending')
   AND o.created_at < now() - %(settle)s::interval
 ORDER BY o.wc_order_id
 LIMIT %(limit)s;
