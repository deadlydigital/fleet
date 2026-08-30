-- ============================================================================
-- 006_verdict_coverage.sql  —  one judgement, restated, is one judgement
--
-- A recurring issue produces one identical observation per cadence. Measured
-- on 30 Aug 2026: MISSING_ANALYTICS_ORDER on tenant 2 produced 45 observations
-- over 44 hours, every one carrying magnitude 29603, all one fingerprint, all
-- verdicted VALID -- 40 of them in a single statement. The verdict table read
-- that as 45 judgements. There were three moments a person formed a view, and
-- one fact.
--
-- WHAT THIS BREAKS THAT WAS ALREADY BROKEN
--
-- `min_verdicts_per_window: 5` exists to stop a rate being computed on too
-- little. Under per-observation counting it is INVERSELY related to how much
-- was judged: an hourly detector banks 168 "verdicts" a week from one
-- judgement and arms the finding, while a detector that fired twice is
-- refused as too thin. The gate measures cadence.
--
-- TWO RATES, WHICH ARE NOT THE SAME QUESTION
--
--   judgement rate  of the things ruled on, what fraction were wrong.
--                   Detector CORRECTNESS. Denominator: judgements.
--   noise rate      of the observations produced, what fraction were false.
--                   What the detector COSTS a human. Denominator: occurrences.
--
-- The existing query is named the first and computes the second, and computes
-- it only if somebody triages every occurrence -- which is the labour this
-- removes. Both are real; both are returned; neither is unqualified.
--
-- NOTHING IS MIGRATED. The 45 verdicts already recorded keep their meaning
-- and become one judgement plus 44 covered occurrences. Coverage is DERIVED,
-- not stored, for the same reason the runner derives its diff and
-- issue_occurrences derives from a trigger: a stored answer is one that can
-- disagree with the facts it was computed from.
--
-- Target: PostgreSQL 13+ (RDS 15.17), applied with the listmonk identity.
-- ============================================================================

-- ============================================================ 1. THE POLICY
--
-- When a magnitude has moved enough that the earlier judgement no longer
-- covers it. Data, per observation type, exactly as routing_policy is: what
-- counts as a material change is a judgement that gets retuned, and retuning
-- it must not be a deploy.
--
-- Severity band changes are NOT configured here -- they come from
-- routing_policy, which already says when a magnitude matters enough to
-- change how the issue is treated. This table is the finer question: a
-- magnitude that stayed in its band but moved a long way inside it.
-- 29603 -> 150 is still CRITICAL and is still something a person would want
-- to look at.
CREATE TABLE verdict_coverage_policy (
    observation_type   text NOT NULL,
    policy_version     int  NOT NULL DEFAULT 1,
    max_relative_change numeric NOT NULL
                       CHECK (max_relative_change >= 0),
    rationale          text NOT NULL,
    PRIMARY KEY (observation_type, policy_version)
);

COMMENT ON TABLE verdict_coverage_policy IS
  'How far a magnitude may drift before an earlier verdict stops covering it.';

INSERT INTO verdict_coverage_policy
        (observation_type, max_relative_change, rationale) VALUES
 ('*', 0.25,
  'Default. A quarter either way is wide enough that an hourly detector '
  'reporting a stable backlog is not re-queued every hour, and narrow enough '
  'that a gap doubling is looked at again.'),
 ('MISSING_ANALYTICS_ORDER', 0.10,
  'A missing-order count that moves 10% is a sync behaving differently, and '
  'the number is large enough that 10% is thousands of orders.'),
 ('DETECTOR_WINDOW_ABANDONED', 0,
  'Never covered. Each abandoned window is its own failure and inheriting a '
  'verdict across them would hide the second one entirely.');

-- ============================================================ 2. THE VIEW
--
-- One row per observation: judged, covered by an earlier judgement, or
-- neither -- and when covered, WHICH verdict covers it and why coverage held.
--
-- The "why" columns are not decoration. "Why is this not in my queue" is
-- otherwise the new version of "why is this issue still open": a question
-- answerable only by a query nobody runs. The console reads these columns.
--
-- COVERAGE KEY: (fingerprint, detector_version, issue_key_version).
-- Both versions are in it. A detector that changed version is a different
-- detector, and inheriting a verdict across that boundary would conceal
-- exactly the change the false-positive rate exists to detect.
--
-- WHY THIS WALKS THE TIMELINE INSTEAD OF JOINING TO THE NEAREST VERDICT
--
-- Two reasons, and the first is a correctness hole rather than a nicety.
--
-- 1. Anchoring on the NEAREST earlier verdict lets a magnitude drift without
--    limit. Forty-five hourly observations each 1% above the one before are
--    each within any sane allowance of their neighbour, and the last is 57%
--    above the first. Every step is covered and the total move is never
--    examined. Anchoring on the judgement that STARTED the run closes that:
--    the comparison is always against the thing a person actually looked at.
--
-- 2. A redundant verdict is not a judgement. All 45 of the observations this
--    was built for carry a verdict, 40 entered in one statement. If having a
--    verdict made an observation a judgement, nothing would collapse and the
--    denominator would be 45 again. So an own verdict that AGREES with the
--    covering one is a restatement and stays covered; one that DISAGREES is a
--    person changing their mind, which is a real judgement, breaks coverage,
--    and starts a new run.
CREATE VIEW observation_coverage AS
WITH RECURSIVE policy AS (
    SELECT observation_type, max_relative_change
      FROM verdict_coverage_policy WHERE policy_version = 1
),
seq AS (
    SELECT o.id, o.fingerprint, o.detector_key, o.detector_version,
           o.issue_key_version, o.observation_type, o.observed_at,
           o.magnitude, o.run_mode,
           v.verdict AS own_verdict, v.id AS own_verdict_id,
           v.created_at AS own_verdict_at,
           coalesce(p.max_relative_change, pd.max_relative_change, 0)
               AS allowed_change,
           route_severity(o.observation_type, o.magnitude) AS band,
           row_number() OVER (
               PARTITION BY o.fingerprint, o.detector_version, o.issue_key_version
               ORDER BY o.observed_at, o.id) AS rn
      FROM observations o
      LEFT JOIN observation_verdicts own_v ON own_v.observation_id = o.id
      LEFT JOIN observation_verdicts v ON v.id = own_v.id
      LEFT JOIN policy p  ON p.observation_type  = o.observation_type
      LEFT JOIN policy pd ON pd.observation_type = '*'
),
walk AS (
    -- The first observation of each coverage key. It can never be covered:
    -- there is nothing earlier to cover it.
    SELECT s.*,
           CASE WHEN s.own_verdict IS NOT NULL THEN s.id END      AS anchor_id,
           CASE WHEN s.own_verdict IS NOT NULL THEN s.magnitude END AS anchor_magnitude,
           CASE WHEN s.own_verdict IS NOT NULL THEN s.band END    AS anchor_band,
           CASE WHEN s.own_verdict IS NOT NULL THEN s.own_verdict END AS anchor_verdict,
           CASE WHEN s.own_verdict IS NOT NULL THEN s.own_verdict_id END AS anchor_verdict_id,
           CASE WHEN s.own_verdict IS NOT NULL THEN s.observed_at END AS anchor_observed_at,
           false AS covered,
           NULL::numeric AS relative_change,
           false AS reopened_between
      FROM seq s WHERE s.rn = 1

    UNION ALL

    SELECT n.*,
           -- The anchor is carried forward even when coverage BREAKS, and is
           -- replaced only by a new judgement. Clearing it on a break lost
           -- the one thing the row needed to explain itself: an observation
           -- whose band had moved reported "nothing earlier has been judged"
           -- instead of naming the move. The anchor is what coverage is
           -- measured against AND what the reason refers to; `covered` alone
           -- says whether it currently holds.
           CASE WHEN n.own_verdict IS NOT NULL AND NOT c.covered_now
                THEN n.id ELSE w.anchor_id END,
           CASE WHEN n.own_verdict IS NOT NULL AND NOT c.covered_now
                THEN n.magnitude ELSE w.anchor_magnitude END,
           CASE WHEN n.own_verdict IS NOT NULL AND NOT c.covered_now
                THEN n.band ELSE w.anchor_band END,
           CASE WHEN n.own_verdict IS NOT NULL AND NOT c.covered_now
                THEN n.own_verdict ELSE w.anchor_verdict END,
           CASE WHEN n.own_verdict IS NOT NULL AND NOT c.covered_now
                THEN n.own_verdict_id ELSE w.anchor_verdict_id END,
           CASE WHEN n.own_verdict IS NOT NULL AND NOT c.covered_now
                THEN n.observed_at ELSE w.anchor_observed_at END,
           c.covered_now,
           c.rel,
           c.reopened
      FROM walk w
      JOIN seq n
        ON  n.fingerprint       = w.fingerprint
        AND n.detector_version  = w.detector_version
        AND n.issue_key_version = w.issue_key_version
        AND n.rn = w.rn + 1
      CROSS JOIN LATERAL (
          SELECT
            -- A REOPEN, not the issue's first appearance. io.opened_at
            -- > i.first_seen is what makes it one: the initial occurrence
            -- opens at first_seen, and counting that as a reopen would break
            -- coverage between the first two observations of every issue --
            -- which it did, until the first run of this view against real
            -- data reported two judgements where there was one.
            EXISTS (SELECT 1 FROM issues i
                      JOIN issue_occurrences io ON io.issue_id = i.id
                     WHERE i.fingerprint = n.fingerprint
                       AND io.opened_at > i.first_seen
                       AND w.anchor_observed_at IS NOT NULL
                       AND io.opened_at >  w.anchor_observed_at
                       AND io.opened_at <= n.observed_at) AS reopened,
            CASE WHEN w.anchor_magnitude IS NULL OR w.anchor_magnitude = 0
                 THEN NULL
                 ELSE abs(n.magnitude - w.anchor_magnitude) / abs(w.anchor_magnitude)
            END AS rel
      ) c0
      CROSS JOIN LATERAL (
          SELECT c0.reopened, c0.rel,
                 (w.anchor_id IS NOT NULL
                  AND NOT c0.reopened
                  AND n.band IS NOT DISTINCT FROM w.anchor_band
                  AND (CASE WHEN c0.rel IS NULL
                            THEN n.magnitude IS NOT DISTINCT FROM w.anchor_magnitude
                            ELSE c0.rel <= n.allowed_change END)
                  -- a disagreeing verdict is a person changing their mind
                  AND (n.own_verdict IS NULL
                       OR n.own_verdict = w.anchor_verdict)) AS covered_now
      ) c
)
SELECT w.id                    AS observation_id,
       w.fingerprint, w.detector_key, w.detector_version, w.issue_key_version,
       w.observation_type, w.observed_at, w.magnitude, w.run_mode, w.band,
       w.own_verdict, w.own_verdict_id, w.own_verdict_at,
       w.covered,
       -- The judgement denominator. An own verdict that merely restates the
       -- covering one is not one of these.
       (w.own_verdict IS NOT NULL AND NOT w.covered) AS is_judgement,
       (w.own_verdict IS NOT NULL AND w.covered)     AS redundant_verdict,
       CASE WHEN w.covered THEN w.anchor_id END          AS anchor_observation_id,
       CASE WHEN w.covered THEN w.anchor_verdict_id END  AS covering_verdict_id,
       CASE WHEN w.covered THEN w.anchor_verdict END     AS covering_verdict,
       CASE WHEN w.covered THEN w.anchor_observed_at END AS anchor_observed_at,
       CASE WHEN w.covered THEN w.anchor_magnitude END   AS anchor_magnitude,
       CASE WHEN w.covered THEN w.anchor_band END        AS anchor_band,
       w.relative_change, w.allowed_change, w.reopened_between,

       -- The effective verdict: its own, or the one covering it. This is what
       -- the rates count, and what "triaged" means.
       coalesce(w.own_verdict, CASE WHEN w.covered THEN w.anchor_verdict END)
                                                         AS effective_verdict,

       CASE WHEN w.covered AND w.own_verdict IS NOT NULL
              THEN format('restates the judgement of %s -- same fingerprint, '
                          '%s band, magnitude within %s%% of the judged %s',
                          to_char(w.anchor_observed_at, 'DD Mon HH24:MI'),
                          w.band, round(w.allowed_change * 100, 1),
                          w.anchor_magnitude)
            WHEN w.covered
              THEN format('covered by the judgement of %s -- same fingerprint, '
                          '%s band, magnitude within %s%% of the judged %s',
                          to_char(w.anchor_observed_at, 'DD Mon HH24:MI'),
                          w.band, round(w.allowed_change * 100, 1),
                          w.anchor_magnitude)
            WHEN w.own_verdict IS NOT NULL AND w.rn = 1
              THEN 'the first observation of this fingerprint, judged directly'
            WHEN w.own_verdict IS NOT NULL
              THEN 'judged directly, and not a restatement of an earlier one'
            WHEN w.reopened_between
              THEN 'the issue closed and reopened after the last judgement, so '
                   'this is a recurrence rather than a restatement'
            WHEN w.anchor_id IS NULL
              THEN 'nothing earlier on this fingerprint has been judged at this '
                   'detector and issue-key version'
            WHEN w.band IS DISTINCT FROM w.anchor_band
              THEN format('severity moved from %s to %s since the judgement of %s',
                          w.anchor_band, w.band,
                          to_char(w.anchor_observed_at, 'DD Mon HH24:MI'))
            WHEN w.relative_change > w.allowed_change
              THEN format('magnitude moved %s%% from the judged %s, past the '
                          '%s%% this type allows',
                          round(w.relative_change * 100, 1), w.anchor_magnitude,
                          round(w.allowed_change * 100, 1))
            ELSE 'not covered'
       END                                              AS coverage_reason
  FROM walk w;

COMMENT ON VIEW observation_coverage IS
  'Per observation: judged, covered by an earlier judgement, or neither -- '
  'with the covering verdict and the reason coverage held or did not. '
  'is_judgement is the false-positive rate denominator; a verdict that merely '
  'restates the covering one is redundant_verdict and is not counted twice.';

-- ============================================================ 3. GRANTS

GRANT SELECT ON verdict_coverage_policy, observation_coverage
      TO fleet_detector_reader, fleet_console_reader, fleet_console;
GRANT SELECT ON verdict_coverage_policy, observation_coverage TO fleet_detector;
