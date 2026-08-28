-- Is this tenant's analytics table present and readable in this snapshot?
-- to_regclass returns NULL for a missing schema instead of raising, so the
-- ordinary case costs no aborted savepoint. has_table_privilege takes the
-- oid form deliberately: it is strict, so a missing table yields NULL rather
-- than an error, and "absent" stays distinguishable from "not ours to read".
SELECT probe.oid IS NOT NULL                            AS table_exists,
       coalesce(has_table_privilege(probe.oid, 'SELECT'), false) AS readable
  FROM (SELECT to_regclass(%(qualified)s)::oid AS oid) AS probe;
