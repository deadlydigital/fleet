-- ============================================================================
-- 007_research_floor.sql  —  a protected floor for the fleet repository
--
-- A research task writes a document into ~/fleet. That inverts the property
-- every code task has relied on.
--
-- For a code task the acceptance check is out of reach BY CONSTRUCTION: the
-- agent works in a worktree of the platform repo and the check lives in
-- ~/fleet, a repository it cannot see. A research task works in a worktree of
-- ~/fleet, so contracts/checks/ is a file it could write to. An agent that can
-- edit the check judging it can pass anything -- the same rule as tests, in a
-- new place.
--
-- protected_path_floor had rows for deadly-digital-platform and none for
-- fleet, so a contract making contracts/checks/ writable was storable. These
-- rows make it refuseable at insert.
--
-- The boundary check already rejects anything outside writable_paths, and a
-- research contract declares exactly one. This is the second lock: it stops a
-- contract being AUTHORED that would open the first.
--
-- Target: PostgreSQL 13+ (RDS 15.17), applied with the listmonk identity.
-- ============================================================================

INSERT INTO protected_path_floor (repo, glob, rationale) VALUES
 ('fleet', 'contracts/**',
  'the acceptance contracts, and the checks inside them. An agent that can '
  'edit what judges it can pass anything -- the tests rule, one repo over'),
 ('fleet', 'tests/**',
  'the suite that proves the runner, the console and the schema behave'),
 ('fleet', 'runner/**',
  'the runner itself: the thing deriving the diff must not be diffable by the '
  'agent it is deriving against'),
 ('fleet', 'console/**',
  'the review surface. A document task has no business changing how branches '
  'are reviewed'),
 ('fleet', 'detectors/**',
  'track 1. Research reads its output; it does not edit its code'),
 ('fleet', 'proposer/**',
  'track 2, same reason'),
 ('fleet', 'systemd/**',
  'unit files, which decide what runs and under what sandbox'),
 ('fleet', 'specs/**',
  'a spec instructs a task. Research is output and belongs in research/; a '
  'task that could edit its own spec could edit the instructions it is judged '
  'against'),
 ('fleet', '.env',
  'the credentials. Gitignored, so absent from a worktree, and named here so '
  'that stays true if it ever stops being ignored');

-- The migrations, named one by one rather than by glob. `0*.sql` would also
-- match a future 010_*.sql, which sounds like a feature until the file that
-- needs protecting is the one nobody remembered to name. Adding a migration
-- means adding a row, and a review that notices its absence.
INSERT INTO protected_path_floor (repo, glob, rationale)
SELECT 'fleet', g, 'a migration. A schema change is never research output'
  FROM unnest(ARRAY[
      '001_v1_core.sql', '001_v1_core_assertions.sql', '001_v1_core_fixtures.sql',
      '002_proposals.sql', '002_proposals_assertions.sql',
      '003_tasks.sql', '003_tasks_assertions.sql',
      '004_console_reader.sql', '004_console_reader_assertions.sql',
      '005_console_decisions.sql', '005_console_decisions_assertions.sql',
      '006_verdict_coverage.sql', '006_verdict_coverage_assertions.sql',
      '007_research_floor.sql', '007_research_floor_assertions.sql']) AS g;
