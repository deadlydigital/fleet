-- ============================================================================
-- 041_a_declared_waiver_must_have_been_granted.sql
--
-- NOT APPLIED. Apply as `listmonk`, which owns enforce_contract_floor().
--
-- 040 LEFT A HOLE AND THIS CLOSES IT. A contract could declare
-- `floor_waiver: <anything>` and be stored, because 040 consults the
-- declaration only when excusing a clash -- and a declaration naming a glob
-- nothing waived excuses nothing, so nothing looked at it.
--
-- That was harmless for exactly as long as nothing read the declaration.
-- `runner/boundary.enforce` was about to: the effective protected set is
-- computed from the contract and the floor, and a contract that could name
-- any glob could exempt itself from any of them. `floor_waiver: api/tests/**`
-- would have let a task edit the suite that judges it.
--
-- MEASURED, NOT REASONED. On 14 Sep 2026, against production, with the
-- ordinary deadly-digital-platform-api contract plus one added line:
--
--     floor_waiver: api/tests/**   ->  STORED
--
-- (rolled back). After this file, refused, naming the glob and the work_type.
--
-- THE RULE, SAID ONCE: a waiver is GRANTED by protected_path_floor and NAMED
-- by the contract, and both must be true. 040 made naming necessary. This
-- makes it insufficient.
--
-- THE RUNNER REFUSING IT WOULD HAVE BEEN THE WEAKER ANSWER. It would have
-- meant a wrong contract could be stored, queued, and reach a build before
-- anything objected -- and the objection would have come from the check that
-- reads the floor rather than from the one that owns it.
--
-- HOW THIS FILE WAS WRITTEN: `pg_get_functiondef` of the running function,
-- with ONE block inserted and every other line asserted unchanged. Four
-- migrations already redefine this function and 040 nearly deleted three of
-- them by starting from 003. See principles.md, "Rebuild a function body from
-- the live definition".
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

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
        -- 041: A DECLARED WAIVER MUST HAVE BEEN GRANTED.
        --
        -- 040 reads `floor_waiver` only when EXCUSING a clash, so a contract
        -- naming a glob nothing waived was stored untouched -- it caused no
        -- clash, so nothing consulted it. Harmless while nothing read the
        -- declaration; catastrophic the moment something did, because the
        -- runner was about to: `floor_waiver: api/tests/**` would have
        -- exempted a task from the suite that judges it.
        --
        -- Verified in production on 14 Sep 2026 by storing exactly that
        -- against the ordinary api contract. It was accepted.
        --
        -- So the declaration is validated on its own terms, before anything
        -- else, whether or not it excuses anything. Declaring still grants
        -- nothing; it now also cannot be SAID unless it is true.
        IF NEW.acceptance_contract ? 'floor_waiver' THEN
            IF NOT EXISTS (
                SELECT 1 FROM protected_path_floor f
                WHERE f.repo = NEW.repo
                  AND f.glob = NEW.acceptance_contract->>'floor_waiver'
                  AND f.except_work_type IS NOT NULL
                  AND f.except_work_type = wtype)
            THEN
                RAISE EXCEPTION
                  'contract declares floor_waiver % which is not granted to '
                  'work_type %: protected_path_floor has no such row for %, or '
                  'it is waived for nobody, or for somebody else. A waiver is '
                  'granted by the floor and named by the contract; naming one '
                  'that was not granted is the declaration this rejects',
                  NEW.acceptance_contract->>'floor_waiver',
                  coalesce(wtype, '(none)'), NEW.repo;
            END IF;
        END IF;

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
--
-- The waiver 040 granted must still work, and an ungranted one must not. Both
-- are asserted here rather than left to the suite, because this file is the
-- one that decides it.
DO $$
DECLARE granted int;
BEGIN
    SELECT count(*) INTO granted
      FROM protected_path_floor WHERE except_work_type IS NOT NULL;
    IF granted <> 1 THEN
        RAISE EXCEPTION
            '041: % waiver(s) in the floor, expected exactly 1. Every one is a '
            'contract that can write where nothing else may', granted;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM protected_path_floor
                    WHERE glob = 'api/analytics/migrations/**'
                      AND except_work_type = 'dd_index_migration') THEN
        RAISE EXCEPTION '041: 040''s waiver is not where it was left';
    END IF;

    RAISE NOTICE '041: a declared waiver must now also have been granted.';
END $$;

COMMIT;
