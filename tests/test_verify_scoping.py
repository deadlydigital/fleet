"""Aiming verification at the change, and linking dependencies for it."""
from __future__ import annotations

from pathlib import Path

import pytest

from runner import verify, worktree
from runner.boundary import GitError


# ---- {changed_files} ------------------------------------------------------

def test_expansion_filters_by_suffix():
    cmd, found, n = verify.expand_changed_files(
        "ruff check {changed_files:.py}", ["api/analytics/services/analytics_engine.py", "platform/a.tsx"])
    assert (cmd, found, n) == ("ruff check api/analytics/services/analytics_engine.py", True, 1)


def test_expansion_takes_several_suffixes():
    cmd, _, n = verify.expand_changed_files(
        "tsc {changed_files:.ts,.tsx}",
        ["platform/a.tsx", "platform/b.ts", "api/analytics/services/analytics_engine.py"])
    assert n == 2 and "api/analytics/services/analytics_engine.py" not in cmd


def test_expansion_without_a_filter_takes_everything():
    cmd, _, n = verify.expand_changed_files(
        "check {changed_files}", ["a.py", "b.tsx"])
    assert n == 2 and "a.py" in cmd and "b.tsx" in cmd


def test_expansion_quotes_paths_with_spaces():
    """These reach a shell, so a path with a space must not become two."""
    cmd, _, _ = verify.expand_changed_files("check {changed_files}", ["a b.py"])
    assert "'a b.py'" in cmd


def test_a_command_without_a_placeholder_is_untouched():
    cmd, found, _ = verify.expand_changed_files("tsc --noEmit", ["a.py"])
    assert cmd == "tsc --noEmit" and found is False


# ---- what happens when a filter matches nothing --------------------------

def test_a_check_with_no_matching_files_is_skipped_not_run(tmp_path):
    """A bare `ruff check` with no paths would lint the whole tree, which is
    the repo-wide gate this replaces. It must not run at all."""
    result = verify.run(tmp_path, ["exit 1 # {changed_files:.py}"], 30,
                        changed=["platform/a.tsx"])
    assert len(result.checks) == 1
    assert not result.checks[0].ran
    assert result.checks[0].skipped_reason
    assert result.checks[0].passed          # skipping is not failing


def test_a_run_where_every_check_skipped_does_not_pass(tmp_path):
    """Nothing could look at this change, so nothing was established."""
    result = verify.run(tmp_path, ["true # {changed_files:.py}"], 30,
                        changed=["platform/a.tsx"])
    assert not result.passed


def test_a_run_with_one_real_check_and_one_skipped_passes(tmp_path):
    result = verify.run(
        tmp_path, ["true", "true # {changed_files:.py}"], 30,
        changed=["platform/a.tsx"])
    assert result.passed
    assert [c.ran for c in result.checks] == [True, False]


def test_the_expanded_command_is_recorded(tmp_path):
    result = verify.run(tmp_path, ["true {changed_files:.py}"], 30,
                        changed=["api/analytics/services/analytics_engine.py"])
    assert result.checks[0].command == "true {changed_files:.py}"
    assert result.checks[0].expanded == "true api/analytics/services/analytics_engine.py"


# ---- the runner's facts reach the checks ---------------------------------

def test_checks_receive_the_runner_derived_facts(tmp_path):
    result = verify.run(
        tmp_path,
        ['test "$FLEET_BASE_SHA" = abc123 && test -n "$FLEET_CHANGED_FILES"'],
        30, changed=["api/analytics/services/analytics_engine.py"], facts={"FLEET_BASE_SHA": "abc123"})
    assert result.passed


def test_changed_files_are_exported_one_per_line(tmp_path):
    result = verify.run(
        tmp_path, ['test "$(printf %s "$FLEET_CHANGED_FILES" | wc -l)" = 1'],
        30, changed=["a.py", "b.py"])
    assert result.passed


# ---- dependency links ----------------------------------------------------

def test_links_are_created_and_removed(tmp_path):
    src = tmp_path / "node_modules"
    (src / "pkg").mkdir(parents=True)
    wt = tmp_path / "wt" / "platform"
    wt.mkdir(parents=True)
    root = tmp_path / "wt"

    created = worktree.link_dependencies(root, {"platform/node_modules": str(src)})
    assert (root / "platform/node_modules/pkg").exists()

    worktree.unlink_dependencies(created)
    assert not (root / "platform/node_modules").exists()
    assert (src / "pkg").exists(), "unlinking must not follow into the real tree"


def test_a_link_target_outside_the_worktree_is_refused(tmp_path):
    src = tmp_path / "node_modules"
    src.mkdir()
    root = tmp_path / "wt"
    root.mkdir()
    with pytest.raises(GitError, match="outside the worktree"):
        worktree.link_dependencies(root, {"../escape": str(src)})


def test_a_missing_link_source_is_refused(tmp_path):
    root = tmp_path / "wt"
    root.mkdir()
    with pytest.raises(GitError, match="does not exist"):
        worktree.link_dependencies(root, {"platform/node_modules": "/nope"})


def test_a_link_will_not_replace_an_existing_path(tmp_path):
    src = tmp_path / "node_modules"
    src.mkdir()
    root = tmp_path / "wt"
    (root / "platform" / "node_modules").mkdir(parents=True)
    with pytest.raises(GitError, match="already exists"):
        worktree.link_dependencies(root, {"platform/node_modules": str(src)})


# ---- a checker that is not on disk ----------------------------------------
#
# Contracts name checkers by absolute path into a tree that is NOT the one
# under verification -- an interpreter, and a script in another repository.
# Those paths can stop resolving without anybody touching the task, and when
# they do the command exits non-zero exactly like a failing check. Reported as
# one, it sends a reviewer to read a diff that is fine.

def test_a_missing_checker_is_unresolved_not_failed(tmp_path):
    """The distinction step 1 exists to draw."""
    result = verify.run(tmp_path, ["/nonexistent/python /nonexistent/check.py"], 30)
    assert result.unresolved
    assert not result.passed
    check = result.checks[0]
    assert check.unresolved_reason and "/nonexistent/python" in check.unresolved_reason
    assert not check.passed          # and NOT treated as a skip
    assert not check.ran


def test_a_missing_checker_never_reads_as_a_pass(tmp_path):
    """The failure mode the branch ordering in Check.passed guards against.

    An unresolved check has `ran` False, and the skip branch returns True for
    anything that did not run. Were the branches the other way round, a
    checker that had gone missing would PASS -- worse than either other
    reading, because it merges unverified work.
    """
    result = verify.run(tmp_path, ["/nonexistent/check.py"], 30)
    assert result.checks[0].passed is False
    assert result.passed is False


def test_nothing_runs_when_any_checker_is_missing(tmp_path):
    """Resolution is checked up front, over the whole contract.

    The resolvable check must not run: its result could not change the
    outcome, and reporting its exit code would answer a question nobody asked
    while the real answer is "this could not be judged".
    """
    marker = tmp_path / "ran"
    result = verify.run(
        tmp_path,
        [f"touch {marker}", "/nonexistent/python /nonexistent/check.py"], 30)
    assert not marker.exists(), "a check ran despite the contract being unresolvable"
    assert result.unresolved and not result.passed
    assert len(result.checks) == 2               # the whole contract is reported
    assert result.checks[0].skipped_reason and not result.checks[0].unresolved_reason
    assert result.checks[1].unresolved_reason


def test_a_relative_path_is_not_treated_as_a_missing_checker(tmp_path):
    """Relative paths resolve inside the worktree -- the task's own business.

    Only absolute paths reach out of the tree under verification, and only
    those can go missing for reasons unrelated to the change.
    """
    result = verify.run(tmp_path, ["test -f does/not/exist.py"], 30)
    assert not result.unresolved
    assert result.checks[0].ran and not result.checks[0].passed   # a real failure


def test_an_unparseable_command_is_not_called_unresolved(tmp_path):
    """A command this cannot split is one it has no opinion about."""
    assert verify.unresolved_paths("echo 'unbalanced") == []


# ---- a check that was killed did not answer -------------------------------

class TestAKilledCheckIsNotAVerdict:
    """`exit_code != 0` is two different facts and was read as one.

    11 Sep 2026: re-verifying task 53 under fleet-automerge's 512M,
    `tsc --noEmit` exited 134 -- 128+6, SIGABRT, V8 refusing to continue
    because the cgroup would not give it memory. `Check.passed` was False,
    `Verification.unresolved` was False, and console/reverify.py's failure
    branch printed "the branch verifies on its own and FAILS when merged into
    main as it stands now. The base moved under it." Every clause was false.

    The two most likely environment failures in this system are a memory kill
    and a read-only filesystem, and the class that exists to hold "the check
    never ran" held neither.
    """

    def test_a_signalled_check_is_not_a_failure(self, tmp_path):
        v = verify.run(tmp_path, [
            'python3 -c "import os, signal; os.kill(os.getpid(), signal.SIGABRT)"'], 60)
        check = v.checks[0]
        assert check.exit_code == 134
        assert check.killed_reason and "SIGABRT" in check.killed_reason
        assert check.passed is False
        assert check.ran is False, "a killed check established nothing"
        assert v.undecided is True
        assert v.passed is False

    def test_a_killed_check_is_not_reported_as_unresolved(self):
        """Different sentences, different repairs. Unresolved sends a reader
        to the contract; killed sends them to the unit's limits."""
        killed = verify.Check("c", 137, 1, "", killed_reason="SIGKILL")
        assert verify.Verification(checks=[killed]).unresolved is False
        assert verify.Verification(checks=[killed]).undecided is True

    def test_an_ordinary_failure_is_still_a_failure(self, tmp_path):
        """The gate this change must not widen. exit 1 is a verdict."""
        v = verify.run(tmp_path, ["exit 1"], 60)
        assert v.checks[0].killed_reason is None
        assert v.checks[0].passed is False
        assert v.undecided is False, (
            "a check that said no must not be reported as a check that "
            "never ran -- that would turn every real failure into a refusal "
            "nobody can act on")

    def test_a_passing_check_is_untouched(self, tmp_path):
        v = verify.run(tmp_path, ["true"], 60)
        assert v.passed is True and v.undecided is False

    def test_a_negative_returncode_is_the_shell_itself_being_signalled(self):
        assert verify.killed_by(-9, None) is not None
        assert "SIGKILL" in verify.killed_by(-9, None)

    def test_a_cgroup_oom_kill_is_named_as_one(self):
        """Authoritative where the exit code is a guess: the kernel says it
        killed something for memory, so the reason says so rather than
        inferring it from 137."""
        why = verify.killed_by(1, 1)
        assert why and "OOM-killed" in why and "not a verdict" in why

    def test_no_oom_and_an_ordinary_code_is_still_a_verdict(self):
        assert verify.killed_by(1, 0) is None
        assert verify.killed_by(2, None) is None

    def test_the_whole_signal_range_is_covered(self):
        """128+N for every N a process can die on. A short list is how 134
        was missed: nobody predicts which signal the next environment failure
        arrives as."""
        for signum in (2, 4, 6, 7, 8, 9, 11, 13, 15, 24, 25):
            assert verify.killed_by(128 + signum, 0) is not None, signum

    def test_128_itself_is_not_a_signal(self):
        """128 is 128+0 and no signal 0 kills anything."""
        assert verify.killed_by(128, 0) is None


# ---- node_modules is farmed so a tool can write inside it ------------------

class TestAFarmedLinkIsWritable:
    """One symlink for the whole tree makes every path inside it read-only
    when the source is, and vitest writes inside it:

        EROFS: open '<trial>/platform/node_modules/.vite/vitest/results.json'

    Measured 11 Sep 2026 re-verifying task 53 with ProtectHome=read-only.
    vitest exits 1 on that, not on a signal, so it was reported as the branch
    failing to verify.
    """

    def _tree(self, tmp_path):
        src = tmp_path / "node_modules"
        (src / "pkg").mkdir(parents=True)
        (src / ".bin").mkdir()
        (src / ".bin" / "vitest").write_text("#!/bin/sh\n")
        (src / ".vite" / "vitest").mkdir(parents=True)
        (src / ".vite" / "vitest" / "results.json").write_text('{"stale": true}')
        root = tmp_path / "wt"
        (root / "platform").mkdir(parents=True)
        return src, root

    def test_the_farmed_directory_itself_is_real_and_writable(self, tmp_path):
        src, root = self._tree(tmp_path)
        worktree.link_dependencies(root, {"platform/node_modules": str(src)})
        nm = root / "platform/node_modules"
        assert nm.is_dir() and not nm.is_symlink()
        (nm / ".vite" / "vitest").mkdir(parents=True, exist_ok=True)
        (nm / ".vite" / "vitest" / "results.json").write_text("{}")
        assert (nm / ".vite/vitest/results.json").read_text() == "{}"

    def test_the_write_does_not_reach_the_real_tree(self, tmp_path):
        """The property the trial rests on: it leaves nothing."""
        src, root = self._tree(tmp_path)
        created = worktree.link_dependencies(root, {"platform/node_modules": str(src)})
        (root / "platform/node_modules/.vite/vitest").mkdir(parents=True, exist_ok=True)
        (root / "platform/node_modules/.vite/vitest/results.json").write_text("{}")
        assert (src / ".vite/vitest/results.json").read_text() == '{"stale": true}'
        worktree.unlink_dependencies(created)
        assert (src / "pkg").exists() and (src / ".bin" / "vitest").exists()
        assert (src / ".vite/vitest/results.json").exists()
        assert not (root / "platform/node_modules").exists()

    def test_packages_and_bin_still_resolve_to_the_real_ones(self, tmp_path):
        """`.bin` holds the executables the checks invoke. Copying or
        emptying it would mean the trial runs a different tsc."""
        src, root = self._tree(tmp_path)
        worktree.link_dependencies(root, {"platform/node_modules": str(src)})
        assert (root / "platform/node_modules/pkg").resolve() == (src / "pkg").resolve()
        assert (root / "platform/node_modules/.bin/vitest").resolve() \
            == (src / ".bin" / "vitest").resolve()

    def test_a_cache_arrives_empty_rather_than_carrying_another_trees_result(
            self, tmp_path):
        """A results.json from the real checkout is a verdict about a tree
        that is not this one."""
        src, root = self._tree(tmp_path)
        worktree.link_dependencies(root, {"platform/node_modules": str(src)})
        vite = root / "platform/node_modules/.vite"
        assert vite.is_dir() and not vite.is_symlink()
        assert list(vite.iterdir()) == []

    def test_a_non_farmed_link_is_still_one_symlink(self, tmp_path):
        """contracts/draft-spec.yaml links a whole repository checkout as
        `reference/...`. Farming that would turn its .git into a symlink."""
        src = tmp_path / "checkout"
        (src / ".git").mkdir(parents=True)
        root = tmp_path / "wt"
        root.mkdir()
        worktree.link_dependencies(root, {"reference/dd": str(src)})
        assert (root / "reference/dd").is_symlink()
