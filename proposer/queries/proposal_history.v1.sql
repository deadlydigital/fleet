-- Every finding this layer has already raised, and when it last raised it.
-- Suppression reads from here: a daily cycle that cannot remember yesterday
-- spends its five slots re-reporting the same five things.
SELECT p.finding_key,
       max(p.created_at) AS last_proposed_at,
       count(*)          AS times_proposed,
       min(p.created_at) AS first_proposed_at
  FROM proposals p
 GROUP BY 1;
