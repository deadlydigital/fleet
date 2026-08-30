"""Research tasks: a document is the artifact, and the runner is unchanged."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from runner import boundary, config, evidence, worktree

FLEET_FLOOR = ["contracts/**", "tests/**", "runner/**", "console/**",
               "detectors/**", "proposer/**", "systemd/**", "specs/**", ".env"]
CHECK = Path("/home/ubuntu/fleet/contracts/checks/research_document_shape.py")


def sh(cwd: Path, *args: str) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"{' '.join(args)}: {r.stderr}"
    return r.stdout


# ---- the floor: the agent now lives in the repo holding its own check ------

def test_a_contract_making_the_checks_writable_cannot_be_stored(console):
    """For a code task the check was out of reach by construction. For a
    research task it is a file in the same repo, so the floor is what keeps
    it out of reach."""
    import psycopg
    contract = {"work_type": "research", "repo": "fleet", "base_branch": "main",
                "writable_paths": ["contracts/checks/**"],
                "protected_paths": [g for g in FLEET_FLOOR if g != "contracts/**"],
                "verification": ["true"], "max_diff_lines": 100}
    with pytest.raises(psycopg.errors.RaiseException):
        console.execute(
            "INSERT INTO tasks (title, spec_md, repo, base_branch,"
            " acceptance_contract, max_cost_gbp)"
            " VALUES ('sneaky','x','fleet','main',%s,1.00)",
            (json.dumps(contract),))


def test_the_shipped_research_contract_is_storable(console):
    import yaml
    c = yaml.safe_load(Path("/home/ubuntu/fleet/contracts/research.yaml").read_text())
    row = console.execute(
        "INSERT INTO tasks (title, spec_md, repo, base_branch,"
        " acceptance_contract, max_cost_gbp)"
        " VALUES ('research','# spec','fleet','main',%s,5.00) RETURNING id",
        (json.dumps(c),)).fetchone()
    assert row["id"] > 0


def test_the_boundary_refuses_a_write_to_the_check(dsns):
    import yaml
    c = yaml.safe_load(Path("/home/ubuntu/fleet/contracts/research.yaml").read_text())
    change = boundary.Change(base_sha="a", head_sha="b",
                             paths=["contracts/checks/research_document_shape.py"],
                             status={"contracts/checks/research_document_shape.py": "M"})
    verdict = boundary.enforce(change, c)
    assert not verdict.clean
    assert "contracts/**" in verdict.protected_hits.values()


# ---- the whole-tree snapshot ---------------------------------------------

def test_an_untracked_write_is_caught(tmp_path):
    """Your addition: a write to an untracked path shows in neither git nor a
    tracked-file comparison."""
    repo = tmp_path / "r"
    repo.mkdir()
    sh(repo, "git", "init", "-q", "-b", "main")
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "t")
    (repo / ".gitignore").write_text("ignored/\n")
    (repo / "tracked.txt").write_text("x")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "base")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "dep.js").write_text("original")

    snap = worktree.Untouched.of(repo)
    snap.assert_unchanged(repo, "repo")            # stable

    (repo / "ignored" / "dep.js").write_text("tampered with")
    with pytest.raises(Exception, match="without git seeing it"):
        snap.assert_unchanged(repo, "repo")


def test_a_brand_new_ignored_file_is_caught(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    sh(repo, "git", "init", "-q", "-b", "main")
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "t")
    (repo / ".gitignore").write_text("ignored/\n")
    (repo / "a.txt").write_text("x")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "base")
    (repo / "ignored").mkdir()
    snap = worktree.Untouched.of(repo)
    (repo / "ignored" / "new.js").write_text("planted")
    with pytest.raises(Exception, match="without git seeing it"):
        snap.assert_unchanged(repo, "repo")


# ---- the evidence pack ----------------------------------------------------

def test_the_pack_records_the_sql_and_the_moment(dsns, tmp_path):
    results = evidence.run_queries(
        [{"key": "issues", "reader": "fleet", "sql": "SELECT count(*) AS n FROM issues"}])
    text = evidence.render(results, {"id": 1, "title": "t"})
    assert "SELECT count(*) AS n FROM issues" in text
    assert "The agent did not run these and cannot run others" in text


def test_a_failing_query_is_recorded_not_swallowed(dsns):
    results = evidence.run_queries(
        [{"key": "broken", "reader": "fleet", "sql": "SELECT * FROM nope"}])
    assert not results[0].ok
    text = evidence.render(results, {"id": 1, "title": "t"})
    assert "FAILED and produced no reading" in text
    assert "A missing reading is not a zero" in text


def test_a_contract_cannot_name_an_arbitrary_dsn(dsns):
    """A contract that could name a connection string could name a writing one."""
    results = evidence.run_queries(
        [{"key": "x", "reader": "postgres://somewhere", "sql": "SELECT 1"}])
    assert not results[0].ok
    assert "may name only" in results[0].error


def test_the_reader_session_is_read_only(dsns):
    results = evidence.run_queries(
        [{"key": "w", "reader": "fleet", "sql": "DELETE FROM tasks"}])
    assert not results[0].ok


# ---- the acceptance check -------------------------------------------------

def run_check(cwd: Path, changed: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, FLEET_CHANGED_FILES=changed)
    return subprocess.run(["/home/ubuntu/fleet/.venv/bin/python", str(CHECK)],
                          cwd=cwd, capture_output=True, text=True, env=env)


@pytest.fixture
def gold(tmp_path) -> Path:
    (tmp_path / "research").mkdir()
    doc = subprocess.run(["git", "-C", "/home/ubuntu/fleet", "show",
                          "73dc37f:specs/metorik-gap.md"],
                         capture_output=True, text=True).stdout
    (tmp_path / "research" / "gold.md").write_text(doc)
    return tmp_path


def test_the_gold_standard_passes(gold):
    """metorik-gap.md is the standard. A check that fails it is wrong."""
    r = run_check(gold, "research/gold.md")
    assert r.returncode == 0, r.stdout


def test_the_other_exemplar_passes(tmp_path):
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "r.md").write_text(
        Path("/home/ubuntu/fleet/specs/refund-hook.md").read_text())
    r = run_check(tmp_path, "research/r.md")
    assert r.returncode == 0, r.stdout


def test_a_thin_document_fails(tmp_path):
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "t.md").write_text("# A\nMetorik has features.\n")
    assert run_check(tmp_path, "research/t.md").returncode == 1


def test_a_document_with_no_limits_section_fails(gold):
    doc = (gold / "research" / "gold.md")
    doc.write_text(doc.read_text().replace("## What I could not verify",
                                           "## Some other heading"))
    r = run_check(gold, "research/gold.md")
    assert r.returncode == 1
    assert "what could not be verified" in r.stdout


def test_an_invented_repo_path_fails(gold):
    doc = (gold / "research" / "gold.md")
    doc.write_text(doc.read_text()
                   + "\n\nSee `api/analytics/routes/invented.py` for the detail.\n")
    r = run_check(gold, "research/gold.md")
    assert r.returncode == 1
    assert "do not exist" in r.stdout


def test_two_snapshots_of_an_untouched_repo_agree(tmp_path):
    """Taking a snapshot runs `git status`, which refreshes .git/index. If the
    digest covered .git, every tick would report tampering."""
    repo = tmp_path / "r"
    repo.mkdir()
    sh(repo, "git", "init", "-q", "-b", "main")
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "t")
    (repo / "a.txt").write_text("x")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "base")
    first = worktree.Untouched.of(repo)
    sh(repo, "git", "status", "--porcelain")
    first.assert_unchanged(repo, "repo")


def test_a_path_to_code_that_is_not_in_these_repos_is_not_demanded(tmp_path):
    """refund-hook.md cites the connector plugin and says in as many words
    that its source is not in the repo. Demanding it resolve would fail a
    document for being honest about where its evidence came from."""
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "r.md").write_text(
        Path("/home/ubuntu/fleet/specs/refund-hook.md").read_text())
    r = run_check(tmp_path, "research/r.md")
    assert r.returncode == 0, r.stdout


def test_a_non_markdown_file_in_the_diff_fails(gold):
    (gold / "research" / "x.py").write_text("print(1)")
    r = run_check(gold, "research/gold.md\nresearch/x.py")
    assert r.returncode == 1
    assert "non-markdown" in r.stdout
