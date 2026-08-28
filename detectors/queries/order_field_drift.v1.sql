-- ORDER_FIELD_DRIFT
-- total is double precision in public and numeric(10,2) in analytics. The
-- round-and-cast is required: comparing the float directly makes every
-- correctly-synced row look like drift.
SELECT count(*) AS n
  FROM public.orders p
  JOIN {analytics_schema}.orders a ON a.wc_order_id = p.woo_order_id
 WHERE p.tenant_id = %(t)s
   AND (p.status IS DISTINCT FROM a.status
        OR round(p.total::numeric, 2) IS DISTINCT FROM a.total);
