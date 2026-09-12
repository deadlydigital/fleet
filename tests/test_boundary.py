"""The derived diff, and what it refuses.

These tests build real git repositories. A boundary check tested against a
mocked `git diff` proves the mock agrees with the checker, which is not the
property anyone needs.
"""
from __future__ import annotations


def _ensure(p):
    """The fixtures write a nested analytics path now that api/app.py
    is floored (017); its parent does not exist in a bare fixture repo."""
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

import subprocess
from pathlib import Path

import pytest

from runner import boundary

CONTRACT = {
    "writable_paths": ["platform/app/**", "api/analytics/services/analytics_engine.py", "platform/app/**"],
    "protected_paths": ["api/tests/**", "api/pytest.ini", "api/alembic/**"],
    "max_diff_lines": 100,
}


def run(cwd: Path, *args: str) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"{' '.join(args)}: {r.stderr}"
    return r.stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    """A repository shaped like the platform, with a base commit."""
    r = tmp_path / "repo"
    r.mkdir()
    run(r, "git", "init", "-q", "-b", "main")
    run(r, "git", "config", "user.email", "t@t")
    run(r, "git", "config", "user.name", "t")
    for p, body in [
        ("api/analytics/services/analytics_engine.py", "def app():\n    '''old'''\n"),
        ("api/services/thing.py", "x = 1\n"),
        ("api/tests/test_thing.py", "def test_x():\n    assert True\n"),
        ("api/pytest.ini", "[pytest]\n"),
        ("api/alembic/env.py", "# migrations\n"),
        ("platform/app/page.tsx", "export default () => null\n"),
        ("README.md", "# readme\n"),
    ]:
        f = r / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    (r / ".gitignore").write_text("*.log\n")
    run(r, "git", "add", "-A")
    run(r, "git", "commit", "-q", "-m", "base")
    return r


def base_sha(repo: Path) -> str:
    return run(repo, "git", "rev-parse", "HEAD").strip()


# ---- globs ----------------------------------------------------------------

@pytest.mark.parametrize("glob,path,expected", [
    ("api/tests/**", "api/tests/test_x.py", True),
    ("api/tests/**", "api/tests/deep/test_x.py", True),
    ("api/tests/**", "api/testsuite/x.py", False),
    ("api/tests/**", "api/services/x.py", False),
    ("api/pytest.ini", "api/pytest.ini", True),
    ("api/pytest.ini", "api/pytest.ini.bak", False),
    ("platform/*", "platform/app/page.tsx", False),
    ("platform/**", "platform/app/page.tsx", True),
    ("api/services/**", "api/services/a/b/c.py", True),
])
def test_glob_matching(glob, path, expected):
    assert bool(boundary.glob_to_regex(glob).match(path)) is expected


def test_single_star_does_not_cross_a_separator():
    """A contract author who wrote platform/* meaning the whole tree should
    find out from a rejected diff, not a merged one."""
    assert not boundary.glob_to_regex("platform/*").match("platform/app/p.tsx")
    assert boundary.glob_to_regex("platform/*").match("platform/page.tsx")


# ---- derivation -----------------------------------------------------------

def test_a_clean_change_inside_the_contract(repo):
    base = base_sha(repo)
    _ensure(repo / "api" / "analytics" / "services" / "analytics_engine.py").write_text("def app():\n    '''new'''\n")
    assert boundary.commit_agent_work(repo, "work")
    change = boundary.derive(repo, base)
    assert change.paths == ["api/analytics/services/analytics_engine.py"]
    verdict = boundary.enforce(change, CONTRACT)
    assert verdict.clean
    assert verdict.reasons() == []


def test_editing_the_test_suite_is_caught(repo):
    """The rule the whole track is built on."""
    base = base_sha(repo)
    (repo / "api" / "tests" / "test_thing.py").write_text(
        "def test_x():\n    assert True  # relaxed\n")
    boundary.commit_agent_work(repo, "work")
    change = boundary.derive(repo, base)
    verdict = boundary.enforce(change, CONTRACT)
    assert not verdict.clean
    assert verdict.protected_hits == {"api/tests/test_thing.py": "api/tests/**"}


def test_neutering_the_suite_config_is_caught(repo):
    """Editing pytest.ini rather than a test is the same defeat, one layer
    out. It is on the floor for that reason."""
    base = base_sha(repo)
    (repo / "api" / "pytest.ini").write_text("[pytest]\naddopts = --ignore=api/tests\n")
    boundary.commit_agent_work(repo, "work")
    verdict = boundary.enforce(boundary.derive(repo, base), CONTRACT)
    assert not verdict.clean
    assert "api/pytest.ini" in verdict.protected_hits


def test_adding_a_new_file_to_a_protected_tree_is_caught(repo):
    base = base_sha(repo)
    (repo / "api" / "tests" / "test_new.py").write_text("def test_y():\n    pass\n")
    boundary.commit_agent_work(repo, "work")
    verdict = boundary.enforce(boundary.derive(repo, base), CONTRACT)
    assert "api/tests/test_new.py" in verdict.protected_hits


def test_deleting_a_test_is_caught(repo):
    """The cheapest way to make a suite pass."""
    base = base_sha(repo)
    (repo / "api" / "tests" / "test_thing.py").unlink()
    boundary.commit_agent_work(repo, "work")
    change = boundary.derive(repo, base)
    verdict = boundary.enforce(change, CONTRACT)
    assert change.status["api/tests/test_thing.py"] == "D"
    assert not verdict.clean


def test_moving_a_file_into_a_protected_tree_is_caught(repo):
    """A rename has two sides and both of them count."""
    base = base_sha(repo)
    src = repo / "api" / "services" / "thing.py"
    dst = repo / "api" / "tests" / "thing.py"
    dst.write_text(src.read_text())
    src.unlink()
    boundary.commit_agent_work(repo, "work")
    verdict = boundary.enforce(boundary.derive(repo, base), CONTRACT)
    assert not verdict.clean
    assert any("api/tests/thing.py" == p for p in verdict.protected_hits)


def test_untracked_files_are_not_a_way_out(repo):
    """The agent never commits. The runner does, with `git add -A`, so a file
    the agent simply left on disk is still in the comparison."""
    base = base_sha(repo)
    (repo / "api" / "tests" / "sneaky.py").write_text("# not added\n")
    boundary.commit_agent_work(repo, "work")
    verdict = boundary.enforce(boundary.derive(repo, base), CONTRACT)
    assert "api/tests/sneaky.py" in verdict.protected_hits


def test_a_file_outside_every_writable_path_is_caught(repo):
    """README.md is neither writable nor protected. The contract is the
    statement of what this task was allowed to be."""
    base = base_sha(repo)
    (repo / "README.md").write_text("# readme\n\nrewritten\n")
    boundary.commit_agent_work(repo, "work")
    verdict = boundary.enforce(boundary.derive(repo, base), CONTRACT)
    assert not verdict.clean
    assert verdict.outside_writable == ["README.md"]
    assert verdict.protected_hits == {}


def test_diff_line_limit(repo):
    base = base_sha(repo)
    (repo / "api" / "services" / "thing.py").write_text(
        "\n".join(f"x{i} = {i}" for i in range(500)) + "\n")
    boundary.commit_agent_work(repo, "work")
    verdict = boundary.enforce(boundary.derive(repo, base), CONTRACT)
    assert verdict.over_diff_limit
    assert not verdict.clean


def test_no_change_at_all(repo):
    base = base_sha(repo)
    assert boundary.commit_agent_work(repo, "work") is False
    change = boundary.derive(repo, base)
    assert change.empty
    assert change.head_sha == base


def test_ignored_writes_are_reported_not_punished(repo):
    base = base_sha(repo)
    (repo / "debug.log").write_text("noise\n")
    _ensure(repo / "api" / "analytics" / "services" / "analytics_engine.py").write_text("def app():\n    '''new'''\n")
    boundary.commit_agent_work(repo, "work")
    change = boundary.derive(repo, base)
    assert "debug.log" in change.ignored_writes
    assert "debug.log" not in change.paths
    assert boundary.enforce(change, CONTRACT).clean


# ---- the agent's account is never the input -------------------------------

def test_a_lying_agent_does_not_get_a_clean_boundary(repo):
    """The property the runner exists to have.

    The agent edits the suite and reports that it edited one service file.
    The verdict is derived from git and does not change."""
    base = base_sha(repo)
    (repo / "api" / "tests" / "test_thing.py").write_text("def test_x():\n    pass\n")
    boundary.commit_agent_work(repo, "work")
    change = boundary.derive(repo, base)
    change.reported = ["api/services/thing.py"]      # the agent's story

    verdict = boundary.enforce(change, CONTRACT)
    assert not verdict.clean
    assert "api/tests/test_thing.py" in verdict.protected_hits

    assert change.divergence["touched_but_unclaimed"] == ["api/tests/test_thing.py"]
    assert change.divergence["claimed_but_untouched"] == ["api/services/thing.py"]


def test_an_honest_report_gets_no_credit_either(repo):
    """Symmetry: the report changes nothing in either direction."""
    base = base_sha(repo)
    (repo / "api" / "tests" / "test_thing.py").write_text("def test_x():\n    pass\n")
    boundary.commit_agent_work(repo, "work")
    change = boundary.derive(repo, base)
    honest = boundary.enforce(change, CONTRACT)
    change.reported = ["api/tests/test_thing.py"]
    assert boundary.enforce(change, CONTRACT) == honest


# ---- the suite digest -----------------------------------------------------

def test_suite_digest_is_stable_when_the_suite_does_not_move(repo):
    base = base_sha(repo)
    before = boundary.suite_digest(repo, base, CONTRACT["protected_paths"])
    _ensure(repo / "api" / "analytics" / "services" / "analytics_engine.py").write_text("def app():\n    '''new'''\n")
    boundary.commit_agent_work(repo, "work")
    after = boundary.suite_digest(repo, "HEAD", CONTRACT["protected_paths"])
    assert before == after


def test_suite_digest_moves_when_the_suite_does(repo):
    base = base_sha(repo)
    before = boundary.suite_digest(repo, base, CONTRACT["protected_paths"])
    (repo / "api" / "tests" / "test_thing.py").write_text("def test_x():\n    pass\n")
    boundary.commit_agent_work(repo, "work")
    after = boundary.suite_digest(repo, "HEAD", CONTRACT["protected_paths"])
    assert before != after


# ---- creatable_paths: add is permitted, modify is not ---------------------
#
# specs/unattended-operation.md §3.2. The exception exists so an agent can add
# ONE test; the floor's argument is about modification, and adding a file
# cannot weaken a test that already exists.

def _change(paths_and_status, diff_lines=10):
    from runner.boundary import Change
    c = Change(base_sha="a" * 40, head_sha="b" * 40, diff_lines=diff_lines)
    for p, st in paths_and_status.items():
        c.paths.append(p)
        c.status[p] = st
    c.paths.sort()
    return c


CREATABLE_CONTRACT = {
    "writable_paths": ["api/analytics/routes/orders.py"],
    "protected_paths": ["api/tests/**"],
    "creatable_paths": ["api/tests/analytics/test_fleet_*.py"],
    "max_diff_lines": 400,
}


def test_an_added_creatable_test_is_permitted():
    v = boundary.enforce(
        _change({"api/tests/analytics/test_fleet_28_windows.py": "A"}),
        CREATABLE_CONTRACT)
    assert v.clean, v.reasons()


def test_a_MODIFIED_creatable_test_is_still_refused():
    """The half the floor is actually about: an agent that edits an existing
    test can make it pass."""
    v = boundary.enforce(
        _change({"api/tests/analytics/test_fleet_28_windows.py": "M"}),
        CREATABLE_CONTRACT)
    assert not v.clean
    assert "api/tests/analytics/test_fleet_28_windows.py" in v.protected_hits


def test_a_DELETED_creatable_test_is_still_refused():
    v = boundary.enforce(
        _change({"api/tests/analytics/test_fleet_28_windows.py": "D"}),
        CREATABLE_CONTRACT)
    assert not v.clean


def test_adding_a_test_OUTSIDE_the_creatable_glob_is_refused():
    """`api/tests/**` is protected; only the narrow fleet pattern is excepted."""
    v = boundary.enforce(
        _change({"api/tests/analytics/test_parity.py": "A"}), CREATABLE_CONTRACT)
    assert not v.clean
    assert "api/tests/analytics/test_parity.py" in v.protected_hits


def test_adding_a_conftest_is_refused():
    """A conftest can override fixtures for tests it did not write, which is
    editing the suite by another name."""
    v = boundary.enforce(
        _change({"api/tests/analytics/conftest.py": "A"}), CREATABLE_CONTRACT)
    assert not v.clean


def test_a_contract_with_no_creatable_paths_behaves_exactly_as_before():
    """The exception must be opt-in. Every existing contract has no
    creatable_paths and must be judged identically to before 020."""
    plain = {k: v for k, v in CREATABLE_CONTRACT.items() if k != "creatable_paths"}
    v = boundary.enforce(
        _change({"api/tests/analytics/test_fleet_28_windows.py": "A"}), plain)
    assert not v.clean
    assert v.protected_hits


# ---------------------------------------------------------------------------
# TWO BUDGETS: the production diff and the mandated test are counted apart.
#
# Added 11 Sep 2026. The defect these protect is measured, not hypothetical:
# two dd_api tasks were refused on size whose production halves were well
# inside the limit they broke, because the test `creatable_paths` requires
# them to add came out of the same budget as the change it tests.
#
#   task 62   494 = 300 production + 194 test   refused against 400
#   task 67   459 = 272 production + 187 test   refused against 400
#
# Both are reproduced below at their real figures.
# ---------------------------------------------------------------------------

TEST_GLOB = "api/tests/analytics/test_fleet_*.py"

SPLIT_CONTRACT = {
    "writable_paths": ["api/analytics/services/analytics_engine.py"],
    "protected_paths": ["api/tests/**", "api/pytest.ini", "api/alembic/**"],
    "creatable_paths": [TEST_GLOB],
    "max_diff_lines": 400,
    "max_test_diff_lines": 300,
}


def _write(repo, rel, churn):
    """Write `rel` so the derived diff for it is exactly `churn` lines.

    The runner counts added PLUS deleted, and these fixture files are not
    empty, so replacing one costs its existing length in deletions. The tests
    below assert real figures from real runs, and they are only those figures
    if that is taken off here rather than left to drift.
    """
    p = _ensure(repo / rel)
    existing = len(p.read_text().splitlines()) if p.exists() else 0
    added = churn - existing
    assert added >= 0, f"{rel} is already {existing} lines, over a {churn} budget"
    p.write_text("\n".join(f"x{i} = {i}" for i in range(added))
                 + ("\n" if added else ""))


def _verdict(repo, base, contract):
    boundary.commit_agent_work(repo, "work")
    return boundary.enforce(boundary.derive(repo, base), contract)


def test_the_added_test_does_not_spend_the_production_budget(repo):
    """Task 67's real shape: 272 production + 187 test, against 400 and 300.

    Under one budget this is 459 against 400 and is refused. It is the change
    the split exists for, so it is the first thing asserted about it.
    """
    base = base_sha(repo)
    _write(repo, "api/analytics/services/analytics_engine.py", 272)
    _write(repo, "api/tests/analytics/test_fleet_orders_export.py", 187)
    verdict = _verdict(repo, base, SPLIT_CONTRACT)

    assert verdict.prod_diff_lines == 272
    assert verdict.test_diff_lines == 187
    assert verdict.diff_lines == 459, "the recorded total still means the total"
    assert not verdict.over_diff_limit
    assert not verdict.over_test_limit
    assert verdict.clean


def test_task_62s_shape_also_passes(repo):
    """494 = 300 + 194. The other run refused by the single budget."""
    base = base_sha(repo)
    _write(repo, "api/analytics/services/analytics_engine.py", 300)
    _write(repo, "api/tests/analytics/test_fleet_ltv.py", 194)
    verdict = _verdict(repo, base, SPLIT_CONTRACT)
    assert (verdict.prod_diff_lines, verdict.test_diff_lines) == (300, 194)
    assert verdict.clean


def test_the_same_two_changes_are_refused_without_an_allowance(repo):
    """The broken state, demonstrated rather than described.

    Same diff, same 400, and the only difference is that the contract does not
    budget for the test it mandates. If this ever stops failing, the split
    above is no longer doing anything and its passes mean nothing.
    """
    base = base_sha(repo)
    _write(repo, "api/analytics/services/analytics_engine.py", 272)
    _write(repo, "api/tests/analytics/test_fleet_orders_export.py", 187)
    no_allowance = {k: v for k, v in SPLIT_CONTRACT.items()
                    if k != "max_test_diff_lines"}
    verdict = _verdict(repo, base, no_allowance)

    assert verdict.over_diff_limit
    assert not verdict.clean
    assert verdict.prod_diff_lines == 459, "with no allowance, all of it is production"
    assert verdict.test_diff_lines == 0


def test_an_oversized_production_diff_is_still_refused(repo):
    """The split widens one budget; it does not remove the other."""
    base = base_sha(repo)
    _write(repo, "api/analytics/services/analytics_engine.py", 401)
    verdict = _verdict(repo, base, SPLIT_CONTRACT)
    assert verdict.over_diff_limit
    assert not verdict.clean
    assert "401 changed lines outside the added test exceeds the contract's 400" \
        in verdict.reasons()


def test_an_oversized_test_is_refused_on_its_own_budget(repo):
    """A ceiling that cannot fire is not a ceiling. 301 against 300."""
    base = base_sha(repo)
    _write(repo, "api/analytics/services/analytics_engine.py", 10)
    _write(repo, "api/tests/analytics/test_fleet_huge.py", 301)
    verdict = _verdict(repo, base, SPLIT_CONTRACT)
    assert verdict.over_test_limit
    assert not verdict.over_diff_limit
    assert not verdict.clean
    assert "301 lines of added test exceeds the contract's 300" in verdict.reasons()


class TestSizeOnlyIsSeparableFromTheRest:
    """Which refusals can still have their checks believed.

    Verification is skipped on a boundary violation because a change that
    touched a protected path may have touched the SUITE. That argument covers
    exactly the protected and outside-writable cases and nothing else -- a
    diff that is merely too long was admitted path by path, so its checks mean
    what they always mean. runner/cycle.tick reads this to decide whether to
    collect the evidence before refusing; see Boundary.size_only for what task
    69 paid to establish the difference.
    """

    def test_too_much_production_is_size_only(self, repo):
        base = base_sha(repo)
        _write(repo, "api/analytics/services/analytics_engine.py", 401)
        verdict = _verdict(repo, base, SPLIT_CONTRACT)
        assert verdict.over_diff_limit and not verdict.clean
        assert verdict.size_only

    def test_too_much_test_is_size_only(self, repo):
        base = base_sha(repo)
        _write(repo, "api/analytics/services/analytics_engine.py", 10)
        _write(repo, "api/tests/analytics/test_fleet_huge.py", 301)
        verdict = _verdict(repo, base, SPLIT_CONTRACT)
        assert verdict.over_test_limit and not verdict.clean
        assert verdict.size_only

    def test_a_protected_path_is_not(self, repo):
        base = base_sha(repo)
        _write(repo, "api/pytest.ini", 3)
        verdict = _verdict(repo, base, SPLIT_CONTRACT)
        assert verdict.protected_hits
        assert not verdict.size_only

    def test_a_path_outside_the_contract_is_not(self, repo):
        base = base_sha(repo)
        _write(repo, "README.md", 3)
        verdict = _verdict(repo, base, SPLIT_CONTRACT)
        assert verdict.outside_writable
        assert not verdict.size_only

    def test_oversized_AND_protected_is_not(self, repo):
        """The combination is the one that matters: length is forgivable
        enough to run the checks, and the suite being touched is not, so the
        pair has to land on the stricter side."""
        base = base_sha(repo)
        _write(repo, "api/analytics/services/analytics_engine.py", 401)
        _write(repo, "api/pytest.ini", 3)
        verdict = _verdict(repo, base, SPLIT_CONTRACT)
        assert verdict.over_diff_limit and verdict.protected_hits
        assert not verdict.size_only

    def test_a_clean_verdict_is_not_size_only_either(self, repo):
        """Nothing is wrong with it, so there is no refusal to qualify."""
        base = base_sha(repo)
        _write(repo, "api/analytics/services/analytics_engine.py", 10)
        verdict = _verdict(repo, base, SPLIT_CONTRACT)
        assert verdict.clean
        assert not verdict.size_only


def test_a_modified_test_is_not_an_added_one(repo):
    """creatable_paths is ADD-only, and the split follows it exactly.

    A test that already exists is protected, and editing one must not buy the
    change a second budget to hide production lines in.
    """
    base = base_sha(repo)
    existing = _ensure(repo / "api/tests/analytics/test_fleet_existing.py")
    existing.write_text("x = 1\n")
    run(repo, "git", "add", "-A")
    run(repo, "git", "-c", "user.email=t@t", "-c", "user.name=t",
        "commit", "-m", "the test already exists")
    base = base_sha(repo)

    existing.write_text("\n".join(f"y{i} = {i}" for i in range(50)) + "\n")
    verdict = _verdict(repo, base, SPLIT_CONTRACT)

    assert verdict.test_diff_lines == 0, "modifying a test buys no allowance"
    assert "api/tests/analytics/test_fleet_existing.py" in verdict.protected_hits
    assert not verdict.clean


def test_a_contract_with_no_allowance_behaves_exactly_as_before(repo):
    """Every contract without creatable_paths is unchanged by all of this.

    CONTRACT has no creatable_paths and a limit of 100. The message is the one
    this check has always printed, word for word.
    """
    base = base_sha(repo)
    _write(repo, "api/analytics/services/analytics_engine.py", 101)
    verdict = _verdict(repo, base, CONTRACT)
    assert verdict.over_diff_limit
    assert verdict.test_diff_lines == 0
    assert verdict.prod_diff_lines == verdict.diff_lines == 101
    assert "101 changed lines exceeds the contract's 100" in verdict.reasons()


def test_a_contract_mandating_a_test_must_budget_for_it(tmp_path):
    """config.load_contract refuses creatable_paths with no allowance.

    This is the defect made unrepeatable rather than merely fixed. Granting
    the permission without the budget is exactly the state the api contract
    was in between 9 and 11 Sep 2026, and it cost two runs that had already
    been paid for before anyone saw it.
    """
    import yaml

    from runner import config

    base = yaml.safe_load(
        Path("contracts/deadly-digital-platform-api.yaml").read_text())
    assert base["creatable_paths"] and base["max_test_diff_lines"], \
        "the fixture is only meaningful if the real contract declares both"

    del base["max_test_diff_lines"]
    p = tmp_path / "broken.yaml"
    p.write_text(yaml.safe_dump(base))
    with pytest.raises(RuntimeError, match="max_test_diff_lines"):
        config.load_contract(base["repo"], p)


def test_a_contract_mandating_a_test_must_state_the_figure_it_tells(tmp_path):
    """And the target, which is the half the agent actually sees.

    12 Sep 2026: max_test_diff_lines became a runaway bound at 1200 and stopped
    being the number in the prompt. A contract that mandates a test without a
    test_diff_target sends the agent at 75% of the bound -- 900 lines, three
    times the figure anyone wants -- which is the same class of silent defect
    as the rule above and is refused in the same place.
    """
    import yaml

    from runner import config

    base = yaml.safe_load(
        Path("contracts/deadly-digital-platform-api.yaml").read_text())
    assert base["creatable_paths"] and base["test_diff_target"], \
        "the fixture is only meaningful if the real contract declares both"
    assert base["test_diff_target"] < base["max_test_diff_lines"], \
        "the told figure has to sit under the bound or there is no gap at all"

    del base["test_diff_target"]
    p = tmp_path / "no-target.yaml"
    p.write_text(yaml.safe_dump(base))
    with pytest.raises(RuntimeError, match="test_diff_target"):
        config.load_contract(base["repo"], p)


def test_every_real_contract_still_loads():
    """A whole-file assertion, because the rule above can refuse one of ours.

    Reads the real contracts rather than a fixture: conftest's rule is that a
    test about a ceiling reads the artefact that decides.
    """
    import yaml

    from runner import config

    for path in sorted(Path("contracts").glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        config.load_contract(data["repo"], path)
