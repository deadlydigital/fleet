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

    ("the reader is not secretly the writer",
     "console/config.py",
     'return base_config.require("FLEET_CONSOLE_READER_DSN")',
     'return base_config.require("FLEET_CONSOLE_DSN")',
     "tests/test_console_decide.py::test_the_reader_connection_cannot_write"),
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
