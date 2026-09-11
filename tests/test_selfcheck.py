"""The gate, made reachable during the run — and capped.

Three draft specs died at draft_spec_shape.py for the same reason. The
diagnosis that shaped this file: of the six paths that failed, **five were
files the spec proposed to create** and three of those were declared writable
in the same document and accepted there. One rule for a declared path and a
stricter one for the identical string in prose.

So there are two halves here:

  * the check stops contradicting itself, and names an abbreviation as an
    abbreviation instead of as a path that resolves nowhere
  * the check becomes runnable by the agent, CAPPED at three, with every
    invocation recorded — because an agent that can run the gate without
    limit can mutate paths until it goes green, which passes without
    establishing anything
"""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

FLEET = Path.home() / "fleet"
PLATFORM = Path.home() / "deadly-digital-platform"
CHECK = FLEET / "contracts" / "checks" / "draft_spec_shape.py"
SELFCHECK = FLEET / "contracts" / "checks" / "spec_selfcheck.sh"
PY = FLEET / ".venv" / "bin" / "python"


#: The widest contract for each work_type these fixtures use. NAMED, since
#: specs/auto-approval.md §14 made `contract` a required field: the check no
#: longer derives it, so a fixture without one fails on the missing field and
#: every test here would assert on that message instead of on path judging.
#: The wide contract is chosen so the fixtures' paths are covered — these
#: tests are about how paths are judged, not about which boundary is right.
CONTRACT_FOR = {"dd_api": "deadly-digital-platform-api.yaml",
                "dd_frontend": "dd-analytics-frontend.yaml"}


def _with_contract(body: str) -> str:
    """Add `contract:` to a fleet-spec block that has none."""
    import re as _re
    m = _re.search(r"```fleet-spec\s*\n(.*?)\n```", body, _re.S)
    if not m:
        return body
    block = yaml.safe_load(m.group(1)) or {}
    if block.get("contract") or not block.get("work_type"):
        return body
    named = CONTRACT_FOR.get(str(block["work_type"]))
    if not named:
        return body
    return (body[:m.start(1)] + yaml.safe_dump({**block, "contract": named}).rstrip()
            + body[m.end(1):])


def spec(writable, prose_paths, work_type="dd_api", contract=None):
    fields = {
        "work_type": work_type, "repo": "deadly-digital-platform",
        "title": "A spec", "writable_paths": writable}
    named = contract if contract is not None else CONTRACT_FOR.get(work_type)
    if named:
        fields["contract"] = named
    block = yaml.safe_dump(fields)
    prose = "\n".join(f"- `{p}` does the thing" for p in prose_paths)
    # NOT textwrap.dedent. The block is interpolated before dedent runs, so
    # only its FIRST line carries the template's indent and the rest sit at
    # column 0 -- dedent then finds a common prefix of zero, strips nothing,
    # and the YAML is invalid in a way that looks like the check's fault.
    # `### 1. ...` IS NOT DECORATION. draft_spec_shape rule 7 refuses a draft
    # that numbers no requirements (specs/auto-approval.md §9.12 step 1), so
    # a fixture without one fails for a reason that has nothing to do with
    # what these tests are about -- and every test here would then be
    # asserting on the numbering message instead of on path judging.
    return ("# A spec\n\n```fleet-spec\n" + block + "```\n\n"
            "### 1. The change\n\n"
            + prose + "\n\nProse enough to be a document, describing what the\n"
            "change does and why it is worth making, at some length.\n")


def run_check(tmp_path, text, name="drafts/a-spec.md"):
    doc = tmp_path / name
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(text)
    r = subprocess.run((str(PY), str(CHECK)), cwd=tmp_path,
                       env={**os.environ, "FLEET_CHANGED_FILES": name},
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# ---- the check no longer contradicts itself --------------------------------

class TestProseAndDeclaredPathsAreJudgedTheSameWay:

    def test_a_file_the_spec_will_create_passes_in_prose(self, tmp_path):
        """THE BUG THAT KILLED TASK 23.

        It declared a to-be-created path writable, the check
        accepted it there, and then failed the identical string for being in
        the prose. £1.93 for nothing the agent did wrong.
        """
        # UNDER THE FRONTEND CONTRACT, since §14 made the check verify that
        # the declared contract covers the declared paths. The api contract's
        # writable_paths are an explicit list of existing files, so NO new file
        # is inside it — a created file there is only ever a test, via
        # creatable_paths, which is not declared writable. The frontend
        # contract's paths are globs, so a new file under one is covered. What
        # these tests are about — prose and declared paths judged the same way
        # — is unchanged.
        new = "platform/app/(dashboard)/analytics/customers/ltv-panel.tsx"
        assert not (PLATFORM / new).exists()
        code, out = run_check(tmp_path, spec([new], [new],
                                             work_type="dd_frontend"))
        assert code == 0, out

    def test_the_same_string_declared_and_cited_cannot_disagree(self, tmp_path):
        new = "platform/app/(dashboard)/analytics/customers/ltv-panel.tsx"
        declared_only = run_check(tmp_path, spec([new], [],
                                                  work_type="dd_frontend"))[0]
        also_cited = run_check(tmp_path, spec([new], [new],
                                              work_type="dd_frontend"))[0]
        assert declared_only == also_cited == 0

    def test_a_new_file_in_a_directory_that_does_not_exist_still_fails(
            self, tmp_path):
        code, out = run_check(tmp_path, spec(
            ["api/analytics/routes/orders.py"], ["api/nowhere/at/all/thing.py"]))
        assert code == 1
        assert "whose directory does not either" in out

    def test_an_existing_path_passes(self, tmp_path):
        code, out = run_check(tmp_path, spec(
            ["api/analytics/routes/orders.py"],
            ["api/analytics/routes/orders.py"]))
        assert code == 0, out


class TestAnAbbreviationIsNamedAsOne:

    def test_it_says_which_path_was_meant(self, tmp_path):
        """THE ONE REAL ERROR IN THE THREE FAILURES.

        `routes/orders.py` is not a path; the same document declared
        `api/analytics/routes/orders.py` correctly. Recall, not knowledge — so
        the message supplies the thing that was not recalled.
        """
        code, out = run_check(tmp_path, spec(
            ["api/analytics/routes/orders.py"], ["routes/orders.py"]))
        assert code == 1
        assert "abbreviated" in out
        assert "routes/orders.py -> api/analytics/routes/orders.py" in out

    def test_an_abbreviation_of_a_file_nobody_has_is_not_called_one(
            self, tmp_path):
        code, out = run_check(tmp_path, spec(
            ["api/analytics/routes/orders.py"], ["routes/payments.py"]))
        assert code == 1
        assert "do not exist" in out


class TestReplayingTheThreeRealFailures:
    """Measured, not assumed. The branches are still in the repository."""

    @staticmethod
    def draft(task: int) -> tuple[str, str]:
        name = subprocess.run(
            ("git", "-C", str(FLEET), "show", f"fleet/task-{task}",
             "--stat", "--format="), capture_output=True, text=True).stdout
        rel = next(t for t in name.split() if t.startswith("drafts/"))
        body = subprocess.run(("git", "-C", str(FLEET), "show",
                               f"fleet/task-{task}:{rel}"),
                              capture_output=True, text=True).stdout
        # THE HISTORICAL DRAFTS PREDATE `contract`, WHICH §14 MADE REQUIRED.
        #
        # These three replay real documents to prove the PATH rules behave as
        # recorded; they are not about the contract field, and they can never
        # grow one — the branches are frozen history. So the fixture supplies
        # it, choosing by work_type exactly as the old derivation would have,
        # which keeps each test asserting on the thing it was written for.
        return rel, _with_contract(body)

    def test_task_23_is_refused_for_coverage_not_for_its_paths(self, tmp_path):
        """CHANGED 11 Sep 2026, and the new answer is the truer one.

        This asserted `code == 0` — task 23's draft passing the path rules
        after they were unified. It still passes those, but §14 added an
        earlier question: does the declared contract make the declared paths
        writable? It does not. `api/analytics/routes/coupons.py` and
        `api/analytics/services/coupon_report.py` are in no contract's writable
        set, so this draft could never have been queued whatever the path rules
        said — `autoqueue` would have refused it after the draft was paid for.

        Task 23 FAILED and was abandoned on 11 Sep. This is the check telling
        it so at draft time instead.
        """
        rel, body = self.draft(23)
        code, out = run_check(tmp_path, body, name=rel)
        assert code == 1
        assert "does not make" in out
        assert "No contract for this work_type and repo covers all of them" in out

    def test_task_24_is_refused_for_coverage_before_its_paths_are_judged(
            self, tmp_path):
        """CHANGED 11 Sep 2026, same reason as task 23's.

        This asserted the refusal named `routes/categories.py` and NOT
        `category_report.py`, which was the point of unifying rules 3 and 6: a
        file the spec intends to create is legitimate. Both remain true of the
        path rules, and neither is reached, because §14 asks first whether the
        declared contract covers the declared paths — and
        `api/analytics/services/category_report.py` is in no contract's
        writable set.

        That is the earlier and more useful refusal: a legitimate new file is
        still not one this contract may write, and no amount of correct path
        spelling changes that. Task 24 FAILED and was abandoned on 11 Sep.
        """
        rel, body = self.draft(24)
        code, out = run_check(tmp_path, body, name=rel)
        assert code == 1
        assert "category_report.py" in out
        assert "does not make" in out

    def test_task_25_still_fails_and_names_the_correction(self, tmp_path):
        rel, body = self.draft(25)
        code, out = run_check(tmp_path, body, name=rel)
        assert code == 1
        assert "routes/orders.py -> api/analytics/routes/orders.py" in out


# ---- the cap ---------------------------------------------------------------

class TestTheSelfCheckIsCapped:

    @staticmethod
    def harness(tmp_path, cap="3"):
        subprocess.run(("git", "init", "-q"), cwd=tmp_path)
        (tmp_path / "drafts").mkdir()
        (tmp_path / "drafts" / "a-spec.md").write_text(
            spec(["api/analytics/routes/orders.py"], ["routes/orders.py"]))
        state = tmp_path.parent / f"state-{tmp_path.name}.log"
        env = {**os.environ,
               "FLEET_SELFCHECK_STATE": str(state),
               "FLEET_SELFCHECK_MAX": cap,
               "FLEET_SELFCHECK_COMMAND": f"{PY} {CHECK}"}
        return env, state

    def run(self, tmp_path, env):
        return subprocess.run((str(SELFCHECK),), cwd=tmp_path, env=env,
                              capture_output=True, text=True)

    def test_it_reproduces_the_gate_exactly(self, tmp_path):
        env, _ = self.harness(tmp_path)
        r = self.run(tmp_path, env)
        assert r.returncode == 1
        assert "routes/orders.py -> api/analytics/routes/orders.py" in r.stdout

    def test_the_fourth_invocation_is_refused(self, tmp_path):
        env, _ = self.harness(tmp_path)
        for _ in range(3):
            assert self.run(tmp_path, env).returncode == 1
        r = self.run(tmp_path, env)
        assert r.returncode == 3
        assert "used all 3 self-checks" in r.stdout

    def test_the_cap_is_configuration_not_a_literal(self, tmp_path):
        env, _ = self.harness(tmp_path, cap="1")
        assert self.run(tmp_path, env).returncode == 1
        assert self.run(tmp_path, env).returncode == 3

    def test_every_invocation_is_recorded(self, tmp_path):
        env, state = self.harness(tmp_path)
        self.run(tmp_path, env)
        self.run(tmp_path, env)
        from runner.packs import read_selfcheck
        runs = read_selfcheck(str(state))
        assert [r["n"] for r in runs] == [1, 2]
        assert all(r["exit_code"] == 1 for r in runs)
        assert "abbreviated" in runs[0]["output"]

    def test_an_untracked_file_is_seen(self, tmp_path):
        """`git status --porcelain` collapses an untracked DIRECTORY to
        `drafts/`, and the check then reported "no markdown file in the diff"
        about a diff containing exactly one. -uall is why that works."""
        env, _ = self.harness(tmp_path)
        r = self.run(tmp_path, env)
        assert "drafts/a-spec.md" in r.stdout
        assert "no markdown file" not in r.stdout


# ---- the paths pack --------------------------------------------------------

class TestThePathsPackIsGatedOnCapability:
    """A listing follows the READ-ONLY TREE, not the work type.

    Gating on a label means a future contract that adds a read-only worktree
    gets nothing until somebody remembers to add its name to a list. Gating on
    the capability means it is covered the moment it has one -- and a listing
    of a tree the agent may already read grants nothing new.
    """

    def test_readable_repos_grants_a_listing(self, tmp_path):
        from runner.packs import read_only_trees
        trees = read_only_trees(
            {"readable_repos": ["deadly-digital-platform"]}, Path.home())
        assert set(trees) == {"deadly-digital-platform"}

    def test_a_worktree_link_to_a_checkout_grants_one_too(self, tmp_path):
        from runner.packs import read_only_trees
        trees = read_only_trees(
            {"worktree_links": {"reference/x": str(PLATFORM)}}, Path.home())
        assert set(trees) == {"deadly-digital-platform"}

    def test_a_link_to_something_that_is_not_a_repo_does_not(self, tmp_path):
        from runner.packs import read_only_trees
        (tmp_path / "node_modules").mkdir()
        trees = read_only_trees(
            {"worktree_links": {"node_modules": str(tmp_path / "node_modules")}},
            Path.home())
        assert trees == {}

    def test_a_contract_with_no_read_only_tree_gets_nothing(self, tmp_path):
        from runner.packs import write_paths_pack
        assert write_paths_pack(tmp_path, {}, Path.home()) == (None, 0)

    def test_the_real_draft_spec_contract_is_covered_without_a_new_key(self):
        """It declares no readable_repos -- the capability comes from its
        existing worktree_links, which is the point."""
        from runner.packs import read_only_trees
        c = yaml.safe_load((FLEET / "contracts" / "draft-spec.yaml").read_text())
        assert c.get("readable_repos") is None
        assert set(read_only_trees(c, Path.home())) == {"deadly-digital-platform"}


class TestThePathsPackIsGeneratedNotCommitted:

    def test_it_lists_real_files_and_says_how_to_cite_them(self, tmp_path):
        from runner.packs import write_paths_pack
        out, n = write_paths_pack(tmp_path, {
            "readable_repos": ["deadly-digital-platform"],
            "paths_pack": {"roots": ["api/analytics/routes"]}}, Path.home())
        text = out.read_text()
        assert n > 5
        assert "api/analytics/routes/orders.py" in text
        assert "IN FULL from the repository root" in text

    def test_it_is_written_outside_the_worktree(self, tmp_path):
        """Inside it, the file lands in the derived diff and the boundary
        refuses it -- the trap the evidence pack solved by committing, which
        is the option ruled out here."""
        from runner.packs import write_paths_pack
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        packs = tmp_path / "worktree-packs"
        out, _ = write_paths_pack(packs, {
            "readable_repos": ["deadly-digital-platform"],
            "paths_pack": {"roots": ["api/analytics/routes"]}}, Path.home())
        assert worktree not in out.parents
        assert list(worktree.iterdir()) == []

    def test_the_runner_removes_it_with_the_worktree(self):
        """A listing that outlived its run would be a figure nothing
        re-derives, which is the shape this replaced."""
        src = (FLEET / "runner" / "cycle.py").read_text()
        assert "shutil.rmtree(packs_dir" in src
        assert "worktree.remove(repo, wt_path)" in src

    def test_it_is_not_committed(self):
        """A committed listing of both trees is readable by every later task,
        including ones whose contract makes that repository writable."""
        src = (FLEET / "runner" / "cycle.py").read_text()
        commit_block = src[src.index("boundary.commit_agent_work("):][:400]
        assert "paths" not in commit_block.lower()


class TestTheSelfCheckEnvironment:

    def test_the_command_is_the_contracts_own_verification(self):
        from runner.packs import selfcheck_env
        env = selfcheck_env({"self_check": True,
                             "verification": ["/bin/true", "/bin/false"]})
        assert env["FLEET_SELFCHECK_COMMAND"] == "/bin/true"
        assert env["FLEET_SELFCHECK_MAX"] == "3"

    def test_a_contract_that_does_not_ask_for_it_gets_nothing(self):
        from runner.packs import selfcheck_env
        assert selfcheck_env({"verification": ["/bin/true"]}) == {}

    def test_the_state_file_is_outside_the_worktree(self, tmp_path):
        """Inside it, every invocation writes a file the boundary refuses --
        so the act of checking would fail the branch."""
        from runner.packs import selfcheck_env
        env = selfcheck_env({"self_check": True, "verification": ["/bin/true"]})
        assert not str(env["FLEET_SELFCHECK_STATE"]).startswith(str(tmp_path))
        assert str(env["FLEET_SELFCHECK_STATE"]).startswith("/tmp")


class TestTheContractSaysAllOfThis:

    def test_draft_spec_declares_a_scoped_bash_and_nothing_wider(self):
        c = yaml.safe_load((FLEET / "contracts" / "draft-spec.yaml").read_text())
        bash = [t for t in c["agent_tools"] if t.startswith("Bash")]
        assert bash == ["Bash(/home/ubuntu/fleet/contracts/checks/spec_selfcheck.sh)"]
        assert "Bash" not in c["agent_tools"]        # not the bare tool

    def test_the_script_it_may_run_is_protected(self):
        c = yaml.safe_load((FLEET / "contracts" / "draft-spec.yaml").read_text())
        assert "contracts/**" in c["protected_paths"]

    def test_the_cap_is_in_the_contract(self):
        c = yaml.safe_load((FLEET / "contracts" / "draft-spec.yaml").read_text())
        assert c["self_check"] is True and c["self_check_max"] == 3


class TestTheSameShapeGuard:
    """A path in run N absent from run N-1 was introduced, not uncovered.

    The check reports every unresolved path at once, so fixing one cannot
    reveal another. A new one means the agent tried a different spelling.
    """

    @staticmethod
    def write(tmp_path, cited):
        (tmp_path / "drafts").mkdir(exist_ok=True)
        (tmp_path / "drafts" / "a-spec.md").write_text(
            spec(["api/analytics/routes/orders.py"], [cited]))

    def harness(self, tmp_path):
        subprocess.run(("git", "init", "-q"), cwd=tmp_path)
        state = tmp_path.parent / f"shape-{tmp_path.name}.log"
        return {**os.environ, "FLEET_SELFCHECK_STATE": str(state),
                "FLEET_SELFCHECK_MAX": "3",
                "FLEET_SELFCHECK_COMMAND": f"{PY} {CHECK}"}, state

    def run(self, tmp_path, env):
        return subprocess.run((str(SELFCHECK),), cwd=tmp_path, env=env,
                              capture_output=True, text=True)

    def test_a_new_offending_path_warns(self, tmp_path):
        env, state = self.harness(tmp_path)
        self.write(tmp_path, "routes/orders.py")
        self.run(tmp_path, env)
        self.write(tmp_path, "routes/payments.py")     # a different spelling
        r = self.run(tmp_path, env)
        assert "WARNING" in r.stdout and "names a path the previous run did not" in r.stdout

        from runner.packs import read_selfcheck
        runs = read_selfcheck(str(state))
        assert runs[0]["shape_changed"] is False
        assert runs[1]["shape_changed"] is True

    def test_the_same_failure_twice_does_not_warn(self, tmp_path):
        env, state = self.harness(tmp_path)
        self.write(tmp_path, "routes/orders.py")
        self.run(tmp_path, env)
        r = self.run(tmp_path, env)
        assert "WARNING" not in r.stdout
        from runner.packs import read_selfcheck
        assert all(not x["shape_changed"] for x in read_selfcheck(str(state)))

    def test_it_warns_rather_than_refusing(self, tmp_path):
        """The terminal check enforces correctness. This only makes the
        mutation visible -- refusing would block a legitimate rewrite."""
        env, _ = self.harness(tmp_path)
        self.write(tmp_path, "routes/orders.py")
        self.run(tmp_path, env)
        self.write(tmp_path, "routes/payments.py")
        r = self.run(tmp_path, env)
        assert r.returncode == 1        # the check's verdict, not a refusal
