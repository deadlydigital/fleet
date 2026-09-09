-- ============================================================================
-- 018_gdpr_floor.sql  —  erasure is not work an unattended agent does
--
-- 017 floored the email surface. This floors the one path left inside the
-- analytics tree that 017 deliberately did not take, and it is a decision
-- rather than an omission being tidied up: 017's scope was email, and widening
-- it silently would have been the same mistake in the other direction as
-- leaving api/app.py writable.
--
-- WHY gdpr.py AND NOT THE REST OF api/analytics/services
--
-- Every other module there computes a number. This one DELETES A PERSON, on
-- request, under a legal obligation with a statutory deadline. The failure
-- modes are not symmetrical with the rest of the tree:
--
--   a report that computes the wrong figure is wrong until someone notices
--   an erasure that deletes too much cannot be undone by reverting the commit
--   an erasure that deletes too little is a breach that looks like success
--
-- The whole argument for taking the brakes off is that everything is
-- reversible through git. Erasure is the one thing in this repository that is
-- not: the commit reverts, the rows do not come back, and a subject who asked
-- to be forgotten and was not has a complaint git cannot answer.
--
-- So this is the class the floor exists for, and it is floored for the same
-- reason api/alembic/** is -- 'a schema change is a separate decision from a
-- feature'. An erasure change is a separate decision from a report.
--
-- WHAT IT DOES NOT COVER, STATED SO NOBODY READS MORE INTO IT
--
--   api/services/gdpr_identity.py     the email-matching rules erasure uses
--   api/services/gdpr_replay_scrub.py scrubbing replay payloads
--
-- Both are already unreachable: api/services/** left the api contract's
-- writable paths in 017 because it holds email_sender.py and
-- template_renderer.py. They are NOT on the floor, so a contract could make
-- them writable again without the database objecting. They are named here so
-- that the next person widening api/services knows what is in it.
-- ============================================================================

INSERT INTO protected_path_floor (repo, glob, rationale) VALUES
 ('deadly-digital-platform', 'api/analytics/services/gdpr.py',
  'erasure: the one change in this repository that reverting the commit does not undo, so it is a separate decision from a feature')
ON CONFLICT (repo, glob) DO NOTHING;
