-- False-positive rate by detector and observation type -- TWO rates, because
-- they are two questions.
--
--   JUDGEMENT rate   of the things a person ruled on, what fraction were
--                    wrong. Measures whether the DETECTOR IS CORRECT.
--                    Denominator: judgements, from observation_coverage.
--   NOISE rate       of the observations produced, what fraction were false.
--                    Measures what the detector COSTS a human.
--                    Denominator: occurrences carrying an effective verdict.
--
-- v1 was named the first and computed the second, and computed it only if
-- somebody triaged every occurrence. Measured 30 Aug 2026: one fingerprint,
-- 45 hourly observations, every one magnitude 29603, all verdicted -- 40 in a
-- single statement. v1's denominator was 45. There was one judgement.
--
-- That is not a rounding error in a gate. `min_verdicts_per_window` was
-- INVERSELY related to how much had been judged: an hourly detector banked
-- 168 "verdicts" a week from one judgement and armed the finding, while a
-- detector that fired twice was refused as too thin. The gate measured
-- cadence.
--
-- Both rates are returned and both denominators are returned with them. A
-- rate whose denominator is not on screen is a rate somebody will quote.
--
-- Bucketed by when the OBSERVATION was made, not when the verdict was
-- entered -- unchanged from v1, and for the same reason: the question is
-- whether the detector's behaviour is changing, and a burst of catch-up
-- triage would move a verdict-time series without any detector having
-- changed at all.
--
-- %(window)s is one window length; the comparison window is the one before it.
WITH scoped AS (
    SELECT c.detector_key,
           c.observation_type,
           c.observed_at,
           c.is_judgement,
           c.own_verdict,
           c.effective_verdict,
           c.covered,
           c.observed_at >= now() - %(window)s::interval AS is_recent
      FROM observation_coverage c
     WHERE c.run_mode = 'SCHEDULED'
       AND c.observed_at >= now() - (2 * %(window)s::interval)
)
SELECT detector_key,
       observation_type,

       -- The judgement rate's inputs. `recent_verdicts` keeps its name
       -- because the finding reads it, and now means what the name always
       -- implied: judgements, not restatements of one.
       count(*) FILTER (WHERE is_recent AND is_judgement)          AS recent_verdicts,
       count(*) FILTER (WHERE is_recent AND is_judgement
                          AND own_verdict = 'FALSE_POSITIVE')      AS recent_false_positives,
       count(*) FILTER (WHERE NOT is_recent AND is_judgement)      AS prior_verdicts,
       count(*) FILTER (WHERE NOT is_recent AND is_judgement
                          AND own_verdict = 'FALSE_POSITIVE')      AS prior_false_positives,

       count(*) FILTER (WHERE is_recent)                           AS recent_observations,
       count(*) FILTER (WHERE NOT is_recent)                       AS prior_observations,

       -- The noise rate. No threshold and no finding for a fortnight: it is
       -- the more actionable number for dd-trustworthy -- "this detector
       -- costs 45 interruptions per fact" -- but nobody yet knows what a bad
       -- value looks like, and picking one now would be inventing it.
       count(*)                                                    AS occurrences,
       count(*) FILTER (WHERE effective_verdict IS NOT NULL)        AS occurrences_ruled,
       count(*) FILTER (WHERE effective_verdict = 'FALSE_POSITIVE') AS occurrences_false,
       count(*) FILTER (WHERE covered)                              AS occurrences_covered,

       -- The whole-period judgement figures, for the console.
       count(*) FILTER (WHERE is_judgement)                        AS judgements,
       count(*) FILTER (WHERE is_judgement
                          AND own_verdict = 'FALSE_POSITIVE')      AS judgement_false_positives,
       count(*) FILTER (WHERE is_judgement
                          AND own_verdict = 'INCONCLUSIVE')        AS judgement_inconclusive,
       count(*) FILTER (WHERE effective_verdict IS NULL)           AS untriaged
  FROM scoped
 GROUP BY 1, 2
 ORDER BY 1, 2;
