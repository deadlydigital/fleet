-- When this layer first said anything. A finding of the form "nothing has
-- happened here in N days" is unknowable until the layer itself is older
-- than N days, and firing it before then reports the fact that it has just
-- been switched on.
SELECT min(created_at) AS first_proposal_at,
       count(*)        AS total_proposals,
       count(DISTINCT cycle_id) AS cycles
  FROM proposals;
