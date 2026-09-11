-- decision_reach v2. v1 selected task_status and nothing else about
-- delivery, so its merged/failed split disagreed with
-- decision_outcomes for any task shipped by hand. v1 is kept because
-- readings taken under it are attributed to it.
-- Every decision, and the work that descends from it -- BY BOTH ROUTES.
--
-- `decision_outcomes` joins tasks on `decision_log.task_id` and nothing else,
-- so it sees only the decisions that were recorded with a task already in
-- hand. 013 records the other direction: the approval surface writes
-- `candidates.approval_decision_id` and then fills in `spec_task_id` and
-- `work_task_id` as the tasks are created. On the live record that second
-- route is the difference between one decision reading as an unknown and
-- reading as six tasks with three failures in them.
--
-- One row per (decision, linked task); a decision with no linked work appears
-- once with a NULL task. That shape is deliberate -- collapsing to one row per
-- decision would need an aggregate here, and the caller wants each task's repo
-- and commit separately to ask git about it.
--
-- `link` distinguishes the two routes rather than hiding them. They are not
-- the same claim: DIRECT is a task someone named when recording the decision,
-- CANDIDATE is a task the approval surface created from it.
WITH linked AS (
    SELECT d.id AS decision_id, d.task_id, 'DIRECT'::text AS link
      FROM decision_log d
     WHERE d.task_id IS NOT NULL
    UNION
    SELECT c.approval_decision_id, t.id, 'CANDIDATE'
      FROM candidates c
      CROSS JOIN LATERAL (VALUES (c.spec_task_id), (c.work_task_id)) AS v(id)
      JOIN tasks t ON t.id = v.id
     WHERE c.approval_decision_id IS NOT NULL
),
-- WHAT LANDED, as recorded by the console at merge time. `base_sha_after` is
-- verified against the remote before any verdict is written, and app.py puts
-- it on the HUMAN_DECISION step as `merge.merge_commit`. It identifies the
-- merge itself, which the branch tip cannot: a tip being an ancestor of main
-- is consistent with the merge but does not say which commit performed it.
--
-- `already_merged` MUST be read with it. It is `base_sha_after`, the base
-- branch AFTER the operation -- and when the branch was already in the base
-- there was no operation, so that sha is simply where the base stood and
-- belongs to whatever landed last. On this record task 1 reads
-- `already_merged: true` with a `merge_commit` of 63130ad7, which is
-- "Merge branch 'docs/backend-gate-findings'" and has nothing to do with it.
landed AS (
    SELECT DISTINCT ON (r.task_id)
           r.task_id,
           s.payload -> 'merge' ->> 'merge_commit'          AS merge_commit,
           (s.payload -> 'merge' ->> 'already_merged')::boolean AS already_merged,
           (s.payload -> 'merge' ->> 'push_verified')::boolean  AS push_verified
      FROM run_steps s
      JOIN runs r ON r.id = s.run_id
     WHERE s.step_type = 'HUMAN_DECISION' AND r.task_id IS NOT NULL
       AND s.payload -> 'merge' IS NOT NULL
     ORDER BY r.task_id, s.created_at DESC
),
-- The branch tip as it stood when the work was last proposed. A task that
-- took four attempts has four of these; the newest is the one that was
-- reviewed, and the earlier ones describe attempts that were replaced.
tip AS (
    SELECT DISTINCT ON (r.task_id)
           r.task_id,
           s.payload ->> 'patch_commit_sha' AS patch_commit_sha,
           s.payload ->> 'base_commit_sha'  AS base_commit_sha,
           r.work_type
      FROM run_steps s
      JOIN runs r ON r.id = s.run_id
     WHERE s.step_type = 'PATCH_PROPOSED' AND r.task_id IS NOT NULL
     ORDER BY r.task_id, s.created_at DESC
)
SELECT
    d.id            AS decision_id,
    d.product,
    d.decision,
    d.decided_at,
    d.origin,
    d.subject,
    l.link,
    t.id            AS task_id,
    t.status        AS task_status,
    -- v2, 11 Sep 2026. THE STATUS IS NOT THE DELIVERY, and reading it as one
    -- counted four tasks as not delivered over work that is in production.
    -- specs/auto-approval.md §9.17: `tasks.status` stays FAILED and a pointer
    -- says whether the work shipped anyway. Selected here so precedent counts
    -- what decision_outcomes counts; see precedent._delivered.
    t.shipped_by_decision_id,
    t.repo          AS task_repo,
    t.base_branch,
    t.objective_ref,
    tip.work_type,
    tip.patch_commit_sha,
    landed.merge_commit,
    landed.already_merged,
    landed.push_verified,
    agg.runs_total,
    agg.total_cost_gbp
  FROM decision_log d
  LEFT JOIN linked l ON l.decision_id = d.id
  LEFT JOIN tasks  t ON t.id = l.task_id
  LEFT JOIN tip      ON tip.task_id = t.id
  LEFT JOIN landed   ON landed.task_id = t.id
  LEFT JOIN LATERAL (
      SELECT count(*)::int AS runs_total,
             coalesce(sum(r.committed_gbp), 0)::numeric(12,4) AS total_cost_gbp
        FROM runs r WHERE r.task_id = t.id
  ) agg ON t.id IS NOT NULL
 ORDER BY d.id, t.id;
