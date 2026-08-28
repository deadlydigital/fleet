-- Observations no one has ruled on. The input the false-positive rate is
-- starved of, counted per detector and observation type so the answer says
-- where the gap is rather than only how big it is.
SELECT o.detector_key,
       o.observation_type,
       count(*)                                     AS untriaged,
       min(o.observed_at)                           AS oldest_observed_at,
       max(o.observed_at)                           AS newest_observed_at,
       extract(epoch FROM now() - min(o.observed_at))::bigint AS oldest_age_seconds
  FROM observations o
  LEFT JOIN observation_verdicts v ON v.observation_id = o.id
 WHERE v.id IS NULL
   AND o.run_mode = 'SCHEDULED'
 GROUP BY 1, 2
 ORDER BY 1, 2;
