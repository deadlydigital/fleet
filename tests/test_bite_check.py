"""The frontend half of the bite check, and the hole it had.

contracts/checks/new_test_bites.sh was written for `api` and pytest. The
frontend contract points it at `platform` and vitest, and doing that surfaced a
defect that had been latent since it was written:

  STEP 4 TOOK ANY NON-ZERO EXIT AS "THE TEST FAILED, AS IT MUST".

The pre-change tree is materialised with `git archive`, which contains no
gitignored directory -- so platform/node_modules is absent and vitest cannot
start there at all. A runner that never started exits non-zero, so every
frontend task would have passed this check having run nothing. That is the
class of defect the file exists to prevent, in the file itself.

Two things fix it and both are covered here: runners report 2 for could-not-run
and the check distinguishes it, and contracts/checks/vitest_one_file.sh links
node_modules into the tree it is given so the ordinary path works at all.

WHY THE FIXTURE IS A SYNTHETIC PLATFORM AND NOT A CLONE OF THE REAL ONE

What is under test is the scripts' exit-code contract, not the platform's
vitest configuration. A tree with the real `include` pattern, one module and
one test runs in half a second; cloning the platform to assert the same three
exit codes would cost seconds per test and establish nothing more. The real
configuration is exercised by the contract itself, and by
tests/test_platform_floor.py::test_the_creatable_glob_matches_what_vitest_collects.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BITES = ROOT / "contracts" / "checks" / "new_test_bites.sh"
VITEST_RUNNER = ROOT / "contracts" / "checks" / "vitest_one_file.sh"
NODE_MODULES = Path("/home/ubuntu/deadly-digital-platform/platform/node_modules")

pytestmark = pytest.mark.skipif(
    not NODE_MODULES.is_dir(),
    reason="the platform's node_modules is not on this machine")

VITEST_CONFIG = """import { defineConfig } from 'vitest/config';
export default defineConfig({
  test: { include: ['./__tests__/unit/**/*.{test,spec}.{ts,tsx}'], globals: true },
});
"""

BASE_LABEL = "export const label = (spanDays: number) => `vs previous ${spanDays} days`\n"

#: The change: the label names the window that was COMPARED, not the one that
#: was asked for. The same shape as the frontend follow-up task 28's spec
#: describes, reduced to one function.
CHANGED_LABEL = (
    "export const label = (spanDays: number, comparedDays?: number) =>\n"
    "  `vs previous ${comparedDays ?? spanDays} days`\n")

BITING_TEST = """import { describe, it, expect } from 'vitest'
import { label } from '../../../app/label'
describe('label', () => {
  it('names the window that was compared, not the one asked for', () => {
    expect(label(61, 366)).toBe('vs previous 366 days')
  })
})
"""

VACUOUS_TEST = """import { describe, it, expect } from 'vitest'
describe('vacuous', () => { it('asserts nothing', () => { expect(true).toBe(true) }) })
"""

TEST_PATH = "platform/__tests__/unit/analytics/test_fleet_label.test.ts"
PATTERN = "__tests__/unit/analytics/test_fleet_*.test.ts"


def sh(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def write(repo: Path, rel: str, body: str) -> None:
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)


@pytest.fixture
def repo(tmp_path) -> Path:
    """A platform-shaped git repository, with node_modules gitignored exactly
    as the real one has it -- which is what makes the archive tree empty."""
    r = tmp_path / "repo"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.email", "t@t")
    sh(r, "git", "config", "user.name", "t")
    write(r, "platform/vitest.config.ts", VITEST_CONFIG)
    write(r, "platform/app/label.ts", BASE_LABEL)
    write(r, ".gitignore", "node_modules\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-q", "-m", "base")
    return r


def base_sha(repo: Path) -> str:
    return sh(repo, "git", "rev-parse", "HEAD").stdout.strip()


def change(repo: Path, *, label: str, test: str) -> None:
    write(repo, "platform/app/label.ts", label)
    write(repo, TEST_PATH, test)
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "change")


def run_bites(repo: Path, base: str, **env_over) -> subprocess.CompletedProcess:
    env = dict(os.environ,
               FLEET_BASE_SHA=base,
               FLEET_TEST_RUNNER=str(VITEST_RUNNER))
    env.update(env_over)
    return subprocess.run(
        [str(BITES), "platform", PATTERN, "__tests__"],
        cwd=repo, env=env, capture_output=True, text=True)


# ---- the runner ------------------------------------------------------------

def test_the_runner_works_in_a_tree_with_no_node_modules(repo, tmp_path):
    """The case that matters: `git archive` produces exactly this tree."""
    archive = tmp_path / "archive"
    archive.mkdir()
    tar = subprocess.run(["git", "archive", base_sha(repo)], cwd=repo,
                         capture_output=True)
    subprocess.run(["tar", "-x", "-C", str(archive)], input=tar.stdout, check=True)
    write(archive, TEST_PATH, BITING_TEST)
    write(archive, "platform/app/label.ts", CHANGED_LABEL)
    assert not (archive / "platform" / "node_modules").exists()

    r = subprocess.run([str(VITEST_RUNNER), "platform",
                        TEST_PATH[len("platform/"):]],
                       cwd=archive, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (archive / "platform" / "node_modules").exists(), \
        "the link it made was left behind"


def test_the_runner_reports_a_failing_test_as_one(repo, tmp_path):
    write(repo, TEST_PATH, BITING_TEST)          # against the UNCHANGED label
    r = subprocess.run([str(VITEST_RUNNER), "platform",
                        TEST_PATH[len("platform/"):]],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 1, r.stdout


def test_a_filter_matching_no_collected_file_is_could_not_run(repo):
    """vitest exits 1 for "No test files found", and a 1 here would be read as
    a failing test. It is neither: nothing ran."""
    write(repo, "platform/__tests__/unit/analytics/notatest.ts", "export const x = 1\n")
    r = subprocess.run([str(VITEST_RUNNER), "platform",
                        "__tests__/unit/analytics/notatest.ts"],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 2, r.stdout


def test_an_existing_node_modules_is_left_alone(repo):
    """A worktree the runner has already linked must not have its link removed
    by this script -- it removes only what it created."""
    (repo / "platform" / "node_modules").symlink_to(NODE_MODULES)
    write(repo, TEST_PATH, BITING_TEST)
    write(repo, "platform/app/label.ts", CHANGED_LABEL)
    r = subprocess.run([str(VITEST_RUNNER), "platform",
                        TEST_PATH[len("platform/"):]],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert (repo / "platform" / "node_modules").is_symlink()


# ---- the bite check ---------------------------------------------------------

def test_a_test_that_bites_passes(repo):
    base = base_sha(repo)
    change(repo, label=CHANGED_LABEL, test=BITING_TEST)
    r = run_bites(repo, base)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "the added test bites" in r.stdout


def test_a_vacuous_test_is_refused(repo):
    base = base_sha(repo)
    change(repo, label=CHANGED_LABEL, test=VACUOUS_TEST)
    r = run_bites(repo, base)
    assert r.returncode == 1, r.stdout
    assert "passes against the code as it was BEFORE the change" in r.stdout


def test_a_runner_that_cannot_start_is_could_not_run_not_a_bite(repo):
    """THE REGRESSION GUARD.

    Before this, step 4 read any non-zero exit from the pre-change tree as "the
    test failed, as it must" -- so a runner that could not start reported PASS,
    and every frontend task would have got one. The tree here is exactly that
    situation: the change's own tree can run vitest, the archive tree cannot.
    """
    (repo / "platform" / "node_modules").symlink_to(NODE_MODULES)
    base = base_sha(repo)
    change(repo, label=CHANGED_LABEL, test=BITING_TEST)
    r = run_bites(repo, base, FLEET_PLATFORM_NODE_MODULES="/nonexistent")
    assert r.returncode == 2, r.stdout
    assert "could not run against the pre-change tree" in r.stdout
    assert "bites" not in r.stdout


def test_a_change_that_adds_no_test_is_refused(repo):
    base = base_sha(repo)
    write(repo, "platform/app/label.ts", CHANGED_LABEL)
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "no test")
    r = run_bites(repo, base)
    assert r.returncode == 1
    assert "adds no test matching" in r.stdout


def test_touching_the_suite_beyond_the_added_test_is_refused(repo):
    """The suite directory is an argument now: platform/__tests__, not
    platform/tests. A check looking in the wrong place would find nothing and
    pass."""
    write(repo, "platform/__tests__/unit/analytics/existing.test.ts",
          "import { it, expect } from 'vitest'\nit('x', () => expect(1).toBe(1))\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "an existing test")
    base = base_sha(repo)
    write(repo, "platform/__tests__/unit/analytics/existing.test.ts",
          "import { it, expect } from 'vitest'\nit('x', () => expect(2).toBe(2))\n")
    change(repo, label=CHANGED_LABEL, test=BITING_TEST)
    r = run_bites(repo, base)
    assert r.returncode == 1, r.stdout
    assert "touches the suite beyond the one added test" in r.stdout


def test_two_added_tests_are_refused(repo):
    base = base_sha(repo)
    write(repo, "platform/__tests__/unit/analytics/test_fleet_other.test.ts",
          VACUOUS_TEST)
    change(repo, label=CHANGED_LABEL, test=BITING_TEST)
    r = run_bites(repo, base)
    assert r.returncode == 1
    assert "test files were added and this check proves one" in r.stdout


# ---- the backend path, which this change must not have moved ---------------

STUB_RUNNER = """#!/bin/bash
# Stands in for pytest_unit_per_file.sh so the backend argument handling can be
# exercised without docker or a database.
#
#   0  the tree under test contains the changed marker
#   1  it does not
#   2  could not run -- either always (FLEET_STUB_CANNOT_RUN) or only in the
#      scratch tree (FLEET_STUB_CANNOT_RUN_WITHOUT_GIT), which is what a
#      resource guard or a missing gitignored dependency looks like.
[ -n "${FLEET_STUB_CANNOT_RUN:-}" ] && exit 2
if [ -n "${FLEET_STUB_CANNOT_RUN_WITHOUT_GIT:-}" ] && [ ! -e .git ]; then exit 2; fi
grep -q CHANGED "$1/analytics/services/thing.py" && exit 0
exit 1
"""


@pytest.fixture
def api_repo(tmp_path) -> Path:
    r = tmp_path / "api_repo"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.email", "t@t")
    sh(r, "git", "config", "user.name", "t")
    write(r, "api/analytics/services/thing.py", "value = 1\n")
    write(r, "api/tests/analytics/test_existing.py", "def test_x():\n    assert True\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-q", "-m", "base")
    return r


@pytest.fixture
def stub_runner(tmp_path) -> Path:
    p = tmp_path / "stub_runner.sh"
    p.write_text(STUB_RUNNER)
    p.chmod(0o755)
    return p


def run_bites_api(repo, base, runner, **env_over):
    """No positional arguments at all -- the backend defaults."""
    env = dict(os.environ, FLEET_BASE_SHA=base, FLEET_TEST_RUNNER=str(runner))
    env.update(env_over)
    return subprocess.run([str(BITES)], cwd=repo, env=env,
                          capture_output=True, text=True)


def test_the_backend_defaults_still_resolve(api_repo, stub_runner):
    """`api`, `tests/analytics/test_fleet_*.py` and `tests` are still what you
    get with no arguments, which is how contracts/deadly-digital-platform-api
    .yaml invokes this."""
    base = base_sha(api_repo)
    write(api_repo, "api/analytics/services/thing.py", "value = 1  # CHANGED\n")
    write(api_repo, "api/tests/analytics/test_fleet_thing.py",
          "def test_it():\n    assert True\n")
    sh(api_repo, "git", "add", "-A")
    sh(api_repo, "git", "commit", "-q", "-m", "change")
    r = run_bites_api(api_repo, base, stub_runner)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "the added test bites" in r.stdout


def test_the_backend_suite_guard_still_looks_in_api_tests(api_repo, stub_runner):
    base = base_sha(api_repo)
    write(api_repo, "api/tests/analytics/test_existing.py",
          "def test_x():\n    assert 1 == 1\n")
    write(api_repo, "api/analytics/services/thing.py", "value = 1  # CHANGED\n")
    write(api_repo, "api/tests/analytics/test_fleet_thing.py",
          "def test_it():\n    assert True\n")
    sh(api_repo, "git", "add", "-A")
    sh(api_repo, "git", "commit", "-q", "-m", "change")
    r = run_bites_api(api_repo, base, stub_runner)
    assert r.returncode == 1, r.stdout
    assert "touches the suite beyond the one added test" in r.stdout


def test_a_backend_runner_that_cannot_run_is_reported_as_that(api_repo, stub_runner):
    """pytest_unit_per_file.sh reports 2 when the test database is unreachable
    or when memory is below its floor. Before this change that arrived at step
    3 as "the added test does not pass against its own change" -- a failing
    check, which sends a reviewer to read a diff that is fine. It is the
    misreport runner.verify.unresolved_paths exists to avoid, one layer down.
    """
    base = base_sha(api_repo)
    write(api_repo, "api/analytics/services/thing.py", "value = 1  # CHANGED\n")
    write(api_repo, "api/tests/analytics/test_fleet_thing.py",
          "def test_it():\n    assert True\n")
    sh(api_repo, "git", "add", "-A")
    sh(api_repo, "git", "commit", "-q", "-m", "change")
    r = run_bites_api(api_repo, base, stub_runner, FLEET_STUB_CANNOT_RUN="1")
    assert r.returncode == 2, r.stdout
    assert "bites" not in r.stdout


def test_a_backend_runner_that_dies_only_in_the_scratch_tree_is_not_a_bite(
        api_repo, stub_runner):
    """THE BACKEND'S VERSION OF THE FRONTEND HOLE, and it is narrower rather
    than absent.

    Step 3 runs in the worktree and step 4 in a `git archive` tree. A runner
    that works in the first and not the second reports 2 at step 4 only, and
    that is the case the old code read as "fails, as it must" and passed. On
    the frontend it was every task; here it needs pytest_unit_per_file.sh's
    memory floor or its database check to fire between the two runs -- rare,
    and contracts/deadly-digital-platform-api.yaml merges unattended on the
    strength of this check.
    """
    base = base_sha(api_repo)
    write(api_repo, "api/analytics/services/thing.py", "value = 1  # CHANGED\n")
    write(api_repo, "api/tests/analytics/test_fleet_thing.py",
          "def test_it():\n    assert True\n")
    sh(api_repo, "git", "add", "-A")
    sh(api_repo, "git", "commit", "-q", "-m", "change")
    r = run_bites_api(api_repo, base, stub_runner,
                      FLEET_STUB_CANNOT_RUN_WITHOUT_GIT="1")
    assert r.returncode == 2, r.stdout
    assert "could not run against the pre-change tree" in r.stdout
    assert "bites" not in r.stdout
