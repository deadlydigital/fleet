-- A catalog fingerprint, comparable across two servers with different owners
-- and different login roles. pg_dump is not usable here: the versions differ
-- (15.17 vs 16.15) and every object would differ on OWNER TO alone.
\pset format unaligned
\pset tuples_only on
\pset footer off
-- FIRST, so a reader knows which comparisons below are meaningful. The two
-- servers are not the same major version, and `pg_get_viewdef` deparses
-- differently across them.
SELECT 'SERVER ' || current_setting('server_version_num')::int / 10000;
SELECT 'TABLE  ' || c.relname
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind IN ('r','p','v') ORDER BY 1;
SELECT 'COL    ' || table_name || '.' || column_name || ' ' || data_type
       || coalesce('(' || character_maximum_length || ')','')
       || coalesce('(' || numeric_precision || ',' || numeric_scale || ')','')
       || ' null=' || is_nullable
       || ' default=' || coalesce(regexp_replace(column_default,'::[a-z_ ]+','','g'),'-')
  FROM information_schema.columns WHERE table_schema='public' ORDER BY 1;
SELECT 'CONS   ' || rel.relname || ' ' || con.conname || ' ' || pg_get_constraintdef(con.oid)
  FROM pg_constraint con JOIN pg_class rel ON rel.oid=con.conrelid
  JOIN pg_namespace n ON n.oid=rel.relnamespace WHERE n.nspname='public' ORDER BY 1;
SELECT 'INDEX  ' || indexname || ' ' || regexp_replace(indexdef,'^CREATE (UNIQUE )?INDEX [^ ]+ ','\1')
  FROM pg_indexes WHERE schemaname='public' ORDER BY 1;
SELECT 'TRIG   ' || c.relname || ' ' || t.tgname || ' ' || pg_get_triggerdef(t.oid)
  FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
  JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND NOT t.tgisinternal ORDER BY 1;
SELECT 'FUNC   ' || p.proname || ' ' || md5(pg_get_functiondef(p.oid))
  FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND p.prokind='f' ORDER BY 1;
SELECT 'VIEW   ' || c.relname || ' opts=' || coalesce(array_to_string(c.reloptions,','),'-')
       || ' ' || md5(pg_get_viewdef(c.oid))
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='public' AND c.relkind='v' ORDER BY 1;
SELECT 'TYPE   ' || t.typname || ' ' || string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder)
  FROM pg_type t JOIN pg_enum e ON e.enumtypid=t.oid
  JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='public'
 GROUP BY t.typname ORDER BY 1;
-- Privileges for the fleet_* group roles only. Login roles and the owner
-- differ by environment and are deliberately out of the comparison.
SELECT 'GRANT  ' || r.rolname || ' ' || c.relname || ' ' || p.priv
  FROM pg_roles r, pg_class c, pg_namespace n,
       unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) AS p(priv)
 WHERE n.oid=c.relnamespace AND n.nspname='public' AND c.relkind IN ('r','p','v')
   AND r.rolname LIKE 'fleet\_%' AND r.rolcanlogin=false
   AND has_table_privilege(r.oid, c.oid, p.priv) ORDER BY 1;
