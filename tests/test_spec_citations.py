"""The marker convention: every numbered requirement is cited in the diff.

specs/auto-approval.md §9.12, built 10 Sep 2026 after `draft_spec` came off
console/automerge.NEVER_UNATTENDED and `fleet-automerge` came off --dry-run.
§9.12 rejected it on the grounds that "on the frontend contract, where a
person already reads the spec, it adds annotation cost for a check weaker
than the reader it sits beside". There is no reader left for it to be weaker
than.

THESE TESTS RUN THE CHECK AS THE RUNNER RUNS IT -- a real git repository, a
real diff, environment facts, exit codes -- rather than importing a function
out of it. The check IS a subprocess contract: exit 0, 1 and 2 mean three
different things to runner/verify.py and to console/automerge.py, and a test
that called main() would not be testing the thing that gets run.

AND THE FIXTURE IS THE REAL CONTRACT SHAPE WHERE IT MATTERS. The first
version of test_automerge's draft-spec test passed while the real path could
not have worked, because the fixture contract carried `creatable_paths` that
contracts/draft-spec.yaml does not. Anything here that asserts about a
contract reads the yaml off disk.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

FLEET = Path("/home/ubuntu/fleet")
CHECK = FLEET / "contracts/checks/spec_requirements_cited.py"
PYTHON = FLEET / ".venv/bin/python"

SPEC = """
### 1. The proxy forwards the four parameters

Words about the proxy.

### 2. The page sends them

**2.1 has_discount is three-state, not a checkbox.** Words.

**2.5 The table cells set the filters.** Words.

### 3. Clearing
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(("git", "-C", str(repo)) + args,
                          capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", ".")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "page.tsx").write_text("const a = 1;\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


def run(repo: Path, added: str, spec: str | None = SPEC,
        base: str | None = None):
    """Add `added` as a commit and run the check the way the runner does."""
    (repo / "page.tsx").write_text("const a = 1;\n" + added)
    before = _git(repo, "rev-parse", "HEAD")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    env = dict(os.environ)
    env.pop("FLEET_SPEC_MD", None)
    env.pop("FLEET_BASE_SHA", None)
    if spec is not None:
        env["FLEET_SPEC_MD"] = spec
    if base is not False:
        env["FLEET_BASE_SHA"] = base or before
    return subprocess.run([str(PYTHON), str(CHECK)], cwd=repo, env=env,
                          capture_output=True, text=True)


# ---- what it refuses ------------------------------------------------------


def test_a_requirement_cited_nowhere_refuses(repo):
    r = run(repo, "// spec:1 forwards them\n")
    assert r.returncode == 1
    assert "2.1" in r.stdout and "2.5" in r.stdout and "3" in r.stdout


def test_the_refusal_says_a_claim_is_not_an_implementation(repo):
    """The message is the only place the agent learns what the token means,
    and a token written over work that was not done is worse than none."""
    r = run(repo, "const b = 2;\n")
    assert "NOT THAT IT WAS MET" in r.stdout
    assert "Do not cite a requirement you did not implement." in r.stdout


def test_a_token_already_in_the_tree_does_not_count(repo):
    """Added lines only. On a parity push consecutive tasks touch the same
    files, so inheriting a predecessor's citations is not hypothetical."""
    (repo / "page.tsx").write_text(
        "const a = 1;\n// spec:1 spec:2.1 spec:2.5 spec:3\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "citations land first")
    r = run(repo, "const unrelated = 3;\n")
    assert r.returncode == 1
    assert "4 of 4" in r.stdout or "cited nowhere" in r.stdout


def test_a_longer_id_does_not_satisfy_a_shorter_one(repo):
    r = run(repo, "// spec:2.50 spec:1 spec:3 spec:2.1\n")
    assert r.returncode == 1
    assert "2.5  The table cells" in r.stdout


# ---- what it accepts ------------------------------------------------------


def test_every_leaf_cited_passes(repo):
    r = run(repo, "// spec:1\n// spec:2.1\n// spec:2.5\n/** spec:3 */\n")
    assert r.returncode == 0, r.stdout
    assert "does not establish that any of them was implemented" in r.stdout


def test_a_parent_is_carried_by_a_cited_child(repo):
    """`### 2. The page sends them` has no content of its own. Demanding a
    token for it teaches the agent to sprinkle tokens rather than mean them."""
    r = run(repo, "// spec:1\n// spec:2.1\n// spec:2.5\n// spec:3\n")
    assert r.returncode == 0
    assert "2  The page sends them" not in r.stdout


def test_a_parent_with_no_cited_child_is_still_missing(repo):
    r = run(repo, "// spec:1\n// spec:3\n")
    assert r.returncode == 1
    assert "2.1" in r.stdout and "2.5" in r.stdout


def test_case_does_not_matter(repo):
    r = run(repo, "// SPEC:1\n// Spec:2.1\n// spec:2.5\n// spec:3\n")
    assert r.returncode == 0, r.stdout


# ---- what it reports as could-not-run, never as a pass --------------------


def test_a_spec_that_numbers_nothing_is_could_not_run(repo):
    """Not a pass. A check that cannot fail sits in the verification list
    looking like a gate."""
    r = run(repo, "// nothing\n", spec="Just some prose about the work.")
    assert r.returncode == 2
    assert "never as a pass" in r.stdout


def test_a_missing_spec_fact_is_could_not_run(repo):
    r = run(repo, "// spec:1\n", spec=None)
    assert r.returncode == 2
    assert "FLEET_SPEC_MD" in r.stdout


def test_a_missing_base_sha_is_could_not_run(repo):
    r = run(repo, "// spec:1\n", base=False)
    assert r.returncode == 2
    assert "FLEET_BASE_SHA" in r.stdout


# ---- it would have caught the thing it was written for --------------------


def test_it_refuses_task_53s_real_diff_against_task_53s_real_spec():
    """§9.12 claims "It would have failed task 53". Asserted rather than
    quoted: the spec is the one on the task row, the diff is the one that
    merged, and the requirement that was never implemented is §2.5.

    Skipped rather than failed when the platform checkout does not carry
    those commits -- a machine without them cannot answer this, which is not
    the same as the claim being false.
    """
    platform = Path("/home/ubuntu/deadly-digital-platform")
    base = "a5cf98ecc48899a7830bcd59fab27db993c6c783"
    head = "2d51cfd4d3801a0ce033c95f256673731388c509"
    if not (platform / ".git").exists():
        pytest.skip("no platform checkout on this host")
    for sha in (base, head):
        if subprocess.run(["git", "-C", str(platform), "cat-file", "-e", sha],
                          capture_output=True).returncode:
            pytest.skip(f"{sha[:12]} is not in this checkout")

    from console import db
    row = db.one("SELECT spec_md FROM tasks WHERE id = 53")
    if not row:
        pytest.skip("task 53 is not in this database")

    out = subprocess.run(
        ["git", "-C", str(platform), "diff", "--unified=0", f"{base}..{head}"],
        capture_output=True, text=True, check=True).stdout
    added = [ln for ln in out.splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]

    import sys
    sys.path.insert(0, str(FLEET / "contracts/checks"))
    import spec_requirements_cited as chk
    from console import requirements

    reqs = requirements.parse(row["spec_md"])
    assert len(reqs) == 8, "task 53's spec numbers eight requirements"
    cited = [q.id for q in reqs
             if any(chk.token(q.id).search(ln) for ln in added)]
    assert cited == [], f"expected none cited, got {cited}"


# ---- the convention holds together ----------------------------------------


class TestTheGateAndTheContractsAgree:
    def test_the_contracts_that_merge_unattended_run_it(self):
        """dd_frontend and dd_api are the two with `auto_merge: true` and no
        reader. If a third gets one, it needs this too."""
        for name in ("dd-analytics-frontend.yaml",
                     "deadly-digital-platform-api.yaml"):
            data = yaml.safe_load((FLEET / "contracts" / name).read_text())
            assert any("spec_requirements_cited.py" in c
                       for c in data["verification"]), name

    def test_it_runs_first_because_it_is_the_cheapest(self):
        """dd-analytics-frontend's own argument: task 55 spent 107 seconds of
        tsc and vitest to be failed by a check that could have answered in
        under a second."""
        for name in ("dd-analytics-frontend.yaml",
                     "deadly-digital-platform-api.yaml"):
            data = yaml.safe_load((FLEET / "contracts" / name).read_text())
            assert "spec_requirements_cited.py" in data["verification"][0], name


class TestTheDraftStageGuaranteesNumbering:
    """The citation gate reports could-not-run against a spec that numbers
    nothing, so a spec-writer that stopped numbering would turn it off. Rule 7
    of draft_spec_shape.py is what stops that."""

    def _shape(self, tmp_path, body: str):
        draft = FLEET / "drafts" / "test_fleet_numbering_probe.md"
        draft.write_text(body)
        try:
            return subprocess.run(
                [str(PYTHON),
                 str(FLEET / "contracts/checks/draft_spec_shape.py")],
                cwd=FLEET, capture_output=True, text=True,
                env={**os.environ,
                     "FLEET_CHANGED_FILES": f"drafts/{draft.name}"})
        finally:
            draft.unlink(missing_ok=True)

    BLOCK = ("```fleet-spec\n"
             "work_type: dd_frontend\n"
             "repo: deadly-digital-platform\n"
             "title: A probe\n"
             "writable_paths:\n"
             "  - platform/app/(dashboard)/analytics/orders/page.tsx\n"
             "```\n")

    def test_a_draft_that_numbers_nothing_is_refused(self, tmp_path):
        r = self._shape(tmp_path, self.BLOCK + "\nJust prose about the work.\n")
        assert r.returncode == 1
        assert "numbers no requirements" in r.stdout + r.stderr

    def test_a_draft_that_numbers_its_requirements_passes(self, tmp_path):
        r = self._shape(
            tmp_path,
            self.BLOCK + "\n### 1. The page sends them\n\nWords.\n")
        assert r.returncode == 0, r.stdout
        assert "1 numbered requirement" in r.stdout

    def test_the_real_drafts_on_disk_already_satisfy_it(self):
        """A rule that would refuse the corpus it was written against is a
        rule about the corpus, not about the specs."""
        for draft in sorted((FLEET / "drafts").glob("*.md")):
            r = subprocess.run(
                [str(PYTHON),
                 str(FLEET / "contracts/checks/draft_spec_shape.py")],
                cwd=FLEET, capture_output=True, text=True,
                env={**os.environ,
                     "FLEET_CHANGED_FILES": f"drafts/{draft.name}"})
            assert r.returncode == 0, f"{draft.name}: {r.stdout}"
            assert "numbered requirement" in r.stdout


class TestThePromptAndTheGateAskForTheSameThing:
    """An agent that satisfies the prompt must pass the check. A prompt
    listing a different set from the gate is how a requirement falls between
    two lists and nobody catches it."""

    def test_the_prompt_lists_the_leaves_the_gate_wants(self):
        from runner import agent
        contract = {"writable_paths": ["a.tsx"], "protected_paths": ["x/**"],
                    "max_diff_lines": 600,
                    "verification": [str(CHECK)]}
        prompt = agent.build_prompt({"spec_md": SPEC}, contract)
        assert "`spec:1`" in prompt
        assert "`spec:2.1`" in prompt and "`spec:2.5`" in prompt
        assert "`spec:3`" in prompt
        # The parent is satisfied by its children, so asking for it would be
        # asking for more than the gate enforces.
        assert "`spec:2`  " not in prompt

    def test_a_contract_without_the_check_gets_no_annotation_burden(self):
        from runner import agent
        contract = {"writable_paths": ["a.tsx"], "protected_paths": ["x/**"],
                    "max_diff_lines": 600, "verification": ["true"]}
        prompt = agent.build_prompt({"spec_md": SPEC}, contract)
        assert "Cite every numbered requirement" not in prompt
