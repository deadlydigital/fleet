-- ============================================================================
-- 040_an_index_is_not_a_schema_change.sql
--
-- NOT APPLIED. Apply as `listmonk`, which owns enforce_contract_floor() and
-- protected_path_floor. Nothing on this host holds it: the fleet DSN connects
-- as dd_detector_login. That separation is 014 §6's and it is the right one --
-- the identity that runs under a floor does not move the floor.
--
-- ONE FLOOR ROW GAINS AN EXCEPTION, FOR ONE work_type, FOR ONE PATH.
-- Nothing else moves.
--
-- WHAT THIS IS FOR, AND IT WAS MEASURED BEFORE IT WAS PROPOSED
--
-- On 14 Sep 2026 every analytics page was slow. Measured against the API on
-- tenant 2: dashboard 21.3s, revenue 6.5s, customers 6.1s, products 3.0s,
-- sources 2.9s, orders 0.7s. Of the dashboard's 6.5s of SQL, 85% is one query
-- run twice -- `_query_period_stats` -- and its plan is:
--
--     Seq Scan on orders          2,887,010 rows, to remove 2,063 (0.07%)
--     Hash Join                   -> 1,724,169 rows
--     Sort (external merge, 50MB) -> to produce 21,280 rows
--
-- Eighty-one rows read and sorted for every one kept, under a 4MB work_mem.
-- Every index on that table is a single-column btree.
--
-- THE INDEX COULD NOT BE WRITTEN BY ANYTHING THIS SYSTEM RUNS, and the reason
-- is this floor row. api/analytics/migrations/** is protected for every
-- contract on the repository, correctly: a task that can alter the schema can
-- drop a column. The consequence, unnoticed until it was looked for, is that
-- the loop has been shipping features onto a schema it structurally cannot
-- make fast -- and the mechanism that would have said so was refusing the
-- rows. Candidates 27 and 35 are both schema work, both held as
-- `protected_path`, both correctly held under the contracts that existed.
--
-- FOUR THINGS ENFORCE THAT FLOOR AND I FOUND THE FOURTH BY TRYING
--
--   1. the boundary check refuses a write outside writable_paths;
--   2. console/rank.py gate 6 holds a candidate naming a protected path;
--   3. console/autodeploy refuses to deploy a range containing a migration;
--   4. THIS FUNCTION refuses to store the contract at all.
--
-- The first three are in the tree and greppable. The fourth is in the
-- database, and a contract that opens the crack cannot even be INSERTed
-- without it. That is why this file exists rather than a yaml change alone.
--
-- WHY AN EXCEPTION AND NOT A NARROWER FLOOR ROW
--
-- The obvious alternative is to replace the row with narrower ones --
-- protect migration.py, runner.py, predicates.py and versions/** separately,
-- then let one contract omit versions/**. It is rejected because a floor row
-- is a statement that a path is protected FOR EVERYONE, and the rationale
-- column exists so nobody deletes one without meeting the reason. Splitting
-- the row to make a hole leaves four rows whose collective meaning is "this
-- tree is protected, except where it is not", and the exception is then
-- invisible at the point of reading. A column named `except_work_type` says
-- it where it is true, and `SELECT * FROM protected_path_floor WHERE
-- except_work_type IS NOT NULL` enumerates every hole in one query.
--
-- WHAT MAKES THE EXCEPTION SAFE, AND IT IS NOT THIS FILE
--
-- The waiver admits contracts whose work_type is `dd_index_migration`. What
-- such a contract may then do is fixed by contracts/dd-index-migration.yaml
-- and enforced by contracts/checks/index_migration_only.py, whose whitelist is
-- STRUCTURAL: api/analytics/migrations/migration.py defines three step types,
-- and the check admits `CreateIndexStep` only. `SQLStep` and `DataStep` are
-- refused by type, so there is no SQL for a blacklist to have missed. The
-- machinery itself -- migration.py, runner.py, predicates.py -- stays
-- protected by that contract, because a task that can edit migration.py can
-- redefine CreateIndexStep and the whitelist becomes a whitelist of a word.
--
-- THE DEPLOY GATE IS UNTOUCHED AND THAT IS DELIBERATE. console/autodeploy
-- refuses any range containing a migration, because deploy.sh migrates BEFORE
-- the code swap and a migration is the one action reverting a commit does not
-- undo. The loop may now WRITE and merge an index migration; a person still
-- runs the deploy that applies it. The human gate moves to where the
-- irreversibility is, from three steps upstream where it was stopping the
-- fleet from noticing the problem at all.
--
-- WHAT IS GIVEN UP, STATED PLAINLY. "No unattended task can alter the schema"
-- was a structural fact needing no judgement, checkable with one grep. It
-- becomes a VERIFIED fact resting on index_migration_only.py being correct and
-- on nobody adding a second work_type to this waiver. That is the whole cost.
--
-- HOW THE FUNCTION BELOW WAS WRITTEN, BECAUSE THE FIRST ATTEMPT WAS WRONG
--
-- FOUR migrations redefine enforce_contract_floor(): 003, 017, 020 and 024.
-- The first version of this file was written from 003, the oldest, and thereby
-- deleted 017's `contract_is_new`, 020's creatable-path grounding and 024's
-- paired-paths rule -- three checks removed by a change that reads, in the
-- diff, as an addition. It also reworded one RAISE in passing.
--
-- The body below is `pg_get_functiondef` of what is RUNNING, with three
-- textual patches applied and every untouched marker asserted present. Diff it
-- against the live definition before believing it; the only differences should
-- be `wtype`, and the waiver conditions in the three refusals.
--
-- The suite caught the first attempt, and caught it sideways: four
-- paired-paths tests went red, a rule this migration never mentions. See
-- principles.md, "Rebuild a function body from the live definition".
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- ------------------------------------------------------------------ 1. column
--
-- NULL means what every row means today: protected for every contract, no
-- exceptions. A non-NULL value names the ONE work_type that may treat this
-- glob as writable, and only for the paths its own contract declares.
ALTER TABLE protected_path_floor
    ADD COLUMN IF NOT EXISTS except_work_type text;

COMMENT ON COLUMN protected_path_floor.except_work_type IS
  'The one work_type this row does not bind, or NULL for all of them. Every '
  'hole in the floor is enumerable with: SELECT * FROM protected_path_floor '
  'WHERE except_work_type IS NOT NULL. A hole that is not in that list does '
  'not exist.';

UPDATE protected_path_floor
   SET except_work_type = 'dd_index_migration'
 WHERE repo = 'deadly-digital-platform'
   AND glob = 'api/analytics/migrations/**';

-- api/alembic/** is NOT waived and must never be: it is the shared schema, and
-- nothing an index on a tenant table needs lives in it.

-- -------------------------------------------------------------- 2. the guard
--
-- Two carve-outs, both keyed on the same row, because the function refuses a
-- contract twice: once for not carrying the glob, and once for declaring a
-- writable path that overlaps it.
CREATE OR REPLACE FUNCTION public.enforce_contract_floor()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
    missing        text;
    clash          text;
    floor_breach   text;
    ungrounded     text;
    unpaired       text;
    shapeless      text;
    contract_is_new boolean;
    -- 040: the contract's work_type, for the one floor row that is
    -- waived for one of them. NULL for a contract that declares none,
    -- which matches no waiver.
    wtype          text := NEW.acceptance_contract->>'work_type';
BEGIN
    contract_is_new := (TG_OP = 'INSERT')
                       OR (NEW.acceptance_contract IS DISTINCT FROM OLD.acceptance_contract);

    IF contract_is_new THEN
        SELECT string_agg(f.glob || ' (' || f.rationale || ')', '; ' ORDER BY f.glob)
          INTO missing
        FROM protected_path_floor f
        WHERE f.repo = NEW.repo
          -- 040: a row waived for THIS work_type is not required of it.
          AND (f.except_work_type IS NULL
               OR f.except_work_type IS DISTINCT FROM wtype)
          AND NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(
                            NEW.acceptance_contract->'protected_paths') p(g)
            WHERE p.g = f.glob);

        IF missing IS NOT NULL THEN
            RAISE EXCEPTION 'contract for % does not protect %', NEW.repo, missing;
        END IF;

        SELECT string_agg(w.g || ' overlaps ' || p.g, '; ')
          INTO clash
        FROM jsonb_array_elements_text(NEW.acceptance_contract->'writable_paths')  w(g)
        CROSS JOIN jsonb_array_elements_text(NEW.acceptance_contract->'protected_paths') p(g)
        WHERE glob_prefix(w.g) <> '' AND glob_prefix(p.g) <> ''
          AND (glob_prefix(w.g) = glob_prefix(p.g)
            OR glob_prefix(p.g) LIKE glob_prefix(w.g) || '/%'
            OR glob_prefix(w.g) LIKE glob_prefix(p.g) || '/%')
          -- 040: and not the waived row, for the waived work_type. The
          -- contract still CARRIES that glob -- dropping it would exempt the
          -- contract from the migration machinery too -- so without this it
          -- would be refused here instead.
          AND NOT EXISTS (
            SELECT 1 FROM protected_path_floor f
            WHERE f.repo = NEW.repo AND f.glob = p.g
              AND f.except_work_type IS NOT NULL
              AND f.except_work_type = wtype
              -- AND THE CONTRACT MUST HAVE SAID SO. The waiver is not
              -- ambient: a contract that does not name the glob in
              -- `floor_waiver` is refused here exactly as before, so the
              -- hole is legible in the file and not only in this table.
              AND NEW.acceptance_contract->>'floor_waiver' = p.g);

        IF clash IS NOT NULL THEN
            RAISE EXCEPTION 'contract is self-contradictory: %', clash;
        END IF;

        -- 020: every creatable glob must sit inside a protected one.
        SELECT string_agg(c.g, '; ')
          INTO ungrounded
        FROM jsonb_array_elements_text(
                 coalesce(NEW.acceptance_contract->'creatable_paths', '[]'::jsonb)) c(g)
        WHERE NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(
                            NEW.acceptance_contract->'protected_paths') p(g)
            WHERE glob_prefix(p.g) <> ''
              AND (glob_prefix(c.g) = glob_prefix(p.g)
                OR glob_prefix(c.g) LIKE glob_prefix(p.g) || '/%'));

        IF ungrounded IS NOT NULL THEN
            RAISE EXCEPTION
              'creatable_paths must narrow protected_paths, and % is not inside '
              'any protected glob. A creatable path that is not already '
              'protected is a grant nobody declared.', ungrounded;
        END IF;

        -- 024, shape: a group that cannot fail is worse than no group.
        SELECT string_agg(msg, '; ')
          INTO shapeless
        FROM (
            SELECT CASE
                     WHEN jsonb_typeof(grp) <> 'object'
                       THEN 'a paired_paths entry is not a mapping'
                     WHEN jsonb_typeof(grp->'paths') <> 'array'
                       OR jsonb_array_length(grp->'paths') < 2
                       THEN 'a paired_paths group has fewer than two paths, so it '
                            'pairs nothing'
                     WHEN coalesce(btrim(grp->>'why'), '') = ''
                       THEN 'a paired_paths group has no why, so a refusal under it '
                            'would not say what to do'
                   END AS msg
            FROM jsonb_array_elements(
                     coalesce(NEW.acceptance_contract->'paired_paths', '[]'::jsonb)) g(grp)
        ) s
        WHERE msg IS NOT NULL;

        IF shapeless IS NOT NULL THEN
            RAISE EXCEPTION 'paired_paths is malformed: %', shapeless;
        END IF;

        -- 024, grounding: a paired path the task cannot write is a check that
        -- cannot fail, and it reads exactly like one that can.
        SELECT string_agg(p.path, '; ')
          INTO unpaired
        FROM (
            SELECT jsonb_array_elements_text(grp->'paths') AS path
            FROM jsonb_array_elements(
                     coalesce(NEW.acceptance_contract->'paired_paths', '[]'::jsonb)) g(grp)
            WHERE jsonb_typeof(grp->'paths') = 'array'
        ) p
        WHERE NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(
                            NEW.acceptance_contract->'writable_paths') w(g)
            WHERE glob_prefix(w.g) <> ''
              AND (p.path = glob_prefix(w.g)
                OR p.path LIKE glob_prefix(w.g) || '/%'));

        IF unpaired IS NOT NULL THEN
            RAISE EXCEPTION
              'paired_paths names % which is not inside any writable path. The '
              'task cannot write it, so the pair can only be satisfied by '
              'writing neither -- a check that cannot fail.', unpaired;
        END IF;
    END IF;

    SELECT string_agg(w.g || ' reaches ' || f.glob || ' (' || f.rationale || ')', '; ')
      INTO floor_breach
    FROM jsonb_array_elements_text(NEW.acceptance_contract->'writable_paths') w(g)
    CROSS JOIN protected_path_floor f
    WHERE f.repo = NEW.repo
      AND glob_prefix(w.g) <> '' AND glob_prefix(f.glob) <> ''
      AND (glob_prefix(w.g) = glob_prefix(f.glob)
        OR glob_prefix(f.glob) LIKE glob_prefix(w.g) || '/%'
        OR glob_prefix(w.g) LIKE glob_prefix(f.glob) || '/%')
      -- 040, AND THIS IS THE STRONGEST OF THE THREE. The two above compare a
      -- contract against ITSELF; this one compares it against the floor table,
      -- so a contract cannot buy a write by editing its own protected_paths.
      -- The waiver is carved out on the same two conditions as before: the row
      -- must be waived for this work_type, AND the contract must have named it.
      AND NOT (f.except_work_type IS NOT NULL
               AND f.except_work_type = wtype
               AND NEW.acceptance_contract->>'floor_waiver' = f.glob);

    IF floor_breach IS NOT NULL THEN
        RAISE EXCEPTION 'contract writes where the floor forbids: %', floor_breach;
    END IF;

    RETURN NEW;
END; $function$;

ALTER FUNCTION enforce_contract_floor() OWNER TO fleet_owner;

-- ---------------------------------------------------------------- assertions
DO $$
DECLARE holes int;
        waived text;
BEGIN
    SELECT count(*) INTO holes
      FROM protected_path_floor WHERE except_work_type IS NOT NULL;
    IF holes <> 1 THEN
        RAISE EXCEPTION
            '040: % holes in the floor, expected exactly 1. Every one of them '
            'is a contract that can write where nothing else may; if a second '
            'is wanted it arrives by its own migration, with its own argument',
            holes;
    END IF;

    SELECT glob INTO waived FROM protected_path_floor
     WHERE except_work_type = 'dd_index_migration';
    IF waived IS DISTINCT FROM 'api/analytics/migrations/**' THEN
        RAISE EXCEPTION '040: the waiver is on %, expected '
                        'api/analytics/migrations/**', waived;
    END IF;

    -- ALEMBIC IS NOT WAIVED, asserted rather than assumed. It is the shared
    -- schema and the one path this exception must never reach.
    IF EXISTS (SELECT 1 FROM protected_path_floor
                WHERE glob = 'api/alembic/**' AND except_work_type IS NOT NULL) THEN
        RAISE EXCEPTION '040: api/alembic/** has been waived. It is the shared '
                        'schema; an index on a tenant table does not need it';
    END IF;

    RAISE NOTICE '040: one waiver, api/analytics/migrations/** for '
                 'dd_index_migration. Everything else is unchanged.';
END $$;

COMMIT;
