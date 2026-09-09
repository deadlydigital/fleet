-- ============================================================================
-- 020_creatable_paths.sql  —  an exception that can only ever narrow
--
-- specs/unattended-operation.md §3.2 added `creatable_paths` to the contract:
-- globs where a file may be ADDED and may not be modified, even when a
-- protected glob covers it. It exists so an agent can write ONE new test,
-- because `api/tests/**` is floored and a feature that lands with no test
-- covering it makes "675 tests passed" mean "broke nothing" while reading as
-- "verified".
--
-- runner/boundary.py grants that exception on the diff status: `A` and a
-- matching glob, permitted; anything else refused exactly as before.
--
-- WHAT THIS FILE STOPS
--
-- The database knows nothing about `creatable_paths` -- the floor checks
-- protected_paths and writable_paths, so a contract could carry
-- `creatable_paths: ['**']` and the trigger would be satisfied while the
-- boundary let the agent create anything anywhere, including inside the
-- floored trees the whole design rests on.
--
-- The rule: EVERY CREATABLE GLOB MUST BE COVERED BY A PROTECTED ONE.
--
-- That makes `creatable_paths` strictly a narrowing of `protected_paths` and
-- never a widening of `writable_paths`. A creatable glob naming somewhere not
-- already protected is either pointless -- writable_paths would cover it -- or
-- it is a grant nobody declared, and the second is the one worth refusing.
--
-- It also means the blast radius is bounded by a list the floor already
-- polices: to make something creatable you must first protect it, and the
-- floor decides what protection cannot be dropped.
-- ============================================================================

CREATE OR REPLACE FUNCTION enforce_contract_floor() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    missing        text;
    clash          text;
    floor_breach   text;
    ungrounded     text;
    contract_is_new boolean;
BEGIN
    contract_is_new := (TG_OP = 'INSERT')
                       OR (NEW.acceptance_contract IS DISTINCT FROM OLD.acceptance_contract);

    IF contract_is_new THEN
        SELECT string_agg(f.glob || ' (' || f.rationale || ')', '; ' ORDER BY f.glob)
          INTO missing
        FROM protected_path_floor f
        WHERE f.repo = NEW.repo
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
            OR glob_prefix(w.g) LIKE glob_prefix(p.g) || '/%');

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
    END IF;

    SELECT string_agg(w.g || ' reaches ' || f.glob || ' (' || f.rationale || ')', '; ')
      INTO floor_breach
    FROM jsonb_array_elements_text(NEW.acceptance_contract->'writable_paths') w(g)
    CROSS JOIN protected_path_floor f
    WHERE f.repo = NEW.repo
      AND glob_prefix(w.g) <> '' AND glob_prefix(f.glob) <> ''
      AND (glob_prefix(w.g) = glob_prefix(f.glob)
        OR glob_prefix(f.glob) LIKE glob_prefix(w.g) || '/%'
        OR glob_prefix(w.g) LIKE glob_prefix(f.glob) || '/%');

    IF floor_breach IS NOT NULL THEN
        RAISE EXCEPTION 'contract writes where the floor forbids: %', floor_breach;
    END IF;

    RETURN NEW;
END; $$;
