-- ============================================================================
-- 002_proposals.sql  —  Fleet track 2, proposal layer
--
-- This layer proposes. It does not act. Nothing here writes to
-- deadly_digital, nothing here writes to a track 1 table, and the only
-- track 1 access it is granted is SELECT.
--
-- Nothing in 001_v1_core.sql is altered. The only statements touching
-- 001's objects are GRANTs to the two roles introduced here.
--
-- Target: PostgreSQL 13+ (RDS 15.17), applied with the listmonk identity.
-- ============================================================================

-- ============================================================ 1. ROLES
--
-- fleet_proposer          may INSERT proposals and their evidence.
--                         It may not read a proposal back, it may not read
--                         track 1, and it may not record a decision.
-- fleet_detector_reader   may SELECT track 1's tables and nothing else.
--
-- Two roles rather than one because a single role that could both read the
-- detectors and write proposals would make the read path and the write path
-- the same principal. The cycle opens two connections on purpose.
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['fleet_proposer','fleet_detector_reader'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
END $$;

GRANT USAGE ON SCHEMA public TO fleet_proposer, fleet_detector_reader;

-- ============================================================ 2. TYPES
--
-- Enums, not CHECK constraints, for the vocabularies a human reads and
-- filters on. A reason code that can be spelled freely is a reason code that
-- cannot be counted, and counting rejections by reason is the only way this
-- layer finds out what it is bad at.

CREATE TYPE proposal_kind AS ENUM
    ('OBSERVATION','RECOMMENDATION','RESEARCH','RISK');

CREATE TYPE proposal_reversibility AS ENUM
    ('TRIVIAL','COSTLY','ONE_WAY');

CREATE TYPE decision_verdict AS ENUM
    ('ACCEPT','REJECT','DEFER_30D');

CREATE TYPE decision_reason_code AS ENUM
    ('ALREADY_KNOWN','WRONG_PRIORITY','TOO_EXPENSIVE','BAD_REASONING',
     'MISSING_CONTEXT','NOT_MY_CALL','DISAGREE_WITH_PREMISE');

-- ============================================================ 3. TABLES

CREATE TABLE proposals (
    id             bigserial PRIMARY KEY,
    cycle_id       uuid        NOT NULL,
    kind           proposal_kind NOT NULL,
    area           text        NOT NULL,
    -- Stable identity of the finding, independent of how its title is worded
    -- and of the numbers in it. A daily cycle without this re-proposes the
    -- same open issue every morning until the cap is all it can say.
    finding_key    text        NOT NULL,
    title          text        NOT NULL,
    body           text        NOT NULL,
    objective_ref  text,
    est_effort     text CHECK (est_effort IN ('MINUTES','HOURS','DAYS','WEEKS')),
    est_impact     text CHECK (est_impact IN ('UNKNOWN','LOW','MEDIUM','HIGH')),
    reversibility  proposal_reversibility NOT NULL,
    confidence     numeric(4,3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    created_at     timestamptz NOT NULL DEFAULT now(),

    -- Every proposal names an objective from the quarter's file, or it is a
    -- RISK. The set of valid ids is quarterly data and deliberately not
    -- frozen into the schema; the shape is checked here, membership is
    -- checked by the producer against the file.
    CONSTRAINT proposals_objective_ck
        CHECK (objective_ref IS NOT NULL OR kind = 'RISK'),
    CONSTRAINT proposals_objective_shape_ck
        CHECK (objective_ref IS NULL OR objective_ref ~ '^[a-z0-9][a-z0-9-]*$'),

    -- An OBSERVATION that carries an effort and an impact estimate is a
    -- recommendation wearing a disguise. V1 produces observations, so the
    -- database refuses to let one arrive dressed as advice.
    CONSTRAINT proposals_observation_no_estimate_ck
        CHECK (kind <> 'OBSERVATION'
               OR (est_effort IS NULL AND est_impact IS NULL)),
    -- The converse: advice without a cost is not advice.
    CONSTRAINT proposals_recommendation_estimate_ck
        CHECK (kind <> 'RECOMMENDATION'
               OR (est_effort IS NOT NULL AND est_impact IS NOT NULL)),

    CONSTRAINT proposals_title_ck CHECK (length(btrim(title)) > 0),
    CONSTRAINT proposals_body_ck  CHECK (length(btrim(body))  > 0)
);

COMMENT ON COLUMN proposals.confidence IS
  'Confidence that the claim is true, not that it matters. A finding computed '
  'from a SQL count is 1.0 and still may be worth nothing.';

CREATE TABLE proposal_evidence (
    id              bigserial PRIMARY KEY,
    proposal_id     bigint      NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    adapter         text        NOT NULL,
    query_key       text        NOT NULL,
    value           jsonb       NOT NULL,
    fetched_at      timestamptz NOT NULL,
    -- The bound the adapter declared for this query, and whether the data
    -- was already outside it when it was read. Carried on the row because a
    -- staleness flag that lives only in the process dies with the process,
    -- and the person deciding weeks later needs to know the evidence was old.
    freshness_bound interval    NOT NULL,
    stale           boolean     NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT proposal_evidence_value_ck
        CHECK (jsonb_typeof(value) = 'object'),
    CONSTRAINT proposal_evidence_size_ck
        CHECK (pg_column_size(value) < 16384),
    CONSTRAINT proposal_evidence_bound_ck
        CHECK (freshness_bound > interval '0')
);

CREATE TABLE decisions (
    id               bigserial PRIMARY KEY,
    proposal_id      bigint NOT NULL UNIQUE REFERENCES proposals(id),
    verdict          decision_verdict NOT NULL,
    reason_code      decision_reason_code,
    -- Who, recorded by the database rather than claimed by the client. The
    -- authority trigger says a member of fleet_console decided; this says
    -- which one.
    decided_by       text        NOT NULL DEFAULT current_user,
    decided_at       timestamptz NOT NULL DEFAULT now(),
    -- Seconds of human attention. The point of the number is to make the
    -- cost of reviewing this layer visible: a layer that costs more
    -- attention than it saves is a layer to switch off.
    decision_seconds numeric(10,3) NOT NULL CHECK (decision_seconds >= 0),

    -- Filled in later, by whoever finds out what happened.
    executed         boolean,
    abandoned_at     timestamptz,
    outcome_note     text,

    -- An ACCEPT needs no excuse. Everything else does.
    CONSTRAINT decisions_reason_ck
        CHECK (verdict = 'ACCEPT' OR reason_code IS NOT NULL)
);

-- ============================================================ 4. INDEXES

CREATE INDEX proposals_cycle_idx     ON proposals (cycle_id, created_at);
CREATE INDEX proposals_finding_idx   ON proposals (finding_key, created_at DESC);
CREATE INDEX proposals_objective_idx ON proposals (objective_ref, created_at DESC);
CREATE INDEX proposals_kind_idx      ON proposals (kind, created_at DESC);
CREATE INDEX proposal_evidence_proposal_idx ON proposal_evidence (proposal_id);
CREATE INDEX decisions_verdict_idx   ON decisions (verdict, decided_at DESC);
CREATE INDEX decisions_reason_idx    ON decisions (reason_code, decided_at DESC)
    WHERE reason_code IS NOT NULL;

-- ============================================================ 5. FUNCTIONS

-- ---- evidence -------------------------------------------------------------
-- A proposal with no evidence is an opinion. Checked at COMMIT, not at
-- INSERT, because the evidence rows reference the proposal id and therefore
-- cannot exist before it. SECURITY DEFINER because fleet_proposer is not
-- allowed to read either table back.
CREATE FUNCTION require_proposal_evidence() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE pid bigint;
BEGIN
    -- Branch rather than CASE: plpgsql resolves OLD.proposal_id even in the
    -- arm it will not take, and OLD has no fields on INSERT.
    IF TG_OP = 'DELETE' THEN pid := OLD.proposal_id; ELSE pid := NEW.id; END IF;

    -- Gone by commit time: a rolled-back insert, or a cascade from the
    -- proposal itself. Nothing left to be evidence for.
    IF NOT EXISTS (SELECT 1 FROM public.proposals WHERE id = pid) THEN
        RETURN NULL;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM public.proposal_evidence
                   WHERE proposal_id = pid) THEN
        RAISE EXCEPTION 'proposal % carries no evidence', pid
            USING ERRCODE = 'check_violation',
                  HINT = 'insert at least one proposal_evidence row for it '
                         'in the same transaction';
    END IF;
    RETURN NULL;
END; $$;

-- ---- the cap --------------------------------------------------------------
-- Five items per cycle, and it is not configurable. A cap that can be raised
-- is a cap that will be raised on the morning the layer has six things it
-- feels strongly about. Forcing the cut is the entire mechanism: it is what
-- makes the layer rank rather than enumerate.
CREATE FUNCTION enforce_cycle_cardinality() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE n int;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(NEW.cycle_id::text, 0));

    SELECT count(*) INTO n FROM public.proposals WHERE cycle_id = NEW.cycle_id;

    IF n >= 5 THEN
        RAISE EXCEPTION 'cycle % already holds % proposals (cap is 5)',
            NEW.cycle_id, n
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END; $$;

-- ---- decision authority ---------------------------------------------------
-- The same rule as observation_verdicts, for the same reason. A layer that
-- can record its own approval is an agent marking its own work as passing.
-- fleet_proposer is deliberately absent from this list and always will be.
CREATE FUNCTION enforce_decision_authority() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NOT pg_has_role(current_user, 'fleet_console', 'MEMBER') THEN
        RAISE EXCEPTION '% may not record decisions', current_user;
    END IF;
    RETURN NEW;
END; $$;

-- A decision is a record of a judgement made at a moment, with a cost. The
-- judgement and its cost freeze; what happened next does not.
CREATE FUNCTION guard_decision_immutability() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.proposal_id      IS DISTINCT FROM OLD.proposal_id
    OR NEW.verdict          IS DISTINCT FROM OLD.verdict
    OR NEW.reason_code      IS DISTINCT FROM OLD.reason_code
    OR NEW.decided_by       IS DISTINCT FROM OLD.decided_by
    OR NEW.decided_at       IS DISTINCT FROM OLD.decided_at
    OR NEW.decision_seconds IS DISTINCT FROM OLD.decision_seconds THEN
        RAISE EXCEPTION 'the verdict on proposal % is settled; only executed, '
                        'abandoned_at and outcome_note may change',
            OLD.proposal_id;
    END IF;
    RETURN NEW;
END; $$;

-- ============================================================ 6. TRIGGERS

-- Append-only, on the same terms as observations and run_steps: application
-- principals cannot mutate, fleet_admin may DELETE for retention.
CREATE TRIGGER proposals_immutable BEFORE UPDATE OR DELETE ON proposals
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER proposal_evidence_immutable BEFORE UPDATE OR DELETE ON proposal_evidence
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE CONSTRAINT TRIGGER proposals_require_evidence
    AFTER INSERT ON proposals
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION require_proposal_evidence();

-- The other half: retention deleting the last evidence row must not leave a
-- bare proposal behind.
CREATE CONSTRAINT TRIGGER proposal_evidence_last_row
    AFTER DELETE ON proposal_evidence
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION require_proposal_evidence();

CREATE TRIGGER proposals_cycle_cardinality BEFORE INSERT ON proposals
    FOR EACH ROW EXECUTE FUNCTION enforce_cycle_cardinality();

CREATE TRIGGER decisions_authority BEFORE INSERT OR UPDATE ON decisions
    FOR EACH ROW EXECUTE FUNCTION enforce_decision_authority();
CREATE TRIGGER decisions_immutable BEFORE UPDATE ON decisions
    FOR EACH ROW EXECUTE FUNCTION guard_decision_immutability();
CREATE TRIGGER decisions_no_delete BEFORE DELETE ON decisions
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();

-- ============================================================ 7. OWNERSHIP

ALTER FUNCTION require_proposal_evidence()  OWNER TO fleet_owner;
ALTER FUNCTION enforce_cycle_cardinality()  OWNER TO fleet_owner;

-- What those definer functions read, and nothing else.
GRANT SELECT ON public.proposals         TO fleet_owner;
GRANT SELECT ON public.proposal_evidence TO fleet_owner;

-- ============================================================ 8. GRANTS

REVOKE ALL ON proposals, proposal_evidence, decisions FROM PUBLIC;

-- The proposer writes and cannot read what it wrote. The single exception is
-- proposals.id: INSERT ... RETURNING id requires SELECT on the returned
-- column, and the evidence rows need that id to exist.
GRANT INSERT      ON proposals         TO fleet_proposer;
GRANT SELECT (id) ON proposals         TO fleet_proposer;
GRANT INSERT      ON proposal_evidence TO fleet_proposer;
GRANT USAGE, SELECT ON SEQUENCE proposals_id_seq, proposal_evidence_id_seq
      TO fleet_proposer;

-- The read-only side of the layer. Track 1's tables, SELECT, nothing more.
GRANT SELECT ON detector_registry, detector_definition_boundaries,
      source_registry, routing_policy, detector_runs, observations, issues,
      observation_verdicts, issue_occurrences
      TO fleet_detector_reader;

-- Its own past output, so a daily cycle can tell a new finding from
-- yesterday's. Deliberately not decisions: the layer may see what it said,
-- not how it was graded.
GRANT SELECT ON proposals, proposal_evidence TO fleet_detector_reader;

-- The console reads everything this layer produced and is the only principal
-- that may decide.
GRANT SELECT ON proposals, proposal_evidence, decisions TO fleet_console;
GRANT INSERT ON decisions TO fleet_console;
GRANT UPDATE (executed, abandoned_at, outcome_note) ON decisions TO fleet_console;
GRANT USAGE, SELECT ON SEQUENCE decisions_id_seq TO fleet_console;
