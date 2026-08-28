-- When a person last recorded a verdict, and how much is waiting.
-- The false-positive rate is only as fresh as this.
SELECT max(v.created_at)                        AS last_verdict_at,
       count(*)                                 AS total_verdicts,
       count(DISTINCT v.detector_key)           AS detectors_verdicted
  FROM observation_verdicts v;
