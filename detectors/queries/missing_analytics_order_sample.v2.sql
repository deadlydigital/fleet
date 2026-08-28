-- Up to five offending source order ids. Ordered, so the evidence is stable
-- across runs. Ids only: no email, no name, no address.
--
-- v2. v1 was the same query without the OFFSET 0, and took 2.1s to return
-- five rows. EXPLAIN showed why: the planner estimates this anti-join yields
-- rows=1 when it actually yields 29,603, so it believed no LIMIT could ever
-- short-circuit, and chose a parallel hash anti-join that builds a hash over
-- all 2.84M analytics rows -- spilling to 32 batches on temp -- materialises
-- every offending row, and only then takes five. The LIMIT bought nothing.
--
-- The estimate is the defect, and no join-shape rewrite fixes an estimate.
-- OFFSET 0 is an optimisation fence: it stops the subquery being pulled up
-- into an anti-join at all, so NOT EXISTS stays a per-row filter over an
-- ordered index-only scan of uq_tenant_order (tenant_id, woo_order_id), and
-- the LIMIT stops the scan after five surviving rows. 2117ms -> 0.2ms, and
-- 137,609 buffers -> 23.
--
-- The cost of the fence is that it walks the index in woo_order_id order
-- until it finds five offenders, so it is fast when offenders sort early and
-- slow when they sort late. Measured on the reverse ordering, where every
-- offender sorts last, it takes 5.1s against v1's 2.1s. Today's gap is the
-- 2026-08-18 rebuild, whose unmigrated orders are the LOWEST ids in the
-- table -- they are the first rows this scan touches. A future gap caused by
-- a live sync failing would instead be the highest ids, and would land on
-- the slow side. See README; this is a known trade, not an oversight.
SELECT p.woo_order_id AS offending_id
  FROM public.orders p
 WHERE p.tenant_id = %(t)s AND p.woo_order_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM {analytics_schema}.orders a
                   WHERE a.wc_order_id = p.woo_order_id
                   OFFSET 0)
 ORDER BY p.woo_order_id
 LIMIT %(limit)s;
