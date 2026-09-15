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
import re
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
    """3, not 1, since 15 Sep 2026: this check has no opinion about the code.
    It still REFUSES -- verify.Check.passed is False for an obligation."""
    r = run(repo, "// spec:1 forwards them\n")
    assert r.returncode == 3
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
    assert r.returncode == 3
    assert "4 of 4" in r.stdout or "cited nowhere" in r.stdout


def test_a_longer_id_does_not_satisfy_a_shorter_one(repo):
    r = run(repo, "// spec:2.50 spec:1 spec:3 spec:2.1\n")
    assert r.returncode == 3
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
    assert r.returncode == 3
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


class TestAFullStopIsNotAWordCharacter:
    """15 Sep 2026. The guard was `(?![\\w.\\d])` -- no dot at all -- and it has
    two jobs that the dot only half serves:

        `spec:2.5` must not match inside `spec:2.51`   -- `(?!\\w)` does that
        `spec:2`   must not match inside `spec:2.5`    -- needs the dot rule

    Rejecting EVERY following dot also rejects one ending a sentence. Task 87's
    branch carried `* spec:6. The API half of this shipped months before the
    page read it:` -- a correct citation of requirement 6, in prose -- and was
    refused. Run 62, GBP 3.63, attempt 1 of 2 spent, and the rebuild rewrote
    the feature rather than adding the token.

    Replayed over every patch commit in the fleet's history -- 76, of which 33
    have a spec that numbers anything -- the narrowed guard changes exactly one
    verdict: run 62's, FAIL to PASS.
    """

    def test_task_87s_real_line_is_a_citation(self, repo):
        r = run(repo, "// spec:1 spec:2.1 spec:2.5\n"
                      "/* spec:3. The API half of this shipped months "
                      "before the page read it. */\n")
        assert r.returncode == 0, r.stdout

    def test_a_parent_still_does_not_match_inside_its_child(self, repo):
        """The job the dot rule exists for, and the one the narrowing must not
        drop: citing 2.5 is not citing 2 by textual accident. 2 is satisfied
        here by the parent rule instead, which is a different mechanism."""
        from contextlib import suppress
        import importlib.util
        spec = importlib.util.spec_from_file_location("c", str(CHECK))
        mod = importlib.util.module_from_spec(spec)
        with suppress(SystemExit):
            spec.loader.exec_module(mod)
        assert not mod.token("2").search("// spec:2.5 clicking a cell")
        assert not mod.token("2.5").search("// spec:2.51 a longer id")
        assert not mod.token("6").search("// myspec:6 a suffix")

    @pytest.mark.parametrize("form", ["(spec:3)", "spec:3, and", "spec:3; then",
                                      "spec:3 -- so", "SPEC:3.", "spec:3."])
    def test_the_other_punctuation_that_ends_a_clause(self, repo, form):
        """One line per case, and it has to differ between cases: `run()`
        rewrites the file and commits, so a line repeated from the previous
        case is diff CONTEXT rather than an added line, and this check counts
        added lines only. That is the check working, and it caught this test."""
        r = run(repo, f"// spec:1 spec:2.1 spec:2.5 {form}\n")
        assert r.returncode == 0, f"{form}: {r.stdout}"

    def test_a_child_cited_with_a_full_stop_carries_its_parent(self, repo):
        r = run(repo, "// spec:1\n// spec:2.1. and spec:2.5.\n// spec:3.\n")
        assert r.returncode == 0, r.stdout


class TestItCannotCorroborateItself:
    """15 Sep 2026. The hole 042 opened in this check two days after it landed.

    console/adopt.corroborate() re-runs a FAILING check in a clone at the base,
    with FLEET_BASE_SHA and FLEET_HEAD_SHA set to the same commit, to establish
    whether it fails without the branch applied. For a check that reads the
    TREE that is a real question and task 100 is why it exists.

    For THIS check it is not a question at all. The diff is empty by
    construction, so nothing is cited, so it fails -- every time, for every
    branch, whatever the branch did. Matched on command and exit code, which is
    all adopt._corroboration_for() and 042's SQL compare, that excused this
    check for every branch: the one gate in the path that reads a spec, and the
    only thing that noticed task 102 had not proved its central claim.

    The fix is not output comparison. Task 100's excused check printed `1 of 43
    files` on the branch and `1 of 42` at the base, so requiring the tails to
    match would refuse the case the feature exists for. The check says so
    itself instead, in the vocabulary that already existed: exit 2, which both
    layers already refuse as evidence.
    """

    def test_an_empty_diff_is_could_not_run_and_not_a_failure(self, repo):
        """base == HEAD, which is exactly the corroboration run."""
        head = _git(repo, "rev-parse", "HEAD")
        env = dict(os.environ)
        env["FLEET_SPEC_MD"] = SPEC
        env["FLEET_BASE_SHA"] = head
        env["FLEET_HEAD_SHA"] = head
        r = subprocess.run([str(PYTHON), str(CHECK)], cwd=repo, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 2, r.stdout
        assert "adds no lines" in r.stdout
        assert "could not run" in r.stdout

    def test_the_message_names_the_hole_it_closes(self, repo):
        """The next person to read this exit code needs to know why it is a 2
        and not a 1, or it will be 'simplified' back into the hole."""
        head = _git(repo, "rev-parse", "HEAD")
        env = dict(os.environ)
        env["FLEET_SPEC_MD"] = SPEC
        env["FLEET_BASE_SHA"] = head
        r = subprocess.run([str(PYTHON), str(CHECK)], cwd=repo, env=env,
                           capture_output=True, text=True)
        assert "BASE-CORROBORATION" in r.stdout
        assert "corroborate ITSELF" in r.stdout

    def test_two_is_refused_as_evidence_by_the_module(self, repo):
        """The exit code is only half of it -- this asserts the other half,
        that adopt refuses to build an excuse out of an undecided base check.
        Asserted here, beside the check that produces the 2, because the two
        halves are one rule and a test for either alone would pass while the
        rule was broken."""
        from runner import verify
        from console import adopt
        base_side = {"command": "cite", "exit_code": 2,
                     "undecided_reason": verify.killed_by(2, None)}
        branch_side = {"command": "cite", "exit_code": 1,
                       "skipped_reason": None, "unresolved_reason": None,
                       "undecided_reason": None, "timed_out": False}
        assert verify.killed_by(2, None) is not None
        assert adopt._corroboration_for(
            branch_side, [{"base_commit_sha": "b", "checks": [base_side]}],
            "b") is None

    def test_a_branch_that_adds_lines_and_cites_nothing_still_refuses(self, repo):
        """The 2 must be reachable ONLY by an empty diff. A branch that adds
        lines and cites nothing is an ordinary obligation refusal -- 3, and
        Check.passed False -- otherwise the fix has turned the gate off, which
        is the opposite of the point."""
        r = run(repo, "const b = 2;\n")
        assert r.returncode == 3
        assert "cited nowhere" in r.stdout

    def test_a_passing_branch_still_passes(self, repo):
        r = run(repo, "// spec:1 spec:2.1 spec:2.5 spec:3 all of them\n")
        assert r.returncode == 0, r.stdout


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

    #: `contract` is declared because §14 made it required. These tests are
    #: about NUMBERING, so the block must otherwise be valid or every one of
    #: them asserts on the contract message instead.
    BLOCK = ("```fleet-spec\n"
             "work_type: dd_frontend\n"
             "repo: deadly-digital-platform\n"
             "contract: dd-analytics-frontend.yaml\n"
             "title: A probe\n"
             "writable_paths:\n"
             "  - platform/app/(dashboard)/analytics/orders/page.tsx\n"
             "```\n")

    def test_a_draft_that_numbers_nothing_is_refused(self, tmp_path):
        """draft_spec_shape.py, NOT the citation check -- 1 here is a verdict
        about the draft in front of it, which is the artefact it judges."""
        r = self._shape(tmp_path, self.BLOCK + "\nJust prose about the work.\n")
        assert r.returncode == 1
        assert "numbers no requirements" in r.stdout + r.stderr

    def test_a_draft_that_numbers_its_requirements_passes(self, tmp_path):
        r = self._shape(
            tmp_path,
            self.BLOCK + "\n### 1. The page sends them\n\nWords.\n")
        assert r.returncode == 0, r.stdout
        assert "1 numbered requirement" in r.stdout

    #: The two drafts rule 8 refuses, named rather than excused.
    #:
    #: THIS LIST IS NOT A WEAKENING OF THE RULE. The class docstring's premise
    #: -- a rule that refuses the corpus it was written against is a rule about
    #: the corpus -- holds for 23 of the 25 drafts on disk. These two are the
    #: corpus being wrong, not the rule: each numbers requirements demanding a
    #: production measurement, each produced exactly one task, and both of
    #: those tasks died of it with every code check green.
    #:
    #:     restrict-the-acquiring-order-cte-to-the-window  -> task 102, GBP 4.74
    #:     fold-the-per-manifest-reconciliation-queries    -> task 109, GBP 5.15
    #:
    #: They are left on disk unedited because they are the record of what was
    #: written, and rewriting them would erase the evidence for the rule. A
    #: THIRD name appearing here is not a bigger allow-list; it means rule 8 is
    #: firing on something it should not, and the rule is what to look at.
    KNOWN_UNBUILDABLE = {
        "restrict-the-acquiring-order-cte-to-the-window.md",
        "fold-the-per-manifest-reconciliation-queries.md",
    }

    def test_the_real_drafts_on_disk_already_satisfy_it(self, tmp_path):
        """A rule that would refuse the corpus it was written against is a
        rule about the corpus, not about the specs.

        The drafts on disk PREDATE `contract`, which §14 made required on
        11 Sep 2026, so they are replayed with it supplied — the same thing
        tests/test_selfcheck.py does for the task-23/24/25 branches. A new
        required field refusing documents written before it existed is not the
        corpus failing the rule; it is the rule being younger than the corpus.
        What this test is about is NUMBERING, and that is unchanged.

        SINCE 15 Sep 2026 TWO DRAFTS ARE EXPECTED TO FAIL, and the test asserts
        that they do rather than skipping them — see KNOWN_UNBUILDABLE. A rule
        whose only evidence is a test fixture is a rule nobody has checked
        against real prose; these two are the real prose, and they are the two
        that cost money.
        """
        import yaml as _yaml
        for draft in sorted((FLEET / "drafts").glob("*.md")):
            body = draft.read_text()
            m = re.search(r"```fleet-spec\s*\n(.*?)\n```", body, re.S)
            if m:
                block = _yaml.safe_load(m.group(1)) or {}
                if not block.get("contract"):
                    named = {"dd_api": "deadly-digital-platform-api.yaml",
                             "dd_frontend": "dd-analytics-frontend.yaml",
                             "research": "research.yaml"}.get(
                                 str(block.get("work_type")))
                    if named:
                        block["contract"] = named
                        body = (body[:m.start(1)]
                                + _yaml.safe_dump(block).rstrip()
                                + body[m.end(1):])
            (tmp_path / "drafts").mkdir(exist_ok=True)
            (tmp_path / "drafts" / draft.name).write_text(body)
            r = subprocess.run(
                [str(PYTHON),
                 str(FLEET / "contracts/checks/draft_spec_shape.py")],
                cwd=tmp_path, capture_output=True, text=True,
                env={**os.environ,
                     "FLEET_CHANGED_FILES": f"drafts/{draft.name}"})
            if draft.name in self.KNOWN_UNBUILDABLE:
                assert r.returncode == 1, (
                    f"{draft.name} is one of the two drafts that numbered a "
                    f"requirement its build agent could not perform. If it "
                    f"passes now, rule 8 has stopped catching the case it was "
                    f"written for.")
                assert "cannot satisfy" in r.stdout + r.stderr
                continue
            assert r.returncode == 0, f"{draft.name}: {r.stdout}{r.stderr}"
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


class TestARequirementTheAgentCannotPerform:
    """Rule 8 of draft_spec_shape.py, 15 Sep 2026.

    Rule 7 makes a spec enforceable. This makes it SATISFIABLE. A requirement
    the build agent has no tools to perform cannot be cited honestly, so
    spec_requirements_cited.py refuses the branch -- with every code check
    green -- and the run dies with its attempt spent.

        task 102   GBP 4.74   "the identity is PROVED on production data",
                              "report the measurement", and a requirement
                              conditional on that measurement
        task 109   GBP 5.15   "proved on production data, per period, with the
                              dataset named", "report the statement count and
                              the time, before and after" -- written by the
                              draft-spec agent five days after 102 died of it

    MEASURED, NOT ASSERTED. Over every numbered requirement in the task table
    on 15 Sep 2026 -- 254 across 76 specs -- the rule flags exactly the five
    above and nothing else.
    """

    def _shape(self, body: str):
        draft = FLEET / "drafts" / "test_fleet_rule8_probe.md"
        draft.write_text(body)
        try:
            return subprocess.run(
                [str(PYTHON), str(FLEET / "contracts/checks/draft_spec_shape.py")],
                cwd=FLEET, capture_output=True, text=True,
                env={**os.environ, "FLEET_CHANGED_FILES": f"drafts/{draft.name}"})
        finally:
            draft.unlink(missing_ok=True)

    BLOCK = ("```fleet-spec\n"
             "work_type: dd_frontend\n"
             "repo: deadly-digital-platform\n"
             "contract: dd-analytics-frontend.yaml\n"
             "title: A probe\n"
             "writable_paths:\n"
             "  - platform/app/(dashboard)/analytics/orders/page.tsx\n"
             "```\n")

    OK_REQ = "### 1. The page sends the filters\n\nWords about it.\n"

    def test_a_buildable_spec_passes(self):
        r = self._shape(self.BLOCK + self.OK_REQ)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_task_102s_requirement_5_is_refused(self):
        r = self._shape(self.BLOCK + self.OK_REQ +
                        "\n### 2. The identity is PROVED on production data, "
                        "the way task 100's requirement 3 was\n\nWords.\n")
        out = r.stdout + r.stderr
        assert r.returncode == 1
        assert "cannot satisfy" in out
        assert "no shell" in out

    def test_task_109s_requirement_7_is_refused(self):
        r = self._shape(self.BLOCK + self.OK_REQ +
                        "\n### 2. Report the statement count and the time, "
                        "before and after\n\nWords.\n")
        assert r.returncode == 1 and "cannot satisfy" in r.stdout + r.stderr

    def test_a_requirement_conditional_on_one_is_refused_too(self):
        """Task 102's requirement 7. It demands no measurement itself, so the
        phrase list does not touch it -- and it is unbuildable all the same,
        because it is gated on one the agent cannot satisfy."""
        r = self._shape(
            self.BLOCK + self.OK_REQ +
            "\n### 2. Report the measurement after the restriction\n\nWords.\n"
            "\n### 3. The LATERAL form, only if requirement 2's measurement "
            "justifies it\n\nWords.\n")
        assert r.returncode == 1
        assert "conditional on requirement 2" in r.stdout + r.stderr

    def test_a_conditional_on_a_BUILDABLE_requirement_is_fine(self):
        """The conditional rule must not fire on every `only if requirement N`
        -- only when N is itself unsatisfiable."""
        r = self._shape(
            self.BLOCK + self.OK_REQ +
            "\n### 2. The table renders the coupon column\n\nWords.\n"
            "\n### 3. The export includes it, only if requirement 2 shipped\n"
            "\nWords.\n")
        assert r.returncode == 0, r.stdout + r.stderr

    def test_the_message_says_what_to_do_instead(self):
        """A refusal that does not say how to fix it costs a second draft."""
        r = self._shape(self.BLOCK + self.OK_REQ +
                        "\n### 2. Report the measurement after the change\n\nW.\n")
        out = r.stdout + r.stderr
        assert "STATE THE FIGURE INSTEAD OF ASKING FOR IT" in out
        assert "lateral-acquiring-order-in-three-call-sites.md" in out
        assert "not ready to\nbe queued" in r.stdout or "not ready to be queued" in out

    def test_it_says_it_catches_shape_and_not_intent(self):
        """The same sentence spec_requirements_cited.py carries about itself.
        The phrase list came from two incidents, not a survey, and a reader who
        takes a green here as proof the spec is buildable is wrong."""
        r = self._shape(self.BLOCK + self.OK_REQ +
                        "\n### 2. Report the measurement after the change\n\nW.\n")
        out = r.stdout + r.stderr
        assert "SHAPE, NOT INTENT" in out
        assert "not from a\nsurvey" in r.stdout or "not from a survey" in out


class TestRuleEightReadsTheContract:
    """It asks the contract what tools the agent will get, rather than keeping
    a list of which contracts lack a shell. Eleven of twelve have none today,
    and that is the kind of fact that is wrong the week after it is written."""

    def _mod(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dss", str(FLEET / "contracts/checks/draft_spec_shape.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_the_default_comes_from_runner_yaml(self):
        """A contract that declares no agent_tools gets runner.yaml's set, so
        a copy here would be asking a different question from the runner."""
        assert self._mod()._default_agent_tools() == [
            "Read", "Edit", "Write", "Grep", "Glob"]

    def test_a_contract_with_no_bash_has_no_shell(self):
        assert self._mod().has_a_shell("deadly-digital-platform-api.yaml") is False

    def test_an_unreadable_contract_declines_to_judge(self):
        """None, not False. A rule that fires because a file is missing is a
        rule about the filesystem."""
        m = self._mod()
        assert m.has_a_shell("no-such-contract.yaml") is None
        from console import requirements
        reqs = requirements.parse(
            "### 1. Report the measurement after the change\n\nWords.\n")
        assert m.unbuildable_requirements(reqs, "no-such-contract.yaml") == []

    def test_a_pinned_command_is_not_a_shell(self):
        """draft-spec.yaml grants Bash(<one script>) with no wildcard. It
        cannot time a request or open a database, so it does not exempt."""
        assert self._mod().has_a_shell("draft-spec.yaml") is False

    def test_a_real_shell_exempts(self, tmp_path):
        m = self._mod()
        for grant, expected in (("Bash", True), ("Bash(/usr/bin/psql *)", True),
                                ("Bash(/one/pinned.sh)", False)):
            y = tmp_path / "probe.yaml"
            y.write_text("work_type: x\nrepo: y\nagent_tools:\n  - Read\n"
                         f"  - {grant}\n")
            m.CONTRACTS = tmp_path
            assert m.has_a_shell("probe.yaml") is expected, grant
