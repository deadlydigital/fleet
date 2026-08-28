-- ORPHANED_ANALYTICS_ORDER
-- Rows the analytics schema believes in and the source does not.
SELECT count(*) AS n
  FROM {analytics_schema}.orders a
 WHERE NOT EXISTS (SELECT 1 FROM public.orders p
                   WHERE p.tenant_id = %(t)s AND p.woo_order_id = a.wc_order_id);
