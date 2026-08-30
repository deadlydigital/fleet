-- ============================================================================
-- 003_tasks.sql  —  Fleet track 3, the task runner
--
-- Track 1 detects. Track 2 proposes. This track executes a spec you wrote
-- and stops at a branch. It never merges and it never deploys: there is no
-- transition in this file that reaches DEPLOYED, and the runner identity is
-- not a member of any role that could write one.
--
-- Two things here are not application concerns and are deliberately not left
-- to the runner:
--
--   * what a task may not touch. The floor is a table, checked by trigger at
--     insert. A contract that fails to protect the suite judging it cannot be
--     stored, so the runner cannot be pointed at one.
--   * who may move a task to a reviewed state. A runner that could set MERGED
--     is an agent marking its own work as passing, which is the rule 001 and
--     002 both already turn on.
--
-- Target: PostgreSQL 13+ (RDS 15.17), applied with the listmonk identity.
-- ============================================================================

-- ============================================================ 1. ROLES
--
-- fleet_task_runner   claims a task, opens its run, records the branch, and
--                     moves the task between the states a machine is allowed
--                     to move it between. It is not a member of fleet_agent
--                     or fleet_verifier: the patch step and the verification
--                     step are written by those identities, so the thing that
--                     proposes a diff is not the thing that certifies it.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_task_runner') THEN
        CREATE ROLE fleet_task_runner NOLOGIN;
    END IF;
END $$;

-- ============================================================ 2. THE FLOOR
--
-- The set of paths no task may declare writable, per repo. Data, not code,
-- for the same reason no threshold in track 1 is a literal: adding a repo or
-- a newly protected tree is an INSERT, and the rule that made it protected
-- stays next to it.
--
-- rationale is NOT NULL because a protected path whose reason has been lost
-- is a protected path someone will eventually delete.
CREATE TABLE protected_path_floor (
    repo      text NOT NULL,
    glob      text NOT NULL,
    rationale text NOT NULL,
    PRIMARY KEY (repo, glob)
);

INSERT INTO protected_path_floor (repo, glob, rationale) VALUES
 ('deadly-digital-platform', 'api/tests/**',
  'the suite that judges the work'),
 ('deadly-digital-platform', 'api/pytest.ini',
  'suite configuration; an ignore rule here passes everything without touching a test'),
 ('deadly-digital-platform', 'api/ruff.toml',
  'lint configuration, same reason as pytest.ini'),
 ('deadly-digital-platform', 'api/alembic/**',
  'a schema change is a separate decision from a feature'),
 ('deadly-digital-platform', 'api/analytics/migrations/**',
  'the analytics schema, same reason as alembic'),
 ('deadly-digital-platform', 'platform/__tests__/**',
  'the platform suite'),
 ('deadly-digital-platform', 'platform/vitest.config.ts',
  'platform suite configuration'),
 ('deadly-digital-platform', 'platform/playwright.config.ts',
  'platform end-to-end configuration');

-- ============================================================ 3. TASKS

CREATE TABLE tasks (
    id                  bigserial PRIMARY KEY,
    queue               text        NOT NULL DEFAULT 'default',
    title               text        NOT NULL CHECK (length(btrim(title)) > 0),
    spec_md             text        NOT NULL CHECK (length(btrim(spec_md)) > 0),
    repo                text        NOT NULL,
    base_branch         text        NOT NULL DEFAULT 'main',
    acceptance_contract jsonb       NOT NULL,
    status              text        NOT NULL DEFAULT 'QUEUED'
                        CHECK (status IN ('QUEUED','RUNNING','READY_FOR_REVIEW',
                                          'FAILED','ABANDONED',
                                          'MERGED','REJECTED','REWORK')),
    priority            int         NOT NULL DEFAULT 100,
    objective_ref       text,
    max_cost_gbp        numeric(10,4) NOT NULL CHECK (max_cost_gbp > 0),

    -- A task cannot exist without a wall-clock cap. The ceiling is in the
    -- constraint rather than in configuration: a stuck agent burning budget
    -- in a loop is the failure this guards, and a cap that can be raised
    -- without a migration will be raised on the morning something needs
    -- longer.
    timeout_seconds     int         NOT NULL DEFAULT 1800
                        CHECK (timeout_seconds > 0 AND timeout_seconds <= 3600),

    created_at          timestamptz NOT NULL DEFAULT now(),
    claimed_at          timestamptz,
    completed_at        timestamptz,
    branch_name         text,
    attempts            int         NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts        int         NOT NULL DEFAULT 1 CHECK (max_attempts >= 1),

    CONSTRAINT tasks_attempts_ck CHECK (attempts <= max_attempts),

    -- The shape the runner relies on. A contract missing any of these is a
    -- contract the runner would have to guess at.
    CONSTRAINT tasks_contract_shape_ck CHECK (
        jsonb_typeof(acceptance_contract->'writable_paths')  = 'array'
    AND jsonb_typeof(acceptance_contract->'protected_paths') = 'array'
    AND jsonb_typeof(acceptance_contract->'verification')    = 'array'
    AND jsonb_array_length(acceptance_contract->'verification') > 0
    AND jsonb_array_length(acceptance_contract->'writable_paths') > 0
    AND (acceptance_contract->>'max_diff_lines')::int > 0
    AND acceptance_contract->>'work_type' IS NOT NULL)
);

COMMENT ON COLUMN tasks.timeout_seconds IS
  'Wall-clock cap for one attempt. Enforced by the runner, bounded here.';
COMMENT ON COLUMN tasks.priority IS
  'Lower is sooner. Claim order is (priority, id), so it is stable.';

CREATE INDEX tasks_claimable_idx ON tasks (queue, priority, id)
    WHERE status = 'QUEUED';
CREATE INDEX tasks_review_idx ON tasks (status, completed_at DESC)
    WHERE status = 'READY_FOR_REVIEW';

-- ============================================================ 4. RUNS, REUSED
--
-- One task maps to one run. `runs` and `run_steps` already carry acceptance
-- boundaries, step authority and budget reservation, and a parallel log for
-- this track would be a second place for the same facts to disagree.
--
-- 001 required every run to name an issue, because every run then came from
-- a detection. Feature work has no issue to name. Rather than invent one --
-- a synthetic issue would be read by the coverage predicates and by track
-- 2's findings as a real open problem -- the column becomes nullable and a
-- run must name exactly one origin. Every row written before this migration
-- names an issue and stays valid.
ALTER TABLE runs ALTER COLUMN issue_id DROP NOT NULL;
ALTER TABLE runs ADD COLUMN task_id bigint REFERENCES tasks(id);
ALTER TABLE runs ADD CONSTRAINT runs_one_origin_ck
    CHECK ((issue_id IS NOT NULL) <> (task_id IS NOT NULL));

COMMENT ON COLUMN runs.task_id IS
  'Set for track 3 runs. Exactly one of issue_id and task_id is non-null.';

-- The 001 index (one active run per issue) is unaffected: task runs carry a
-- null issue_id and a unique index does not constrain nulls. This is its
-- counterpart, and it is what makes "one task per tick, serial" true even if
-- a second runner is started by mistake.
CREATE UNIQUE INDEX runs_one_active_per_task ON runs (task_id)
    WHERE status IN ('ACTIVE','AWAITING_HUMAN');

-- A run may not carry more budget than the task authorised. Without this the
-- runner could open its own run with any spend_limit it liked, and
-- max_cost_gbp would be decoration.
CREATE FUNCTION enforce_task_run_budget() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE cap numeric(10,4);
BEGIN
    IF NEW.task_id IS NULL THEN RETURN NEW; END IF;
    SELECT max_cost_gbp INTO cap FROM tasks WHERE id = NEW.task_id;
    IF NEW.spend_limit_gbp > cap THEN
        RAISE EXCEPTION 'run spend limit % exceeds task %''s max_cost_gbp %',
            NEW.spend_limit_gbp, NEW.task_id, cap;
    END IF;
    RETURN NEW;
END; $$;

CREATE TRIGGER runs_task_budget BEFORE INSERT OR UPDATE ON runs
    FOR EACH ROW EXECUTE FUNCTION enforce_task_run_budget();

-- ============================================================ 5. TRANSITIONS
--
-- The state machine, as data. Every legal move names the role allowed to
-- make it. What this table does not contain is the point of it: there is no
-- row taking the runner from READY_FOR_REVIEW to anything, so the merge
-- decision cannot be made by the process that produced the branch.
CREATE TABLE task_transitions (
    from_status   text NOT NULL,
    to_status     text NOT NULL,
    required_role text NOT NULL,
    note          text NOT NULL,
    PRIMARY KEY (from_status, to_status)
);

INSERT INTO task_transitions (from_status, to_status, required_role, note) VALUES
 ('QUEUED',           'RUNNING',          'fleet_task_runner', 'claimed'),
 ('RUNNING',          'READY_FOR_REVIEW', 'fleet_task_runner', 'branch pushed'),
 ('RUNNING',          'FAILED',           'fleet_task_runner', 'attempts exhausted'),
 ('RUNNING',          'QUEUED',           'fleet_task_runner', 'requeued below max_attempts'),
 ('QUEUED',           'ABANDONED',        'fleet_console',     'withdrawn before it ran'),
 ('RUNNING',          'ABANDONED',        'fleet_console',     'withdrawn mid-flight'),
 ('FAILED',           'ABANDONED',        'fleet_console',     'given up on'),
 ('FAILED',           'QUEUED',           'fleet_console',     'retried by hand'),
 ('READY_FOR_REVIEW', 'MERGED',           'fleet_console',     'you merged it'),
 ('READY_FOR_REVIEW', 'REJECTED',         'fleet_console',     'you threw it away'),
 ('READY_FOR_REVIEW', 'REWORK',           'fleet_console',     'you sent it back'),
 ('REWORK',           'QUEUED',           'fleet_console',     'requeued with feedback');

CREATE FUNCTION enforce_task_transition() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE req text;
BEGIN
    IF NEW.status = OLD.status THEN RETURN NEW; END IF;

    SELECT required_role INTO req FROM task_transitions
    WHERE from_status = OLD.status AND to_status = NEW.status;

    IF req IS NULL THEN
        RAISE EXCEPTION 'task % may not move % -> %', OLD.id, OLD.status, NEW.status;
    END IF;
    IF NOT pg_has_role(current_user, req, 'MEMBER') THEN
        RAISE EXCEPTION '% may not move task % -> % (requires %)',
            current_user, OLD.status, NEW.status, req;
    END IF;

    -- A branch is what this track produces. Claiming it is ready without one
    -- is the one lie the status column could otherwise tell.
    IF NEW.status = 'READY_FOR_REVIEW' THEN
        IF NEW.branch_name IS NULL THEN
            RAISE EXCEPTION 'task % cannot be ready for review without a branch',
                OLD.id;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM runs WHERE task_id = OLD.id) THEN
            RAISE EXCEPTION 'task % cannot be ready for review without a run',
                OLD.id;
        END IF;
    END IF;

    RETURN NEW;
END; $$;

CREATE TRIGGER tasks_transition BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION enforce_task_transition();

-- ============================================================ 6. THE CONTRACT
--
-- Two checks, both at write time, because a contract is only useful before
-- the work starts.
--
-- The first is that the floor is named. Not implied -- named, literally, in
-- protected_paths. An implicit floor is one the person reading the contract
-- cannot see, and the contract is the artifact a review reads to find out
-- what the agent was allowed to do.
--
-- The second is that nothing writable overlaps it. 'api/**' writable and
-- 'api/tests/**' protected is a contract that contradicts itself, and the
-- runner would have to pick a winner at diff time.
CREATE FUNCTION glob_prefix(p_glob text) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
    SELECT rtrim(regexp_replace(p_glob, '\*.*$', ''), '/') ;
$$;

CREATE FUNCTION enforce_contract_floor() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    missing text;
    clash   text;
BEGIN
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

    RETURN NEW;
END; $$;

CREATE TRIGGER tasks_contract_floor BEFORE INSERT OR UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION enforce_contract_floor();

-- ============================================================ 7. IMMUTABILITY
--
-- The contract may be edited while the task is waiting, and never once it has
-- been handed to an agent. A boundary that can move while the work is inside
-- it is not a boundary.
--
-- spec_md is append-only. Rework feedback is the only learning signal this
-- design has, and an UPDATE that could shorten it would lose the record of
-- why the last attempt was wrong.
CREATE FUNCTION guard_task_immutability() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.acceptance_contract IS DISTINCT FROM OLD.acceptance_contract
       AND OLD.status <> 'QUEUED' THEN
        RAISE EXCEPTION
          'the acceptance contract of task % is frozen while it is %',
          OLD.id, OLD.status;
    END IF;

    IF NEW.spec_md <> OLD.spec_md AND left(NEW.spec_md, length(OLD.spec_md)) <> OLD.spec_md
    THEN
        RAISE EXCEPTION 'spec_md is append-only (task %)', OLD.id;
    END IF;

    IF NEW.repo <> OLD.repo OR NEW.base_branch <> OLD.base_branch THEN
        RAISE EXCEPTION 'task % may not change repo or base branch', OLD.id;
    END IF;

    RETURN NEW;
END; $$;

CREATE TRIGGER tasks_immutable BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION guard_task_immutability();

-- ============================================================ 8. CLAIMING
--
-- SKIP LOCKED, as scheduled_checks does it, so two runners started by mistake
-- take different tasks rather than the same one.
--
-- SECURITY INVOKER on purpose. A definer function here would run as the owner
-- and satisfy the transition trigger's role check no matter who called it,
-- which would make section 5 advisory.
CREATE FUNCTION claim_task(p_queue text DEFAULT NULL) RETURNS bigint
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE t bigint;
BEGIN
    SELECT id INTO t FROM tasks
    WHERE status = 'QUEUED'
      AND (p_queue IS NULL OR queue = p_queue)
      AND attempts < max_attempts
    ORDER BY priority, id
    FOR UPDATE SKIP LOCKED
    LIMIT 1;

    IF t IS NULL THEN RETURN NULL; END IF;

    UPDATE tasks
       SET status = 'RUNNING', claimed_at = now(), attempts = attempts + 1
     WHERE id = t;

    RETURN t;
END; $$;

-- Rework in one step, because it is one decision. The note is appended with
-- its date, so a task on its third pass reads as a conversation.
CREATE FUNCTION rework_task(p_task_id bigint, p_note text) RETURNS void
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF length(btrim(coalesce(p_note, ''))) = 0 THEN
        RAISE EXCEPTION 'rework requires a note: the note is the whole point';
    END IF;

    UPDATE tasks
       SET status  = 'REWORK',
           spec_md = spec_md || E'\n\n---\n\n## Rework, '
                     || to_char(now(), 'YYYY-MM-DD HH24:MI') || E'\n\n' || p_note
     WHERE id = p_task_id AND status = 'READY_FOR_REVIEW';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'task % is not awaiting review', p_task_id;
    END IF;

    UPDATE tasks
       SET status = 'QUEUED', claimed_at = NULL, completed_at = NULL,
           branch_name = NULL
     WHERE id = p_task_id;
END; $$;

-- ============================================================ 9. OWNERSHIP

ALTER FUNCTION enforce_task_run_budget()   OWNER TO fleet_owner;
ALTER FUNCTION enforce_task_transition()   OWNER TO fleet_owner;
ALTER FUNCTION enforce_contract_floor()    OWNER TO fleet_owner;
ALTER FUNCTION guard_task_immutability()   OWNER TO fleet_owner;
ALTER FUNCTION glob_prefix(text)           OWNER TO fleet_owner;

-- ============================================================ 10. GRANTS

REVOKE ALL ON tasks, task_transitions, protected_path_floor FROM PUBLIC;

-- Functions are EXECUTE TO PUBLIC by default, which would make the grants
-- below decorative. Revoked first, exactly as 001 does for the budget
-- functions.
REVOKE ALL ON FUNCTION claim_task(text)             FROM PUBLIC;
REVOKE ALL ON FUNCTION rework_task(bigint, text)    FROM PUBLIC;

-- The orchestrator. It reads the whole task, moves it between machine
-- states, and records the branch. It cannot insert a task -- the queue is
-- written by you -- and it cannot delete one.
GRANT SELECT ON tasks TO fleet_task_runner;
GRANT UPDATE (status, claimed_at, completed_at, branch_name, attempts)
      ON tasks TO fleet_task_runner;
GRANT SELECT ON task_transitions, protected_path_floor TO fleet_task_runner;
-- SELECT on runs as well as INSERT: the transition trigger asks whether a
-- run exists before letting a task be called ready, and INSERT ... RETURNING
-- id reads the column it returns. Without it the guard fails closed on a
-- permission error rather than on the condition it is checking.
GRANT SELECT, INSERT ON runs TO fleet_task_runner;
GRANT UPDATE (status, completed_at) ON runs TO fleet_task_runner;
GRANT USAGE, SELECT ON SEQUENCE runs_id_seq TO fleet_task_runner;
GRANT EXECUTE ON FUNCTION claim_task(text) TO fleet_task_runner;

-- The two identities that write steps. They read the task because the spec
-- and the contract are their input, and they hold no write on it at all.
GRANT SELECT ON tasks, protected_path_floor TO fleet_agent, fleet_verifier;

-- 001 created step_authority and granted it to nobody, so enforce_step_authority()
-- raised "permission denied for table step_authority" instead of the message it
-- was written to raise. It failed closed, so nothing was ever unguarded -- but
-- the first agent to write a step would have been stopped by the wrong error,
-- and the rule it enforces is one this track depends on. Additive grant, in
-- the same spirit as 002's grants onto 001's tables.
GRANT SELECT ON step_authority TO fleet_agent, fleet_verifier, fleet_task_runner;

-- The console owns the queue and every reviewed state.
GRANT SELECT, INSERT, UPDATE, DELETE ON tasks TO fleet_console;
GRANT SELECT ON task_transitions, protected_path_floor TO fleet_console;
-- The console reviews branches, so it reads the run behind one. It is the
-- same read the transition trigger performs on its behalf.
GRANT SELECT ON runs, run_steps TO fleet_console;
GRANT USAGE, SELECT ON SEQUENCE tasks_id_seq TO fleet_console;
GRANT EXECUTE ON FUNCTION rework_task(bigint, text) TO fleet_console;

-- Track 2 reads this track's output, as it reads track 1's: to notice that an
-- objective has had nothing said about it. It does not write here.
GRANT SELECT ON tasks TO fleet_detector_reader;
