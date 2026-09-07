-- ============================================================================
-- 013_approval_surface.sql  —  candidates, their dispositions, and the ceilings
--
-- Spec: specs/approval-surface.md.
--
-- THIS FILE ADDS THE FIRST CEILING ON TASK CREATION, AND THE ORDER MATTERS
--
-- There is no production path that creates a task today: `INSERT INTO tasks`
-- appears in seven files and every one is under tests/. There is also no runner
-- timer -- the runner is hand-invoked. So the thing that currently prevents an
-- overnight batch of wrong branches is that a person types a command, which is
-- not a control anyone chose.
--
-- The ceilings below are what replace that, and §6.1 of the spec makes the
-- ordering a requirement rather than a preference: THEY MUST EXIST BEFORE
-- `fleet-runner.timer` DOES. A timer is a one-line unit file and therefore the
-- easiest thing here to add casually.
--
-- WHY THE CAPS ARE LITERALS IN A FUNCTION AND NOT ROWS IN A CONFIG TABLE
--
-- Same reason 003 gives for `timeout_seconds <= 3600`: "a cap that can be
-- raised without a migration will be raised on the morning something needs
-- longer." Both numbers here are GUESSES and are labelled as such in the spec;
-- raising one should cost a migration and leave a commit behind.
--
-- Target: PostgreSQL 15+, same floor as 010 and 012.
-- ============================================================================

\set ON_ERROR_STOP on

-- ============================================================ 1. CEILINGS

--: The most tasks that may sit QUEUED at once, across every work type.
--: A GUESS, in the way the manifest settle lag and the level-3 id cap are
--: guesses. Spec §6.2: draft-spec tasks and the code tasks they produce both
--: count against this, deliberately -- exempting one kind would make the
--: ceiling describe something other than what is running.
CREATE OR REPLACE FUNCTION fleet_max_queued_tasks() RETURNS int
LANGUAGE sql IMMUTABLE AS $$ SELECT 5 $$;

--: The most candidates that may be approved under ONE decision. Equal to the
--: queue depth on purpose: a batch that cannot be queued is a batch that should
--: not have been approved.
--:
--: This is the cap that keeps §4's single batch reason honest. Four related
--: items can share one rationale; twenty unrelated ones cannot, and the reason
--: becomes a paragraph pretending to be one. The cap is on how many may be
--: TICKED at once, never on how many may be listed for review -- generating
--: candidates is cheap and reviewing them is the work.
CREATE OR REPLACE FUNCTION fleet_max_approval_batch() RETURNS int
LANGUAGE sql IMMUTABLE AS $$ SELECT 5 $$;

-- ============================================================ 2. TABLES

CREATE TABLE IF NOT EXISTS candidate_batches (
    id              bigserial PRIMARY KEY,

    -- Where the list came from, and AT WHAT COMMIT. A findings document moves;
    -- a batch attributable to "the Metorik gap list" without a sha is
    -- attributable to a morning. Same discipline as evidence_query_version on
    -- observations and as_of on brief_claims.
    source_document text NOT NULL CHECK (length(btrim(source_document)) > 0),
    source_sha      text NOT NULL CHECK (length(btrim(source_sha)) > 0),
    source_repo     text NOT NULL,

    generated_at    timestamptz NOT NULL DEFAULT now(),
    generated_by    text NOT NULL DEFAULT current_user,
    note            text
);

COMMENT ON TABLE candidate_batches IS
  'One list of candidate work items, attributable to a findings document at a '
  'commit. A batch with no candidates means a producer ran and found nothing, '
  'which is not the same as a producer that did not run.';

CREATE TABLE IF NOT EXISTS candidates (
    id            bigserial PRIMARY KEY,
    batch_id      bigint NOT NULL REFERENCES candidate_batches(id),

    title         text NOT NULL CHECK (length(btrim(title)) > 0),
    rationale     text NOT NULL CHECK (length(btrim(rationale)) > 0),
    repo          text NOT NULL CHECK (length(btrim(repo)) > 0),

    -- NO work_type COLUMN, AND ITS ABSENCE IS THE DECISION.
    --
    -- The draft spec chooses it (spec §1, decided 7 Sep 2026). A producer
    -- reading a findings document does not know whether an item is a code
    -- change or an investigation, and requiring it here would make the producer
    -- guess at exactly the thing the spec-writing step exists to determine.
    --
    -- The cost is that nothing upstream establishes the work_type names a real
    -- contract, so the draft-spec check has to. That check already validates
    -- paths against the tree; validating the contract exists is the same kind
    -- of assertion in the same place.

    objective_ref text,

    -- A CITATION, NOT A COPY, and each entry carries what it was read at.
    evidence      jsonb NOT NULL DEFAULT '[]'::jsonb
                  CHECK (jsonb_typeof(evidence) = 'array'),

    -- Advisory, and explicitly not the contract. Input to the draft-spec path
    -- check. Empty is a claim that the finding named no paths, not that none
    -- exist.
    suggested_paths text[] NOT NULL DEFAULT '{}',

    est_cost_gbp   numeric(10,4) CHECK (est_cost_gbp IS NULL OR est_cost_gbp > 0),
    est_diff_lines int CHECK (est_diff_lines IS NULL OR est_diff_lines > 0),

    -- THREE DISPOSITIONS, and the middle one is the point.
    --   PENDING   not yet reviewed
    --   APPROVED  became a draft-spec task
    --   NOT_NOW   not rejected and NOT GONE -- carried into the next batch by
    --             the surface, retaining its original batch_id, so a candidate
    --             carried five times is itself a finding
    --   REJECTED  will not be done, reason required, kept forever
    disposition   text NOT NULL DEFAULT 'PENDING'
                  CHECK (disposition IN ('PENDING','APPROVED','NOT_NOW','REJECTED')),
    disposition_reason text,

    -- The batch approval this candidate was ticked under. NULL until decided.
    -- The cap in section 3 counts on this column.
    approval_decision_id bigint REFERENCES decision_log(id),

    decided_at    timestamptz,
    spec_task_id  bigint REFERENCES tasks(id),
    work_task_id  bigint REFERENCES tasks(id),

    -- Rejections are the informative half and this is where the typing goes.
    CONSTRAINT candidates_rejection_says_why_ck CHECK (
        disposition <> 'REJECTED'
        OR (disposition_reason IS NOT NULL
            AND length(btrim(disposition_reason)) > 0)),

    -- An approved candidate cites the decision that approved it. Without this
    -- the batch reason in decision_log would be unattached to what it approved.
    CONSTRAINT candidates_approved_cites_decision_ck CHECK (
        disposition <> 'APPROVED' OR approval_decision_id IS NOT NULL),

    -- PENDING is the only state a producer may emit; everything else is a
    -- review outcome and carries a timestamp.
    CONSTRAINT candidates_decided_is_stamped_ck CHECK (
        (disposition = 'PENDING') = (decided_at IS NULL))
);

COMMENT ON COLUMN candidates.disposition IS
  'NOT_NOW is not a rejection and is not discarded: the surface carries it into '
  'the next batch keeping its original batch_id, so repetition is visible.';

CREATE INDEX IF NOT EXISTS candidates_batch_idx ON candidates (batch_id, id);
CREATE INDEX IF NOT EXISTS candidates_pending_idx ON candidates (disposition, id)
    WHERE disposition IN ('PENDING','NOT_NOW');
CREATE INDEX IF NOT EXISTS candidates_decision_idx
    ON candidates (approval_decision_id) WHERE approval_decision_id IS NOT NULL;

-- ============================================================ 3. ENFORCEMENT

-- A producer may not pre-approve, and may not write to `tasks`. The first is
-- enforceable here; the second is a grant (section 4).
CREATE OR REPLACE FUNCTION enforce_candidate_arrives_pending() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.disposition <> 'PENDING' THEN
        RAISE EXCEPTION 'a candidate arrives PENDING; % is a review outcome',
                        NEW.disposition
            USING HINT = 'a producer that could pre-approve is the autonomy '
                         'this surface exists to refuse';
    END IF;
    RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS candidates_arrive_pending ON candidates;
CREATE TRIGGER candidates_arrive_pending BEFORE INSERT ON candidates
    FOR EACH ROW EXECUTE FUNCTION enforce_candidate_arrives_pending();

-- No more than `fleet_max_approval_batch()` candidates under one decision.
CREATE OR REPLACE FUNCTION enforce_approval_batch_cap() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE n int; cap int := fleet_max_approval_batch();
BEGIN
    IF NEW.approval_decision_id IS NULL THEN RETURN NEW; END IF;
    SELECT count(*) INTO n FROM candidates
     WHERE approval_decision_id = NEW.approval_decision_id AND id <> NEW.id;
    IF n >= cap THEN
        RAISE EXCEPTION 'approval batch cap: % candidates already approved '
                        'under decision %, the cap is %',
                        n, NEW.approval_decision_id, cap
            USING HINT = 'the cap keeps one batch reason honest; a larger '
                         'batch needs more than one reason, not a bigger cap';
    END IF;
    RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS candidates_batch_cap ON candidates;
CREATE TRIGGER candidates_batch_cap BEFORE INSERT OR UPDATE ON candidates
    FOR EACH ROW EXECUTE FUNCTION enforce_approval_batch_cap();

-- THE QUEUE DEPTH, ON `tasks` ITSELF.
--
-- On the table rather than in the surface, because the surface is not the only
-- thing that could ever insert a task and a ceiling that only one caller
-- respects is a convention, not a ceiling.
--
-- Counts every QUEUED task regardless of work type: a draft-spec task and the
-- code task it produces both occupy the queue, which is the behaviour §6.2
-- describes and not an oversight.
CREATE OR REPLACE FUNCTION enforce_queue_depth() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE n int; cap int := fleet_max_queued_tasks();
BEGIN
    IF NEW.status <> 'QUEUED' THEN RETURN NEW; END IF;
    SELECT count(*) INTO n FROM tasks WHERE status = 'QUEUED';
    IF n >= cap THEN
        RAISE EXCEPTION 'queue depth: % tasks already QUEUED, the cap is %',
                        n, cap
            USING HINT = 'this replaces "a person types run_task.py". Raising '
                         'it is a migration, deliberately.';
    END IF;
    RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS tasks_queue_depth ON tasks;
CREATE TRIGGER tasks_queue_depth BEFORE INSERT ON tasks
    FOR EACH ROW EXECUTE FUNCTION enforce_queue_depth();

-- ============================================================ 4. GRANTS

REVOKE ALL ON candidate_batches, candidates FROM PUBLIC;

-- The console reviews and decides.
GRANT SELECT, INSERT, UPDATE ON candidates TO fleet_console;
GRANT SELECT, INSERT ON candidate_batches TO fleet_console;
GRANT USAGE, SELECT ON SEQUENCE candidates_id_seq        TO fleet_console;
GRANT USAGE, SELECT ON SEQUENCE candidate_batches_id_seq TO fleet_console;

-- The read-only page.
GRANT SELECT ON candidate_batches, candidates TO fleet_console_reader;

-- The daily brief reports on them; it holds SELECT and nothing else.
GRANT SELECT ON candidate_batches, candidates TO fleet_detector;

GRANT DELETE ON candidate_batches, candidates TO fleet_admin;

-- NOT GRANTED, and the absence is the invariant:
--   any producer identity gets INSERT on candidate_batches and candidates and
--   NOTHING on tasks. Only the approval surface creates tasks, and only from a
--   ticked row. That is what makes the surface the single path rather than the
--   usual path.
