"""Revert each guard in turn, confirm its test fails, restore.

    .venv/bin/python tests/revert_guards.py

Not a pytest module: it edits the source tree, so it must run alone and
restore what it touched even when a test crashes. Run it after changing
anything in console/merge.py, console/decide.py or console/config.py.

WHY THIS EXISTS
    A test that passes whether or not the guard is present is not testing the
    guard, and it is indistinguishable from one that is until somebody checks.
    On the first run this found three: the dirty-tree test matched a substring
    that also appears in the conflict message; the push-verification test
    asserted a happy path in which the push really does land, so the check
    could be deleted without effect; and the reader test accepted
    ReadOnlySqlTransaction as well as InsufficientPrivilege, so the session
    flag masked whether the ROLE was read-only at all.
"""
import subprocess, sys
from pathlib import Path

ROOT = Path("/home/ubuntu/fleet")

CASES = [
    ("task is READY_FOR_REVIEW",
     "console/merge.py",
     '    if task["status"] != "READY_FOR_REVIEW":',
     '    if False:',
     "tests/test_console_decide.py::test_accept_on_a_non_ready_task_refuses"),

    ("branch matches the task's recorded branch",
     "console/merge.py",
     '    if branch != task["branch_name"]:',
     '    if False:',
     "tests/test_console_decide.py::test_accept_with_a_mismatched_branch_name_refuses"),

    ("branch name matches fleet/task-N",
     "console/merge.py",
     '    if not BRANCH_RE.match(branch):',
     '    if False:',
     "tests/test_console_decide.py::test_a_branch_name_of_the_wrong_shape_refuses"),

    ("branch is not the base branch",
     "console/merge.py",
     '    if branch == base:',
     '    if False:',
     "tests/test_console_decide.py::test_merging_the_base_into_itself_refuses"),

    ("working tree is clean",
     "console/merge.py",
     '    if dirty:',
     '    if False:',
     "tests/test_console_decide.py::test_a_dirty_working_tree_refuses"),

    ("checkout is on the base branch",
     "console/merge.py",
     '    if head != base:',
     '    if False:',
     "tests/test_console_decide.py::test_a_checkout_on_another_branch_refuses"),

    ("a conflicted merge is aborted and records nothing",
     "console/merge.py",
     '        if merged.returncode != 0:',
     '        if False:',
     "tests/test_console_decide.py::test_a_conflicting_merge_records_nothing_and_leaves_the_tree_clean"),

    ("the push is verified against the remote, not trusted",
     "console/merge.py",
     '    if not r.push_verified:',
     '    if False:',
     "tests/test_console_decide.py::test_a_push_that_did_not_land_is_caught"),

    ("the task has not been decided while the page was open",
     "console/decide.py",
     '                if waited["status"] != "READY_FOR_REVIEW":',
     '                if False:',
     "tests/test_console_decide.py::test_a_task_decided_while_the_page_was_open_refuses"),

    ("the reject reason is one the database accepts",
     "console/decide.py",
     '    if decision != ACCEPT_DECISION and decision not in REJECT_REASONS:',
     '    if False:',
     "tests/test_console_decide.py::test_reject_refuses_a_reason_the_database_would_refuse"),

    # The session flag is not the guard -- the ROLE is, and removing
    # `conn.read_only` changes nothing because the grant still refuses. The
    # reversion that matters is pointing the reader at the writer, which is
    # the misconfiguration this test exists to catch.
    ("the branch tip is the commit that was verified",
     "console/merge.py",
     '    if tip != recorded_patch:',
     '    if False:',
     "tests/test_reverify.py::test_a_commit_appended_after_verification_is_refused"),

    ("the branch was not rebased under the recorded branch point",
     "console/merge.py",
     '        if merge_base != branch_point:',
     '        if False:',
     "tests/test_reverify.py::test_a_rebased_branch_is_still_refused"),

    # The one the whole re-verification rests on: verifying the BRANCH instead
    # of the merged tree re-establishes what the original run established and
    # proves nothing new.
    ("re-verification runs against the merged tree, not the branch",
     "console/reverify.py",
     'trial, base_sha = worktree.create_detached(repo, worktree_root, name, base)',
     'trial, base_sha = worktree.create_detached(repo, worktree_root, name, branch)',
     "tests/test_reverify.py::test_it_verifies_the_merged_tree_not_the_branch"),

    ("a failing re-verification stops the merge",
     "console/reverify.py",
     '        if not result.passed:',
     '        if False:',
     "tests/test_reverify.py::test_a_clean_merge_into_broken_code_is_caught"),

    ("a conflicting trial merge is refused",
     "console/reverify.py",
     '        if merged.returncode != 0:',
     '        if False:',
     "tests/test_reverify.py::test_a_conflicting_merge_is_reported_as_one"),

    # ---- the decision log's half of review.py ---------------------------
    ("a verdict needs a reason in words, not only a code",
     "review.py",
     '    if not (why or "").strip():',
     '    if False:',
     "tests/test_review.py::TestEveryVerdictOpensADecision"
     "::test_a_verdict_with_no_sentence_is_refused_before_the_database"),

    # The verdict and its log entry are one write or neither. Reverted, the
    # first INSERT survives a failure in the second and a caller that swallows
    # the error commits a verdict with no record of why it was reached.
    ("the verdict and the decision log land together",
     "review.py",
     "    with conn.transaction():\n        decision = conn.execute(",
     "    if True:\n        decision = conn.execute(",
     "tests/test_review.py::TestBothOrNeither"
     "::test_a_failed_log_write_takes_the_verdict_with_it"),

    ("a skip records nothing",
     "review.py",
     '        if verdict == "SKIP":',
     "        if False:",
     "tests/test_review.py::TestSkipLogsNothing::test_a_skip_records_neither"),

    ("the reader is not secretly the writer",
     "console/config.py",
     'return base_config.require("FLEET_CONSOLE_READER_DSN")',
     'return base_config.require("FLEET_CONSOLE_DSN")',
     "tests/test_console_decide.py::test_the_reader_connection_cannot_write"),

    # ---- precedent: the condition on which the proposer may read the log ----
    #
    # 010 refuses the proposal layer's read identity any sight of
    # `decision_log`, so that a layer cannot learn what gets approved and
    # propose that instead. The cycle now reads it on a third connection, and
    # the ONLY thing standing in for that refusal is that the reading never
    # reaches the ranking. These four are that claim, proven rather than
    # asserted.
    #
    # The first version of the test could not catch the first two: it seeded
    # one finding, and a one-item list sorts identically in every order. The
    # crowded fixture and the two worlds differing on every scalar are both
    # here because of what this script reported.
    ("precedent does not reach the ranking (by total)",
     "proposer/cycle.py",
     "    ordered = sorted(fresh, key=lambda f: rank(f, objectives))",
     "    _b = (result.precedent.total if result.precedent else 0) % 2\n"
     "    ordered = sorted(fresh, key=lambda f: rank(f, objectives),\n"
     "                     reverse=bool(_b))",
     "tests/test_precedent.py::test_precedent_cannot_change_what_is_proposed"),

    ("precedent does not reach the ranking (by rejections)",
     "proposer/cycle.py",
     "    ordered = sorted(fresh, key=lambda f: rank(f, objectives))",
     "    _b = result.precedent.rejected if result.precedent else 0\n"
     "    ordered = sorted(fresh, key=lambda f: rank(f, objectives),\n"
     "                     reverse=bool(_b))",
     "tests/test_precedent.py::test_precedent_cannot_change_what_is_proposed"),

    ("the cycle actually reads the log",
     "proposer/cycle.py",
     "    result.precedent = _read_precedent(precedent_dsn, cycle_config)",
     "    pass",
     "tests/test_precedent.py::test_precedent_cannot_change_what_is_proposed"),

    ("rank() is never handed precedent",
     "proposer/cycle.py",
     "def rank(finding: Finding, objectives: Objectives):",
     "def rank(finding: Finding, objectives: Objectives, precedent=None):",
     "tests/test_precedent.py::test_rank_cannot_reach_precedent_because_it_is_not_given_any"),

    # ---- outcomes: the two ways the obvious derivation goes wrong ----------
    ("merged status and git ancestry are both carried",
     "outcomes.py",
     "        return self.status_says_merged != (self.ancestry == IN_MAIN)",
     "        return False",
     "tests/test_outcomes.py::TestMergeEvidenceCarriesBothClaims::"
     "test_a_commit_that_never_landed_but_reads_merged_is_the_finding"),

    ("an unreadable git answer is not a disagreement",
     "outcomes.py",
     "        if not self.computable:\n            return False",
     "        if not self.computable:\n            pass",
     "tests/test_outcomes.py::TestMergeEvidenceCarriesBothClaims::"
     "test_an_unreadable_answer_is_never_a_disagreement"),

    ("the baseline comes from the task, not a constant",
     "outcomes.py",
     "    base_branch = base_branch or \"main\"",
     "    base_branch = \"main\"",
     "tests/test_outcomes.py::TestTheBaselineComesFromTheData::"
     "test_the_task_base_branch_is_what_is_compared"),

    ("a local baseline is labelled as local",
     "outcomes.py",
     "    local_note = (\" (a LOCAL branch on this host, not the shared repository)\"\n"
     "                  if is_local else \"\")",
     "    local_note = \"\"",
     "tests/test_outcomes.py::TestTheBaselineComesFromTheData::"
     "test_a_local_branch_answers_a_weaker_question_and_says_so"),

    ("git ancestry never overrides the deploy verdict",
     "outcomes.py",
     "    return DeployEvidence(verdict, why, in_running)",
     "    if in_running:\n        return DeployEvidence(\"SHIPPED\", why, in_running)\n"
     "    return DeployEvidence(verdict, why, in_running)",
     # Pointed at the NON-OVERRIDE test, not the frontend one. The real
     # frontend state carries no sha at all -- its `detail` is a sentence
     # explaining why -- so `in_running` is None there and a reversion that
     # promotes ancestry into the verdict cannot fire. The frontend test
     # proves the routing; this proves the precedence. Found by this script.
     "tests/test_outcomes.py::TestDeployEvidence::"
     "test_ancestry_never_overrides_the_verdict"),

    # ---- precedent: the caveat and the floor -------------------------------
    ("the zero-rejection caveat is under every approval block",
     "proposer/precedent.py",
     "                if fact.approval_claim and self.has_no_rejections:",
     "                if fact.key == \"shape\" and self.has_no_rejections:",
     "tests/test_precedent.py::TestTheZeroRejectionCaveat::"
     "test_it_appears_under_every_approval_derived_block"),

    ("the merge commit is preferred over the branch tip",
     "outcomes.py",
     "    if merge_commit and not already_merged:\n"
     "        return merge_commit, MERGE_COMMIT",
     "    if False:\n        return merge_commit, MERGE_COMMIT",
     "tests/test_outcomes.py::TestWhichCommitIsAskedAbout::"
     "test_the_merge_commit_is_preferred_over_the_branch_tip"),

    ("already_merged refuses the recorded merge sha",
     "outcomes.py",
     "    if merge_commit and not already_merged:",
     "    if merge_commit:",
     "tests/test_outcomes.py::TestWhichCommitIsAskedAbout::"
     "test_already_merged_refuses_the_recorded_sha"),

    ("a thin group is listed, not compared",
     "proposer/precedent.py",
     "        if len(rows) < floor:",
     "        if False:",
     "tests/test_precedent.py::TestBelowTheFloorAGroupIsListedNotCompared::"
     "test_a_thin_group_keeps_its_counts_and_loses_the_comparison"),
]


def run(test: str) -> bool:
    r = subprocess.run([".venv/bin/python", "-m", "pytest", test, "-q",
                        "--no-header", "-x"], cwd=ROOT,
                       capture_output=True, text=True)
    return r.returncode == 0


failures = []
for label, rel, needle, replacement, test in CASES:
    path = ROOT / rel
    original = path.read_text()
    if needle not in original:
        failures.append(f"{label}: could not find the guard to revert in {rel}")
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
print(f"all {len(CASES)} guards proven: removing each one makes its test fail")
