SELECT p.woo_order_id AS offending_id
  FROM public.orders p
  JOIN {analytics_schema}.orders a ON a.wc_order_id = p.woo_order_id
 WHERE p.tenant_id = %(t)s
   AND (p.status IS DISTINCT FROM a.status
        OR round(p.total::numeric, 2) IS DISTINCT FROM a.total)
 ORDER BY p.woo_order_id
 LIMIT %(limit)s;
