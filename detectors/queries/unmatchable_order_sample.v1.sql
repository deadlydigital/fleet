-- The source primary key, because woo_order_id is precisely what is absent.
SELECT p.id AS offending_id
  FROM public.orders p
 WHERE p.tenant_id = %(t)s AND p.woo_order_id IS NULL
 ORDER BY p.id
 LIMIT %(limit)s;
