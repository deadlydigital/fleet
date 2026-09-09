-- ============================================================================
-- 024_paired_paths.sql  —  "both files or neither", and it has to be able to
--                          bite
--
-- specs/dashboard-comparison-windows.md ends with a requirement no contract
-- could express until now:
--
--   "The follow-up frontend task -- separate, dd_frontend, not in scope here --
--    must land the label change and the proxy change TOGETHER. Widening
--    platform/app/api/analytics/dashboard/route.ts first would let
--    platform/app/(dashboard)/analytics/page.tsx render 'vs previous 366 days'
--    over a year-on-year comparison, which is a worse sentence than the
--    unqualified one this change exists to fix."
--
-- A contract can say what may be written and what may not. It could not say
-- that two files must move together, so that sentence was a note in a spec and
-- nothing checked it. `paired_paths` is the key that checks it, and
-- contracts/checks/paired_paths.py is what reads it against the runner-derived
-- diff -- the same shape as new_test_bites.sh, which reads the diff rather than
-- the agent's account of it.
--
-- THE SHAPE
--
--   paired_paths:
--     - why: one sentence, printed in the refusal
--       paths:
--         - platform/app/api/analytics/dashboard/route.ts
--         - platform/app/(dashboard)/analytics/page.tsx
--
-- Within a group: every path in the diff, or none of them.
--
-- ============================================================================
-- WHAT THIS FILE STOPS, AND WHY IT IS NOT 020's ARGUMENT
-- ============================================================================
--
-- 020 exists because `creatable_paths` GRANTS something: an ungrounded glob is
-- a permission nobody declared, so the database refuses one. `paired_paths`
-- grants nothing -- it only ever adds a requirement -- so the risk is the
-- opposite one, and it is this codebase's recurring failure rather than a new
-- one: A CHECK THAT CANNOT FAIL.
--
-- A group naming a path outside writable_paths is exactly that. The task cannot
-- write that file, so the file is never in the diff, so the group's condition
-- is satisfiable only by writing neither -- and the pairing that was supposed
-- to force two files to move together instead forbids one of them from moving
-- at all, silently, with a green check on the end of it. A typo'd path does the
-- same thing and looks identical.
--
-- So the rule: EVERY PAIRED PATH MUST BE INSIDE A WRITABLE ONE.
--
-- Two more shape rules, for the same reason rather than for tidiness:
--
--   a group of fewer than two paths pairs nothing, and passes always
--   a group with no `why` refuses an agent without telling it what to do,
--   which in practice means the agent drops one of the two files and retries
--
-- What this CANNOT establish is the half specs/dashboard-comparison-windows.md
-- actually cares about: that the label is right. Both files moving together is
-- a fact about the diff and is checkable here. Whether the sentence the page
-- renders describes the window the proxy asked for is a fact about behaviour,
-- and only a render test asserting it can say so -- and the agent chooses what
-- its test asserts. That gap is why the first spec under this key carries
-- `auto_merge: false`. See contracts/dd-analytics-frontend.yaml.
-- ============================================================================

CREATE OR REPLACE FUNCTION enforce_contract_floor() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    missing        text;
    clash          text;
    floor_breach   text;
    ungrounded     text;
    unpaired       text;
    shapeless      text;
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
        OR glob_prefix(w.g) LIKE glob_prefix(f.glob) || '/%');

    IF floor_breach IS NOT NULL THEN
        RAISE EXCEPTION 'contract writes where the floor forbids: %', floor_breach;
    END IF;

    RETURN NEW;
END; $$;
