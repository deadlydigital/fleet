-- ============================================================================
-- dd_048_the_evidence_reader_loses_the_api_key.sql
--
-- Apply as `listmonk`. RUNS AGAINST `deadly_digital`, not `fleet`. Named
-- `dd_048_` and not `048_` for the reason dd_047 records: tests/conftest.py
-- globs [0-9][0-9][0-9]_*.sql and hands every match to the fleet test template.
--
-- ============================================================================
-- WHY
-- ============================================================================
--
-- `dd_detector_login` is the read-only role the evidence pack uses. It held
-- SELECT on ALL COLUMNS of public.tenants, which includes `api_key` and
-- `api_key_hash`. The pack is written into the worktree at a path the contract
-- declares writable -- research-metorik-gap.yaml points it inside research/ --
-- and is therefore COMMITTED. A query selecting api_key would have put a
-- tenant credential in the repository.
--
-- runner/evidence.py now refuses a TASK-authored query that references
-- tenants, and redacts credential-shaped values out of task-authored results.
-- That covers the agent-written path. It does not cover a CONTRACT-level
-- query, which a person writes, and it should not have to: the role simply
-- has no business reading the column.
--
-- ============================================================================
-- MEASURED BEFORE CHANGED, because a privilege change that breaks a reader at
-- 3am is worse than the exposure it closes
-- ============================================================================
--
-- Every consumer of public.tenants through this role, found by an exhaustive
-- search of the only repository that holds the credential:
--
--   detectors/queries/tenants_active.v1.sql   SELECT id FROM public.tenants
--                                             WHERE is_active ORDER BY id
--   brief/pass_.py:901                        SELECT count(*) FROM tenants
--                                             WHERE is_active
--   contracts/research-metorik-gap.yaml:120   SELECT id, name, created_at
--                                             FROM public.tenants ORDER BY id
--
-- Four columns between them: id, name, created_at, is_active. NOTHING reads
-- api_key or api_key_hash. There is no `SELECT *` against tenants anywhere,
-- which is the form this change would break.
--
-- WHAT COULD NOT BE MEASURED, stated rather than glossed: pg_stat_statements
-- is NOT installed on this server, so there is no per-statement history and no
-- runtime attribution. The evidence above is static and complete for this
-- repository; it cannot prove that nothing outside it has ever used the
-- credential. The credential appears in no systemd unit and in no .env outside
-- ~/fleet, which is as far as that can be checked from here.
--
-- ============================================================================
-- REVERSIBLE IN ONE LINE
-- ============================================================================
--
--     GRANT SELECT ON public.tenants TO dd_detector_login;
--
-- restores exactly what was held before. If a reader breaks, that is the fix,
-- and it costs nothing to apply.
-- ============================================================================

\set ON_ERROR_STOP on

-- ORDER MATTERS, AND THE FIRST VERSION OF THIS FILE HAD IT BACKWARDS.
--
-- It granted the four columns and then revoked the table, on the reasoning
-- that the role should never be without the access it needs. That is wrong:
-- in PostgreSQL `REVOKE SELECT ON <table>` removes the privilege on the table
-- AND on every column of it, so the column grants issued a moment earlier went
-- with it. The transaction committed and dd_detector_login briefly held no
-- access to tenants at all -- caught within seconds by the assertion at the
-- foot of this file, which is the reason it is there.
--
-- REVOKE FIRST, GRANT SECOND. Both inside one transaction, so no concurrent
-- reader can observe the gap: the revoke and the grant are visible together or
-- not at all.
BEGIN;

REVOKE SELECT ON public.tenants FROM dd_detector_login;

GRANT SELECT (id, name, created_at, is_active) ON public.tenants
    TO dd_detector_login;

COMMIT;

-- ----------------------------------------------------------------------------
-- What this file claims.
DO $$
DECLARE bad text;
BEGIN
    -- The four columns every real consumer reads are still readable.
    SELECT string_agg(c, ', ') INTO bad FROM (
        SELECT c FROM unnest(ARRAY['id','name','created_at','is_active']) c
         WHERE NOT has_column_privilege('dd_detector_login', 'public.tenants',
                                        c, 'SELECT')
    ) x;
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'dd_048: the reader lost columns it needs: %', bad;
    END IF;

    -- And the two it must not read are gone.
    SELECT string_agg(c, ', ') INTO bad FROM (
        SELECT c FROM unnest(ARRAY['api_key','api_key_hash']) c
         WHERE has_column_privilege('dd_detector_login', 'public.tenants',
                                    c, 'SELECT')
    ) x;
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'dd_048: the reader can still read %', bad;
    END IF;

    RAISE NOTICE 'dd_048 ok  four columns readable, api_key and api_key_hash are not';
END $$;
