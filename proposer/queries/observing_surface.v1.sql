-- What is actually watching, so that "nothing broke" can be refused with a
-- reason rather than asserted from an empty count.
--
-- The regression question is not hard to write -- `issues.first_seen >
-- decided_at` is one predicate -- and it returns zero for every decision in
-- the log. That zero is worthless and this query is why: two detectors, both
-- on one product, watching analytics order reconciliation and detector
-- liveness. The decisions in the log changed CI configuration, documentation,
-- revenue routes and a frontend page, and nothing here observes any of them.
--
-- A clean bill computed over detectors that watch nothing the decisions
-- touched is worse than no number, so the caller states this list as the
-- reason the claim is UNCOMPUTED.
SELECT r.detector_key,
       r.product,
       count(DISTINCT i.id) FILTER (WHERE i.status = 'OPEN') AS open_issues
  FROM detector_registry r
  LEFT JOIN issues i ON i.detector_key = r.detector_key
 GROUP BY r.detector_key, r.product
 ORDER BY r.detector_key;
