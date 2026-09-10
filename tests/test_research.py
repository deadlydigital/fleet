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


# ---- what the guard deliberately does not watch, and what it says ---------

def _repo_with_deps(tmp_path, name="r"):
    """A checkout with a gitignored dependency tree, like the platform one."""
    repo = tmp_path / name
    repo.mkdir()
    sh(repo, "git", "init", "-q", "-b", "main")
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "t")
    # Two ignored trees: one the contract links, one it does not. The second
    # is what proves the exclusion did not widen into "stop watching".
    (repo / ".gitignore").write_text("node_modules/\n.cache/\n")
    (repo / "src.ts").write_text("x")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "base")
    cache = repo / "node_modules" / ".vite" / "vitest"
    cache.mkdir(parents=True)
    (cache / "results.json").write_text('{"version":"1.6.1","results":[]}')
    (repo / ".cache").mkdir()
    return repo, cache / "results.json"


class TestLinkedDependencyTreesAreNotWatched:
    """Task 49, exactly: every check passed, the branch pushed, and the guard
    failed it because vitest wrote 131 bytes into the checkout's node_modules
    -- which the runner had itself linked the worktree's node_modules at,
    because copying gigabytes per task is not an option.
    """

    def test_a_write_to_the_dependency_tree_fails_without_the_exclusion(
            self, tmp_path):
        """The bug, held so the fix cannot be mistaken for a no-op."""
        repo, results = _repo_with_deps(tmp_path)
        snap = worktree.Untouched.of(repo)
        results.write_text('{"version":"1.6.1","results":[["t",{"failed":true}]]}')
        with pytest.raises(Exception, match="without git seeing it"):
            snap.assert_unchanged(repo, "repo")

    def test_and_passes_when_the_contract_linked_it(self, tmp_path):
        repo, results = _repo_with_deps(tmp_path)
        snap = worktree.Untouched.of(repo, exclude=[repo / "node_modules"])
        results.write_text('{"version":"1.6.1","results":[["t",{"failed":true}]]}')
        snap.assert_unchanged(repo, "repo")

    def test_the_exclusion_does_not_widen_past_what_was_linked(self, tmp_path):
        """Excluding node_modules must not stop watching the repository.

        The guard's real job is catching a write the AGENT made outside its
        worktree, where the derived diff would show nothing at all. An
        exclusion that quietly covered the tracked tree would remove that.
        """
        repo, _ = _repo_with_deps(tmp_path)
        snap = worktree.Untouched.of(repo, exclude=[repo / "node_modules"])
        # Into a DIFFERENT ignored tree, so git sees nothing and only the
        # digest can catch it -- which is the path the exclusion touches.
        (repo / ".cache" / "planted.js").write_text("the agent wrote here")
        with pytest.raises(Exception, match="without git seeing it"):
            snap.assert_unchanged(repo, "repo")

    def test_excluding_the_root_switches_nothing_off(self, tmp_path):
        """A contract naming the repo root must not disable the guard.

        os.walk yields the root before its children and the prune only ever
        matches a CHILD path, so this is safe by construction rather than by a
        check somebody has to remember.
        """
        repo, _ = _repo_with_deps(tmp_path)
        snap = worktree.Untouched.of(repo, exclude=[repo])
        (repo / ".cache" / "planted.js").write_text("still watched")
        with pytest.raises(Exception, match="without git seeing it"):
            snap.assert_unchanged(repo, "repo")

    def test_the_check_reuses_the_snapshot_exclusions(self, tmp_path):
        """Before and after are compared over the same ground.

        assert_unchanged takes no exclusion argument; it reads the one recorded
        on the snapshot. A guard that could be checked against a different set
        from the one it was taken with would report its own drift as tampering.
        """
        repo, results = _repo_with_deps(tmp_path)
        snap = worktree.Untouched.of(repo, exclude=[repo / "node_modules"])
        assert snap.excluded == (str((repo / "node_modules").resolve()),)
        results.write_text("rewritten")
        snap.assert_unchanged(repo, "repo")


class TestTheFailureNamesTheFile:
    """Task 49's error was "63395 files before, 63395 after" -- two identical
    numbers offered as evidence, because the count is incidental to a digest
    over size and mtime. That is a reporting defect independent of the guard,
    and it is why the failure went unread for a day.
    """

    def test_a_modified_file_is_named_with_what_changed(self, tmp_path):
        repo, results = _repo_with_deps(tmp_path)
        snap = worktree.Untouched.of(repo)
        results.write_text("x" * 400)
        with pytest.raises(Exception) as exc:
            snap.assert_unchanged(repo, "repo")
        msg = str(exc.value)
        assert "node_modules/.vite/vitest/results.json" in msg
        assert "1 modified" in msg
        assert "-> 400 bytes" in msg

    def test_a_same_size_rewrite_says_the_mtime_moved(self, tmp_path):
        """Task 49's actual shape: 131 bytes before and after."""
        repo, results = _repo_with_deps(tmp_path)
        size = results.stat().st_size
        snap = worktree.Untouched.of(repo)
        import os
        st = results.stat()
        os.utime(results, ns=(st.st_atime_ns, st.st_mtime_ns + 1))
        with pytest.raises(Exception) as exc:
            snap.assert_unchanged(repo, "repo")
        assert f"{size} bytes, mtime moved" in str(exc.value)

    def test_an_added_file_is_named(self, tmp_path):
        repo, _ = _repo_with_deps(tmp_path)
        snap = worktree.Untouched.of(repo)
        (repo / "node_modules" / "planted.js").write_text("x")
        with pytest.raises(Exception) as exc:
            snap.assert_unchanged(repo, "repo")
        assert "1 added: node_modules/planted.js" in str(exc.value)

    def test_a_removed_file_is_named(self, tmp_path):
        repo, results = _repo_with_deps(tmp_path)
        snap = worktree.Untouched.of(repo)
        results.unlink()
        with pytest.raises(Exception) as exc:
            snap.assert_unchanged(repo, "repo")
        assert "1 removed:" in str(exc.value)

    def test_many_files_are_capped_and_the_rest_counted(self, tmp_path):
        repo, _ = _repo_with_deps(tmp_path)
        snap = worktree.Untouched.of(repo)
        for i in range(9):
            (repo / "node_modules" / f"f{i}.js").write_text("x")
        with pytest.raises(Exception) as exc:
            snap.assert_unchanged(repo, "repo")
        assert "9 added" in str(exc.value) and "and 4 more" in str(exc.value)

    def test_what_was_not_watched_is_named_when_the_guard_fires(self, tmp_path):
        """An exclusion that hides a real write must be visible to the reader."""
        repo, _ = _repo_with_deps(tmp_path)
        snap = worktree.Untouched.of(repo, exclude=[repo / "node_modules"])
        (repo / ".cache" / "planted.js").write_text("x")
        with pytest.raises(Exception) as exc:
            snap.assert_unchanged(repo, "repo")
        msg = str(exc.value)
        assert "Not watched" in msg and "node_modules" in msg
        assert ".cache/planted.js" in msg

    def test_the_count_is_not_offered_as_the_evidence(self, tmp_path):
        """The regression itself: no "N before, N after" in the message."""
        repo, results = _repo_with_deps(tmp_path)
        snap = worktree.Untouched.of(repo)
        results.write_text("changed")
        with pytest.raises(Exception) as exc:
            snap.assert_unchanged(repo, "repo")
        assert "files before" not in str(exc.value)


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
