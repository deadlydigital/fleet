-- ============================================================================
-- 012_daily_brief.sql  —  a pass that reads the business and writes down what
--                         it saw, and the two identities that keep it honest
--
-- Spec: specs/daily-brief.md. This file is its storage and its permissions.
--
-- TWO TABLES, BECAUSE "FOUND NOTHING" AND "DID NOT RUN" MUST NOT LOOK ALIKE
--
-- A `brief_runs` row with zero `brief_claims` is a positive assertion that a
-- pass happened and had nothing to say. No `brief_runs` row is silence. One
-- table cannot express the difference, and the difference is the whole reason
-- a daily brief is worth keeping -- a reader who cannot tell "quiet" from
-- "broken" will read both as quiet.
--
-- Same argument as `reconciliation_order_id_sets` sitting above
-- `reconciliation_order_ids`, and as `figures_compared` on a reconciliation
-- run. It keeps arriving because it keeps being the thing that goes wrong.
--
-- IN `fleet` FOR THE REASON RECONCILIATION-RUNS §4.2 ALREADY GIVES
--
-- A brief is a record ABOUT the business, not business data. Filing it in
-- `deadly_digital` would put the record inside the thing being recorded and
-- require the reader to hold write access to it, at which point the read-only
-- property that makes the reading credible is gone. Not re-argued here.
--
-- THE RULE IS IN THE CONSTRAINTS, NOT IN THE RENDERER
--
-- Every COMPUTED claim must carry a source and an `as_of`; every UNCOMPUTED one
-- must say why and may not carry a value. Both are CHECK constraints rather
-- than renderer discipline, because a renderer is one refactor away from
-- dropping a field and a constraint is not. A brief whose claims cannot say
-- where they came from is the artefact this whole design exists to prevent, and
-- it is the pleasant one to read.
--
-- Target: PostgreSQL 15+, same floor as 010.
-- ============================================================================

\set ON_ERROR_STOP on

-- ============================================================ 1. WRITER ROLE
--
-- A SEPARATE IDENTITY, AND THAT IS THE POINT.
--
-- `dd_detector_login` reads: `deadly_digital` (orders, tenants,
-- utm_source_alias, analytics_<t>.orders) and, after section 4 below, the
-- fleet tables the brief reports on. It gains NOTHING here. `fleet_brief_writer`
-- writes the two brief tables and can read nothing at all.
--
-- One identity that both reads the business and writes the record of it is the
-- boundary every other part of this system spends effort defending:
-- `detectors/reconciliation.py` opens a read-only transaction and says "this
-- process cannot write to deadly_digital, and that is the point";
-- RECONCILIATION-RUNS §4.2 put the run tables in `fleet` rather than grant the
-- auditor write access to the audited schema. Collapsing the two here would
-- undo both for the convenience of one connection string.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fleet_brief_writer') THEN
        CREATE ROLE fleet_brief_writer NOLOGIN;
    END IF;
END $$;

-- ============================================================ 2. TABLES

CREATE TABLE IF NOT EXISTS brief_runs (
    id                 bigserial PRIMARY KEY,
    generated_at       timestamptz NOT NULL DEFAULT now(),

    -- The previous run's generated_at. NULL on the first ever run, which is a
    -- fact about this brief rather than a gap in it.
    compares_since     timestamptz,

    code_version       text NOT NULL CHECK (length(btrim(code_version)) > 0),

    -- sha256 of objectives-2026-Q4.yaml. A brief written against changed
    -- objectives is detectable rather than silently comparable to one that
    -- was not.
    objectives_version text NOT NULL CHECK (length(btrim(objectives_version)) > 0),

    -- WHICH SOURCES THE PASS COULD REACH, AS IT FOUND THEM -- not as the
    -- roster says they should be. A source reachable yesterday and not today
    -- is the finding, and it is only visible if every run records its own
    -- answer instead of assuming the list.
    sources_reachable   jsonb NOT NULL DEFAULT '[]'::jsonb
                        CHECK (jsonb_typeof(sources_reachable) = 'array'),
    sources_unreachable jsonb NOT NULL DEFAULT '[]'::jsonb
                        CHECK (jsonb_typeof(sources_unreachable) = 'array'),

    claims_total       integer NOT NULL,
    claims_uncomputed  integer NOT NULL,

    -- The brief as issued. Stored because it is the artefact a person read, and
    -- immutable, so it cannot drift from the claims. The CLAIMS are canonical
    -- for comparison; this is the copy of record.
    rendered_markdown  text NOT NULL CHECK (length(btrim(rendered_markdown)) > 0),

    started_at         timestamptz NOT NULL,
    completed_at       timestamptz NOT NULL,

    CONSTRAINT brief_runs_counts_ck
        CHECK (claims_total >= 0
               AND claims_uncomputed BETWEEN 0 AND claims_total),
    CONSTRAINT brief_runs_ordered_ck
        CHECK (completed_at >= started_at)
);

COMMENT ON TABLE brief_runs IS
  'One row per daily pass. A row with zero brief_claims means the pass ran and '
  'had nothing to say; no row means it did not run.';
COMMENT ON COLUMN brief_runs.claims_uncomputed IS
  'On the run row so it can be read without opening the brief. Zero, on the '
  'current grants, is not credible -- see specs/daily-brief.md section 6.';

CREATE TABLE IF NOT EXISTS brief_claims (
    id            bigserial PRIMARY KEY,
    run_id        bigint NOT NULL REFERENCES brief_runs(id) ON DELETE CASCADE,

    -- LOOKS_WRONG is in the vocabulary and is DELIBERATELY UNUSED for now.
    -- Judging needs something to judge against: deriving thresholds from
    -- history blesses whatever today's numbers happen to be, and typing them by
    -- hand creates exactly the hand-maintained tally that was wrong three times
    -- in one day on 7 Sep 2026. The brief ships as description only until there
    -- is something to judge against. The value exists so that adding judgement
    -- later is not a schema change.
    section       text NOT NULL
                  CHECK (section IN ('CHANGED','LOOKS_WRONG','UNCOMPUTED')),

    -- Stable across runs. This is the mechanism that makes accumulation useful:
    -- today's row joins to yesterday's on this key. Without it, comparing two
    -- briefs is prose diffing, and nobody does that twice.
    metric_key    text NOT NULL CHECK (length(btrim(metric_key)) > 0),

    statement     text NOT NULL CHECK (length(btrim(statement)) > 0),

    source        text,
    -- THE INSTANT THE VALUE DESCRIBES, NOT now(). A snapshot read at 03:00 of a
    -- table last written at 21:00 yesterday is as_of 21:00. Getting this wrong
    -- makes a stale number look fresh, which is the failure a daily brief is
    -- most likely to commit and least likely to have caught.
    as_of         timestamptz,

    value_num     numeric,
    value_text    text,

    -- Carried from the previous run's row, NEVER recomputed from today's
    -- database. A backfilled source would otherwise let a brief silently
    -- restate history -- the same defect as a view that recomputes "the
    -- evidence this decision cited".
    previous_num  numeric,
    delta_num     numeric,

    -- "Evidence whose query text cannot be recovered is not evidence"
    -- (detectors/reconciliation.py). Same terms.
    query_key     text,
    query_version integer,

    status        text NOT NULL CHECK (status IN ('COMPUTED','UNCOMPUTED')),
    uncomputed_reason text,

    -- A claim that cannot say where it came from or how old it is does not go
    -- in the brief.
    CONSTRAINT brief_claims_computed_is_sourced_ck CHECK (
        status <> 'COMPUTED'
        OR (source IS NOT NULL
            AND as_of IS NOT NULL
            AND (value_num IS NOT NULL OR value_text IS NOT NULL))),

    -- An uncomputed claim says why, and may not smuggle a value in beside the
    -- excuse.
    CONSTRAINT brief_claims_uncomputed_says_why_ck CHECK (
        status <> 'UNCOMPUTED'
        OR (uncomputed_reason IS NOT NULL
            AND length(btrim(uncomputed_reason)) > 0
            AND value_num IS NULL
            AND value_text IS NULL)),

    -- The section and the status cannot disagree about what a row is.
    CONSTRAINT brief_claims_uncomputed_section_ck CHECK (
        (section = 'UNCOMPUTED') = (status = 'UNCOMPUTED')),

    -- A delta is only meaningful when both sides exist, and must equal them.
    CONSTRAINT brief_claims_delta_is_arithmetic_ck CHECK (
        delta_num IS NULL
        OR (value_num IS NOT NULL AND previous_num IS NOT NULL
            AND delta_num = value_num - previous_num))
);

COMMENT ON TABLE brief_claims IS
  'One claim per row. A COMPUTED claim carries a source and an as_of or it '
  'cannot be inserted; an UNCOMPUTED one carries a reason and no value.';

CREATE INDEX IF NOT EXISTS brief_claims_run_idx
    ON brief_claims (run_id, section);
-- The join that makes two briefs comparable.
CREATE INDEX IF NOT EXISTS brief_claims_metric_idx
    ON brief_claims (metric_key, id DESC);
CREATE INDEX IF NOT EXISTS brief_runs_generated_idx
    ON brief_runs (generated_at DESC);

-- ============================================================ 3. IMMUTABILITY
--
-- Append-only, on the same terms as decision_log and the reconciliation runs. A
-- corrected brief is a NEW brief; the sequence of runs is itself the signal,
-- and a brief that can be edited afterwards is a brief that can be made to have
-- predicted things.
CREATE OR REPLACE FUNCTION guard_brief_immutability() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION 'brief rows are settled; write a new brief rather than '
                    'revising %', TG_TABLE_NAME
        USING HINT = 'the sequence of briefs is the record, not the latest one';
END; $$;

DROP TRIGGER IF EXISTS brief_runs_immutable ON brief_runs;
CREATE TRIGGER brief_runs_immutable BEFORE UPDATE OR DELETE ON brief_runs
    FOR EACH ROW EXECUTE FUNCTION guard_brief_immutability();

DROP TRIGGER IF EXISTS brief_claims_immutable ON brief_claims;
CREATE TRIGGER brief_claims_immutable BEFORE UPDATE OR DELETE ON brief_claims
    FOR EACH ROW EXECUTE FUNCTION guard_brief_immutability();

-- ============================================================ 4. THE GRANTS
--
-- Named individually rather than as a schema-wide grant. A blanket
-- `GRANT SELECT ON ALL TABLES` would hand the reader every table added later
-- without anyone deciding to, which is how a read-only role stops being a
-- statement about what it can see and becomes a statement about when it was
-- created.
--
-- All SELECT. The reader gains no write anywhere.
--
-- GRANTED TO `fleet_detector`, THE GROUP ROLE, NOT TO `dd_detector_login`.
-- The login role is a member of it and inherits these; the login role also
-- exists only on the deployed database, so granting to it directly made this
-- file unappliable to the test template and the suite silently built a schema
-- two migrations behind. 001 creates the group roles for exactly this reason.

-- Decisions, and whether they happened. Reading decision_log is the point: a
-- brief that cannot see what was decided cannot tell anyone whether it was
-- done. decision_outcomes is a security_invoker view, so the reader needs
-- SELECT on what it reads through -- tasks, runs, issues, issue_occurrences --
-- and issues/issue_occurrences it already had.
GRANT SELECT ON decision_log      TO fleet_detector;
GRANT SELECT ON decision_outcomes TO fleet_detector;

-- What fleet executed, and what it cost in attempts.
GRANT SELECT ON tasks     TO fleet_detector;
GRANT SELECT ON runs      TO fleet_detector;
GRANT SELECT ON run_steps TO fleet_detector;

-- Spend. NOT the AWS bill -- see the note in section 5.
GRANT SELECT ON model_calls TO fleet_detector;
GRANT SELECT ON infra_costs TO fleet_detector;

-- What the proposer said, so "it proposed nothing" is a fact the brief read
-- rather than an assumption it inherited.
GRANT SELECT ON proposals         TO fleet_detector;
GRANT SELECT ON proposal_evidence TO fleet_detector;

-- The writer writes and reads nothing. No SELECT, deliberately: a brief writer
-- that could read briefs could be written to compare itself against yesterday,
-- and that comparison belongs to the reader.
GRANT INSERT ON brief_runs, brief_claims TO fleet_brief_writer;
GRANT USAGE, SELECT ON SEQUENCE brief_runs_id_seq   TO fleet_brief_writer;
GRANT USAGE, SELECT ON SEQUENCE brief_claims_id_seq TO fleet_brief_writer;

-- Reading briefs back is the reader's job, and the detector's, since the brief
-- needs yesterday's values to carry forward as previous_num.
GRANT SELECT ON brief_runs, brief_claims TO fleet_detector;
GRANT SELECT ON brief_runs, brief_claims TO fleet_console, fleet_console_reader;

-- Retention, on the same terms as observations, proposals and decision_log.
GRANT DELETE ON brief_runs, brief_claims TO fleet_admin;

-- ============================================================ 5. NOT GRANTED
--
-- AWS BILLING IS NOT HERE AND CANNOT BE.
--
-- `cost-discipline` in objectives-2026-Q4.yaml carries a hard number -- AWS
-- under 200 GBP/month -- and there is no credential on this host that can read
-- it. `infra_costs` is granted above and is NOT a substitute: it is what fleet
-- recorded, not what Amazon charged. Presenting one as the other would be two
-- systems agreeing on a number neither of them got from the biller, which is
-- precisely the failure RECONCILIATION-MANIFEST §11 exists to name.
--
-- So the brief carries the AWS figure as a STANDING UNCOMPUTED CLAIM, every
-- day, until a credential exists. That is the honest state and it is meant to
-- be visible rather than quietly absent.
--
--   deadly_digital.<schema>.daily_metrics  -- a different database; the brief
--        reads analytics_<t>.orders instead and says its trends are
--        order-derived rather than presenting them as revenue
--   GitHub Actions  -- `gh` is not installed and the repo is private, so the
--        brief cannot say whether the build is green and says so
