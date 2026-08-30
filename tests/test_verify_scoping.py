"""Aiming verification at the change, and linking dependencies for it."""
from __future__ import annotations

from pathlib import Path

import pytest

from runner import verify, worktree
from runner.boundary import GitError


# ---- {changed_files} ------------------------------------------------------

def test_expansion_filters_by_suffix():
    cmd, found, n = verify.expand_changed_files(
        "ruff check {changed_files:.py}", ["api/app.py", "platform/a.tsx"])
    assert (cmd, found, n) == ("ruff check api/app.py", True, 1)


def test_expansion_takes_several_suffixes():
    cmd, _, n = verify.expand_changed_files(
        "tsc {changed_files:.ts,.tsx}",
        ["platform/a.tsx", "platform/b.ts", "api/app.py"])
    assert n == 2 and "api/app.py" not in cmd


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
                        changed=["api/app.py"])
    assert result.checks[0].command == "true {changed_files:.py}"
    assert result.checks[0].expanded == "true api/app.py"


# ---- the runner's facts reach the checks ---------------------------------

def test_checks_receive_the_runner_derived_facts(tmp_path):
    result = verify.run(
        tmp_path,
        ['test "$FLEET_BASE_SHA" = abc123 && test -n "$FLEET_CHANGED_FILES"'],
        30, changed=["api/app.py"], facts={"FLEET_BASE_SHA": "abc123"})
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
