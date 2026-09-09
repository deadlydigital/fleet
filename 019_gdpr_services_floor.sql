-- ============================================================================
-- 019_gdpr_services_floor.sql  —  the rest of the erasure path
--
-- 018 floored api/analytics/services/gdpr.py and named these two as NOT
-- covered: unreachable only because api/services/** left the api contract's
-- writable paths in 017, which is a property of a contract rather than of the
-- database. A future contract could make them writable and nothing would
-- object.
--
-- That distinction -- unreachable by contract versus unreachable by floor --
-- is the whole reason 018 exists, so leaving these on the wrong side of it was
-- an inconsistency rather than a decision.
--
--   gdpr_identity.py      the email-matching rules erasure uses to decide WHO
--                         a subject is. Getting this wrong does not fail; it
--                         erases the wrong person, or misses one.
--   gdpr_replay_scrub.py  scrubs subject data out of stored replay payloads.
--                         The payloads outlive the erasure request, so a bug
--                         here is a subject who was erased everywhere except
--                         the place nobody looks.
--
-- Same class as 018 and floored for the same reason: reverting the commit does
-- not undo the deletion, and does not un-miss the one that should have
-- happened.
-- ============================================================================

INSERT INTO protected_path_floor (repo, glob, rationale) VALUES
 ('deadly-digital-platform', 'api/services/gdpr_identity.py',
  'erasure identity: decides WHO a subject is, so a bug erases the wrong person rather than failing'),
 ('deadly-digital-platform', 'api/services/gdpr_replay_scrub.py',
  'erasure of stored replay payloads, which outlive the request; a bug here leaves a subject erased everywhere except where nobody looks')
ON CONFLICT (repo, glob) DO NOTHING;
