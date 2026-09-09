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

    # THREE GUARDS WERE REMOVED HERE ON 9 Sep 2026, deliberately, and this
    # note is left in their place so the absence is a decision rather than a
    # gap somebody has to reconstruct.
    #
    #   "working tree is clean"            console/merge.py, `if dirty:`
    #   "checkout is on the base branch"   console/merge.py, `if head != base:`
    #   "a conflicted merge is aborted"    console/merge.py, `if merged...`
    #
    # All three guarded a merge made IN THE CHECKOUT. The merge is now built
    # and verified in a throwaway clone and published from there, so the
    # console never writes to a checkout at all -- see specs/
    # merge-outside-the-checkout.md. The first two conditions cannot affect
    # the outcome any more, and asserting them would refuse merges that are
    # safe; the second of them is what forced a production tree to be switched
    # to a task's base branch before Accept could be pressed. The conflict
    # guard did not disappear -- it moved to console/reverify.py, where "a
    # conflicting trial merge is refused" below still proves it.
    #
    # What replaced them, as behaviour rather than as guards, is asserted by
    # test_a_dirty_working_tree_no_longer_blocks_a_merge,
    # test_a_checkout_on_another_branch_no_longer_blocks_a_merge and
    # test_a_merge_is_never_attempted_in_the_checkout.

    ("a merge is published only from a verified trial",
     "console/merge.py",
     '    if not trial:',
     '    if False:',
     "tests/test_console_decide.py::test_a_merge_without_a_verified_trial_is_refused"),

    ("the remote must not have moved under the verified merge",
     "console/merge.py",
     '        if not descends:',
     '        if False:',
     "tests/test_console_decide.py::TestTheBaseMustAgreeWithItsRemote"
     "::test_a_remote_that_moved_refuses_before_pushing"),

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
     'trial, base_sha = worktree.create_trial_clone(repo, trial_root, name, base)',
     'trial, base_sha = worktree.create_trial_clone(repo, trial_root, name, branch)',
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

    # A missing checker has the exact shape of a failing check. Removing this
    # does not break the refusal -- it breaks the SENTENCE, which is the whole
    # defect: the reviewer is sent to read a diff that is fine.
    ("a missing checker is could_not_run, not a failing check",
     "console/reverify.py",
     '        if result.unresolved:',
     '        if False:',
     "tests/test_reverify.py"
     "::test_a_missing_checker_is_could_not_run_not_a_failing_check"),

    # Deliberately pointed at the unit test and not at an Accept-level one.
    # `Verification.passed` ALSO refuses an unresolved run, through its
    # `any(c.ran)` clause, so removing this branch does not let a merge
    # through -- the two are independent and either alone is sufficient. An
    # earlier version of this guard claimed it did, named an Accept-level
    # test, and could not be proven, because the claim was false. What this
    # branch is solely responsible for is the per-check reading: without it a
    # checker that has gone missing reports as a PASSING check.
    ("an unresolved check does not read as a passing skip",
     "runner/verify.py",
     '        if self.unresolved_reason is not None:\n            return False',
     '        if False:\n            return False',
     "tests/test_verify_scoping.py::test_a_missing_checker_never_reads_as_a_pass"),

    # A unit that fails to START writes nothing to the brief, so the brief
    # cannot report its own absence. Removing this makes the fleet silent
    # about exactly the failure it cannot otherwise notice.
    ("every fleet unit reports its own failure",
     "systemd/fleet-brief.service",
     'OnFailure=fleet-unit-failed@%n.service',
     '# OnFailure removed',
     "tests/test_unit_failure_notice.py::test_every_fleet_unit_declares_onfailure"),

    # The ceiling that matters once nothing is watching. max_attempts is 1 so
    # a task does not retry itself; the loop is the producer re-emitting a
    # candidate it is FORBIDDEN to deduplicate, and each approval buying the
    # same failure again.
    ("a candidate that has failed twice is not approved automatically",
     "console/approve.py",
     '            if blocked:',
     '            if False:',
     "tests/test_approval_surface.py::TestTheRepeatFailureStop"
     "::test_a_candidate_that_failed_twice_is_refused"),

    # AUTO-MERGE. The failure mode of an eligibility rule is to be
    # accidentally permissive, so both halves are guarded: the hard rule that
    # no flag can reach, and the evidence that the new behaviour works.
    ("a draft spec never merges unattended",
     "console/automerge.py",
     '    if work_type in NEVER_UNATTENDED:',
     '    if False:',
     "tests/test_automerge.py::test_a_draft_spec_is_refused_even_with_auto_merge_true"),

    ("an unattended merge needs a test that bit",
     "console/automerge.py",
     "    if bite.get(\"exit_code\") != 0:",
     "    if False:",
     "tests/test_automerge.py::test_a_test_that_did_not_bite_is_refused"),

    # An unattended decision has no reviewer, so decision_seconds must be NULL
    # rather than a duration measured against a page nobody rendered.
    ("an unattended decision records no review duration",
     "console/decide.py",
     '        if rendered_at is not None:',
     '        if False:',
     "tests/test_console_decide.py::TestDecidedVia::"
     "test_an_unattended_decision_cannot_claim_a_review"),

    # AUTO-DEPLOY. The two refusals that cannot be recovered from by reverting
    # a commit: a migration, and deploying onto an already-drifted production.
    ("a migration is never deployed unattended",
     "console/autodeploy.py",
     '    if migrations:',
     '    if False:',
     "tests/test_autodeploy.py::test_a_migration_in_the_range_is_never_deployed_unattended"),

    ("a stale drift reading is not an OK",
     "console/autodeploy.py",
     '    if age is None or age > MAX_DRIFT_AGE:',
     '    if False:',
     "tests/test_autodeploy.py::test_a_stale_reading_is_not_an_OK"),

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

    # ---- sentry: a failed read must never become a zero -------------------
    #
    # Four expressions of one rule. Each reversion below is a plausible
    # simplification, and each one turns "we could not look" into "there is
    # nothing there" — the sentence that would appear in the brief, in bold,
    # on the morning it is least true.
    ("a missing token fails the subject rather than reading nothing",
     "detectors/sentry.py",
     "        if not self._token:",
     "        if False:",
     "tests/test_sentry_detector.py::TestAFailedReadIsNeverAZero::"
     "test_a_missing_token_fails_the_subject"),

    ("enumeration refuses to return an empty subject list",
     "detectors/sentry.py",
     "        if not self._org or not self._projects:",
     "        if False:",
     "tests/test_sentry_detector.py::TestEnumerationRefusesToBeEmpty::"
     "test_no_project_configured_is_an_error_not_a_clean_run"),

    ("the brief refuses a claim from a run that did not close OK",
     "brief/pass_.py",
     '    if status != "OK":\n'
     '        detail = (error or "").strip() or "no error text was recorded"\n'
     '        who = ',
     '    if False:\n'
     '        detail = (error or "").strip() or "no error text was recorded"\n'
     '        who = ',
     "tests/test_sentry_brief.py::TestAZeroIsNeverPrintedFromAReadThatDidNotHappen::"
     "test_a_stale_zero_is_not_printed_when_the_newest_run_failed"),

    ("the brief refuses a run older than cadence plus grace",
     "brief/pass_.py",
     "    if allowance is not None and age is not None and age > allowance:\n"
     "        return [Claim.uncomputed(\n"
     "            key, label,",
     "    if False:\n"
     "        return [Claim.uncomputed(\n"
     "            key, label,",
     "tests/test_sentry_brief.py::TestAZeroIsNeverPrintedFromAReadThatDidNotHappen::"
     "test_a_run_older_than_cadence_and_grace_is_not_todays_answer"),

    # A PARTIAL run used to record WHICH subject failed and not WHY, so the
    # brief could name the gap but not explain it. Reverting this loses the
    # cause a morning after the process log has rolled.
    ("a PARTIAL run carries the reason, not only the subject",
     "detectors/base.py",
     "                    reason = ctx.first_failure_reason\n"
     "                    if reason:\n"
     "                        error += f\" -- {reason[:300]}\"",
     "                    pass",
     # Pointed at the DETECTOR test, not the brief one. The brief fixture
     # writes `detector_runs.error` directly, so it never exercises base.py's
     # composition at all; only a real failing subject does. Found by this
     # script, which is the second time it has caught a case aimed at a test
     # that could not fail.
     "tests/test_sentry_detector.py::TestAFailedReadIsNeverAZero::"
     "test_an_unauthorised_token_fails_the_subject"),

    # ---- aws cost: a pound ceiling against a dollar bill ------------------
    ("a missing fx reading refuses rather than guessing a rate",
     "detectors/aws_cost.py",
     "        if row is None:\n            raise CostUnavailable(",
     "        if False:\n            raise CostUnavailable(",
     # Pointed at the test that reads the REASON. Without the guard the next
     # line subscripts None and raises TypeError -- still a failed subject, so
     # an assertion on PARTIAL alone cannot tell a refusal from a crash.
     "tests/test_aws_cost.py::TestAMissingRateRefusesRatherThanGuesses::"
     "test_the_refusal_names_the_month_and_the_pair"),

    ("under the ceiling emits nothing",
     "detectors/aws_cost.py",
     "        if percent < 100:\n            return",
     "        if percent < 100:\n            pass",
     "tests/test_aws_cost.py::TestWhatItMeasures::"
     "test_under_the_ceiling_emits_nothing"),

    ("an empty Cost Explorer response is a failed read, not a zero bill",
     "detectors/aws_cost.py",
     "        if not buckets:",
     "        if False:",
     "tests/test_aws_cost.py::TestAFailedReadIsNeverAZeroBill::"
     "test_an_empty_period_list_is_a_failed_read_not_a_zero_bill"),

    ("a ceiling must declare its currency",
     "proposer/objectives.py",
     "    missing = [k for k in (\"amount\", \"currency\", \"period\") if not raw.get(k)]",
     "    missing = [k for k in (\"amount\", \"period\") if not raw.get(k)]",
     "tests/test_aws_cost.py::TestTheThresholdIsTheObjectives::"
     "test_a_ceiling_without_a_currency_is_refused_at_load"),

    ("brief staleness is measured from completed_at, not window_end",
     "brief/pass_.py",
     "       now() - r.completed_at  AS age,\n"
     "       (SELECT max(o.magnitude) FROM observations o",
     "       now() - r.window_end  AS age,\n"
     "       (SELECT max(o.magnitude) FROM observations o",
     "tests/test_aws_cost.py::TestTheBriefClaim::"
     "test_a_settle_lag_does_not_make_a_fresh_run_read_as_stale"),

    # ---- candidate producer: re-verification, not re-reading --------------
    ("a declared probe is re-executed at HEAD",
     "contracts/checks/candidate_block_shape.py",
     "            held, desc = run_probe(repo, probe)\n"
     "            if not held:",
     "            held, desc = run_probe(repo, probe)\n"
     "            if False:",
     "tests/test_candidate_block.py::TestAClaimIsReExecutedNotReRead::"
     "test_a_stale_claim_is_refused_at_head"),

    ("the probe vocabulary is closed",
     "contracts/checks/candidate_block_shape.py",
     '    return False, (f"{kind!r} is not in the probe vocabulary "',
     '    return True, (f"{kind!r} is not in the probe vocabulary "',
     "tests/test_candidate_block.py::TestAClaimIsReExecutedNotReRead::"
     "test_a_probe_outside_the_vocabulary_is_refused"),

    ("a block cannot express a disposition",
     "contracts/checks/candidate_block_shape.py",
     "    for field in FORBIDDEN:\n        if field in c:",
     "    for field in FORBIDDEN:\n        if False:",
     "tests/test_candidate_block.py::TestTheProhibitionsAreInTheShape::"
     "test_a_forbidden_field_is_refused[disposition-APPROVED]"),

    ("an hib_signal must carry its as_of",
     "contracts/checks/candidate_block_shape.py",
     '            if not isinstance(sig, dict) or not sig.get("value") or not sig.get("as_of"):',
     '            if False:',
     "tests/test_candidate_block.py::TestHibSignalIsAFactAndCarriesItsAge::"
     "test_a_signal_without_an_as_of_is_refused"),

    ("the block must declare itself unranked",
     "contracts/checks/candidate_block_shape.py",
     '    if block.get("ordering") != "unranked":',
     "    if False:",
     "tests/test_candidate_block.py::TestTheBlockDoesNotPretendToRank::"
     "test_ordering_must_be_declared_unranked"),

    ("the emitted ceiling is enforced",
     "contracts/checks/candidate_block_shape.py",
     "    if len(candidates) > args.max_candidates:",
     "    if False:",
     "tests/test_candidate_block.py::TestTheCeiling::test_over_the_cap_is_refused"),

    # ---- the draft-spec gate, reachable and capped ------------------------
    ("prose paths get the same parent rule as declared ones",
     "contracts/checks/draft_spec_shape.py",
     "            if (checkout / c).parent.is_dir() or (FLEET / c).parent.is_dir():\n"
     "                continue                      # a file this spec will create",
     "            if False:\n"
     "                continue                      # a file this spec will create",
     "tests/test_selfcheck.py::TestProseAndDeclaredPathsAreJudgedTheSameWay::"
     "test_a_file_the_spec_will_create_passes_in_prose"),

    ("an abbreviation is named as one, with its correction",
     "contracts/checks/draft_spec_shape.py",
     "            if match:\n                abbreviated.append",
     "            if False:\n                abbreviated.append",
     "tests/test_selfcheck.py::TestAnAbbreviationIsNamedAsOne::"
     "test_it_says_which_path_was_meant"),

    ("the self-check is capped",
     "contracts/checks/spec_selfcheck.sh",
     'if [ "$used" -ge "$MAX" ]; then',
     "if false; then",
     "tests/test_selfcheck.py::TestTheSelfCheckIsCapped::"
     "test_the_fourth_invocation_is_refused"),

    ("every self-check invocation is recorded",
     "contracts/checks/spec_selfcheck.sh",
     'if [ -n "$STATE" ]; then\n    {\n      echo "run $n exit=$code shape_changed=$SHAPE_CHANGED"',
     'if false; then\n    {\n      echo "run $n exit=$code shape_changed=$SHAPE_CHANGED"',
     "tests/test_selfcheck.py::TestTheSelfCheckIsCapped::"
     "test_every_invocation_is_recorded"),

    ("the self-check sees untracked files",
     "contracts/checks/spec_selfcheck.sh",
     "CHANGED=$(git status --porcelain -uall 2>/dev/null | awk '{print $NF}')",
     "CHANGED=$(git status --porcelain 2>/dev/null | awk '{print $NF}')",
     "tests/test_selfcheck.py::TestTheSelfCheckIsCapped::"
     "test_an_untracked_file_is_seen"),

    ("the paths pack names the real tree",
     "runner/packs.py",
     "            for p in sorted(start.rglob(\"*\")):",
     "            for p in sorted([]):",
     "tests/test_selfcheck.py::TestThePathsPackIsGeneratedNotCommitted::"
     "test_it_lists_real_files_and_says_how_to_cite_them"),

    ("a worktree_link to a checkout counts as a read-only tree",
     "runner/packs.py",
     "        if (p / \".git\").exists():\n            trees[p.name] = p",
     "        if False:\n            trees[p.name] = p",
     "tests/test_selfcheck.py::TestThePathsPackIsGatedOnCapability::"
     "test_a_worktree_link_to_a_checkout_grants_one_too"),

    ("readable_repos counts as a read-only tree",
     "runner/packs.py",
     "        if p.is_dir():\n            trees[name] = p",
     "        if False:\n            trees[name] = p",
     "tests/test_selfcheck.py::TestThePathsPackIsGatedOnCapability::"
     "test_readable_repos_grants_a_listing"),

    ("a changed offending set is flagged as mutation",
     "contracts/checks/spec_selfcheck.sh",
     '                *) SHAPE_CHANGED=yes ;;',
     '                *) SHAPE_CHANGED=no ;;',
     "tests/test_selfcheck.py::TestTheSameShapeGuard::"
     "test_a_new_offending_path_warns"),

    # ---- a refusal that reaches only one browser tab is a silent failure ---
    ("an outcome cannot be set without being logged",
     "console/app.py",
     '        log.warning("task %s REFUSED: %s%s", task_id,',
     '        pass  # noqa\n        _unused = (lambda *a: None)(',
     "tests/test_console_blocker.py::TestAnOutcomeCannotBeSetWithoutBeingLogged::"
     "test_a_refusal_is_logged_at_warning"),

    # REMOVED 9 Sep 2026 with the refusal it guarded. `preflight` no longer
    # refuses when the checkout is not on the base branch, because the merge
    # is not made there -- so there is no message left to name a fix in. See
    # tests/test_console_blocker.py, which records the same reasoning where
    # the tests used to be.

    ("the page asks preflight before offering the button",
     "console/app.py",
     "            if not check.ok:\n"
     "                blocker = {\"reason\": check.reason, \"detail\": list(check.detail)}",
     "            if False:\n"
     "                blocker = {\"reason\": check.reason, \"detail\": list(check.detail)}",
     "tests/test_console.py::TestTheRefusalIsShownBeforeTheButton::"
     "test_a_ready_task_whose_merge_would_refuse_says_so"),

    ("a preflight that cannot run still yields a blocker",
     "console/app.py",
     '            blocker = {"reason": f"the merge preconditions could not be "',
     '            blocker = None or {"reason": f"" f"',
     "tests/test_console.py::TestTheRefusalIsShownBeforeTheButton::"
     "test_the_page_still_renders_when_preflight_cannot_run"),

    # ---- the base must agree with its remote, before the PUSH -------------
    #
    # Three guards lived here and all three were about the check as it stood
    # in preflight: refusing on `behind`, fetching into the checkout first so
    # the comparison was fresh, and refusing when the count could not be
    # resolved. The check MOVED into `publish` on 9 Sep 2026, where it runs in
    # the trial clone against a remote fetched seconds earlier -- so the fetch
    # into the checkout is gone (it was a write), and the comparison is a
    # `merge-base --is-ancestor` rather than two counts, which cannot return
    # "I could not look" as a number.
    #
    # Its replacement is "the remote must not have moved under the verified
    # merge", above. `_count` survives only to put a number in the message,
    # and its own None-not-zero property is still tested directly by
    # test_count_itself_returns_none_when_git_fails.

    ("_count reports failure as None, not as zero",
     "console/merge.py",
     "    if r.returncode != 0:\n        return None",
     "    if r.returncode != 0:\n        return 0",
     "tests/test_console_decide.py::TestTheBaseMustAgreeWithItsRemote::"
     "test_count_itself_returns_none_when_git_fails"),

    ("decided_via is validated, not taken on trust",
     "console/decide.py",
     "    if decided_via not in DECIDED_VIA:",
     "    if False:",
     "tests/test_console_decide.py::TestDecidedVia::test_an_unknown_value_is_refused"),

    ("decided_via reaches the payload",
     "console/decide.py",
     '        "decided_via": decided_via,',
     '        "decided_via": "console",',
     "tests/test_console_decide.py::TestDecidedVia::"
     "test_a_hand_merge_can_be_recorded_as_one"),

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
