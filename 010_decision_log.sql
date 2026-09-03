-- ============================================================================
-- 010_decision_log.sql  —  what was recommended, what was chosen, what happened
--
-- Fleet already holds proposals, observation verdicts, tasks, runs and costs.
-- What it has never held is the link between them: a proposal was raised, a
-- choice was made, work happened or did not, and nothing in the database says
-- the second of those four things ever occurred. `tasks` is the closest thing
-- to a record of a choice, and it only holds the ones that were approved --
-- the rejections, which are the more informative half, left no trace at all.
--
-- NOT NAMED `decisions`, AND THAT IS NOT A COMPROMISE
--
-- 002 already has a table called `decisions`. It is a different thing and must
-- stay a different thing: it is the verdict on ONE PROPOSAL from the proposal
-- cycle, keyed UNIQUE on proposal_id, with an enum reason code sized for
-- counting what that layer is bad at. This table is the log across every
-- source of a decision -- a proposal, an issue, a task, or nothing at all --
-- with a free-text reason, because the reason a person rejects something is
-- the part that does not fit a vocabulary chosen in advance.
--
-- Widening 002's table to serve both was considered and rejected. It would
-- have meant dropping the UNIQUE on proposal_id (the constraint that makes
-- "one verdict per proposal" true), making proposal_id nullable (removing the
-- FK that makes the cycle's grading complete), and adding a free-text reason
-- beside the enum -- at which point the enum is optional and stops being
-- countable. Two tables, two jobs.
--
-- THE OUTCOME IS NOT IN THIS TABLE, AND THERE IS NOWHERE TO PUT ONE
--
-- Every outcome field lives in `decision_outcomes`, a view that recomputes
-- from current state on every read. There is no `outcome` column, no
-- `worked_out` boolean, no `cost_actual`. That is the enforcement: a column
-- someone can type into is a column that will hold what someone believed at
-- the time they typed, and a decision log whose outcomes are self-reported is
-- a record of intentions wearing the clothes of a record of results.
--
-- The human supplies the decision and the reason. Everything else is either
-- captured from the row being cited (subject, evidence -- see
-- decision_log_capture) or derived at read time (the view).
--
-- Target: PostgreSQL 15+ (RDS 15.17). Higher than 001-009's stated 13+,
-- because `security_invoker` on the view is PG15 and is load-bearing: without
-- it the view would execute as its owner and hand every reader that owner's
-- sight of tasks, runs and issues. The floor is asserted below rather than
-- assumed.
-- ============================================================================

DO $$ BEGIN
    IF current_setting('server_version_num')::int < 150000 THEN
        RAISE EXCEPTION '010 needs PostgreSQL 15 or later for '
                        'security_invoker on decision_outcomes; this is %',
                        current_setting('server_version');
    END IF;
END $$;

-- ============================================================ 1. TYPE
--
-- Three, and DEFERRED is one of them rather than an absence of a row. "We
-- looked at this and chose not to choose yet" is a decision with a reason,
-- and modelling it as silence loses both.
CREATE TYPE decision_choice AS ENUM ('APPROVED','REJECTED','DEFERRED');

-- ============================================================ 2. TABLE

CREATE TABLE decision_log (
    id          bigserial PRIMARY KEY,

    -- A COLUMN, NOT A PARTITION. One log across every product, so "what have
    -- I decided lately" is one query and cross-product patterns are visible.
    -- A table per product would make the second question unanswerable and the
    -- first a UNION someone has to remember to widen.
    product     text NOT NULL CHECK (length(btrim(product)) > 0),

    -- What was proposed, in one line. Captured from whatever is cited; only
    -- typed when nothing is.
    subject     text NOT NULL CHECK (length(btrim(subject)) > 0),

    -- All three nullable and independent. A decision may cite a proposal, an
    -- issue, a task, several, or none -- a decision made on judgement with
    -- nothing to point at is still a decision, and refusing to record it
    -- would push exactly those out of the log.
    proposal_id bigint REFERENCES proposals(id),
    issue_id    bigint REFERENCES issues(id),
    task_id     bigint REFERENCES tasks(id),

    -- The evidence AS IT STOOD, snapshotted rather than joined. Not the
    -- codebase's usual instinct -- almost everything here is derived -- and
    -- the exception is deliberate: `issues.current_magnitude` and `severity`
    -- move, so a view rendering "the evidence this decision cited" would
    -- quietly restate today's numbers as the ones that were in front of the
    -- person. Empty is allowed and means nothing was cited; it is never
    -- filled with something invented to avoid looking empty.
    evidence    jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(evidence) = 'array'),

    decision    decision_choice NOT NULL,

    -- NOT NULL ON EVERY ROW, INCLUDING REJECTIONS AND DEFERRALS.
    --
    -- This is the whole point of the table. A rejected proposal with a reason
    -- is worth more than an approved one, because approval is recoverable
    -- from the work that followed and rejection leaves nothing behind at all.
    -- Free text rather than 002's enum: the reason a thing is rejected is
    -- usually the part that did not fit any vocabulary chosen in advance, and
    -- a forced enum turns it into WRONG_PRIORITY plus a lost sentence.
    reason      text NOT NULL CHECK (length(btrim(reason)) > 0),

    decided_by  text        NOT NULL DEFAULT current_user,
    decided_at  timestamptz NOT NULL DEFAULT now(),

    -- HOW THIS ROW CAME TO EXIST, and how far it can be trusted. Two columns
    -- rather than one because the implication runs one way only: a backfilled
    -- row can never be STATED, but a row recorded live may still be INFERRED
    -- (a decision written up days later from memory). Collapsing them would
    -- lose that, and the asymmetry is what the check below encodes.
    origin      text NOT NULL DEFAULT 'RECORDED'
                CHECK (origin IN ('RECORDED','BACKFILLED')),
    confidence  text NOT NULL DEFAULT 'STATED'
                CHECK (confidence IN ('STATED','INFERRED')),

    CONSTRAINT decision_log_backfill_is_inferred_ck
        CHECK (origin = 'RECORDED' OR confidence = 'INFERRED'),

    -- The sentinels exist so the backfill never has to invent a reason or a
    -- name. They are reserved to it: a live decision that types UNRECORDED is
    -- dodging the NOT NULL, which is the one thing that constraint is for.
    CONSTRAINT decision_log_sentinels_are_backfill_only_ck
        CHECK (origin = 'BACKFILLED'
               OR (reason <> 'UNRECORDED' AND decided_by <> 'UNRECORDED'))
);

COMMENT ON TABLE decision_log IS
  'One row per decision, across all products. Outcomes are NOT here -- see '
  'the decision_outcomes view, which recomputes them from current state.';
COMMENT ON COLUMN decision_log.reason IS
  'NOT NULL on every row including rejections. UNRECORDED is reserved to '
  'backfilled rows and refused on live ones.';
COMMENT ON COLUMN decision_log.evidence IS
  'Snapshot at decision time. Empty means nothing was cited, never that '
  'something was and has been lost.';

CREATE INDEX decision_log_product_idx  ON decision_log (product, decided_at DESC);
CREATE INDEX decision_log_decision_idx ON decision_log (decision, decided_at DESC);
CREATE INDEX decision_log_issue_idx    ON decision_log (issue_id, decided_at DESC)
    WHERE issue_id IS NOT NULL;
CREATE INDEX decision_log_task_idx     ON decision_log (task_id, decided_at DESC)
    WHERE task_id IS NOT NULL;
CREATE INDEX decision_log_proposal_idx ON decision_log (proposal_id, decided_at DESC)
    WHERE proposal_id IS NOT NULL;
CREATE INDEX decision_log_origin_idx   ON decision_log (origin, decided_at DESC);

-- ============================================================ 3. CAPTURE
--
-- Subject and evidence come from the row being cited, so a reviewer typing a
-- decision types the decision and the reason and nothing else. Not
-- SECURITY DEFINER: fleet_console already holds SELECT on all four tables
-- read here, and a definer function would grant sight of them to whoever the
-- trigger is later opened to.
CREATE FUNCTION decision_log_capture() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE ev jsonb;
BEGIN
    IF NEW.subject IS NULL THEN
        SELECT p.title INTO NEW.subject FROM proposals p WHERE p.id = NEW.proposal_id;
    END IF;
    IF NEW.subject IS NULL THEN
        SELECT i.issue_type || ' on ' || i.subject_type || ' ' || i.subject_id
          INTO NEW.subject FROM issues i WHERE i.id = NEW.issue_id;
    END IF;
    IF NEW.subject IS NULL THEN
        SELECT t.title INTO NEW.subject FROM tasks t WHERE t.id = NEW.task_id;
    END IF;
    IF NEW.subject IS NULL THEN
        RAISE EXCEPTION 'a decision needs a subject, and none was given or '
                        'could be taken from a cited proposal, issue or task'
            USING ERRCODE = 'not_null_violation';
    END IF;

    -- Evidence is captured only when the caller left it empty, so a caller
    -- that has assembled its own is never overwritten.
    IF NEW.evidence = '[]'::jsonb AND NEW.proposal_id IS NOT NULL THEN
        SELECT coalesce(jsonb_agg(jsonb_build_object(
                   'kind', 'proposal_evidence', 'adapter', e.adapter,
                   'query_key', e.query_key, 'value', e.value,
                   'fetched_at', e.fetched_at, 'stale', e.stale)
               ORDER BY e.id), '[]'::jsonb)
          INTO ev FROM proposal_evidence e WHERE e.proposal_id = NEW.proposal_id;
        NEW.evidence := ev;
    END IF;

    IF NEW.evidence = '[]'::jsonb AND NEW.issue_id IS NOT NULL THEN
        SELECT jsonb_build_array(jsonb_build_object(
                   'kind', 'issue', 'fingerprint', i.fingerprint,
                   'issue_type', i.issue_type, 'severity', i.severity,
                   'status', i.status, 'magnitude', i.current_magnitude,
                   'unit', i.current_unit, 'occurrence_count', i.occurrence_count,
                   'reopen_count', i.reopen_count, 'first_seen', i.first_seen,
                   'last_seen', i.last_seen))
          INTO ev FROM issues i WHERE i.id = NEW.issue_id;
        NEW.evidence := coalesce(ev, '[]'::jsonb);
    END IF;

    RETURN NEW;
END; $$;

-- ============================================================ 4. AUTHORITY
--
-- The same rule as `decisions` and `observation_verdicts`, for the same
-- reason: a layer that can record its own approval is an agent marking its
-- own work as passing. fleet_proposer and fleet_task_runner are absent from
-- this list and always will be -- the thing that recommends and the thing
-- that executes are both things a decision is made ABOUT.
CREATE FUNCTION enforce_decision_log_authority() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NOT pg_has_role(current_user, 'fleet_console', 'MEMBER') THEN
        RAISE EXCEPTION '% may not record decisions', current_user;
    END IF;
    RETURN NEW;
END; $$;

-- Nothing on this row may change afterwards, and unlike 002 there is no
-- "filled in later" half to leave writable -- because the outcome is derived.
-- 002 left `executed`, `abandoned_at` and `outcome_note` mutable precisely
-- because it had stored outcome columns; removing those removes the reason to
-- have a writable half at all.
CREATE FUNCTION guard_decision_log_immutability() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION 'decision % is settled; outcomes are derived in '
                    'decision_outcomes and are not written here', OLD.id
        USING HINT = 'record a new decision rather than revising an old one';
END; $$;

CREATE TRIGGER decision_log_authority BEFORE INSERT ON decision_log
    FOR EACH ROW EXECUTE FUNCTION enforce_decision_log_authority();
CREATE TRIGGER decision_log_capture_trg BEFORE INSERT ON decision_log
    FOR EACH ROW EXECUTE FUNCTION decision_log_capture();
CREATE TRIGGER decision_log_immutable BEFORE UPDATE ON decision_log
    FOR EACH ROW EXECUTE FUNCTION guard_decision_log_immutability();
CREATE TRIGGER decision_log_no_delete BEFORE DELETE ON decision_log
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();

-- ============================================================ 5. OUTCOMES
--
-- Recomputed on every read, from rows this log does not own and cannot write.
-- `security_invoker` is not a detail: without it the view executes as its
-- owner, and every principal granted SELECT on it would read tasks, runs and
-- issues through that owner's privileges rather than their own.
CREATE VIEW decision_outcomes WITH (security_invoker = true) AS
SELECT
    d.id, d.product, d.subject, d.decision, d.reason, d.decided_by,
    d.decided_at, d.origin, d.confidence, d.evidence,
    d.proposal_id, d.issue_id, d.task_id,

    -- ---- what the task did -------------------------------------------
    t.status AS task_status,
    CASE
        WHEN d.task_id IS NULL                              THEN NULL
        WHEN t.status = 'MERGED'                            THEN 'DELIVERED'
        WHEN t.status IN ('ABANDONED','REJECTED','FAILED')  THEN 'NOT_DELIVERED'
        ELSE 'IN_FLIGHT'
    END AS task_outcome,

    -- Every run of the task, not the latest. A task that took four attempts
    -- cost what all four cost; the newest run alone understates it by the
    -- price of every attempt that failed.
    agg.total_cost_gbp,
    agg.runs_total,

    -- ATTEMPTS TO GREEN IS NULL UNTIL THERE IS A GREEN. A number here for a
    -- task still in flight, or one abandoned, would be attempts-so-far
    -- wearing the name of a result.
    CASE WHEN t.status = 'MERGED' THEN t.attempts END AS attempts_to_green,

    -- ---- what the issue did ------------------------------------------
    i.status AS issue_status,
    occ.reopened_since_decision,
    occ.resolved_since_decision,

    -- REOPENED WINS OVER RESOLVED, and that ordering is the point. An issue
    -- that was fixed, came back, and was fixed again reads REOPENED, not
    -- RESOLVED_HELD: the decision did not hold, and a log that reported the
    -- current state would say it did. `issue_occurrences` is the source
    -- because it is trigger-maintained and carries the timestamps
    -- `issues.reopen_count` does not -- a counter cannot say whether the
    -- reopen happened before this decision or after it.
    CASE
        WHEN d.issue_id IS NULL                    THEN NULL
        WHEN occ.reopened_since_decision           THEN 'REOPENED'
        WHEN i.status = 'RESOLVED'
         AND occ.resolved_since_decision           THEN 'RESOLVED_HELD'
        WHEN i.status = 'RESOLVED'                 THEN 'RESOLVED_BEFORE_DECISION'
        WHEN i.status = 'SUPPRESSED'               THEN 'SUPPRESSED'
        ELSE 'STILL_OPEN'
    END AS issue_outcome
FROM decision_log d
LEFT JOIN tasks  t ON t.id = d.task_id
LEFT JOIN issues i ON i.id = d.issue_id
LEFT JOIN LATERAL (
    SELECT count(*)::int AS runs_total,
           coalesce(sum(r.committed_gbp), 0)::numeric(12,4) AS total_cost_gbp
      FROM runs r WHERE r.task_id = d.task_id
) agg ON d.task_id IS NOT NULL
LEFT JOIN LATERAL (
    SELECT bool_or(o.opened_at > d.decided_at)  AS reopened_since_decision,
           bool_or(o.closed_at > d.decided_at)  AS resolved_since_decision
      FROM issue_occurrences o WHERE o.issue_id = d.issue_id
) occ ON d.issue_id IS NOT NULL;

COMMENT ON VIEW decision_outcomes IS
  'Decisions with their outcomes recomputed from current state. Nothing here '
  'is stored; there is no column on decision_log any of it could be typed into.';

-- ============================================================ 6. GRANTS

REVOKE ALL ON decision_log, decision_outcomes FROM PUBLIC;

-- The console decides and reads back. No UPDATE and no DELETE: the triggers
-- refuse both, and the absent grant means the refusal is never reached.
GRANT SELECT, INSERT ON decision_log TO fleet_console;
GRANT SELECT ON decision_outcomes TO fleet_console;
GRANT USAGE, SELECT ON SEQUENCE decision_log_id_seq TO fleet_console;

-- The read-only console page.
GRANT SELECT ON decision_log, decision_outcomes TO fleet_console_reader;

-- A GRANT THIS FILE DEPENDS ON, NAMED RATHER THAN ASSUMED
--
-- `decision_outcomes` is security_invoker, so fleet_console reads `issues` and
-- `issue_occurrences` through its own privileges. It gets them from
-- 001_v1_core.sql's `GRANT SELECT ON observations, issues TO fleet_console,
-- fleet_evaluator`, and from 002's grant on issue_occurrences.
--
-- Restated here anyway, and the history is the reason. When this file was
-- written that 001 line existed only on `master`: commits 712195d and a99f17c
-- added it there, and `track-2-foundation` -- the branch carrying 002 through
-- 010, the console and the runner -- had never been merged with it. Production
-- had the grant because the migration identity owns the tables; a database
-- built from this branch's files did not, and the suite failed on exactly
-- that. `master` was merged in (168e8bb) as part of this change, so 001 now
-- carries it again.
--
-- Kept because a file should name what it depends on rather than inherit it
-- silently from a line two migrations away that has already gone missing once.
-- GRANT is idempotent, so it costs nothing and it is what was applied.
-- Narrowed to the two tables this view actually reads: `master`'s line also
-- names `observations`, which nothing here touches.
GRANT SELECT ON issues, issue_occurrences TO fleet_console;

-- Retention, on the same terms as observations and proposals.
GRANT DELETE ON decision_log TO fleet_admin;

-- NOT GRANTED, and each absence is a decision:
--   fleet_detector_reader  the proposal cycle may see what it said, not how
--                          it was graded. Same rule as `decisions`, and the
--                          reason 004 gave the console its own read identity.
--   fleet_proposer         it cannot read its own proposals back; it
--                          certainly cannot read the verdict on them.
--   fleet_task_runner      a decision is made about its work. A runner that
--                          could read the log could be written to act on it,
--                          and V1 has no self-generated tasks.
--   fleet_owner            nothing here is SECURITY DEFINER, so no definer
--                          function needs a read.
