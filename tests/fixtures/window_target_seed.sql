-- A window target for the test template.
--
-- 049's admission trigger refuses every claim when no target is in effect --
-- "a ceiling that cannot read its limit refuses" -- which is correct in
-- production and would otherwise turn every claiming test in the suite red
-- for a reason that has nothing to do with the test.
--
-- Deliberately large. The suite is not the place to exercise the ceiling by
-- accident: tests that mean to hit it lower the target or raise the task's
-- max_output_tokens themselves, and every other test should never notice the
-- trigger exists.
INSERT INTO model_window_target
    (output_tokens_per_week, set_by, effective_from, rationale)
VALUES (1000000000, 'tests/fixtures/window_target_seed.sql',
        TIMESTAMPTZ '2020-01-01 00:00:00+00',
        'the suite needs a target in effect; large enough that only a test '
        'that sets out to cross it ever does');
