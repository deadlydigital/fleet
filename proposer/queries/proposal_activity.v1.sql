-- The layer's own record: when each objective was last spoken about, and
-- when this layer first said anything at all.
--
-- Read as fleet_detector_reader, which holds SELECT on proposals and
-- deliberately not on decisions. The layer may see what it said. It may not
-- see how it was graded, because a layer that can read its own marks can
-- learn to write for the marker rather than for the truth.
SELECT p.objective_ref,
       count(*)             AS proposals,
       max(p.created_at)    AS last_proposed_at,
       min(p.created_at)    AS first_proposed_at
  FROM proposals p
 WHERE p.objective_ref IS NOT NULL
 GROUP BY 1
 ORDER BY 1;
