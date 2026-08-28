-- MISSING_ANALYTICS_ORDER
-- Whole population, not windowed: created_at in public.orders starts at
-- 2026-08-18 because of a table rebuild, so any window on it would step
-- straight over the pre-existing gap.
SELECT count(*) AS n
  FROM public.orders p
 WHERE p.tenant_id = %(t)s AND p.woo_order_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM {analytics_schema}.orders a
                   WHERE a.wc_order_id = p.woo_order_id);
