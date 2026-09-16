"""No check under contracts/checks/ may excuse itself at the base.

THE RULE, WHICH IS OLDER THAN THIS FILE

`042_a_check_that_fails_on_the_base_is_not_evidence.sql` lets a branch be
adopted past a check that fails identically on the base, because such a check
is true about the tree and false about the branch. `console/adopt.corroborate()`
produces that evidence by re-running the failing check in a clone AT THE BASE,
with `FLEET_BASE_SHA` and `FLEET_HEAD_SHA` set to the SAME COMMIT and
`FLEET_CHANGED_FILES` narrowed to the files that exist there.

For a check that reads the TREE that is a real question. For a check whose
subject is the CHANGE it is not a question at all: at the base there is no
change, so the check refuses, and it refuses the same way for EVERY branch.
`adopt._corroboration_for()` and 042 both match on the COMMAND and the EXIT
CODE and neither compares output, so a 1 there makes the check corroborate
ITSELF -- an adoption gate excused by the gate it was meant to pass.

WHY THIS FILE EXISTS AND THE PER-CHECK TESTS DO NOT COVER IT

It has now happened twice, to two different checks, with the second found only
because someone went looking:

  * `spec_requirements_cited.py`, 15 Sep 2026. Fixed there, and the fix was
    written up in that file at length.
  * `new_test_bites.sh`, 16 Sep 2026, on task 118 -- whose recorded failure was
    that the branch's OWN ADDED TEST did not pass, the least excusable finding
    a run can produce, and which adopt would have waved through.

The sweep that followed found three more: `research_document_shape.py`,
`draft_spec_shape.py`, `deploy_script_shape.py` and `candidate_block_shape.py`
all returned 1 with an empty changed-file list.

Four separate fixes in four files is not a fix for the class. THIS is: every
file under contracts/checks/ must be classified below, and every check whose
subject is the change is run with nothing to look at and must not answer 1. A
NEW check cannot be added without appearing here, because the first test in
this file compares the registry against the directory.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKS = ROOT / "contracts" / "checks"
PY = ROOT / ".venv" / "bin" / "python"
DD = Path("/home/ubuntu/deadly-digital-platform")

#: Checks whose subject is THE CHANGE: they read `git diff BASE..HEAD`,
#: FLEET_CHANGED_FILES, or a {changed_files} expansion. At the base they have
#: no input, so their answer is not about the branch and must not be a 1.
#:
#: The value is the working directory the check is run in and the extra
#: environment it needs, because a check run in the wrong repo fails for a
#: reason that has nothing to do with this rule.
DIFF_READING = {
    "spec_requirements_cited.py": (ROOT, {"FLEET_SPEC_MD": ""}),
    "new_test_bites.sh": (None, {}),            # needs a git repo; see below
    "research_document_shape.py": (ROOT, {}),
    "draft_spec_shape.py": (ROOT, {}),
    "deploy_script_shape.py": (ROOT, {}),
    "candidate_block_shape.py": (ROOT, {}),
    "index_migration_only.py": (ROOT, {}),
    "paired_paths.py": (ROOT, {"FLEET_CONTRACT": json.dumps(
        {"paired_paths": [{"paths": ["README.md", "principles.md"],
                           "why": "the registry needs a real group"}]})}),
    "ruff_no_new_findings.py": (ROOT, {}),
}

#: Checks whose subject is THE TREE. They read files and answer the same
#: question at the base that they answer on the branch, which is the case 042
#: exists for -- task 100's analytics suite is one of these. Running them at
#: the base is evidence, and nothing here may change that.
TREE_READING = {
    "acquiring_page_shape.py",
    "order_filters_shape.py",
    "proxy_passthrough.py",
    "revenue_granularity_doc.py",
    "utm_alias_cutover_diff.py",
    "pytest_unit_per_file.sh",
    "vitest_one_file.sh",
}

#: Not in a verification list at all, so corroborate() never runs it.
#: `spec_selfcheck.sh` is an agent_tools entry in contracts/draft-spec.yaml --
#: a preview of the gate, run by the agent during the run. It derives its own
#: changed set from `git status` and already exits 2 when nothing has changed.
NOT_A_GATE = {"spec_selfcheck.sh"}


def check_files() -> set[str]:
    return {p.name for p in CHECKS.iterdir()
            if p.is_file() and p.suffix in (".py", ".sh")}


def test_every_check_is_classified():
    """THE GUARD THAT MAKES THIS A SWEEP AND NOT FIVE FIXES.

    A check added to contracts/checks/ without a line here fails this, and the
    person adding it has to answer the one question that matters: does this
    check read the change, or the tree? Getting it wrong is recoverable --
    getting it unasked is how the class stayed open for a day and a half.
    """
    classified = set(DIFF_READING) | TREE_READING | NOT_A_GATE
    on_disk = check_files()
    assert on_disk - classified == set(), (
        "these checks are not classified in tests/test_base_corroboration.py: "
        f"{sorted(on_disk - classified)}. Decide whether each reads the CHANGE "
        "(add it to DIFF_READING, and make sure it exits 2 when the change is "
        "empty) or the TREE (add it to TREE_READING).")
    assert classified - on_disk == set(), (
        f"classified but absent from {CHECKS}: {sorted(classified - on_disk)}")


@pytest.fixture
def empty_diff_repo(tmp_path) -> tuple[Path, str]:
    """A git repository whose BASE and HEAD are the same commit.

    That is exactly the tree `corroborate()` builds: `worktree.create_trial_clone`
    at the recorded base, with FLEET_HEAD_SHA set to the same sha.
    """
    r = tmp_path / "repo"
    (r / "api" / "tests" / "analytics").mkdir(parents=True)
    (r / "api" / "thing.py").write_text("value = 1\n")
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t"),
                 ("config", "user.name", "t"), ("add", "-A"),
                 ("commit", "-q", "-m", "base")):
        subprocess.run(["git", *args], cwd=r, capture_output=True, check=False)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r,
                         capture_output=True, text=True).stdout.strip()
    return r, sha


@pytest.mark.parametrize("name", sorted(DIFF_READING))
def test_a_check_that_reads_the_change_does_not_answer_1_at_the_base(
        name, empty_diff_repo):
    """1 is what gets matched and excused. 2 and 0 are both refused as
    evidence -- 2 because `_excusable()` and 042 reject an undecided base
    check outright, 0 because it can never equal the failing branch's code.

    This asserts the property, not a particular exit code, because the honest
    answer differs by check: most cannot speak at all and say 2, while
    `ruff_no_new_findings.py` compares findings on the changed python files
    and correctly reports 0 -- there are none, on either side of nothing.
    """
    where, extra = DIFF_READING[name]
    repo, sha = empty_diff_repo
    cwd = where or repo
    path = CHECKS / name
    cmd = [str(path)] if path.suffix == ".sh" else [str(PY), str(path)]
    env = dict(os.environ, FLEET_BASE_SHA=sha, FLEET_HEAD_SHA=sha,
               FLEET_CHANGED_FILES="", **extra)
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                       timeout=180)
    assert r.returncode != 1, (
        f"{name} exits 1 with nothing to read. console/adopt.corroborate() "
        f"runs it that way at the base, adopt._corroboration_for() and 042 "
        f"match on command and exit code, and neither compares output -- so "
        f"this check excuses ITSELF for every branch that runs it. Exit 2 "
        f"(could not run) instead, and only for the EMPTY case: a real change "
        f"that fails this check must still exit 1.\n{r.stdout}{r.stderr}")
    assert r.returncode in (0, 2), (
        f"{name} exited {r.returncode}, which is neither a verdict nor "
        f"could-not-run:\n{r.stdout}{r.stderr}")


def test_the_tree_reading_checks_are_the_ones_042_exists_for():
    """Not a behaviour test -- a statement of what must NOT be changed.

    Widening the rule above to "no check may fail at the base" would delete the
    feature. Task 100 was adopted because `pytest_unit_per_file.sh` failed
    identically at the base on a hand-maintained migration tally, and task 118
    hit the same test one migration later. Those failures ARE evidence, and
    they are 1.
    """
    assert "pytest_unit_per_file.sh" in TREE_READING
    assert "pytest_unit_per_file.sh" not in DIFF_READING
