-- ============================================================================
-- 017_email_floor.sql  —  Fleet does not go near email, as a refusal
--
-- specs/unattended-operation.md §2. The fleet is about to merge and deploy
-- without a person in the loop, and the email platform is being resurrected
-- separately. "Do not touch email" has to be a thing the database refuses,
-- not a thing a contract author remembers.
--
-- WHY A PATH LIST DOES NOT ALREADY DO THIS
--
-- api/app.py is 19,300 lines and 180 endpoints, THIRTY-NINE of them email:
-- 16 /api/flows, 14 /api/campaigns, 6 /api/deliverability, 3 /api/suppression.
-- And api/app.py is declared writable in
-- contracts/deadly-digital-platform-api.yaml. So a task under that contract
-- today may rewrite the campaign sender and the boundary check passes clean.
--
-- The email platform is not a module that can be excluded. It is interleaved
-- in the single most-writable file in the repository, so the file goes on the
-- floor whole. Analytics work does not need it: tasks 26 and 28 both wrote
-- only under api/analytics/.
--
-- THE TWO A PATH LIST WOULD MISS
--
-- api/analytics/routes/interventions.py and
-- api/analytics/services/trigger_router.py sit INSIDE the analytics tree the
-- fleet owns, and trigger_router.py already writes intervention rows with
-- channel='email'. It sends nothing today -- it says so in its own docstring.
-- It is the most likely place for an autonomous fleet to grow into the email
-- platform by accident rather than by decision, and that is the whole reason
-- it is here.
--
-- ============================================================================
-- PART 1: the floor is a property of the CONTRACT, not of every UPDATE
--
-- enforce_contract_floor() fires BEFORE INSERT OR UPDATE and re-checks the
-- whole contract every time. acceptance_contract is frozen once a task leaves
-- QUEUED (guard_task_immutability), so on a status transition it is
-- re-validating something that cannot have changed -- and tightening the floor
-- therefore makes every IN-FLIGHT task unacceptable, retroactively, for a
-- contract that was legal when it was written.
--
-- Measured before writing this: task 28 is READY_FOR_REVIEW under a contract
-- with none of the four globs below, and Accept would have raised
-- 'contract for deadly-digital-platform does not protect ...' on the status
-- UPDATE. A floor that cannot be tightened without stranding queued work is a
-- floor nobody tightens.
--
-- So the two halves are separated by what they are actually about:
--
--   missing-from-protected   checked when the contract is SET (INSERT, or an
--                            UPDATE that changes it). It is a statement about
--                            the contract.
--
--   writable-hits-the-floor  checked on EVERY write, always. It is a statement
--                            about what the task may do, and it is the half
--                            that matters for an in-flight task: a frozen
--                            contract whose writable_paths reach a newly
--                            floored file must still be refused.
--
-- This is strictly tighter than what it replaces, not looser. The old code
-- never compared writable_paths against the floor at all -- only against the
-- contract's own protected_paths, which a contract author chooses.
-- ============================================================================

CREATE OR REPLACE FUNCTION enforce_contract_floor() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    missing        text;
    clash          text;
    floor_breach   text;
    contract_is_new boolean;
BEGIN
    contract_is_new := (TG_OP = 'INSERT')
                       OR (NEW.acceptance_contract IS DISTINCT FROM OLD.acceptance_contract);

    -- (1) Every floor glob must appear in protected_paths. Only when the
    --     contract is being set: see the header.
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

        -- (2) The contract must not contradict itself.
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
    END IF;

    -- (3) ALWAYS, including a status transition on a frozen contract: no
    --     writable path may reach a floored one. This is the half that has to
    --     hold for work already in flight when the floor moves.
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


-- ============================================================================
-- PART 2: the email surface
--
-- Rationales are load-bearing: enforce_contract_floor() prints them in the
-- refusal, so they are what the next person reads when a task will not insert.
-- ============================================================================

INSERT INTO protected_path_floor (repo, glob, rationale) VALUES
 ('deadly-digital-platform', 'api/app.py',
  'the email platform is interleaved here - 39 of its 180 endpoints are flows, campaigns, deliverability and suppression; Fleet does not go near email'),
 ('deadly-digital-platform', 'api/services/email_sender.py',
  'the sender itself'),
 ('deadly-digital-platform', 'api/worker.py',
  '24 email tasks; already protected by contract, floored here so it is unconditional'),
 ('deadly-digital-platform', 'api/analytics/routes/interventions.py',
  'inside the analytics tree, but it is the email side of churn - this is where analytics grows into email by accident'),
 ('deadly-digital-platform', 'api/analytics/services/trigger_router.py',
  'writes intervention rows with channel=email; the day it sends, it is the email platform')
ON CONFLICT (repo, glob) DO NOTHING;
