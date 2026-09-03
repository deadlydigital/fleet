-- ============================================================================
-- 001_v1_core.sql  —  Fleet detection layer, V1
-- Squashed from design deltas 001-020. Single applyable migration.
-- Target: PostgreSQL 13+ (built for RDS 15.17). gen_random_uuid() built in.
-- ============================================================================

-- ============================================================ 1. ROLES
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['fleet_owner','fleet_agent','fleet_verifier',
        'fleet_deployer','fleet_evaluator','fleet_console','fleet_detector',
        'fleet_admin','fleet_model_gateway'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
END $$;

-- Migration principal must be able to transfer ownership to fleet_owner.
-- On RDS the master (rds_superuser) is not a true superuser and does not
-- bypass this. listmonk is a MIGRATION identity, never a runtime principal.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user) THEN
    EXECUTE format('GRANT fleet_owner TO %I', current_user);
  END IF;
END $$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO fleet_owner, fleet_agent, fleet_verifier,
      fleet_deployer, fleet_evaluator, fleet_console, fleet_detector,
      fleet_admin, fleet_model_gateway;

-- ============================================================ 2. CONFIG TABLES

CREATE TABLE detector_registry (
    detector_key             text        NOT NULL,
    issue_key_version        int         NOT NULL,
    product                  text        NOT NULL,
    semantics                text        NOT NULL CHECK (semantics IN ('LEVEL','EVENT')),
    coverage_mode            text        NOT NULL DEFAULT 'GLOBAL'
                             CHECK (coverage_mode IN ('GLOBAL','ENUMERATED')),
    cadence                  interval    NOT NULL,
    grace                    interval    NOT NULL,
    settle_lag               interval    NOT NULL DEFAULT '0',
    evaluation_window        interval    NOT NULL DEFAULT '1 hour',
    schedule_epoch           timestamptz NOT NULL DEFAULT '2026-01-01 00:00:00+00',
    required_clear_runs      int         NOT NULL DEFAULT 2,
    max_attempts             int         NOT NULL DEFAULT 3,
    execution_timeout        interval    NOT NULL DEFAULT '10 minutes',
    max_open_issues          int         NOT NULL DEFAULT 50,
    max_observations_per_run int         NOT NULL DEFAULT 500,
    current_detector_version int         NOT NULL DEFAULT 1,
    maintenance_until        timestamptz,
    retired_at               timestamptz,
    PRIMARY KEY (detector_key, issue_key_version, product)
);

CREATE TABLE detector_definition_boundaries (
    detector_key      text        NOT NULL,
    issue_key_version int         NOT NULL,
    product           text        NOT NULL,
    effective_at      timestamptz NOT NULL,
    successor_version int         NOT NULL,
    reason            text,
    PRIMARY KEY (detector_key, issue_key_version, product)
);

CREATE TABLE source_registry (
    product              text  NOT NULL,
    subject_type         text  NOT NULL,
    subject_id           text  NOT NULL,
    source_type          text  NOT NULL,
    source_preconditions jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (product, subject_type, subject_id, source_type)
);

CREATE TABLE routing_policy (
    observation_type text NOT NULL,
    policy_version   int  NOT NULL DEFAULT 1,
    min_magnitude    numeric NOT NULL DEFAULT 0,
    severity         text NOT NULL
                     CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    PRIMARY KEY (observation_type, policy_version, min_magnitude)
);

CREATE TABLE step_authority (
    step_type     text PRIMARY KEY,
    required_role text NOT NULL
);
INSERT INTO step_authority VALUES
    ('EVIDENCE_COLLECTED',  'fleet_agent'),
    ('HYPOTHESIS_RECORDED', 'fleet_agent'),
    ('PATCH_PROPOSED',      'fleet_agent'),
    ('VERIFICATION_RUN',    'fleet_verifier'),
    ('HUMAN_DECISION',      'fleet_console'),
    ('DEPLOYED',            'fleet_deployer'),
    ('ROLLED_BACK',         'fleet_deployer');

CREATE TABLE infra_costs (
    period_month date          NOT NULL,
    resource     text          NOT NULL,
    cost_gbp     numeric(10,2) NOT NULL,
    PRIMARY KEY (period_month, resource)
);

-- ============================================================ 3. CORE TABLES

CREATE TABLE detector_runs (
    id                     bigserial PRIMARY KEY,
    detector_key           text        NOT NULL,
    detector_version       int         NOT NULL,
    issue_key_version      int         NOT NULL DEFAULT 1,
    product                text        NOT NULL,
    semantics              text        NOT NULL CHECK (semantics IN ('LEVEL','EVENT')),
    run_mode               text        NOT NULL DEFAULT 'SCHEDULED'
                           CHECK (run_mode IN ('SCHEDULED','BACKFILL','MANUAL')),
    backfill_batch_id      uuid,
    coverage_mode          text        NOT NULL DEFAULT 'GLOBAL'
                           CHECK (coverage_mode IN ('GLOBAL','ENUMERATED','PARTIAL')),
    subjects_evaluated     text[],
    subjects_failed        text[],
    window_start           timestamptz NOT NULL,
    window_end             timestamptz NOT NULL,
    started_at             timestamptz NOT NULL DEFAULT now(),
    completed_at           timestamptz,
    last_attempt_at        timestamptz NOT NULL DEFAULT now(),
    attempt_count          int         NOT NULL DEFAULT 1,
    status                 text        NOT NULL DEFAULT 'RUNNING'
                           CHECK (status IN ('RUNNING','OK','PARTIAL','ERROR','TIMEOUT')),
    observations_created   int         NOT NULL DEFAULT 0,
    observations_truncated boolean     NOT NULL DEFAULT false,
    duration_ms            int,
    error                  text,
    CHECK (window_end > window_start),
    CONSTRAINT detector_runs_batch_ck
        CHECK ((run_mode = 'BACKFILL') = (backfill_batch_id IS NOT NULL)),
    -- Close-time invariant: a RUNNING enumerated run legitimately has no
    -- subjects yet, because the array is populated as evaluation proceeds.
    -- Requiring it at open time makes enumerated detectors impossible to start.
    -- subjects_evaluated is required only of a run that COMPLETED
    -- SUCCESSFULLY. A RUNNING run has not evaluated anything yet, and an
    -- ERROR/TIMEOUT run proves nothing, so neither must carry the array.
    -- This matches the coverage predicates, which count only OK and PARTIAL.
    CONSTRAINT coverage_enumerated_ck
        CHECK (coverage_mode <> 'ENUMERATED'
               OR status NOT IN ('OK','PARTIAL')
               OR subjects_evaluated IS NOT NULL),
    CONSTRAINT detector_runs_registry_fk
        FOREIGN KEY (detector_key, issue_key_version, product)
        REFERENCES detector_registry (detector_key, issue_key_version, product)
);

CREATE TABLE observations (
    id                     bigserial PRIMARY KEY,
    detector_run_id        bigint      NOT NULL REFERENCES detector_runs(id),
    detector_key           text        NOT NULL,
    detector_version       int         NOT NULL,
    issue_key_version      int         NOT NULL DEFAULT 1,
    product                text        NOT NULL,
    run_mode               text        NOT NULL DEFAULT 'SCHEDULED'
                           CHECK (run_mode IN ('SCHEDULED','BACKFILL','MANUAL')),
    backfill_batch_id      uuid,
    observation_type       text        NOT NULL,
    observed_at            timestamptz NOT NULL,
    subject_type           text        NOT NULL,
    subject_id             text        NOT NULL,
    fingerprint            text        NOT NULL,
    magnitude              numeric,
    unit                   text,
    expected               numeric,
    actual                 numeric,
    delta                  numeric,
    evidence_query_key     text,
    evidence_query_version int,
    evidence_params        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    evidence_sample        jsonb,
    evidence_source        text,
    created_at             timestamptz NOT NULL DEFAULT now(),
    CHECK (pg_column_size(evidence_sample) < 16384),
    CONSTRAINT observations_batch_ck
        CHECK ((run_mode = 'BACKFILL') = (backfill_batch_id IS NOT NULL)),
    -- Scalar values only. Nested objects/arrays are how free text gets in,
    -- and free text from an external party is an injection channel.
    CONSTRAINT evidence_sample_shape_ck CHECK (
        evidence_sample IS NULL
        OR (jsonb_typeof(evidence_sample) = 'object'
            AND NOT jsonb_path_exists(evidence_sample,
                '$.* ? (@.type() == "object" || @.type() == "array")')))
);

CREATE TABLE issues (
    id                     bigserial PRIMARY KEY,
    fingerprint            text        NOT NULL UNIQUE,
    product                text        NOT NULL,
    issue_type             text        NOT NULL,
    subject_type           text        NOT NULL,
    subject_id             text        NOT NULL,
    detector_key           text        NOT NULL,
    issue_key_version      int         NOT NULL DEFAULT 1,
    first_observation_id   bigint REFERENCES observations(id) ON DELETE SET NULL,
    latest_observation_id  bigint REFERENCES observations(id) ON DELETE SET NULL,
    first_seen             timestamptz NOT NULL,
    last_seen              timestamptz NOT NULL,
    occurrence_count       int         NOT NULL DEFAULT 1,
    reopen_count           int         NOT NULL DEFAULT 0,
    current_magnitude      numeric,
    current_unit           text,
    status                 text        NOT NULL DEFAULT 'OPEN'
                           CHECK (status IN ('OPEN','RESOLVED','SUPPRESSED')),
    resolution_type        text CHECK (resolution_type IN
                           ('CLEARED','DEFINITION_CHANGED','SUPERSEDED')),
    resolved_at            timestamptz,
    resolution_effective_at timestamptz,
    superseded_by_issue_id bigint REFERENCES issues(id),
    severity               text        NOT NULL DEFAULT 'UNTRIAGED'
                           CHECK (severity IN ('UNTRIAGED','LOW','MEDIUM','HIGH','CRITICAL')),
    routing_policy_version int         NOT NULL DEFAULT 1,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'RESOLVED') = (resolved_at IS NOT NULL)),
    CHECK (status <> 'RESOLVED' OR resolution_type IS NOT NULL),
    CHECK (resolution_type <> 'SUPERSEDED' OR superseded_by_issue_id IS NOT NULL),
    CONSTRAINT issues_effective_ck
        CHECK ((status = 'RESOLVED') = (resolution_effective_at IS NOT NULL))
);

CREATE TABLE runs (
    id                      bigserial PRIMARY KEY,
    issue_id                bigint      NOT NULL REFERENCES issues(id),
    work_type               text        NOT NULL,
    contract_version        int         NOT NULL,
    started_at              timestamptz NOT NULL DEFAULT now(),
    completed_at            timestamptz,
    status                  text        NOT NULL DEFAULT 'ACTIVE'
                            CHECK (status IN ('ACTIVE','AWAITING_HUMAN','DEPLOYED',
                                              'ABANDONED','REJECTED','FAILED')),
    spend_limit_gbp         numeric(10,4) NOT NULL,
    committed_gbp           numeric(10,4) NOT NULL DEFAULT 0,
    human_attention_seconds int,
    final_outcome           text CHECK (final_outcome IN
                            ('SUCCESS','RECURRENCE','REGRESSION','INCONCLUSIVE')),
    outcome_at              timestamptz,
    CONSTRAINT runs_budget_ck CHECK (committed_gbp <= spend_limit_gbp)
);

CREATE TABLE budget_reservations (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        bigint NOT NULL REFERENCES runs(id),
    estimate_gbp  numeric(10,6) NOT NULL CHECK (estimate_gbp > 0),
    status        text NOT NULL DEFAULT 'HELD'
                  CHECK (status IN ('HELD','SETTLED','VOID')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    settled_at    timestamptz,
    voided_at     timestamptz,
    voided_reason text
);

CREATE TABLE model_calls (
    id                      bigserial PRIMARY KEY,
    run_id                  bigint REFERENCES runs(id),
    detector_run_id         bigint REFERENCES detector_runs(id),
    reservation_id          uuid   REFERENCES budget_reservations(id),
    provider                text        NOT NULL,
    model                   text        NOT NULL,
    purpose                 text        NOT NULL,
    started_at              timestamptz NOT NULL,
    completed_at            timestamptz NOT NULL,
    prompt_tokens           int,
    completion_tokens       int,
    load_duration_ms        int,
    prompt_eval_duration_ms int,
    eval_duration_ms        int,
    total_duration_ms       int,
    marginal_cost_gbp       numeric(10,6) NOT NULL DEFAULT 0,
    ok                      boolean     NOT NULL DEFAULT true,
    CHECK (run_id IS NOT NULL OR detector_run_id IS NOT NULL)
);
COMMENT ON COLUMN model_calls.marginal_cost_gbp IS
  'API list cost. 0 for local inference. NOT the true cost of a local call.';

CREATE TABLE run_steps (
    id           bigserial PRIMARY KEY,
    run_id       bigint      NOT NULL REFERENCES runs(id),
    sequence     int         NOT NULL,
    step_type    text        NOT NULL CHECK (step_type IN (
                     'EVIDENCE_COLLECTED','HYPOTHESIS_RECORDED','PATCH_PROPOSED',
                     'VERIFICATION_RUN','HUMAN_DECISION','DEPLOYED','ROLLED_BACK')),
    actor        text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    artifact_uri text,
    payload      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    CHECK (step_type <> 'HUMAN_DECISION' OR payload->>'decision' IN (
        'APPROVED','REJECTED_WRONG_DIAGNOSIS','REJECTED_WRONG_FIX',
        'REJECTED_EXCESSIVE_SCOPE','REJECTED_INSUFFICIENT_EVIDENCE',
        'REJECTED_RISK','REJECTED_PRODUCT_DECISION','REJECTED_DUPLICATE'))
);

CREATE TABLE scheduled_checks (
    id          bigserial PRIMARY KEY,
    run_id      bigint      NOT NULL REFERENCES runs(id),
    issue_id    bigint      NOT NULL REFERENCES issues(id),
    fingerprint text        NOT NULL,
    check_kind  text        NOT NULL DEFAULT 'RECURRENCE',
    due_at      timestamptz NOT NULL,
    horizon     text        NOT NULL,
    required    boolean     NOT NULL DEFAULT true,
    status      text        NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','RUNNING','DONE','SKIPPED')),
    result      text CHECK (result IN
                ('SUCCESS','RECURRENCE','REGRESSION','INCONCLUSIVE')),
    detail      jsonb,
    executed_at timestamptz,
    attempts    int NOT NULL DEFAULT 0
);

CREATE TABLE observation_verdicts (
    id                bigserial PRIMARY KEY,
    observation_id    bigint NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    detector_key      text   NOT NULL,
    detector_version  int    NOT NULL,
    issue_key_version int    NOT NULL,
    observation_type  text   NOT NULL,
    verdict           text   NOT NULL
                      CHECK (verdict IN ('VALID','FALSE_POSITIVE','INCONCLUSIVE')),
    verdict_by        text   NOT NULL,
    reason            text,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE issue_occurrences (
    id        bigserial PRIMARY KEY,
    issue_id  bigint      NOT NULL REFERENCES issues(id),
    opened_at timestamptz NOT NULL,
    closed_at timestamptz,
    CHECK (closed_at IS NULL OR closed_at >= opened_at)
);

-- ============================================================ 4. INDEXES

-- detector + semantic schedule version + product + slot boundary
--   -> exactly one logical scheduled run
CREATE UNIQUE INDEX detector_runs_scheduled_slot_uq
    ON detector_runs (detector_key, issue_key_version, product, window_end)
    WHERE run_mode = 'SCHEDULED';
CREATE INDEX detector_runs_key_started_idx ON detector_runs (detector_key, started_at DESC);
CREATE INDEX detector_runs_subjects_idx    ON detector_runs USING gin (subjects_evaluated);

-- Scheduled execution is strictly idempotent per window...
CREATE UNIQUE INDEX observations_scheduled_idem_uq
    ON observations (detector_key, fingerprint, observed_at)
    WHERE run_mode = 'SCHEDULED';
-- ...and every mode is idempotent within a single run, so a crashed and
-- retried run cannot duplicate. Identity is the run, not the wall clock.
CREATE UNIQUE INDEX observations_run_idem_uq ON observations (detector_run_id, fingerprint);
CREATE INDEX observations_fingerprint_idx ON observations (fingerprint, observed_at DESC);
CREATE INDEX observations_run_idx         ON observations (detector_run_id);
CREATE INDEX observations_version_idx     ON observations (detector_key, detector_version);
CREATE INDEX observations_batch_idx       ON observations (backfill_batch_id)
    WHERE backfill_batch_id IS NOT NULL;

CREATE INDEX issues_open_idx    ON issues (status, severity, last_seen DESC) WHERE status = 'OPEN';
CREATE INDEX issues_product_idx ON issues (product, issue_type);

-- One active run per issue. Prevents two agents fighting over the same fix.
CREATE UNIQUE INDEX runs_one_active_per_issue ON runs (issue_id)
    WHERE status IN ('ACTIVE','AWAITING_HUMAN');
CREATE INDEX runs_awaiting_idx ON runs (status, started_at) WHERE status = 'AWAITING_HUMAN';

CREATE INDEX budget_reservations_run_idx ON budget_reservations (run_id, status);
-- one reservation -> zero or one model call
CREATE UNIQUE INDEX model_calls_reservation_uq ON model_calls (reservation_id)
    WHERE reservation_id IS NOT NULL;
CREATE INDEX model_calls_run_idx      ON model_calls (run_id);
CREATE INDEX model_calls_provider_idx ON model_calls (provider, model, started_at DESC);

CREATE UNIQUE INDEX run_steps_seq_uq   ON run_steps (run_id, sequence);
CREATE INDEX run_steps_type_idx        ON run_steps (step_type, created_at DESC);
CREATE INDEX run_steps_decision_idx    ON run_steps ((payload->>'decision'))
    WHERE step_type = 'HUMAN_DECISION';

CREATE INDEX scheduled_checks_due_idx  ON scheduled_checks (due_at) WHERE status = 'PENDING';
CREATE UNIQUE INDEX scheduled_checks_uq ON scheduled_checks (run_id, horizon);

CREATE UNIQUE INDEX observation_verdicts_uq ON observation_verdicts (observation_id);
CREATE INDEX observation_verdicts_type_idx
    ON observation_verdicts (detector_key, detector_version, observation_type, verdict);

CREATE INDEX issue_occurrences_issue_idx ON issue_occurrences (issue_id, opened_at);
CREATE UNIQUE INDEX issue_occurrences_one_open_uq ON issue_occurrences (issue_id)
    WHERE closed_at IS NULL;

-- ============================================================ 5. FUNCTIONS

-- ---- immutability ---------------------------------------------------------
-- Append-only means application processes cannot mutate, not undeletable
-- forever. fleet_admin may DELETE for retention, and only that.
CREATE FUNCTION reject_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP = 'DELETE' AND pg_has_role(current_user, 'fleet_admin', 'MEMBER') THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '% on % denied for %', TG_OP, TG_TABLE_NAME, current_user;
END; $$;

-- ---- routing --------------------------------------------------------------
-- Severity is assigned by policy, not by the detector. Thresholds are data so
-- retuning priorities is not a redeploy.
CREATE FUNCTION route_severity(p_observation_type text, p_magnitude numeric,
                               p_policy_version int DEFAULT 1)
RETURNS text
SET search_path = pg_catalog, public AS $$
    SELECT coalesce(
      (SELECT rp.severity FROM routing_policy rp
       WHERE rp.observation_type = p_observation_type
         AND rp.policy_version   = p_policy_version
         AND rp.min_magnitude   <= coalesce(p_magnitude, 0)
       ORDER BY rp.min_magnitude DESC LIMIT 1),
      'UNTRIAGED');
$$ LANGUAGE sql STABLE;

-- ---- step authority -------------------------------------------------------
-- actor is descriptive. current_user is the authority.
CREATE FUNCTION enforce_step_authority() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE req text;
BEGIN
    SELECT required_role INTO req FROM step_authority WHERE step_type = NEW.step_type;
    IF req IS NULL THEN RAISE EXCEPTION 'unknown step_type %', NEW.step_type; END IF;
    IF NOT pg_has_role(current_user, req, 'MEMBER') THEN
        RAISE EXCEPTION '% may not write step_type % (requires %)',
            current_user, NEW.step_type, req;
    END IF;
    RETURN NEW;
END; $$;

-- ---- acceptance boundary --------------------------------------------------
-- A run cannot modify its own acceptance boundary, cannot verify a stale
-- patch, and cannot deploy anything that is not the latest verified proposal.
CREATE FUNCTION enforce_acceptance_boundary() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE latest_patch text;
BEGIN
    IF NEW.step_type = 'VERIFICATION_RUN' AND NEW.payload->>'result' = 'PASS' THEN
        IF (NEW.payload->>'boundary_clean')::bool IS NOT TRUE
           OR NEW.payload->>'base_commit_sha'  IS NULL
           OR NEW.payload->>'patch_commit_sha' IS NULL
           OR NEW.payload->>'suite_commit_sha' IS NULL
           OR NEW.payload->>'contract_version' IS NULL THEN
            RAISE EXCEPTION
              'PASS requires verifier-derived boundary_clean and full diff provenance';
        END IF;
        SELECT payload->>'patch_commit_sha' INTO latest_patch
        FROM run_steps WHERE run_id = NEW.run_id AND step_type = 'PATCH_PROPOSED'
        ORDER BY sequence DESC LIMIT 1;
        IF latest_patch IS DISTINCT FROM NEW.payload->>'patch_commit_sha' THEN
            RAISE EXCEPTION 'verification targets % but latest proposal is %',
                NEW.payload->>'patch_commit_sha', latest_patch;
        END IF;
    END IF;

    IF NEW.step_type = 'DEPLOYED' THEN
        IF NOT EXISTS (
            SELECT 1 FROM run_steps
            WHERE run_id = NEW.run_id AND step_type = 'VERIFICATION_RUN'
              AND payload->>'result' = 'PASS'
              AND payload->>'patch_commit_sha' = NEW.payload->>'patch_commit_sha')
        THEN
            RAISE EXCEPTION 'deploy of % has no passing verification for that sha',
                NEW.payload->>'patch_commit_sha';
        END IF;
        SELECT payload->>'patch_commit_sha' INTO latest_patch
        FROM run_steps WHERE run_id = NEW.run_id AND step_type = 'PATCH_PROPOSED'
        ORDER BY sequence DESC LIMIT 1;
        IF latest_patch IS DISTINCT FROM NEW.payload->>'patch_commit_sha' THEN
            RAISE EXCEPTION 'deploy of % is stale; latest proposal is %',
                NEW.payload->>'patch_commit_sha', latest_patch;
        END IF;
    END IF;
    RETURN NEW;
END; $$;

-- ---- observation provenance ----------------------------------------------
-- Derived, never supplied. A boundary enforced with metadata the constrained
-- writer controls is not a boundary.
CREATE FUNCTION enforce_observation_run_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE r public.detector_runs;
BEGIN
    SELECT * INTO STRICT r FROM public.detector_runs WHERE id = NEW.detector_run_id;

    NEW.run_mode          := r.run_mode;
    NEW.backfill_batch_id := r.backfill_batch_id;
    NEW.detector_key      := r.detector_key;
    NEW.detector_version  := r.detector_version;
    NEW.issue_key_version := r.issue_key_version;
    NEW.product           := r.product;

    IF r.status <> 'RUNNING' THEN
        RAISE EXCEPTION 'detector_run % is % - cannot accept observations', r.id, r.status;
    END IF;

    IF r.semantics = 'LEVEL' THEN
        -- Effective time of a windowed condition. Database-owned, so the
        -- detector's clock and settle_lag cannot affect it.
        NEW.observed_at := r.window_end;
    ELSE
        IF NEW.observed_at < r.window_start OR NEW.observed_at >= r.window_end THEN
            RAISE EXCEPTION 'observed_at % outside window [%, %)',
                NEW.observed_at, r.window_start, r.window_end;
        END IF;
    END IF;
    RETURN NEW;
END; $$;

-- Only scheduled observations may drive issue lifecycle.
CREATE FUNCTION enforce_scheduled_issue_source() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM observations o
               WHERE o.id IN (NEW.first_observation_id, NEW.latest_observation_id)
                 AND o.run_mode <> 'SCHEDULED') THEN
        RAISE EXCEPTION 'issue lifecycle cannot be driven by a non-scheduled observation';
    END IF;
    RETURN NEW;
END; $$;

-- ---- cardinality ----------------------------------------------------------
-- Advisory lock rather than SELECT ... FOR UPDATE: FOR UPDATE requires UPDATE
-- privilege on detector_registry, which no runtime role should hold.
CREATE FUNCTION enforce_issue_cardinality() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE cap int; open_now int;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.product || '|' || NEW.detector_key || '|'
                         || NEW.issue_key_version::text, 0));

    SELECT max_open_issues INTO cap FROM public.detector_registry
    WHERE detector_key = NEW.detector_key
      AND issue_key_version = NEW.issue_key_version
      AND product = NEW.product;
    IF cap IS NULL THEN RETURN NEW; END IF;

    SELECT count(*) INTO open_now FROM public.issues
    WHERE detector_key = NEW.detector_key
      AND issue_key_version = NEW.issue_key_version
      AND product = NEW.product
      AND status = 'OPEN';

    IF open_now >= cap THEN
        RAISE EXCEPTION 'detector % v% exceeded open-issue cap (% >= %)',
            NEW.detector_key, NEW.issue_key_version, open_now, cap;
    END IF;
    RETURN NEW;
END; $$;

CREATE FUNCTION enforce_observation_cardinality() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE cap int; n int;
BEGIN
    PERFORM pg_advisory_xact_lock(NEW.detector_run_id);

    SELECT reg.max_observations_per_run INTO cap
    FROM public.detector_runs dr
    JOIN public.detector_registry reg
      ON reg.detector_key = dr.detector_key
     AND reg.issue_key_version = dr.issue_key_version
     AND reg.product = dr.product
    WHERE dr.id = NEW.detector_run_id;
    IF cap IS NULL THEN RETURN NEW; END IF;

    SELECT count(*) INTO n FROM public.observations
    WHERE detector_run_id = NEW.detector_run_id;

    IF n >= cap THEN
        UPDATE public.detector_runs SET observations_truncated = true
        WHERE id = NEW.detector_run_id;
        RETURN NULL;   -- suppress the fact; the flag makes the loss loud
    END IF;
    RETURN NEW;
END; $$;

-- Status is derived, not asserted by the closing process.
CREATE FUNCTION derive_detector_run_status() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.observations_truncated AND NEW.status = 'OK' THEN
        NEW.status := 'PARTIAL';
    END IF;
    RETURN NEW;
END; $$;

-- ---- schedule geometry ----------------------------------------------------
-- Geometry fields become historical evidence the moment coverage is judged
-- from them, so they freeze once a scheduled run exists.
CREATE FUNCTION enforce_schedule_immutability() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF (OLD.cadence, OLD.schedule_epoch, OLD.evaluation_window, OLD.settle_lag,
        OLD.grace, OLD.coverage_mode, OLD.semantics)
       IS DISTINCT FROM
       (NEW.cadence, NEW.schedule_epoch, NEW.evaluation_window, NEW.settle_lag,
        NEW.grace, NEW.coverage_mode, NEW.semantics)
    THEN
        IF EXISTS (SELECT 1 FROM public.detector_runs
                   WHERE detector_key = OLD.detector_key
                     AND issue_key_version = OLD.issue_key_version
                     AND product = OLD.product
                     AND run_mode = 'SCHEDULED') THEN
            RAISE EXCEPTION
              'schedule geometry for % v% (%) is frozen: scheduled runs exist. '
              'Create a new issue_key_version instead.',
              OLD.detector_key, OLD.issue_key_version, OLD.product;
        END IF;
    END IF;
    RETURN NEW;
END; $$;

CREATE FUNCTION enforce_registry_no_delete() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.detector_runs
               WHERE detector_key = OLD.detector_key
                 AND issue_key_version = OLD.issue_key_version
                 AND product = OLD.product
                 AND run_mode = 'SCHEDULED') THEN
        RAISE EXCEPTION 'cannot delete registry row with scheduled history; set retired_at';
    END IF;
    RETURN OLD;
END; $$;

CREATE FUNCTION reject_boundary_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN RAISE EXCEPTION 'definition boundaries are append-only'; END; $$;

-- SCHEDULED runs may only be created by open_scheduled_run(), and their
-- geometry is asserted independently of the function that computed it.
CREATE FUNCTION enforce_scheduled_run_origin() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE reg public.detector_registry;
BEGIN
    IF NEW.run_mode = 'SCHEDULED' THEN
        IF NOT pg_has_role(current_user, 'fleet_owner', 'MEMBER') THEN
            RAISE EXCEPTION 'SCHEDULED runs may only be created via open_scheduled_run()';
        END IF;
        SELECT * INTO STRICT reg FROM public.detector_registry
        WHERE detector_key = NEW.detector_key
          AND issue_key_version = NEW.issue_key_version
          AND product = NEW.product;
        IF NEW.window_end - NEW.window_start <> reg.evaluation_window THEN
            RAISE EXCEPTION 'scheduled window duration % <> configured %',
                NEW.window_end - NEW.window_start, reg.evaluation_window;
        END IF;
        IF mod(extract(epoch FROM (NEW.window_end - reg.schedule_epoch))::numeric,
               extract(epoch FROM reg.cadence)::numeric) <> 0 THEN
            RAISE EXCEPTION 'scheduled window_end % is off-grid', NEW.window_end;
        END IF;
    END IF;
    RETURN NEW;
END; $$;

CREATE FUNCTION open_scheduled_run(
    p_detector_key text, p_issue_key_version int, p_product text,
    p_slot_end timestamptz DEFAULT NULL)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE reg public.detector_registry; slot_end timestamptz; slot_start timestamptz;
        n bigint; run_id bigint;
BEGIN
    SELECT * INTO STRICT reg FROM public.detector_registry
    WHERE detector_key = p_detector_key AND issue_key_version = p_issue_key_version
      AND product = p_product;

    IF reg.retired_at IS NOT NULL THEN
        RAISE EXCEPTION 'detector % is retired', p_detector_key;
    END IF;

    IF p_slot_end IS NULL THEN
        n := floor(extract(epoch FROM (now() - reg.settle_lag - reg.schedule_epoch))
                   / extract(epoch FROM reg.cadence));
        slot_end := reg.schedule_epoch + (n * reg.cadence);
    ELSE
        IF mod(extract(epoch FROM (p_slot_end - reg.schedule_epoch))::numeric,
               extract(epoch FROM reg.cadence)::numeric) <> 0 THEN
            RAISE EXCEPTION 'slot_end % is not on the schedule grid', p_slot_end;
        END IF;
        IF p_slot_end > now() - reg.settle_lag THEN
            RAISE EXCEPTION 'slot_end % has not settled yet', p_slot_end;
        END IF;
        slot_end := p_slot_end;
    END IF;

    slot_start := slot_end - reg.evaluation_window;

    INSERT INTO public.detector_runs (
        detector_key, detector_version, issue_key_version, product, semantics,
        run_mode, coverage_mode, window_start, window_end, status)
    VALUES (
        p_detector_key, reg.current_detector_version, p_issue_key_version, p_product,
        reg.semantics, 'SCHEDULED', reg.coverage_mode, slot_start, slot_end, 'RUNNING')
    ON CONFLICT (detector_key, issue_key_version, product, window_end)
        WHERE run_mode = 'SCHEDULED'
    DO UPDATE SET last_attempt_at = public.detector_runs.last_attempt_at
    RETURNING id INTO run_id;
    -- Conflict resolves to the existing logical run and performs NO state
    -- transition. Stale retry is owned entirely by reclaim_stale_detector_run().
    RETURN run_id;
END; $$;

-- SIGKILL, OOM and instance death cannot be handled by application cleanup.
-- Without reclaim, a killed slot permanently blocks retry and the precise
-- window containing lost data is never checked.
CREATE FUNCTION reclaim_stale_detector_run(p_run_id bigint)
RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE r public.detector_runs; reg public.detector_registry;
BEGIN
    SELECT * INTO STRICT r FROM public.detector_runs WHERE id = p_run_id;
    IF r.status <> 'RUNNING' THEN RETURN 'not_running'; END IF;

    SELECT * INTO STRICT reg FROM public.detector_registry
    WHERE detector_key = r.detector_key AND issue_key_version = r.issue_key_version
      AND product = r.product;

    -- execution_timeout, not a cadence-derived guess: how often a detector
    -- runs and how long one execution may take are different questions.
    IF r.last_attempt_at > now() - reg.execution_timeout THEN
        RETURN 'still_live';
    END IF;

    IF r.attempt_count >= reg.max_attempts THEN
        UPDATE public.detector_runs
        SET status = 'ERROR', completed_at = now(),
            error = 'window abandoned after ' || r.attempt_count || ' attempts'
        WHERE id = p_run_id;
        RETURN 'abandoned';
    END IF;

    UPDATE public.detector_runs
    SET status = 'RUNNING', attempt_count = attempt_count + 1,
        last_attempt_at = now(), subjects_evaluated = NULL,
        subjects_failed = NULL, error = NULL
    WHERE id = p_run_id;
    RETURN 'reclaimed';
END; $$;

-- ---- coverage -------------------------------------------------------------
-- ALL EVIDENCE HORIZONS ARE (from, to].
--   from  state already known at the start; never evidence for what followed
--   to    belongs to the interval and may establish its final state
--
-- Four clocks, previously collapsed into two arguments:
--   p_from / p_to   the evidence interval being judged
--   settle_lag      when a slot's data becomes judgeable
--   grace           when an absent execution counts as missing
--   p_as_of         when the judgment is being made
-- settle_lag and grace measure maturity against p_as_of, never against p_to.
CREATE FUNCTION expected_slot_range(
    p_detector_key text, p_issue_key_version int, p_product text,
    p_from timestamptz, p_to timestamptz, p_as_of timestamptz,
    OUT first_slot bigint, OUT last_slot bigint)
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $$
DECLARE reg detector_registry; cad numeric; cutoff timestamptz;
BEGIN
    SELECT * INTO STRICT reg FROM detector_registry
    WHERE detector_key = p_detector_key AND issue_key_version = p_issue_key_version
      AND product = p_product;
    cad := extract(epoch FROM reg.cadence);
    cutoff := least(p_to, p_as_of - reg.settle_lag - reg.grace);
    -- floor()+1, not ceil(): a LEVEL issue's last_seen IS a window_end, so
    -- p_from lands on the grid routinely. The slot at last_seen is evidence
    -- the condition was PRESENT; it cannot also be evidence of its absence.
    first_slot := floor(extract(epoch FROM (p_from - reg.schedule_epoch)) / cad) + 1;
    last_slot  := floor(extract(epoch FROM (cutoff - reg.schedule_epoch)) / cad);
END; $$;

-- Did the required detector executions exist across the interval?
CREATE FUNCTION coverage_horizon_valid(
    p_detector_key text, p_issue_key_version int, p_product text,
    p_from timestamptz, p_to timestamptz, p_as_of timestamptz)
RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $$
DECLARE reg detector_registry; cad numeric; fs bigint; ls bigint; actual bigint;
BEGIN
    SELECT * INTO STRICT reg FROM detector_registry
    WHERE detector_key = p_detector_key AND issue_key_version = p_issue_key_version
      AND product = p_product;
    cad := extract(epoch FROM reg.cadence);

    SELECT first_slot, last_slot INTO fs, ls
    FROM expected_slot_range(p_detector_key, p_issue_key_version, p_product,
                             p_from, p_to, p_as_of);
    IF ls < fs THEN RETURN false; END IF;

    -- A missing slot leaves no row, so it is only visible as a count shortfall.
    -- Adjacency checks are vacuous when evaluation_window > cadence.
    SELECT count(*) INTO actual FROM detector_runs dr
    WHERE dr.detector_key      = p_detector_key
      AND dr.issue_key_version = p_issue_key_version
      AND dr.product           = p_product
      AND dr.run_mode          = 'SCHEDULED'
      AND dr.status IN ('OK','PARTIAL')
      AND dr.observations_truncated = false
      AND round(extract(epoch FROM (dr.window_end - reg.schedule_epoch)) / cad)
          BETWEEN fs AND ls;
    IF actual <> (ls - fs + 1) THEN RETURN false; END IF;

    -- Cardinality-exceeded interval overlapping the horizon. "Not open now"
    -- does not rehabilitate historical evidence.
    IF EXISTS (
        SELECT 1 FROM issue_occurrences occ
        JOIN issues c ON c.id = occ.issue_id
        WHERE c.detector_key = 'fleet_heartbeat'
          AND c.product      = p_product
          AND c.issue_type   = 'DETECTOR_CARDINALITY_EXCEEDED'
          AND c.subject_type = 'detector'
          AND c.subject_id   = p_detector_key
          AND occ.opened_at <= p_to
          AND coalesce(occ.closed_at, 'infinity'::timestamptz) > p_from)
    THEN RETURN false; END IF;

    -- Semantic boundary: no horizon may straddle a definition change.
    RETURN NOT EXISTS (
        SELECT 1 FROM detector_definition_boundaries b
        WHERE b.detector_key      = p_detector_key
          AND b.issue_key_version = p_issue_key_version
          AND b.product           = p_product
          AND b.effective_at >  p_from
          AND b.effective_at <= p_to);
END; $$;

-- Did those executions actually evaluate THIS subject? Not "seen at least
-- once", which proves almost nothing over a seven-day horizon.
CREATE FUNCTION subject_horizon_covered(
    p_detector_key text, p_issue_key_version int, p_product text,
    p_subject_type text, p_subject_id text,
    p_from timestamptz, p_to timestamptz, p_as_of timestamptz)
RETURNS boolean
LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public AS $$
DECLARE reg detector_registry; cad numeric; fs bigint; ls bigint;
        actual bigint; subj text;
BEGIN
    SELECT * INTO STRICT reg FROM detector_registry
    WHERE detector_key = p_detector_key AND issue_key_version = p_issue_key_version
      AND product = p_product;
    cad  := extract(epoch FROM reg.cadence);
    subj := p_subject_type || ':' || p_subject_id;

    SELECT first_slot, last_slot INTO fs, ls
    FROM expected_slot_range(p_detector_key, p_issue_key_version, p_product,
                             p_from, p_to, p_as_of);
    IF ls < fs THEN RETURN false; END IF;

    SELECT count(*) INTO actual FROM detector_runs dr
    WHERE dr.detector_key      = p_detector_key
      AND dr.issue_key_version = p_issue_key_version
      AND dr.product           = p_product
      AND dr.run_mode          = 'SCHEDULED'
      AND dr.status IN ('OK','PARTIAL')
      AND dr.observations_truncated = false
      AND (dr.coverage_mode = 'GLOBAL'
           OR (subj = ANY (dr.subjects_evaluated)
               AND NOT (subj = ANY (coalesce(dr.subjects_failed, '{}')))))
      AND round(extract(epoch FROM (dr.window_end - reg.schedule_epoch)) / cad)
          BETWEEN fs AND ls;

    RETURN actual = (ls - fs + 1);
END; $$;

-- Did it remain the same subject throughout? Subject-level, so one tenant's
-- supersession cannot invalidate every other tenant's horizon.
CREATE FUNCTION subject_identity_stable(
    p_detector_key text, p_issue_key_version int, p_product text,
    p_subject_type text, p_subject_id text,
    p_from timestamptz, p_to timestamptz)
RETURNS boolean
SET search_path = pg_catalog, public AS $$
    SELECT NOT EXISTS (
        SELECT 1 FROM issues x
        WHERE x.detector_key      = p_detector_key
          AND x.issue_key_version = p_issue_key_version
          AND x.product           = p_product
          AND x.subject_type      = p_subject_type
          AND x.subject_id        = p_subject_id
          AND x.resolution_type   = 'SUPERSEDED'
          AND x.resolution_effective_at >  p_from
          AND x.resolution_effective_at <= p_to);
$$ LANGUAGE sql STABLE;

-- ---- budget ---------------------------------------------------------------
-- Tokened reservations: a bare release() would let an agent free unlimited
-- budget by settling calls it never made.
CREATE FUNCTION reserve_model_budget(p_run_id bigint, p_estimate numeric)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE tok uuid;
BEGIN
    UPDATE public.runs SET committed_gbp = committed_gbp + p_estimate
    WHERE id = p_run_id
      AND status IN ('ACTIVE','AWAITING_HUMAN')
      AND committed_gbp + p_estimate <= spend_limit_gbp;
    IF NOT FOUND THEN RETURN NULL; END IF;   -- breaker tripped: do not call
    INSERT INTO public.budget_reservations (run_id, estimate_gbp)
    VALUES (p_run_id, p_estimate) RETURNING id INTO tok;
    RETURN tok;
END; $$;

CREATE FUNCTION settle_model_budget(p_token uuid, p_actual numeric, p_call jsonb)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE res public.budget_reservations; mc_id bigint;
BEGIN
    IF p_actual < 0 THEN RAISE EXCEPTION 'actual cost may not be negative'; END IF;

    UPDATE public.budget_reservations SET status = 'SETTLED', settled_at = now()
    WHERE id = p_token AND status = 'HELD'
    RETURNING * INTO res;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no held reservation % (already settled, voided, or unknown)',
            p_token;
    END IF;

    IF p_actual > res.estimate_gbp THEN
        RAISE EXCEPTION 'actual % exceeds reserved upper bound %',
            p_actual, res.estimate_gbp;
    END IF;

    UPDATE public.runs SET committed_gbp = committed_gbp - (res.estimate_gbp - p_actual)
    WHERE id = res.run_id;

    INSERT INTO public.model_calls (
        run_id, reservation_id, provider, model, purpose, started_at, completed_at,
        prompt_tokens, completion_tokens, load_duration_ms, prompt_eval_duration_ms,
        eval_duration_ms, total_duration_ms, marginal_cost_gbp, ok)
    VALUES (
        res.run_id, p_token,
        p_call->>'provider', p_call->>'model', p_call->>'purpose',
        (p_call->>'started_at')::timestamptz, (p_call->>'completed_at')::timestamptz,
        (p_call->>'prompt_tokens')::int, (p_call->>'completion_tokens')::int,
        (p_call->>'load_duration_ms')::int, (p_call->>'prompt_eval_duration_ms')::int,
        (p_call->>'eval_duration_ms')::int, (p_call->>'total_duration_ms')::int,
        p_actual, coalesce((p_call->>'ok')::bool, true))
    RETURNING id INTO mc_id;
    RETURN mc_id;
END; $$;

-- ACCEPTED LEAK: if the API call succeeded and the gateway crashed before
-- settlement, voiding refunds budget for spend that really occurred. The
-- database cannot prove a request is not in flight; age is the only evidence.
-- Void rate is therefore a health metric, not routine housekeeping.
CREATE FUNCTION void_stale_reservations(p_older_than interval)
RETURNS TABLE (reservation_id uuid, run_id bigint, refunded_gbp numeric)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF p_older_than < interval '30 minutes' THEN
        RAISE EXCEPTION 'refusing to void reservations younger than 30 minutes';
    END IF;
    RETURN QUERY
    WITH stale AS (
        UPDATE public.budget_reservations br SET
            status = 'VOID', voided_at = now(),
            voided_reason = 'stale: no model_call after ' || p_older_than
        WHERE br.status = 'HELD'
          AND br.created_at < now() - p_older_than
          AND NOT EXISTS (SELECT 1 FROM public.model_calls mc
                          WHERE mc.reservation_id = br.id)
        RETURNING br.id, br.run_id AS rid, br.estimate_gbp)
    , refunded AS (
        UPDATE public.runs r SET committed_gbp = r.committed_gbp - s.estimate_gbp
        FROM stale s WHERE r.id = s.rid
        RETURNING s.id, s.rid, s.estimate_gbp)
    SELECT * FROM refunded;
END; $$;

-- ---- outcome --------------------------------------------------------------
-- Precedence: REGRESSION > RECURRENCE. A regression means the intervention
-- caused new harm; a recurrence means it merely failed to hold. When both
-- appear, the label governing future autonomy should describe harm caused.
-- Terminal failures short-circuit while later horizons are pending;
-- SUCCESS never does.
CREATE FUNCTION evaluate_run_outcome(p_run_id bigint) RETURNS text
SET search_path = pg_catalog, public AS $$
    SELECT CASE
        WHEN bool_or(required AND result = 'REGRESSION')   THEN 'REGRESSION'
        WHEN bool_or(required AND result = 'RECURRENCE')   THEN 'RECURRENCE'
        WHEN bool_or(required AND status <> 'DONE')        THEN NULL
        WHEN bool_or(required AND result = 'INCONCLUSIVE') THEN 'INCONCLUSIVE'
        WHEN bool_and(NOT required OR result = 'SUCCESS')  THEN 'SUCCESS'
        ELSE NULL END
    FROM scheduled_checks WHERE run_id = p_run_id;
$$ LANGUAGE sql STABLE;

CREATE FUNCTION guard_final_outcome() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.final_outcome IS DISTINCT FROM OLD.final_outcome
       AND NEW.final_outcome IS DISTINCT FROM evaluate_run_outcome(NEW.id) THEN
        RAISE EXCEPTION 'final_outcome % contradicts scheduled checks (computed %)',
            NEW.final_outcome, evaluate_run_outcome(NEW.id);
    END IF;
    RETURN NEW;
END; $$;

-- ---- verdicts -------------------------------------------------------------
-- False-positive rate gates detector trust, so its inputs must be trusted.
CREATE FUNCTION enforce_verdict_authority() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NOT (pg_has_role(current_user, 'fleet_console',  'MEMBER')
         OR pg_has_role(current_user, 'fleet_evaluator','MEMBER')) THEN
        RAISE EXCEPTION '% may not record observation verdicts', current_user;
    END IF;
    RETURN NEW;
END; $$;

-- ---- occurrences ----------------------------------------------------------
-- A row that can reopen cannot answer historical interval questions about
-- itself. Derived by trigger: lifecycle code that must remember to append is
-- lifecycle code that will eventually forget, and the failure mode is a gap
-- that reads as health.
CREATE FUNCTION maintain_issue_occurrences() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO public.issue_occurrences (issue_id, opened_at)
        VALUES (NEW.id, NEW.first_seen);

    ELSIF OLD.status <> 'RESOLVED' AND NEW.status = 'RESOLVED' THEN
        IF NEW.resolution_effective_at IS NULL THEN
            RAISE EXCEPTION
              'RESOLVED issue % requires a trusted resolution_effective_at', NEW.id;
        END IF;
        UPDATE public.issue_occurrences SET closed_at = NEW.resolution_effective_at
        WHERE issue_id = NEW.id AND closed_at IS NULL;

    ELSIF OLD.status = 'RESOLVED' AND NEW.status <> 'RESOLVED' THEN
        INSERT INTO public.issue_occurrences (issue_id, opened_at)
        VALUES (NEW.id, NEW.last_seen);
    END IF;
    RETURN NULL;
END; $$;
-- SUPPRESSED does NOT close an occurrence. Suppression means "stop telling
-- me", not "the condition ended"; closing on it would let a silenced
-- cardinality incident rehabilitate the evidence it invalidated.

CREATE FUNCTION reject_occurrence_tampering() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NOT pg_has_role(current_user, 'fleet_owner', 'MEMBER') THEN
        RAISE EXCEPTION 'issue_occurrences is maintained by trigger only';
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.opened_at IS DISTINCT FROM OLD.opened_at THEN
        RAISE EXCEPTION 'opened_at is immutable';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END; $$;

-- ---- resolution effective time -------------------------------------------
-- Three distinct times, previously conflated by a coalesce:
--   last_seen                latest evidence the condition WAS present
--   resolution_effective_at  earliest trusted evidence it was ABSENT
--   resolved_at              when the lifecycle transition was executed
CREATE FUNCTION guard_resolution_effective() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.resolution_effective_at IS DISTINCT FROM OLD.resolution_effective_at
       AND NEW.resolution_effective_at IS NOT NULL
       AND NOT pg_has_role(current_user, 'fleet_owner', 'MEMBER') THEN
        RAISE EXCEPTION 'resolution_effective_at is set by the trusted resolver only';
    END IF;
    RETURN NEW;
END; $$;

-- ---- resolver -------------------------------------------------------------
-- The only path that can set CLEARED. It derives its own evidence: effective
-- time = window_end of the Nth covering run after last_seen. Not the
-- resolver's clock, not the last bad observation.
CREATE FUNCTION resolve_cleared_issues() RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE i public.issues; reg public.detector_registry; eff timestamptz;
        judge_at timestamptz := now();      -- one verdict, one clock
        resolved_id bigint; n bigint := 0;
BEGIN
    FOR i IN SELECT * FROM public.issues WHERE status = 'OPEN' LOOP
        SELECT * INTO reg FROM public.detector_registry
        WHERE detector_key = i.detector_key
          AND issue_key_version = i.issue_key_version AND product = i.product;
        CONTINUE WHEN NOT FOUND OR reg.semantics <> 'LEVEL';

        SELECT dr.window_end INTO eff
        FROM public.detector_runs dr
        WHERE dr.detector_key      = i.detector_key
          AND dr.issue_key_version = i.issue_key_version
          AND dr.product           = i.product
          AND dr.run_mode          = 'SCHEDULED'
          AND dr.status IN ('OK','PARTIAL')
          AND dr.observations_truncated = false
          AND dr.window_end > i.last_seen                      -- (from, to]
          AND (dr.coverage_mode = 'GLOBAL'
               OR ((i.subject_type || ':' || i.subject_id) = ANY (dr.subjects_evaluated)
                   AND NOT ((i.subject_type || ':' || i.subject_id)
                            = ANY (coalesce(dr.subjects_failed, '{}')))))
        ORDER BY dr.window_end
        OFFSET (reg.required_clear_runs - 1) LIMIT 1;

        CONTINUE WHEN eff IS NULL;

        -- Horizon judged over [last_seen, eff], NOT to now(): a detector
        -- outage after the clearing evidence does not un-clear a condition
        -- that was properly observed to stop.
        CONTINUE WHEN NOT public.coverage_horizon_valid(
            i.detector_key, i.issue_key_version, i.product,
            i.last_seen, eff, judge_at);
        CONTINUE WHEN NOT public.subject_horizon_covered(
            i.detector_key, i.issue_key_version, i.product,
            i.subject_type, i.subject_id, i.last_seen, eff, judge_at);
        CONTINUE WHEN NOT public.subject_identity_stable(
            i.detector_key, i.issue_key_version, i.product,
            i.subject_type, i.subject_id, i.last_seen, eff);

        -- Compare-and-set on evidence identity. latest_observation_id is
        -- monotonic and changes on every new observation including a reopen,
        -- so it catches the case where status reads OPEN both times.
        UPDATE public.issues SET
            status = 'RESOLVED', resolution_type = 'CLEARED',
            resolved_at = judge_at, resolution_effective_at = eff
        WHERE id = i.id AND status = 'OPEN'
          AND latest_observation_id IS NOT DISTINCT FROM i.latest_observation_id
        RETURNING id INTO resolved_id;

        IF resolved_id IS NOT NULL THEN n := n + 1; END IF;
        resolved_id := NULL;
    END LOOP;
    RETURN n;
END; $$;

-- ---- outcome evaluator ----------------------------------------------------
CREATE FUNCTION execute_due_outcome_checks() RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE c public.scheduled_checks; i public.issues;
        h_from timestamptz; verdict text;
        judge_at timestamptz := now();      -- one batch, one clock
        n bigint := 0;
BEGIN
    FOR c IN
        UPDATE public.scheduled_checks SET status = 'RUNNING',
               attempts = attempts + 1
        WHERE id IN (SELECT id FROM public.scheduled_checks
                     WHERE status = 'PENDING' AND due_at <= judge_at
                     ORDER BY due_at FOR UPDATE SKIP LOCKED LIMIT 50)
        RETURNING *
    LOOP
        SELECT * INTO i FROM public.issues WHERE id = c.issue_id;

        SELECT rs.created_at INTO h_from FROM public.run_steps rs
        WHERE rs.run_id = c.run_id AND rs.step_type = 'DEPLOYED'
        ORDER BY rs.sequence DESC LIMIT 1;

        IF h_from IS NULL THEN
            verdict := 'INCONCLUSIVE';       -- nothing was deployed to measure

        -- Recurrence first: positive evidence beats any absence argument, and
        -- a coverage outage must not soften a known failure.
        ELSIF EXISTS (SELECT 1 FROM public.observations o
                      WHERE o.fingerprint = c.fingerprint
                        AND o.run_mode = 'SCHEDULED'
                        AND o.observed_at >  h_from
                        AND o.observed_at <= c.due_at)
        THEN verdict := 'RECURRENCE';

        ELSIF NOT public.coverage_horizon_valid(
                  i.detector_key, i.issue_key_version, i.product,
                  h_from, c.due_at, judge_at)
           OR NOT public.subject_horizon_covered(
                  i.detector_key, i.issue_key_version, i.product,
                  i.subject_type, i.subject_id, h_from, c.due_at, judge_at)
           OR NOT public.subject_identity_stable(
                  i.detector_key, i.issue_key_version, i.product,
                  i.subject_type, i.subject_id, h_from, c.due_at)
        THEN verdict := 'INCONCLUSIVE';

        ELSE verdict := 'SUCCESS';
        END IF;

        UPDATE public.scheduled_checks SET status = 'DONE', result = verdict,
               executed_at = judge_at
        WHERE id = c.id;

        UPDATE public.runs SET
            final_outcome = public.evaluate_run_outcome(c.run_id),
            outcome_at = CASE WHEN public.evaluate_run_outcome(c.run_id) IS NOT NULL
                              THEN judge_at END
        WHERE id = c.run_id;

        n := n + 1;
    END LOOP;
    RETURN n;
END; $$;
-- REGRESSION is intentionally unproduced. It requires cross-detector impact
-- relationships that do not exist yet; evaluate_run_outcome already ranks it
-- above RECURRENCE for when they do.

-- ---- version transition ---------------------------------------------------
-- The caller proposes the successor configuration; the trusted function
-- assigns its identity. Reading DEFINITION_CHANGED off an issues row would
-- make the boundary conditional on something being open at the time.
CREATE FUNCTION bump_issue_key_version(
    p_detector_key text, p_old_version int, p_product text,
    p_cadence interval, p_evaluation_window interval, p_schedule_epoch timestamptz,
    p_settle_lag interval, p_grace interval, p_coverage_mode text,
    p_semantics text, p_reason text DEFAULT NULL)
RETURNS int
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE t timestamptz := now(); new_v int; old public.detector_registry;
BEGIN
    SELECT * INTO old FROM public.detector_registry
    WHERE detector_key = p_detector_key AND issue_key_version = p_old_version
      AND product = p_product FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'no registry row for % v% (%)',
        p_detector_key, p_old_version, p_product; END IF;

    new_v := p_old_version + 1;
    IF EXISTS (SELECT 1 FROM public.detector_registry
               WHERE detector_key = p_detector_key AND issue_key_version = new_v
                 AND product = p_product) THEN
        RAISE EXCEPTION 'successor issue_key_version % already exists', new_v;
    END IF;

    INSERT INTO public.detector_definition_boundaries
        (detector_key, issue_key_version, product, effective_at,
         successor_version, reason)
    VALUES (p_detector_key, p_old_version, p_product, t, new_v, p_reason);

    INSERT INTO public.detector_registry (
        detector_key, issue_key_version, product,
        cadence, evaluation_window, schedule_epoch, settle_lag, grace,
        coverage_mode, semantics,
        max_attempts, execution_timeout, required_clear_runs,
        max_open_issues, max_observations_per_run, current_detector_version)
    VALUES (
        p_detector_key, new_v, p_product,
        p_cadence, p_evaluation_window, p_schedule_epoch, p_settle_lag, p_grace,
        p_coverage_mode, p_semantics,
        old.max_attempts, old.execution_timeout, old.required_clear_runs,
        old.max_open_issues, old.max_observations_per_run, 1);

    UPDATE public.detector_registry SET retired_at = t
    WHERE detector_key = p_detector_key AND issue_key_version = p_old_version
      AND product = p_product;

    -- Old-version issues close together, at the boundary, in one transaction.
    UPDATE public.issues SET
        status = 'RESOLVED', resolution_type = 'DEFINITION_CHANGED',
        resolved_at = t, resolution_effective_at = t
    WHERE detector_key = p_detector_key AND issue_key_version = p_old_version
      AND product = p_product AND status <> 'RESOLVED';

    RETURN new_v;
END; $$;

-- Boundary comes from the database: the successor's open occurrence. The two
-- intervals abut exactly. No function anywhere accepts an effective time.
CREATE FUNCTION supersede_issue(
    p_issue_id bigint, p_superseded_by bigint, p_expected_observation_id bigint)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE old_i public.issues; new_i public.issues; eff timestamptz;
        old_open timestamptz; done bigint;
BEGIN
    SELECT * INTO STRICT old_i FROM public.issues WHERE id = p_issue_id;
    SELECT * INTO STRICT new_i FROM public.issues WHERE id = p_superseded_by;

    IF p_issue_id = p_superseded_by THEN
        RAISE EXCEPTION 'an issue cannot supersede itself';
    END IF;
    IF new_i.product <> old_i.product OR new_i.detector_key <> old_i.detector_key THEN
        RAISE EXCEPTION 'superseding issue must share product and detector';
    END IF;
    IF new_i.status = 'RESOLVED' THEN
        RAISE EXCEPTION 'superseding issue % is not live', p_superseded_by;
    END IF;

    SELECT occ.opened_at INTO STRICT eff FROM public.issue_occurrences occ
    WHERE occ.issue_id = p_superseded_by AND occ.closed_at IS NULL;

    SELECT occ.opened_at INTO old_open FROM public.issue_occurrences occ
    WHERE occ.issue_id = p_issue_id AND occ.closed_at IS NULL;
    IF old_open IS NOT NULL AND eff < old_open THEN
        RAISE EXCEPTION 'successor opened before the issue it supersedes';
    END IF;

    UPDATE public.issues SET
        status = 'RESOLVED', resolution_type = 'SUPERSEDED',
        resolved_at = now(), resolution_effective_at = eff,
        superseded_by_issue_id = p_superseded_by
    WHERE id = p_issue_id
      AND status <> 'RESOLVED'
      AND latest_observation_id IS NOT DISTINCT FROM p_expected_observation_id
    RETURNING id INTO done;

    RETURN done IS NOT NULL;
END; $$;

-- ---- retention ------------------------------------------------------------
CREATE FUNCTION purge_observations(p_before timestamptz) RETURNS bigint
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE n bigint;
BEGIN
    IF NOT pg_has_role(current_user, 'fleet_admin', 'MEMBER') THEN
        RAISE EXCEPTION 'retention is admin-only';
    END IF;
    IF p_before > now() - interval '18 months' THEN
        RAISE EXCEPTION 'retention floor is 18 months';
    END IF;
    WITH doomed AS (
        DELETE FROM observations o WHERE o.observed_at < p_before
          AND NOT EXISTS (SELECT 1 FROM issues i
                          WHERE i.status = 'OPEN'
                            AND (i.first_observation_id = o.id
                                 OR i.latest_observation_id = o.id))
        RETURNING 1)
    SELECT count(*) INTO n FROM doomed;
    RETURN n;
END; $$;

-- ---- cost views -----------------------------------------------------------
CREATE VIEW v_run_cost_marginal AS
SELECT r.id AS run_id, coalesce(sum(mc.marginal_cost_gbp),0) AS marginal_gbp
FROM runs r LEFT JOIN model_calls mc ON mc.run_id = r.id GROUP BY r.id;

-- Idle GPU time is absorbed by whatever ran, so a mostly-idle instance makes
-- every task look expensive. That is the correct signal.
CREATE VIEW v_run_cost_allocated AS
WITH local_month AS (
    SELECT date_trunc('month', started_at)::date AS m,
           sum(total_duration_ms)::numeric AS ms
    FROM model_calls WHERE provider = 'ollama' GROUP BY 1),
fixed AS (
    SELECT period_month AS m, sum(cost_gbp) AS gbp FROM infra_costs GROUP BY 1)
SELECT r.id AS run_id,
       coalesce(sum(mc.marginal_cost_gbp) FILTER (WHERE mc.provider <> 'ollama'),0)
         AS api_gbp,
       coalesce(sum(
           CASE WHEN mc.provider = 'ollama' AND lm.ms > 0
                THEN f.gbp * mc.total_duration_ms / lm.ms END), 0) AS allocated_gpu_gbp
FROM runs r
LEFT JOIN model_calls mc ON mc.run_id = r.id
LEFT JOIN local_month lm ON lm.m = date_trunc('month', mc.started_at)::date
LEFT JOIN fixed f        ON f.m  = lm.m
GROUP BY r.id;

-- ============================================================ 6. TRIGGERS

CREATE TRIGGER observations_immutable BEFORE UPDATE OR DELETE ON observations
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER run_steps_immutable BEFORE UPDATE OR DELETE ON run_steps
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER model_calls_immutable BEFORE UPDATE OR DELETE ON model_calls
    FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE TRIGGER observations_run_identity BEFORE INSERT ON observations
    FOR EACH ROW EXECUTE FUNCTION enforce_observation_run_identity();
CREATE TRIGGER observations_cardinality BEFORE INSERT ON observations
    FOR EACH ROW EXECUTE FUNCTION enforce_observation_cardinality();

CREATE TRIGGER issues_cardinality BEFORE INSERT ON issues
    FOR EACH ROW EXECUTE FUNCTION enforce_issue_cardinality();
CREATE TRIGGER issues_scheduled_source BEFORE INSERT OR UPDATE ON issues
    FOR EACH ROW EXECUTE FUNCTION enforce_scheduled_issue_source();
CREATE TRIGGER issues_guard_effective BEFORE UPDATE ON issues
    FOR EACH ROW EXECUTE FUNCTION guard_resolution_effective();
CREATE TRIGGER issues_maintain_occurrences AFTER INSERT OR UPDATE ON issues
    FOR EACH ROW EXECUTE FUNCTION maintain_issue_occurrences();

CREATE TRIGGER issue_occurrences_guard
    BEFORE INSERT OR UPDATE OR DELETE ON issue_occurrences
    FOR EACH ROW EXECUTE FUNCTION reject_occurrence_tampering();

CREATE TRIGGER run_steps_authority BEFORE INSERT ON run_steps
    FOR EACH ROW EXECUTE FUNCTION enforce_step_authority();
CREATE TRIGGER run_steps_acceptance BEFORE INSERT ON run_steps
    FOR EACH ROW EXECUTE FUNCTION enforce_acceptance_boundary();

CREATE TRIGGER runs_guard_outcome BEFORE UPDATE ON runs
    FOR EACH ROW EXECUTE FUNCTION guard_final_outcome();

CREATE TRIGGER detector_runs_scheduled_origin BEFORE INSERT ON detector_runs
    FOR EACH ROW EXECUTE FUNCTION enforce_scheduled_run_origin();
CREATE TRIGGER detector_runs_derive_status BEFORE UPDATE ON detector_runs
    FOR EACH ROW EXECUTE FUNCTION derive_detector_run_status();

CREATE TRIGGER detector_registry_geometry_frozen BEFORE UPDATE ON detector_registry
    FOR EACH ROW EXECUTE FUNCTION enforce_schedule_immutability();
CREATE TRIGGER detector_registry_no_delete BEFORE DELETE ON detector_registry
    FOR EACH ROW EXECUTE FUNCTION enforce_registry_no_delete();

CREATE TRIGGER definition_boundaries_immutable
    BEFORE UPDATE OR DELETE ON detector_definition_boundaries
    FOR EACH ROW EXECUTE FUNCTION reject_boundary_mutation();

CREATE TRIGGER observation_verdicts_authority BEFORE INSERT ON observation_verdicts
    FOR EACH ROW EXECUTE FUNCTION enforce_verdict_authority();

-- ============================================================ 7. OWNERSHIP

ALTER FUNCTION enforce_issue_cardinality()        OWNER TO fleet_owner;
ALTER FUNCTION enforce_observation_cardinality()  OWNER TO fleet_owner;
ALTER FUNCTION maintain_issue_occurrences()       OWNER TO fleet_owner;
ALTER FUNCTION open_scheduled_run(text,int,text,timestamptz)     OWNER TO fleet_owner;
ALTER FUNCTION reclaim_stale_detector_run(bigint)               OWNER TO fleet_owner;
ALTER FUNCTION reserve_model_budget(bigint,numeric)             OWNER TO fleet_owner;
ALTER FUNCTION settle_model_budget(uuid,numeric,jsonb)          OWNER TO fleet_owner;
ALTER FUNCTION void_stale_reservations(interval)                OWNER TO fleet_owner;
ALTER FUNCTION resolve_cleared_issues()                         OWNER TO fleet_owner;
ALTER FUNCTION execute_due_outcome_checks()                     OWNER TO fleet_owner;
ALTER FUNCTION supersede_issue(bigint,bigint,bigint)            OWNER TO fleet_owner;
ALTER FUNCTION bump_issue_key_version(text,int,text,interval,interval,timestamptz,
      interval,interval,text,text,text)                         OWNER TO fleet_owner;

-- fleet_owner needs rights on what its definer functions touch, and nothing else.
GRANT SELECT, UPDATE, INSERT ON public.runs                TO fleet_owner;
GRANT SELECT, INSERT, UPDATE  ON public.budget_reservations TO fleet_owner;
GRANT SELECT, INSERT          ON public.model_calls         TO fleet_owner;
GRANT SELECT, UPDATE, INSERT  ON public.detector_runs       TO fleet_owner;
GRANT SELECT, UPDATE, INSERT  ON public.issues              TO fleet_owner;
GRANT SELECT, INSERT, UPDATE  ON public.issue_occurrences   TO fleet_owner;
GRANT SELECT, UPDATE          ON public.scheduled_checks    TO fleet_owner;
GRANT SELECT                  ON public.run_steps           TO fleet_owner;
GRANT SELECT                  ON public.observations        TO fleet_owner;
GRANT SELECT, INSERT, UPDATE  ON public.detector_registry   TO fleet_owner;
GRANT SELECT, INSERT          ON public.detector_definition_boundaries TO fleet_owner;
GRANT USAGE, SELECT ON SEQUENCE model_calls_id_seq, issue_occurrences_id_seq,
      detector_runs_id_seq TO fleet_owner;

-- ============================================================ 8. GRANTS

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;

GRANT SELECT ON detector_registry, source_registry, routing_policy,
      detector_definition_boundaries, issue_occurrences
      TO fleet_detector, fleet_evaluator, fleet_console;

GRANT SELECT, INSERT ON observations TO fleet_detector;
GRANT SELECT, INSERT, UPDATE ON issues TO fleet_detector;
GRANT SELECT, UPDATE ON detector_runs TO fleet_detector;
GRANT USAGE, SELECT ON SEQUENCE observations_id_seq, issues_id_seq TO fleet_detector;

GRANT SELECT ON runs, issues, observations TO fleet_agent, fleet_verifier;
GRANT SELECT, INSERT ON run_steps TO fleet_agent, fleet_verifier,
      fleet_deployer, fleet_console;
GRANT USAGE, SELECT ON SEQUENCE run_steps_id_seq TO fleet_agent, fleet_verifier,
      fleet_deployer, fleet_console;
GRANT UPDATE (status, completed_at) ON runs TO fleet_deployer;
GRANT UPDATE (final_outcome, outcome_at) ON runs TO fleet_evaluator;

GRANT SELECT, INSERT ON observation_verdicts TO fleet_console, fleet_evaluator;
GRANT USAGE, SELECT ON SEQUENCE observation_verdicts_id_seq
      TO fleet_console, fleet_evaluator;
-- Both verdict-recording roles must be able to read what they are ruling on.
-- Without this the verdict path is INSERT-only on a fresh install: the role
-- can record a judgement but cannot see the observation it is judging, and
-- cannot find the untriaged ones at all. It worked in the deployed database
-- only because the migration identity happens to own the tables, which is
-- exactly the difference a fresh install exposes.
--
-- fleet_evaluator is here for the manual half of its job, not the automated
-- one. resolve_cleared_issues() and execute_due_outcome_checks() are
-- SECURITY DEFINER and never needed the grant, which is why the gap survived
-- being exercised: the code path that runs on a timer does not take it.
GRANT SELECT ON observations, issues TO fleet_console, fleet_evaluator;

REVOKE ALL ON FUNCTION reserve_model_budget(bigint,numeric) FROM PUBLIC;
REVOKE ALL ON FUNCTION settle_model_budget(uuid,numeric,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION void_stale_reservations(interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION open_scheduled_run(text,int,text,timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION reclaim_stale_detector_run(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION resolve_cleared_issues() FROM PUBLIC;
REVOKE ALL ON FUNCTION execute_due_outcome_checks() FROM PUBLIC;
REVOKE ALL ON FUNCTION supersede_issue(bigint,bigint,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION bump_issue_key_version(text,int,text,interval,interval,
      timestamptz,interval,interval,text,text,text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION reserve_model_budget(bigint,numeric)    TO fleet_model_gateway;
GRANT EXECUTE ON FUNCTION settle_model_budget(uuid,numeric,jsonb) TO fleet_model_gateway;
GRANT EXECUTE ON FUNCTION void_stale_reservations(interval)       TO fleet_evaluator;
GRANT EXECUTE ON FUNCTION open_scheduled_run(text,int,text,timestamptz) TO fleet_detector;
GRANT EXECUTE ON FUNCTION reclaim_stale_detector_run(bigint)      TO fleet_detector;
GRANT EXECUTE ON FUNCTION resolve_cleared_issues()                TO fleet_evaluator;
GRANT EXECUTE ON FUNCTION execute_due_outcome_checks()            TO fleet_evaluator;
GRANT EXECUTE ON FUNCTION supersede_issue(bigint,bigint,bigint)   TO fleet_console;
GRANT EXECUTE ON FUNCTION bump_issue_key_version(text,int,text,interval,interval,
      timestamptz,interval,interval,text,text,text)               TO fleet_console;
