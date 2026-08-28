-- UNMATCHABLE_ORDER
-- A source order with no woo_order_id cannot be reconciled in either
-- direction, so it is invisible to the other three invariants. Currently
-- zero; the point is to notice the first one.
SELECT count(*) AS n
  FROM public.orders p
 WHERE p.tenant_id = %(t)s AND p.woo_order_id IS NULL;
