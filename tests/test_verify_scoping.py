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
        assert check.undecided_reason and "SIGABRT" in check.undecided_reason
        assert check.passed is False
        assert check.ran is False, "a killed check established nothing"
        assert v.undecided is True
        assert v.passed is False

    def test_a_killed_check_is_not_reported_as_unresolved(self):
        """Different sentences, different repairs. Unresolved sends a reader
        to the contract; killed sends them to the unit's limits."""
        killed = verify.Check("c", 137, 1, "", undecided_reason="SIGKILL")
        assert verify.Verification(checks=[killed]).unresolved is False
        assert verify.Verification(checks=[killed]).undecided is True

    def test_an_ordinary_failure_is_still_a_failure(self, tmp_path):
        """The gate this change must not widen. exit 1 is a verdict."""
        v = verify.run(tmp_path, ["exit 1"], 60)
        assert v.checks[0].undecided_reason is None
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
        """1 is a verdict, and so is any code with no meaning attached.

        2 USED TO BE ASSERTED HERE AND IS NOT ANY MORE -- see the test below.
        3 stands in for "an ordinary non-zero", which is what this protects.
        """
        assert verify.killed_by(1, 0) is None
        assert verify.killed_by(3, None) is None
        assert verify.killed_by(9, None) is None

    def test_exit_2_is_could_not_run_and_not_a_failure(self):
        """The convention the checks document and this classifier did not know.

        Changed 11 Sep 2026. Task 67 was refused with "the branch FAILS when
        merged into main as it stands now" on a `pytest_unit_per_file.sh api
        tests/unit` exit 2 -- and re-run alone against the same merged tree,
        every check passed. The script states its contract on line 5 ("0 if
        all pass, 1 naming the files that did not, 2 if the gate could not run
        at all") and has eight exit-2 paths, every one an environment failure.
        """
        why = verify.killed_by(2, None)
        assert why is not None, "exit 2 is not a verdict about the tree"
        assert "COULD NOT RUN" in why

    def test_the_check_scripts_really_do_use_2_for_could_not_run(self):
        """Read the artefact, per conftest: this rule is about THEM.

        A classifier asserting a convention the scripts do not follow would be
        worse than the gap it replaces.
        """
        import re
        from pathlib import Path
        for name in ("pytest_unit_per_file.sh", "new_test_bites.sh"):
            body = Path("contracts/checks") / name
            text = body.read_text()
            assert "exit 2" in text, f"{name} has no exit 2 to classify"
            # every `exit 2` is reached from a precondition failure, never
            # from the branch's own test results
            assert not re.search(r"failed\+=.*\n.*exit 2", text), name

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


# ---- the precondition: writable before anything runs ----------------------

class TestWritableBeforeAnythingRuns:
    """The class the signal classifier cannot reach.

    A check that dies on the filesystem exits NORMALLY. vitest returned 1 on
    `EROFS: open '<trial>/platform/node_modules/.vite/vitest/results.json'`
    and nothing in the exit code separated it from a failing test, so the
    accept path reported the branch as failing to verify.

    Reading the output for "EROFS" is the answer this codebase refuses for
    git's wording. So the filesystem is asked first, by writing to it.
    """

    def _ro_link(self, tmp_path):
        import os
        ro = tmp_path / "vendor_src"
        ro.mkdir()
        os.chmod(ro, 0o555)
        root = tmp_path / "wt"
        (root / "platform").mkdir(parents=True)
        links = worktree.link_dependencies(root, {"platform/vendor": str(ro)})
        return root, links, ro

    def test_an_unwritable_link_stops_the_run_before_a_check_executes(
            self, tmp_path):
        import os
        root, links, ro = self._ro_link(tmp_path)
        try:
            marker = tmp_path / "it-ran"
            v = verify.run(root, [f"touch {marker}"], 60, links=links)
            assert not marker.exists(), (
                "a check ran despite the precondition failing")
            assert v.undecided is True
            assert v.passed is False
            assert "not writable" in v.checks[0].undecided_reason
            assert str(ro) in v.checks[0].undecided_reason or "vendor" in \
                v.checks[0].undecided_reason
        finally:
            os.chmod(ro, 0o755)

    def test_it_names_the_path_rather_than_the_symptom(self, tmp_path):
        import os
        root, links, ro = self._ro_link(tmp_path)
        try:
            v = verify.run(root, ["true"], 60, links=links)
            assert "vendor" in v.checks[0].undecided_reason
        finally:
            os.chmod(ro, 0o755)

    def test_a_writable_tree_is_not_delayed_by_the_check(self, tmp_path):
        v = verify.run(tmp_path, ["true"], 60)
        assert v.passed is True and v.undecided is False

    def test_a_farmed_node_modules_passes_the_precondition(self, tmp_path):
        """The fix and the assertion that proves it, in one test. A farmed
        link is writable; that is the whole difference."""
        src = tmp_path / "node_modules"
        (src / "pkg").mkdir(parents=True)
        (src / ".vite").mkdir()
        root = tmp_path / "wt"
        (root / "platform").mkdir(parents=True)
        links = worktree.link_dependencies(root, {"platform/node_modules": str(src)})
        assert verify.unwritable(root, links) == []

    def test_the_probe_leaves_nothing(self, tmp_path):
        before = set(p.name for p in tmp_path.iterdir())
        verify.unwritable(tmp_path)
        assert set(p.name for p in tmp_path.iterdir()) == before


# ---- a timeout is a check that did not answer -----------------------------

class TestATimeoutIsInTheSameClass:
    """As often a slow host as a loop in the branch, and nothing in the exit
    tells you which. The deadline expiring is the only fact there is."""

    def test_a_timeout_reports_no_verdict(self, tmp_path):
        v = verify.run(tmp_path, ["sleep 5"], 1)
        check = v.checks[0]
        assert check.timed_out is True
        assert check.undecided_reason and "deadline" in check.undecided_reason
        assert v.undecided is True
        assert v.passed is False

    def test_the_sentence_does_not_claim_which_it_was(self, tmp_path):
        v = verify.run(tmp_path, ["sleep 5"], 1)
        why = v.checks[0].undecided_reason
        assert "does not say which" in why

    def test_a_check_that_never_started_is_also_undecided(self, tmp_path):
        """The deadline already spent when the check came up. Not merely
        unanswered: never asked.

        Driven with a zero deadline rather than by racing two commands --
        `remaining <= 0` is reachable only when a check finishes exactly on
        the boundary, and a test that depends on that is a test that fails on
        a fast morning."""
        v = verify.run(tmp_path, ["true"], 0)
        assert v.undecided is True
        assert any("never ran" in (c.undecided_reason or "") for c in v.checks)
        assert v.passed is False

    def test_timed_out_is_still_recorded_separately(self, tmp_path):
        """Readers distinguish the three. The class is shared; the field is
        not collapsed."""
        v = verify.run(tmp_path, ["sleep 5"], 1)
        assert v.checks[0].timed_out is True
        assert v.checks[0].unresolved_reason is None


class TestTheGateDoesNotDestroyTheRunWaitingBehindIt:
    """The teardown order in pytest_unit_per_file.sh's cleanup().

    Reordered 11 Sep 2026. Releasing the exclusive lock BEFORE stopping the
    services hands the database to the next gate and then deletes it: the
    waiter unblocks the instant fd 9 closes and races `docker compose down`
    for the Postgres it just won. It does not collide loudly -- it reports
    failures belonging to no branch, which is where TEST-004's 81-failure
    baseline came from and what refused task 67 on the night of 11 Sep.

    Asserted on the script because the script is what runs; there is no
    Python in this path to unit-test.
    """

    def _cleanup_body(self) -> str:
        from pathlib import Path
        text = Path("contracts/checks/pytest_unit_per_file.sh").read_text()
        start = text.index("cleanup() {")
        return text[start:text.index("\n}", start)]

    def test_services_go_down_before_the_lock_is_released(self):
        body = self._cleanup_body()
        down = body.index("docker compose")
        release = body.index("exec 9>&-")
        assert down < release, (
            "cleanup() releases the exclusive lock before stopping the test "
            "services, so a gate blocked on that lock inherits a database "
            "being deleted underneath it")

    def test_both_steps_are_still_there(self):
        """A reorder that dropped one of them would pass the test above."""
        body = self._cleanup_body()
        assert "docker compose" in body and "down" in body
        assert "exec 9>&-" in body
