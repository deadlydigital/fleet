-- The shape of the record itself, before anything is said about outcomes.
--
-- Counts and dates only. No rates and no percentages: over a record this size
-- a percentage invites the reading a confidence interval would, and the whole
-- instruction for this block is facts about the record rather than inferences
-- from it.
--
-- `rejected` is selected explicitly even though it is one of the three enum
-- values and could be derived. It is the number every approval sentence has
-- to be read against -- a log with no rejections in it either has had none or
-- is not receiving them, and 010 exists because rejections had been leaving
-- no trace at all. Naming it here means no caller has to remember to ask.
SELECT
    count(*)                                             AS total,
    count(*) FILTER (WHERE decision = 'APPROVED')        AS approved,
    count(*) FILTER (WHERE decision = 'REJECTED')        AS rejected,
    count(*) FILTER (WHERE decision = 'DEFERRED')        AS deferred,
    count(*) FILTER (WHERE origin  = 'BACKFILLED')       AS backfilled,
    count(*) FILTER (WHERE confidence = 'INFERRED')      AS inferred,
    count(DISTINCT product)                              AS products,
    count(DISTINCT decided_at::date)                     AS distinct_days,
    min(decided_at)                                      AS first_decided_at,
    max(decided_at)                                      AS last_decided_at
  FROM decision_log;
