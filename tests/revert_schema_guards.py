"""Revert each schema guard in 010 in turn, confirm its test fails, restore.

    .venv/bin/python tests/revert_schema_guards.py

The sibling of `revert_guards.py`, and it exists for the same reason: a test
that passes whether or not the guard is present is not testing the guard, and
is indistinguishable from one that is until somebody checks.

WHY IT IS A SEPARATE SCRIPT
    `revert_guards.py` edits Python and re-runs one test. These guards are SQL
    -- a NOT NULL, two check constraints, a trigger and four expressions inside
    a view -- so a reversion has to edit `010_decision_log.sql` and get the
    template database rebuilt from it. `tests/conftest.py` builds
    `fleet_test_tmpl` once per session, so each case runs pytest in a fresh
    process. That makes this slower than its sibling and is the whole
    difference between them.

WHAT EACH CASE DOES AND DOES NOT ESTABLISH
    A reversion proves that a test is load-bearing for the line it removes. It
    does not prove the property is completely covered. Two are called out in
    the table below where the distinction matters, rather than left for a
    reader to assume.

    `security_invoker` on the view is deliberately NOT here. Removing it does
    not break any behavioural test -- both console roles hold the base grants
    either way, so the page still renders -- which is exactly why it is checked
    in `010_decision_log_assertions.sql` (J5) against the deployed database
    instead. A reversion script that pretended to cover it would be the failure
    this script exists to find.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/ubuntu/fleet")
MIGRATION = "010_decision_log.sql"
TESTS = "tests/test_decision_log.py"

CASES = [
    # ---- the reason ------------------------------------------------------
    ("reason is NOT NULL",
     MIGRATION,
     "    reason      text NOT NULL CHECK (length(btrim(reason)) > 0),",
     "    reason      text          CHECK (length(btrim(reason)) > 0),",
     f"{TESTS}::TestAReasonIsMandatory::test_a_rejection_with_no_reason_is_refused"),

    ("a blank reason is not a reason",
     MIGRATION,
     "    reason      text NOT NULL CHECK (length(btrim(reason)) > 0),",
     "    reason      text NOT NULL,",
     f"{TESTS}::TestAReasonIsMandatory::test_a_blank_reason_is_refused"),

    ("the backfill sentinel is reserved to the backfill",
     MIGRATION,
     """    CONSTRAINT decision_log_sentinels_are_backfill_only_ck
        CHECK (origin = 'BACKFILLED'
               OR (reason <> 'UNRECORDED' AND decided_by <> 'UNRECORDED'))""",
     """    CONSTRAINT decision_log_sentinels_are_backfill_only_ck
        CHECK (true)""",
     f"{TESTS}::TestAReasonIsMandatory::test_a_live_decision_cannot_use_the_backfill_sentinel"),

    # ---- provenance ------------------------------------------------------
    ("a backfilled row cannot claim stated confidence",
     MIGRATION,
     """    CONSTRAINT decision_log_backfill_is_inferred_ck
        CHECK (origin = 'RECORDED' OR confidence = 'INFERRED'),""",
     """    CONSTRAINT decision_log_backfill_is_inferred_ck
        CHECK (true),""",
     f"{TESTS}::TestBackfilledRowsAreDistinguishable::test_a_backfilled_row_cannot_claim_stated_confidence"),

    # ---- who may write ---------------------------------------------------
    ("only fleet_console may record a decision",
     MIGRATION,
     "    IF NOT pg_has_role(current_user, 'fleet_console', 'MEMBER') THEN\n"
     "        RAISE EXCEPTION '% may not record decisions', current_user;\n"
     "    END IF;",
     "    IF false THEN\n"
     "        RAISE EXCEPTION '% may not record decisions', current_user;\n"
     "    END IF;",
     f"{TESTS}::TestOnlyTheConsoleDecides::test_the_trigger_refuses_the_runner_even_when_it_holds_the_grant"),
    # Pointed at the test that GRANTS the runner INSERT first. Aimed at
    # `test_the_runner_cannot_record_a_decision` this case reported NOT
    # PROVEN, correctly: with the trigger disabled the missing grant still
    # refused, so the test passed and established nothing about the trigger.

    # ---- derived outcomes ------------------------------------------------
    #
    # The ordering IS the guard. Reversed, an issue that resolved, reopened and
    # resolved again reports RESOLVED_HELD -- true of its status right now and
    # false about the decision.
    ("a reopen outranks the current status",
     MIGRATION,
     """        WHEN occ.reopened_since_decision           THEN 'REOPENED'
        WHEN i.status = 'RESOLVED'
         AND occ.resolved_since_decision           THEN 'RESOLVED_HELD'""",
     """        WHEN i.status = 'RESOLVED'
         AND occ.resolved_since_decision           THEN 'RESOLVED_HELD'
        WHEN occ.reopened_since_decision           THEN 'REOPENED'""",
     f"{TESTS}::TestIssueOutcomeIsDerived::test_an_issue_that_reopens_does_not_read_as_a_good_outcome"),

    ("attempts to green is null until there is a green",
     MIGRATION,
     "    CASE WHEN t.status = 'MERGED' THEN t.attempts END AS attempts_to_green,",
     "    t.attempts AS attempts_to_green,",
     f"{TESTS}::TestTaskOutcomeIsDerived::test_an_abandoned_task_reads_not_delivered_and_has_no_green"),

    ("cost is every run, not the latest",
     MIGRATION,
     "    SELECT count(*)::int AS runs_total,\n"
     "           coalesce(sum(r.committed_gbp), 0)::numeric(12,4) AS total_cost_gbp\n"
     "      FROM runs r WHERE r.task_id = d.task_id",
     "    SELECT count(*)::int AS runs_total,\n"
     "           coalesce(max(r.committed_gbp), 0)::numeric(12,4) AS total_cost_gbp\n"
     "      FROM runs r WHERE r.task_id = d.task_id",
     f"{TESTS}::TestTaskOutcomeIsDerived::test_cost_is_every_run_not_the_latest"),

    # Proves the capture is load-bearing. It does NOT prove the snapshot holds
    # still while the issue moves -- that is established by the test's own
    # construction, which mutates the issue after the decision and asserts the
    # earlier value. No single-line reversion can break only that half.
    ("the cited issue's state is captured onto the decision",
     MIGRATION,
     "    IF NEW.evidence = '[]'::jsonb AND NEW.issue_id IS NOT NULL THEN",
     "    IF false THEN",
     f"{TESTS}::TestSubjectAndEvidenceAreCaptured::test_the_issue_evidence_is_a_snapshot_not_a_live_read"),

    ("a decision with nothing cited must name its subject",
     MIGRATION,
     "        RAISE EXCEPTION 'a decision needs a subject, and none was given or '\n"
     "                        'could be taken from a cited proposal, issue or task'\n"
     "            USING ERRCODE = 'not_null_violation';",
     "        NEW.subject := 'untitled';",
     f"{TESTS}::TestSubjectAndEvidenceAreCaptured::test_a_decision_citing_nothing_must_name_its_subject"),
]


def run(test: str) -> bool:
    r = subprocess.run([".venv/bin/python", "-m", "pytest", test, "-q",
                        "--no-header", "-x", "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0


failures = []
for label, rel, needle, replacement, test in CASES:
    path = ROOT / rel
    original = path.read_text()
    if needle not in original:
        failures.append(f"{label}: could not find the guard to revert in {rel}")
        print(f"  NOT FOUND   {label}")
        continue
    try:
        path.write_text(original.replace(needle, replacement, 1))
        still_passes = run(test)
    finally:
        path.write_text(original)
    assert path.read_text() == original, f"failed to restore {rel}"

    if still_passes:
        failures.append(f"{label}: TEST STILL PASSED with the guard removed")
        print(f"  NOT PROVEN  {label}")
    else:
        print(f"  proven      {label}")

print()
if failures:
    print("REVERSION CHECK FAILED:")
    for f in failures:
        print("   " + f)
    sys.exit(1)
print(f"all {len(CASES)} schema guards proven: removing each one makes its test fail")
