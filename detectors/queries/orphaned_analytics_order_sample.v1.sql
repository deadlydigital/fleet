SELECT a.wc_order_id AS offending_id
  FROM {analytics_schema}.orders a
 WHERE NOT EXISTS (SELECT 1 FROM public.orders p
                   WHERE p.tenant_id = %(t)s AND p.woo_order_id = a.wc_order_id)
 ORDER BY a.wc_order_id
 LIMIT %(limit)s;
