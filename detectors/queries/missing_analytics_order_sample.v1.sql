-- Up to five offending source order ids. Ordered, so the evidence is stable
-- across runs. Ids only: no email, no name, no address.
SELECT p.woo_order_id AS offending_id
  FROM public.orders p
 WHERE p.tenant_id = %(t)s AND p.woo_order_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM {analytics_schema}.orders a
                   WHERE a.wc_order_id = p.woo_order_id)
 ORDER BY p.woo_order_id
 LIMIT %(limit)s;
