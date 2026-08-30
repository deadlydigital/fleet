-- Observations nobody has ruled on -- where "ruled on" now includes covered
-- by an earlier judgement of the same fingerprint.
--
-- v1 counted an observation as untriaged unless it carried a verdict of its
-- own, so an hourly recurring issue refilled the queue every hour with the
-- thing already ruled on. That is the labour this removes: the queue should
-- hold things to THINK about, not rows to clear.
--
-- Counted per detector and observation type, so the answer says where the gap
-- is rather than only how big it is. `fingerprints_untriaged` is the number
-- that matters -- distinct facts awaiting a judgement -- and `untriaged` is
-- kept beside it because the two diverging is exactly the condition that
-- prompted this query's second version.
SELECT c.detector_key,
       c.observation_type,
       count(*)                                     AS untriaged,
       count(DISTINCT c.fingerprint)                AS fingerprints_untriaged,
       min(c.observed_at)                           AS oldest_observed_at,
       max(c.observed_at)                           AS newest_observed_at,
       extract(epoch FROM now() - min(c.observed_at))::bigint AS oldest_age_seconds
  FROM observation_coverage c
 WHERE c.effective_verdict IS NULL
   AND c.run_mode = 'SCHEDULED'
 GROUP BY 1, 2
 ORDER BY 1, 2;
