-- ============================================================================
-- 036_a_task_points_at_the_decision_that_shipped_it.sql
--                                  —  specs/auto-approval.md §9.17, and NOT §9.3
--
-- NOT APPLIED. Apply as the identity that owns `tasks` and `decision_log`.
--
-- Four tasks read FAILED over work that shipped:
--
--   49  merged by hand as e275adb          decision 25 (task_id IS NULL)
--   51  merged by hand as aaa65bd          NO DECISION AT ALL
--   55  merged by hand as 8128243          decisions 28 and 29
--   58  merged as 2ce6f50 after re-verify  decision 31
--
-- `decision_outcomes` derives delivery from `tasks.status` alone, so decision
-- 31 renders "task NOT_DELIVERED £1.90" over a refund fix that is in
-- production. The morning page reads the same view.
--
-- §9.3 REFUSED A FAILED -> MERGED EDGE AND THAT REFUSAL STANDS. Such an edge
-- hands every future sweep the rule "a failure may become a merge", and no
-- reader of `tasks.status` could be trusted again. This adds no edge, no
-- status and no transition. `tasks.status` is not written by this migration or
-- by anything it enables.
--
-- WHY A POINTER AND NOT A DERIVATION FROM `decision_log`
--
-- "A decision cites this task" and "this decision shipped it" are different,
-- and the pool already shows it: decisions 28 AND 29 both cite task 55. 28 is
-- the merge; 29 records that it was pushed and deployed. Deriving delivery
-- from the existence of a citing decision would count the deploy record as a
-- second delivery, and would let any future decision mentioning a task change
-- that task's outcome silently. Only the task row can say WHICH one.
--
-- THE COMPOSITE KEY IS THE DESIGN
--
-- The foreign key is (shipped_by_decision_id, id) against (id, task_id), so a
-- decision can be named here only if it CITES THIS VERY TASK. Verified on a
-- throwaway database before this was written:
--
--     pointer NULL                               allowed
--     task 58 -> decision 31 (cites 58)          allowed
--     task 55 -> decision 31 (cites 58)          REFUSED
--     task 55 -> decision 25 (task_id IS NULL)   REFUSED
--
-- NULL passes because the FK is MATCH SIMPLE: a NULL in any column of the
-- referencing key satisfies it. NULL is the ordinary state and means no such
-- decision exists, which for a MERGED task is normal -- the machine did it and
-- needed nobody to vouch.
--
-- IT CREATES A CYCLE, DELIBERATELY AND SAFELY. decision_log.task_id already
-- references tasks(id). The two tables now reference each other. That is fine
-- because this side is nullable and is set AFTER both rows exist: insert the
-- task, record the decision, then point. No deferrable constraint is needed
-- and none is used -- a deferred constraint would let a transaction hold a
-- false statement, briefly, which is the thing being legislated against.
--
-- NOTHING READS IT TO DECIDE ANYTHING, and that is the whole difference
-- between this and the refused edge. `claim_task` orders by (priority, id)
-- over QUEUED rows; console/automerge.py selects READY_FOR_REVIEW;
-- console/autodeploy.py reads deployments; every gate in console/rank.py reads
-- `disposition` and `status`. None changes behaviour by one row. A FAILED task
-- stays unclaimable, unmergeable and undeployable by every machine path. If
-- that ever stops being true this has become the refused edge wearing a
-- column, and the guard is that it has no reader outside the view and the page.
--
-- APPLY WITH, as the identity that owns the tables:
--     psql -v ON_ERROR_STOP=1 -d fleet -f 036_a_task_points_at_the_decision_that_shipped_it.sql
--
-- Target: PostgreSQL 15+, same floor as 013.
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- Referenceable target for the composite key. `id` is already the primary key,
-- so this adds no new uniqueness; it exists so the pair can be referenced.
ALTER TABLE decision_log
    ADD CONSTRAINT decision_log_id_task_key UNIQUE (id, task_id);

ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS shipped_by_decision_id integer;

ALTER TABLE tasks
    ADD CONSTRAINT tasks_shipped_by_decision_fk
    FOREIGN KEY (shipped_by_decision_id, id)
    REFERENCES decision_log (id, task_id);

COMMENT ON COLUMN tasks.shipped_by_decision_id IS
  'The decision that records this task''s work reaching its base branch, when '
  'something other than the task''s own state machine put it there. NULL is '
  'the ordinary state: for a MERGED task the machine did it and needed nobody '
  'to vouch. specs/auto-approval.md §9.17. NOT a status and NOT a transition — '
  'nothing reads this to decide anything, and a FAILED task carrying it is '
  'still unclaimable, unmergeable and undeployable.';

-- The identity that records decisions, and only it. fleet_task_runner must NOT
-- hold this: a runner that can mark its own failed task as shipped is the
-- FAILED -> MERGED edge again, wearing a column instead of a transition.
GRANT UPDATE (shipped_by_decision_id) ON tasks TO fleet_console;

-- ---------------------------------------------------------------------------
-- The derivation follows the pointer instead of inferring from status alone.
-- Column list and order are unchanged, so REPLACE is enough.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW decision_outcomes WITH (security_invoker = true) AS
SELECT
    d.id, d.product, d.subject, d.decision, d.reason, d.decided_by,
    d.decided_at, d.origin, d.confidence, d.evidence,
    d.proposal_id, d.issue_id, d.task_id,

    t.status AS task_status,
    -- DELIVERED_BY_HAND IS ITS OWN VALUE, not folded into DELIVERED. "The
    -- machine merged it" and "a person merged it and wrote down why" are
    -- different facts, and the second is the one worth reading: it says the
    -- automated path did not close this and somebody carried it. A fold would
    -- hide exactly the rows this exists for.
    CASE
        WHEN d.task_id IS NULL                              THEN NULL
        WHEN t.status = 'MERGED'                            THEN 'DELIVERED'
        WHEN t.shipped_by_decision_id IS NOT NULL           THEN 'DELIVERED_BY_HAND'
        WHEN t.status IN ('ABANDONED','REJECTED','FAILED')  THEN 'NOT_DELIVERED'
        ELSE 'IN_FLIGHT'
    END AS task_outcome,

    agg.total_cost_gbp,
    agg.runs_total,

    -- STILL GATED ON MERGED, deliberately. It means "the machine got this
    -- green in N attempts", and for a hand-shipped task it did not.
    CASE WHEN t.status = 'MERGED' THEN t.attempts END AS attempts_to_green,

    i.status AS issue_status,
    occ.reopened_since_decision,
    occ.resolved_since_decision,
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

GRANT SELECT ON decision_outcomes TO fleet_detector;

DO $$
DECLARE n int;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='tasks' AND column_name='shipped_by_decision_id') THEN
        RAISE EXCEPTION '036: tasks.shipped_by_decision_id was not created';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname='tasks_shipped_by_decision_fk') THEN
        RAISE EXCEPTION '036: the composite key was not created, so a task '
                        'could point at a decision about another task';
    END IF;

    IF NOT has_column_privilege('fleet_console','tasks','shipped_by_decision_id','UPDATE') THEN
        RAISE EXCEPTION '036: fleet_console cannot write the pointer';
    END IF;

    -- The runner must not. Stated as an assertion because it is the whole
    -- safety argument, not a default anybody should have to remember.
    IF has_column_privilege('fleet_task_runner','tasks','shipped_by_decision_id','UPDATE') THEN
        RAISE EXCEPTION '036: fleet_task_runner can write the pointer, which '
                        'is the FAILED -> MERGED edge wearing a column';
    END IF;

    SELECT count(*) INTO n FROM information_schema.columns
     WHERE table_name='decision_outcomes' AND column_name='task_outcome';
    IF n <> 1 THEN
        RAISE EXCEPTION '036: decision_outcomes lost task_outcome';
    END IF;
END $$;

COMMIT;
