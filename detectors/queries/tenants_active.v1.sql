-- Enumerate the tenants the reconciliation detector is responsible for.
-- Failure of this query is a failure of enumeration: the run learns nothing
-- and must close ERROR, not OK-with-no-subjects.
SELECT id AS tenant_id
  FROM public.tenants
 WHERE is_active
 ORDER BY id;
