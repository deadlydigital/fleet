-- False-positive rate by detector and observation type.
--
-- Bucketed by when the OBSERVATION was made, not by when the verdict was
-- entered. The question is whether the detector's behaviour is changing, and
-- a burst of catch-up triage would move a verdict-time series without any
-- detector having changed at all.
--
-- The cost of that choice is that the recent window is always the less
-- triaged one, so verdict_coverage is returned alongside every rate and a
-- window with too few verdicts must be treated as unknown, not as zero.
--
-- %(window)s is one window length; the comparison window is the one before it.
WITH verdicted AS (
    SELECT o.detector_key,
           o.observation_type,
           o.observed_at,
           v.verdict
      FROM observations o
      LEFT JOIN observation_verdicts v ON v.observation_id = o.id
     WHERE o.run_mode = 'SCHEDULED'
       AND o.observed_at >= now() - (2 * %(window)s::interval)
)
SELECT detector_key,
       observation_type,

       count(*) FILTER (WHERE observed_at >= now() - %(window)s::interval)
           AS recent_observations,
       count(*) FILTER (WHERE observed_at >= now() - %(window)s::interval
                          AND verdict IS NOT NULL)
           AS recent_verdicts,
       count(*) FILTER (WHERE observed_at >= now() - %(window)s::interval
                          AND verdict = 'FALSE_POSITIVE')
           AS recent_false_positives,

       count(*) FILTER (WHERE observed_at <  now() - %(window)s::interval)
           AS prior_observations,
       count(*) FILTER (WHERE observed_at <  now() - %(window)s::interval
                          AND verdict IS NOT NULL)
           AS prior_verdicts,
       count(*) FILTER (WHERE observed_at <  now() - %(window)s::interval
                          AND verdict = 'FALSE_POSITIVE')
           AS prior_false_positives,

       count(*)                                     AS observations,
       count(*) FILTER (WHERE verdict IS NOT NULL)  AS verdicts,
       count(*) FILTER (WHERE verdict = 'FALSE_POSITIVE') AS false_positives,
       count(*) FILTER (WHERE verdict = 'INCONCLUSIVE')   AS inconclusive
  FROM verdicted
 GROUP BY 1, 2
 ORDER BY 1, 2;
