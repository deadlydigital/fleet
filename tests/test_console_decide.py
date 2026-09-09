"""Accept and reject: the two writes the console has.

Every test here builds a real git repository and drives the real database as
the real roles. A merge guard tested against a mocked git proves the mock
agrees with the guard, which is not the property anyone needs.

The guards are additionally verified by reversion -- see
test_reverting_guards.py -- because a guard whose test passes when the guard
is deleted is not testing the guard.
"""
from __future__ import annotations


def _ensure(p):
    """The fixtures write a nested analytics path now that api/app.py
    is floored (017); its parent does not exist in a bare fixture repo."""
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from console import decide, merge

REPO = "deadly-digital-platform"
from tests.support import PLATFORM_FLOOR

FLOOR = PLATFORM_FLOOR

def contract(**over) -> dict:
    c = {"work_type": "dd_feature", "repo": REPO, "base_branch": "main",
         "contract_version": 1, "writable_paths": ["api/analytics/services/analytics_engine.py"],
         "protected_paths": list(FLOOR), "verification": ["true"],
         "max_diff_lines": 200, "max_cost_gbp": 3.00}
    c.update(over)
    return c


def sh(cwd: Path, *args: str) -> str:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"{' '.join(args)}: {r.stderr}"
    return r.stdout


@pytest.fixture
def origin(tmp_path) -> Path:
    """A bare remote, so push and the verification that follows it are real."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    sh(bare, "git", "init", "-q", "--bare")
    return bare


@pytest.fixture
def repo(tmp_path, origin) -> Path:
    r = tmp_path / "repos" / REPO
    r.mkdir(parents=True)
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.email", "t@t")
    sh(r, "git", "config", "user.name", "t")
    (r / "api").mkdir()
    _ensure(r / "api" / "analytics" / "services" / "analytics_engine.py").write_text("x = 1\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-q", "-m", "base")
    sh(r, "git", "remote", "add", "origin", str(origin))
    sh(r, "git", "push", "-q", "-u", "origin", "main")
    return r


def branch_with_change(repo: Path, name: str, body: str = "x = 2\n",
                       path: str = "api/analytics/services/analytics_engine.py") -> tuple[str, str]:
    """Returns (base_sha_at_branch_point, branch_tip)."""
    base = sh(repo, "git", "rev-parse", "HEAD").strip()
    sh(repo, "git", "checkout", "-q", "-b", name)
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", f"work on {name}")
    tip = sh(repo, "git", "rev-parse", "HEAD").strip()
    sh(repo, "git", "checkout", "-q", "main")
    return base, tip


@pytest.fixture
def task(console, admin, runner, repo):
    """A task at READY_FOR_REVIEW with a run, a patch step and a branch."""
    tid = console.execute(
        "INSERT INTO tasks (title, spec_md, repo, base_branch, acceptance_contract,"
        " max_cost_gbp) VALUES ('a task','# spec',%s,'main',%s,3.00) RETURNING id",
        (REPO, json.dumps(contract()))).fetchone()["id"]
    console.commit()
    runner.execute("SELECT claim_task(NULL)")
    runner.commit()
    rid = admin.execute(
        "INSERT INTO runs (task_id, work_type, contract_version, spend_limit_gbp,"
        " committed_gbp, status) VALUES (%s,'dd_feature',1,3.00,0.75,'AWAITING_HUMAN')"
        " RETURNING id", (tid,)).fetchone()["id"]
    branch = f"fleet/task-{tid}"
    base_sha, tip = branch_with_change(repo, branch)
    admin.execute(
        "INSERT INTO run_steps (run_id, sequence, step_type, actor, payload)"
        " VALUES (%s,1,'PATCH_PROPOSED','fleet-runner/agent',%s)",
        (rid, json.dumps({"base_commit_sha": base_sha, "patch_commit_sha": tip,
                          "files_changed": ["api/analytics/services/analytics_engine.py"], "diff_lines": 1})))
    runner.execute(
        "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name=%s,"
        " completed_at=now() - interval '30 minutes' WHERE id=%s", (branch, tid))
    runner.commit()
    row = console.execute("SELECT * FROM tasks WHERE id=%s", (tid,)).fetchone()
    return {"task": row, "run_id": rid, "branch": branch,
            "base_sha": base_sha, "tip": tip}


@pytest.fixture
def trial(tmp_path):
    """A kept trial clone, built exactly as the accept route builds one.

    `merge_and_push` publishes the commit re-verification tested, so a test
    that calls it directly has to supply a real verified trial — there is no
    path that merges without one, deliberately. Cleaned up here the way the
    route cleans up in its finally.
    """
    from console import reverify
    from runner import worktree
    built = []

    def build(repo, task, **over):
        rv = reverify.run(repo, tmp_path / "merge-trials", dict(task["task"]),
                          contract(**over), task["branch"],
                          recorded_base=task["base_sha"],
                          changed_files=["api/analytics/services/analytics_engine.py"], keep_on_success=True)
        built.append(rv)
        return rv

    yield build
    for rv in built:
        if rv.trial_path:
            worktree.discard_trial_clone(Path(rv.trial_path))


def on_remote(origin: Path, ref: str) -> str:
    """A sha read out of the bare remote itself, not out of a tracking ref."""
    return sh(origin, "git", "rev-parse", "--verify", "--quiet", ref).strip()


# ---- accept: the happy path ----------------------------------------------

def test_accept_merges_pushes_and_verifies(dsns, repo, task, console, origin, trial):
    rv = trial(repo, task)
    assert rv.ok, rv.reason
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"], reverification=rv)
    assert r.ok, r.reason
    assert r.merged and r.pushed and r.push_verified
    assert r.remote_sha == r.base_sha_after

    # THE COMMIT THAT WAS TESTED IS THE COMMIT THAT LANDED, by identity.
    assert r.base_sha_after == rv.merged_sha
    assert on_remote(origin, "main") == rv.merged_sha

    # It landed on the REMOTE, and the checkout was not written to at all.
    assert subprocess.run(["git", "-C", str(origin), "merge-base", "--is-ancestor",
                           task["tip"], "main"]).returncode == 0
    assert subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                           task["branch"], "main"]).returncode != 0, (
        "the merge was made in the checkout; it must be published from the trial")

    decide.record(task=task["task"], run_id=task["run_id"], verdict="MERGED",
                  decision="APPROVED", note="looks right",
                  rendered_at=time.time() - 12,
                  merge={"merge_commit": r.base_sha_after, "pushed": True,
                         "push_verified": True, "remote_sha": r.remote_sha,
                         "already_merged": False})
    row = console.execute("SELECT status FROM tasks WHERE id=%s",
                          (task["task"]["id"],)).fetchone()
    assert row["status"] == "MERGED"


def test_the_verdict_records_both_clocks(dsns, repo, task, console):
    decide.record(task=task["task"], run_id=task["run_id"], verdict="REJECTED",
                  decision="REJECTED_WRONG_FIX", note=None,
                  rendered_at=time.time() - 42)
    payload = console.execute(
        "SELECT payload FROM run_steps WHERE run_id=%s AND step_type='HUMAN_DECISION'",
        (task["run_id"],)).fetchone()["payload"]
    assert 40 <= payload["decision_seconds"] <= 60      # the review
    assert payload["waited_seconds"] > 1700             # sat ~30 minutes
    assert payload["decision"] == "REJECTED_WRONG_FIX"


# ---- accept: every guard --------------------------------------------------

def test_accept_on_a_non_ready_task_refuses(dsns, repo, task, console):
    # REJECTED and not ABANDONED: task_transitions has no
    # READY_FOR_REVIEW -> ABANDONED row, and the trigger says so. The state
    # machine refusing to arrange the fixture is the state machine working.
    console.execute("UPDATE tasks SET status='REJECTED' WHERE id=%s",
                    (task["task"]["id"],))
    console.commit()
    t = dict(task["task"]); t["status"] = "REJECTED"
    r = merge.merge_and_push(repo, t, task["branch"], task["base_sha"], task["tip"])
    assert not r.ok and "not READY_FOR_REVIEW" in r.reason
    assert not r.merged


def test_accept_with_a_mismatched_branch_name_refuses(dsns, repo, task):
    r = merge.merge_and_push(repo, task["task"], "fleet/task-999",
                             task["base_sha"], task["tip"])
    assert not r.ok and "not the branch this task recorded" in r.reason
    assert not r.merged


def test_a_branch_name_of_the_wrong_shape_refuses(dsns, repo, task, console):
    console.execute("UPDATE tasks SET branch_name='hotfix/sneaky' WHERE id=%s",
                    (task["task"]["id"],))
    console.commit()
    t = dict(task["task"]); t["branch_name"] = "hotfix/sneaky"
    r = merge.merge_and_push(repo, t, "hotfix/sneaky", task["base_sha"], task["tip"])
    assert not r.ok and "not a fleet task branch name" in r.reason


def test_merging_the_base_into_itself_refuses(dsns, repo, task, console):
    console.execute("UPDATE tasks SET branch_name='main' WHERE id=%s",
                    (task["task"]["id"],))
    console.commit()
    t = dict(task["task"]); t["branch_name"] = "main"
    r = merge.merge_and_push(repo, t, "main", task["base_sha"], task["tip"])
    assert not r.ok and "into itself" in r.reason


def test_a_dirty_working_tree_no_longer_blocks_a_merge(dsns, repo, task, origin,
                                                       trial):
    """A guard that was removed on purpose, asserted as removed.

    It existed because the merge happened IN this checkout, where uncommitted
    work would have been swept into it. The merge is published from a trial
    clone now and the checkout is never written to, so the state of its
    working tree cannot affect the outcome — and refusing on it would only
    block merges that are perfectly safe.
    """
    _ensure(repo / "api" / "analytics" / "services" / "analytics_engine.py").write_text("uncommitted\n")
    rv = trial(repo, task)
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"], reverification=rv)
    assert r.ok, r.reason
    assert on_remote(origin, "main") == rv.merged_sha
    # And the uncommitted work is still there, untouched.
    assert (repo / "api" / "analytics" / "services" / "analytics_engine.py").read_text() == "uncommitted\n"


def test_a_checkout_on_another_branch_no_longer_blocks_a_merge(
        dsns, repo, task, origin, trial):
    """The guard whose removal is the point of the change.

    `head != base` forced the checkout onto each task's base branch before
    Accept could be pressed — and that checkout is also what the fleet's own
    systemd units run from, so pressing Accept meant switching a production
    tree. On 9 Sep 2026 doing so took out three timers.

    Nothing about the merge depends on where this checkout's HEAD points, so
    nothing about it is checked.
    """
    sh(repo, "git", "checkout", "-q", "-b", "somewhere-else")
    rv = trial(repo, task)
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"], reverification=rv)
    assert r.ok, r.reason
    assert on_remote(origin, "main") == rv.merged_sha
    # The checkout is where it was left, on the branch somebody else was using.
    assert sh(repo, "git", "rev-parse", "--abbrev-ref",
              "HEAD").strip() == "somewhere-else"


def test_a_branch_whose_tip_moved_is_refused(dsns, repo, task):
    """The primary guard is now the tip, not the merge base: it is the check
    that says "this is the code that was verified", and it catches a commit
    appended after verification, which the merge-base check did not."""
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], recorded_patch="0" * 40)
    assert not r.ok and "not what was checked" in r.reason
    assert not r.merged


def test_a_conflicting_merge_records_nothing_and_leaves_the_tree_clean(
        dsns, repo, task, console, origin, trial):
    """A conflict is now found in the trial, before anything is published.

    It used to be found by merging in this checkout and aborting. The tree
    could not be left dirty because nothing was ever done to it.
    """
    # main changes the same line the branch changed
    _ensure(repo / "api" / "analytics" / "services" / "analytics_engine.py").write_text("x = 99\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "conflicting change on main")

    rv = trial(repo, task)
    assert not rv.ok and rv.conflicted, rv.reason

    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"], reverification=rv)
    assert not r.ok
    assert not r.pushed
    assert sh(repo, "git", "status", "--porcelain").strip() == ""
    assert on_remote(origin, "main") != task["tip"], "a conflict reached the remote"
    assert console.execute(
        "SELECT status FROM tasks WHERE id=%s",
        (task["task"]["id"],)).fetchone()["status"] == "READY_FOR_REVIEW"
    assert console.execute(
        "SELECT count(*) AS n FROM run_steps WHERE run_id=%s"
        " AND step_type='HUMAN_DECISION'", (task["run_id"],)).fetchone()["n"] == 0


def test_a_push_that_did_not_land_is_caught(dsns, repo, task, monkeypatch,
                                            console, trial):
    """`git push` exiting 0 is a claim. The guard re-reads the remote.

    The happy-path test cannot prove this one: there the push really does
    land, so removing the check changes nothing. Here the remote is made to
    disagree, which is the only shape in which the guard matters.
    """
    rv = trial(repo, task)
    real_sha = merge._sha

    def lying_sha(r, ref):
        if ref.startswith(f"{merge.PUBLISH_REMOTE}/"):
            return "0" * 40
        return real_sha(r, ref)

    monkeypatch.setattr(merge, "_sha", lying_sha)
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"], reverification=rv)
    assert not r.ok
    assert "reported success" in r.reason
    assert not r.push_verified
    assert console.execute(
        "SELECT count(*) AS n FROM run_steps WHERE run_id=%s"
        " AND step_type='HUMAN_DECISION'", (task["run_id"],)).fetchone()["n"] == 0


def test_a_merge_is_never_attempted_in_the_checkout(dsns, repo, task, trial,
                                                   monkeypatch):
    """The failure that made this change necessary, asserted as impossible.

    ProtectSystem=strict left `~/fleet` read-only, `git merge` in the checkout
    said "cannot lock ref 'ORIG_HEAD': Read-only file system", and task 22
    could not be accepted at all -- after both the preflight and the
    re-verification had passed.

    Rather than testing that the message is worded well, this asserts the
    merge never runs there. A checkout that cannot be written to is now
    irrelevant to Accept, so there is no message to word.
    """
    seen = []
    real = merge._git

    def watching_git(r, *args, **kw):
        if Path(r) == repo:
            seen.append(args)
        return real(r, *args, **kw)

    rv = trial(repo, task)
    monkeypatch.setattr(merge, "_git", watching_git)
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"], reverification=rv)

    assert r.ok, r.reason
    writes = [a for a in seen
              if a and a[0] in {"merge", "fetch", "push", "commit", "checkout",
                                "reset", "update-ref", "gc", "prune"}]
    assert not writes, f"the checkout was written to: {writes}"
    assert seen, "nothing was read from the checkout either; the watch is broken"


def test_a_merge_without_a_verified_trial_is_refused(dsns, repo, task, origin):
    """There is no path that merges without a verified trial, on purpose.

    The obvious fallback — "no trial, so merge in the checkout" — is the
    defect this module was changed to remove. Having it would mean the safe
    path is whichever one happens to be taken.
    """
    before = on_remote(origin, "main")
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"], reverification=None)
    assert not r.ok
    assert "no verified trial" in r.reason
    assert not r.merged and not r.pushed
    assert on_remote(origin, "main") == before


# ---- accept: the already-merged path -------------------------------------

def test_an_already_merged_branch_records_without_merging(dsns, repo, task):
    """The task-26 shape: somebody merged and pushed it by hand.

    The remote is READ here rather than pushed to, because this path has no
    trial clone to push from -- there was nothing to merge, so nothing was
    re-verified. `ls-remote` writes nothing to the checkout.
    """
    sh(repo, "git", "merge", "-q", "--no-ff", "--no-edit", task["branch"])
    sh(repo, "git", "push", "-q", "origin", "main")
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"])
    assert r.ok, r.reason
    assert r.already_merged and not r.merged
    assert r.push_verified and r.remote_sha
    assert any("no merge is required" in d for d in r.detail)
    assert any("already contains" in d for d in r.detail)


def test_an_already_merged_branch_the_remote_does_not_have_is_refused(
        dsns, repo, task):
    """Merged locally, never pushed. Recording MERGED would be a claim about
    one machine.

    This used to push it, which it can no longer do -- pushing needs a clone
    and there is no verified trial on this path. Refusing is the honest
    replacement: the console says what is wrong rather than repairing a state
    it cannot verify.
    """
    sh(repo, "git", "merge", "-q", "--no-ff", "--no-edit", task["branch"])
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"])
    assert not r.ok
    assert "does not have it" in r.reason
    assert "this machine only" in r.reason
    assert r.already_merged and not r.merged and not r.pushed


def test_an_already_merged_branch_whose_tip_moved_refuses(dsns, repo, task):
    """What is in the base must be the commit the run verified.

    The message is the general one now: the tip check became the PRIMARY guard
    for every branch rather than a substitution reserved for already-merged
    ones, so this case is covered by the same rule as the rest instead of by a
    second copy of it.
    """
    sh(repo, "git", "merge", "-q", "--no-ff", "--no-edit", task["branch"])
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], recorded_patch="0" * 40)
    assert not r.ok
    assert "not what was checked" in r.reason
    assert not r.merged and not r.pushed


# ---- reject ---------------------------------------------------------------

def test_reject_leaves_the_branch_untouched(dsns, repo, task, console):
    before_tip = sh(repo, "git", "rev-parse", task["branch"]).strip()
    before_main = sh(repo, "git", "rev-parse", "main").strip()

    decide.record(task=task["task"], run_id=task["run_id"], verdict="REJECTED",
                  decision="REJECTED_EXCESSIVE_SCOPE", note="did three things",
                  rendered_at=time.time() - 5)

    assert sh(repo, "git", "rev-parse", task["branch"]).strip() == before_tip
    assert sh(repo, "git", "rev-parse", "main").strip() == before_main
    assert console.execute("SELECT status FROM tasks WHERE id=%s",
                           (task["task"]["id"],)).fetchone()["status"] == "REJECTED"


def test_reject_refuses_a_reason_the_database_would_refuse(dsns, task):
    with pytest.raises(decide.VerdictNotRecorded, match="not a reason"):
        decide.record(task=task["task"], run_id=task["run_id"], verdict="REJECTED",
                      decision="REJECTED_BECAUSE_I_SAID_SO", note=None,
                      rendered_at=time.time())


def test_the_offered_reasons_are_the_ones_the_database_permits(dsns):
    """A page offering a value the CHECK constraint refuses is a 500 waiting
    for whoever picks it."""
    assert set(decide.REJECT_REASONS) == decide.reasons_in_database()


# ---- the verdict cannot be recorded twice, or against a moved task --------

def test_a_task_decided_while_the_page_was_open_refuses(dsns, task, console):
    console.execute("UPDATE tasks SET status='REJECTED' WHERE id=%s",
                    (task["task"]["id"],))
    console.commit()
    with pytest.raises(decide.VerdictNotRecorded, match="decided by something else"):
        decide.record(task=task["task"], run_id=task["run_id"], verdict="MERGED",
                      decision="APPROVED", note=None, rendered_at=time.time())


# ---- the reader cannot write ---------------------------------------------

def test_the_reader_connection_cannot_write(dsns):
    """The ROLE refuses, not the session flag.

    Accepting either exception here would let the session flag mask a reader
    DSN pointed at the writer: `conn.read_only = True` produces
    ReadOnlySqlTransaction whoever you are connected as. So this opens the
    reader DSN raw, without the flag, and requires InsufficientPrivilege --
    which only a role lacking the grant can raise.
    """
    import psycopg
    from console import config
    with psycopg.connect(config.console_reader_dsn()) as conn:
        for sql in ("UPDATE tasks SET status='MERGED'",
                    "INSERT INTO run_steps (run_id, sequence, step_type, actor)"
                    " VALUES (1,99,'HUMAN_DECISION','x')"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(sql)
            conn.rollback()


def test_the_reader_session_is_also_read_only(dsns):
    """Belt as well as braces: the grant is the guard, this is the backstop."""
    from console import db
    with db.connect() as conn:
        assert conn.read_only is True


def test_the_writer_is_a_different_principal_from_the_reader(dsns):
    from console import db
    assert db.assert_read_only() != db.assert_can_write()


# ---- accept: driven over the HTTP route -----------------------------------
#
# Every test above calls merge.merge_and_push and decide.record directly. That
# is the right shape for testing a guard -- the guard is the unit -- but it
# means the route body itself had no coverage at all: form parsing, the origin
# check, the re-verification call, the redirect, and the module-level names
# each of those needs.
#
# That gap shipped a NameError. accept() built a Path and console/app.py never
# imported pathlib; every test passed, because none of them executed a single
# line of accept(). A name used in one branch of one route is only proved to
# exist by a request that reaches it.


@pytest.fixture
def trial_root(tmp_path, monkeypatch) -> Path:
    """The trial worktree root, pointed somewhere disposable.

    Set through the environment variable the real config function reads, not
    by patching the function out: the setting is part of what is under test
    here, and a test that replaces it would not notice it being read wrongly.
    """
    root = tmp_path / "trials"
    monkeypatch.setenv("FLEET_CONSOLE_TRIAL_ROOT", str(root))
    return root


@pytest.fixture
def route(dsns, repo, trial_root, monkeypatch):
    """The console as its real ASGI app, pointed at the fixture repository."""
    from console import app as app_module
    monkeypatch.setattr(app_module.config, "repo_root", lambda: repo.parent)
    with TestClient(app_module.app) as c:
        yield c


def post_accept(client, task, **over):
    data = {"branch": task["branch"], "rendered_at": time.time() - 12,
            "note": "looks right"}
    data.update(over.pop("data", {}))
    return client.post(f"/tasks/{task['task']['id']}/accept", data=data,
                       headers=over.pop("headers", {"Origin": "http://testserver"}),
                       follow_redirects=False, **over)


def human_decision(console, run_id):
    row = console.execute(
        "SELECT payload FROM run_steps WHERE run_id=%s AND step_type='HUMAN_DECISION'",
        (run_id,)).fetchone()
    return row["payload"] if row else None


def test_accept_over_the_route_merges_reverifies_and_records(
        dsns, repo, task, console, route, trial_root, origin):
    """The whole route, end to end, as the browser drives it."""
    tid = task["task"]["id"]
    r = post_accept(route, task)
    assert r.status_code == 303, r.text
    assert r.headers["location"] == f"/tasks/{tid}"

    assert console.execute("SELECT status FROM tasks WHERE id=%s",
                           (tid,)).fetchone()["status"] == "MERGED"
    # ON THE REMOTE, not in the checkout: the route publishes the trial and
    # never writes here. The checkout is left behind by exactly this merge,
    # which is stated in the outcome rather than silently repaired.
    assert subprocess.run(["git", "-C", str(origin), "merge-base", "--is-ancestor",
                           task["tip"], "main"]).returncode == 0
    assert subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                           task["branch"], "main"]).returncode != 0

    # The re-verification branch is the one that carried the NameError, so the
    # test is only worth anything if it actually ran. A skipped or absent
    # re-verification would pass every other assertion here.
    reverified = human_decision(console, task["run_id"])["merge"]["reverified"]
    assert reverified is not None and reverified["ok"]
    assert not reverified["skipped_reason"] and not reverified["could_not_run"]
    assert [c["command"] for c in reverified["checks"]] == ["true"]

    # And it really used the configured root, rather than falling back to a
    # location the service is not allowed to write to.
    assert trial_root.exists()


def test_accept_over_the_route_refuses_a_cross_origin_post(
        dsns, repo, task, console, route):
    """The CSRF guard, which is route-only logic and so was also uncovered."""
    tid = task["task"]["id"]
    r = post_accept(route, task, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert console.execute("SELECT status FROM tasks WHERE id=%s",
                           (tid,)).fetchone()["status"] == "READY_FOR_REVIEW"


def test_a_trial_worktree_that_cannot_be_created_refuses_and_says_why(
        dsns, repo, task, console, route, tmp_path, monkeypatch):
    """The environmental failure, which used to be an uncaught 500.

    This is the shape the sandbox produced in production: the trial root was
    somewhere the unit could not write, worktree creation raised, and nothing
    caught it. A 500 tells the reviewer the console is broken. The truth is
    narrower and worth saying -- the merge was not made, and the reason is
    that it could not be checked, which is not the same as it failing a check.
    """
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("")                      # mkdir under a file: OSError
    monkeypatch.setenv("FLEET_CONSOLE_TRIAL_ROOT", str(blocked / "trials"))

    tid = task["task"]["id"]
    r = post_accept(route, task)
    assert r.status_code == 303, r.text         # a refusal, never a 500

    # Nothing happened: not merged, not recorded, branch untouched.
    assert console.execute("SELECT status FROM tasks WHERE id=%s",
                           (tid,)).fetchone()["status"] == "READY_FOR_REVIEW"
    assert human_decision(console, task["run_id"]) is None
    assert subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                           task["branch"], "main"]).returncode != 0

    # And the page says which of the two things went wrong. "the trial never
    # ran" is the distinction being tested: a reviewer who reads this must not
    # go looking at the diff for a conflict or a failing check.
    page = route.get(f"/tasks/{tid}").text
    assert "was NOT re-verified" in page
    assert "the trial never ran" in page
    assert "conflicted and was aborted" not in page


def test_a_trial_that_could_not_run_is_distinct_from_one_that_failed(
        dsns, repo, task, tmp_path):
    """could_not_run and a failing check both refuse, and must not look alike.

    Reported as the same thing, a sandbox misconfiguration sends the reviewer
    to read a diff that is perfectly fine.
    """
    from console import reverify
    t = dict(task["task"])

    cannot = reverify.run(repo, Path("/proc/nonexistent/trials"), t,
                          contract(), task["branch"],
                          recorded_base=task["base_sha"], changed_files=[])
    assert not cannot.ok and cannot.could_not_run
    assert cannot.checks == []                  # nothing ran, so nothing to show

    failed = reverify.run(repo, tmp_path / "trials", t,
                          contract(verification=["false"]), task["branch"],
                          recorded_base=task["base_sha"], changed_files=[])
    assert not failed.ok and not failed.could_not_run
    assert [c["exit_code"] for c in failed.checks] == [1]


# ---- accept: the sandbox the route actually runs inside --------------------
#
# The route can be correct and Accept still fail, because the console runs
# under a systemd sandbox and the trial worktree is a write. That is exactly
# what happened: ProtectHome=read-only made runner.yaml's worktree_root
# unwritable, so the first Accept to reach re-verification died on it.
#
# The unit file is the source of truth for both tests below -- they parse the
# real one rather than restating it, so relaxing or tightening the sandbox is
# reflected here instead of drifting away from here.

UNIT = Path(__file__).resolve().parent.parent / "systemd" / "fleet-console.service"


def unit_settings() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in UNIT.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def test_the_trial_root_is_not_a_path_the_unit_denies():
    """A static tie between the setting and the sandbox, with no sudo needed.

    The sandbox test below is the real proof, but it needs privileges that not
    every checkout has. This one always runs, so pointing the trial root back
    into home fails the suite everywhere rather than only where sudo works.
    """
    from console import config
    root = config.TRIAL_ROOT
    settings = unit_settings()
    writable = [Path(p) for p in settings.get("ReadWritePaths", "").split()]

    if settings.get("ProtectHome") in ("read-only", "yes", "tmpfs"):
        under_home = root == Path("/home") or Path("/home") in root.parents
        granted = any(w == root or w in root.parents for w in writable)
        assert not under_home or granted, (
            f"{root} is under /home, which the unit mounts "
            f"{settings['ProtectHome']}, and no ReadWritePaths entry covers it")

    # /tmp is the intended home for it, and only because PrivateTmp gives the
    # unit its own. Without that the trial would be world-visible scratch.
    if root == Path("/tmp") or Path("/tmp") in root.parents:
        assert settings.get("PrivateTmp") == "true", (
            f"{root} is in /tmp but the unit does not set PrivateTmp")


def sandbox_confinement() -> list[str]:
    settings = unit_settings()
    confinement = [f"-p{k}={settings[k]}"
                   for k in ("ProtectSystem", "ProtectHome", "ReadWritePaths",
                             "PrivateTmp")
                   if k in settings]
    assert confinement, f"{UNIT.name} declares no confinement to test"
    return confinement


@pytest.mark.skipif(
    subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0
    or shutil.which("systemd-run") is None,
    reason="needs passwordless sudo and systemd-run to build the real sandbox")
def test_a_trial_can_be_built_and_merged_under_the_service_sandbox():
    """Build the unit's real sandbox and run the REAL operation inside it.

    THIS TEST USED TO ASSERT A PROXY, and the proxy is why the bug shipped
    green. It ran `mkdir -p <trial_root>/sandbox-probe` -- the half of the
    operation that works -- and concluded the trial root was usable. It was:
    /tmp is writable under PrivateTmp and always was. The half that failed was
    never run, because `git worktree add` also writes into the repository it
    links FROM, and no mkdir under /tmp will ever discover that.

    So this calls create_trial_clone and merges, against the checkout the
    suite is running from -- which is the repository the console may only
    read, and the exact case that failed. A proxy cannot be substituted here
    without deleting the thing being tested.

    Not a re-implementation of the sandbox either: the confinement settings
    are read out of the unit file, so this asserts the property for the
    sandbox that is really deployed.
    """
    from console import config
    project = Path(__file__).resolve().parent.parent
    base = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    # Run it as the console would: the real function, on the real repo, with
    # the real root, inside the real confinement.
    program = (
        "import pathlib, subprocess, sys\n"
        "sys.path.insert(0, %r)\n"
        "from runner import worktree\n"
        "trial, sha = worktree.create_trial_clone("
        "    pathlib.Path(%r), pathlib.Path(%r), 'sandbox-probe', %r)\n"
        "r = subprocess.run(['git', '-C', str(trial), 'merge-base',"
        "                    '--is-ancestor', sha, 'HEAD'])\n"
        "assert r.returncode == 0, 'the trial is not at the base commit'\n"
        "worktree.discard_trial_clone(trial)\n"
        "assert not trial.exists(), 'the trial outlived its own teardown'\n"
        "print('TRIAL OK')\n"
    ) % (str(project), str(project), str(config.TRIAL_ROOT), base)

    r = subprocess.run(
        ["sudo", "systemd-run", "--quiet", "--wait", "--collect", "--pipe",
         "-pUser=ubuntu", f"-pWorkingDirectory={project}", *sandbox_confinement(),
         str(project / ".venv" / "bin" / "python"), "-c", program],
        capture_output=True, text=True)
    assert "TRIAL OK" in r.stdout, (
        f"the console cannot build a trial for a repository it may only read, "
        f"under its own sandbox: {(r.stdout + r.stderr).strip()}")


def test_a_trial_writes_nothing_into_the_repository_it_came_from(repo, tmp_path):
    """The claim reverify.py makes in its own docstring, as an assertion.

    "A FAILURE RECORDS NOTHING AND LEAVES NOTHING" was false for every Accept
    that reached re-verification before 2026-09-09: the trial was a linked
    worktree, so its merge commit and tree were written into the SOURCE
    repository's shared object store, and `git worktree remove` does not take
    them back. Nothing read them, but the docstring was not telling the truth.

    Counting objects rather than inspecting refs, because the leak was
    unreferenced -- a check on refs or on `worktree list` would have passed
    while the objects piled up.
    """
    from runner import worktree

    branch_with_change(repo, "fleet/task-900", body="y = 3\n")
    tip = sh(repo, "git", "rev-parse", "fleet/task-900").strip()
    before_objects = sorted(p.name for p in (repo / ".git" / "objects").rglob("*")
                            if p.is_file())

    trial, sha = worktree.create_trial_clone(repo, tmp_path / "trials",
                                             "leak-probe", "main")
    # The tip by SHA, not by ref name. A clone reaches it as
    # `origin/fleet/task-900` and a linked worktree as `fleet/task-900`, and a
    # test that named either would fail on the NAME when the implementation
    # regressed -- passing off a ref-resolution error as proof about objects.
    # By sha both merge, and the only thing left to differ is the leak.
    merged = subprocess.run(
        ["git", "-C", str(trial), "-c", "user.name=t", "-c", "user.email=t@t",
         "merge", "--no-ff", "--no-edit", tip],
        capture_output=True, text=True)
    assert merged.returncode == 0, merged.stdout + merged.stderr
    worktree.discard_trial_clone(trial)

    after_objects = sorted(p.name for p in (repo / ".git" / "objects").rglob("*")
                           if p.is_file())
    assert after_objects == before_objects, (
        f"the trial merge left {len(after_objects) - len(before_objects)} "
        f"object(s) in {repo}/.git/objects")
    assert not (repo / ".git" / "worktrees").exists(), (
        "the trial registered a worktree in the source repository")


@pytest.mark.skipif(
    subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0
    or shutil.which("systemd-run") is None,
    reason="needs passwordless sudo and systemd-run to build the real sandbox")
def test_the_runners_worktree_root_is_not_writable_under_that_sandbox():
    """The reason the console has a root of its own, kept as an assertion.

    If this ever starts failing, the sandbox has been widened and the separate
    console root is no longer buying anything -- which is worth finding out
    deliberately rather than discovering the grant by accident.
    """
    import yaml
    runner_root = Path(yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "runner.yaml").read_text()
    )["worktree_root"])
    confinement = sandbox_confinement()
    probe = runner_root / "sandbox-probe"
    r = subprocess.run(
        ["sudo", "systemd-run", "--quiet", "--wait", "--collect", "--pipe",
         "-pUser=ubuntu", *confinement,
         "/bin/bash", "-c", f"mkdir -p {probe} && rmdir {probe}"],
        capture_output=True, text=True)
    assert r.returncode != 0, (
        f"{runner_root} is writable under the console's sandbox -- the unit "
        f"has been widened, and console/config.py's reasoning is now stale")


# ---------------------------------------------------------------------------
# The base must agree with its remote, checked BEFORE the merge.
#
# merge_and_push already verified the push against the remote -- after a merge
# commit existed, which is too late to prevent what it detects. Task 26 was
# merged into a local main two commits behind origin/main, produced 39b7844,
# could not push it, and correctly recorded nothing. The refusal was right and
# one step late.
# ---------------------------------------------------------------------------

class TestTheBaseMustAgreeWithItsRemote:
    """The check MOVED into `publish`; it did not go away.

    It used to compare the checkout's base against a remote-TRACKING ref,
    which is only as fresh as the last fetch -- and `merge_and_push` kept it
    fresh by fetching into the checkout, which is a write this module no
    longer makes. It now runs inside the trial clone, against a remote fetched
    seconds earlier, and asks the sharper question: is the commit about to be
    pushed a descendant of what is actually on the remote?
    """

    @staticmethod
    def advance_remote(repo: Path, origin: Path, tmp_path: Path) -> None:
        """Someone else merges a PR: the remote moves, this checkout does not."""
        other = tmp_path / "elsewhere"
        sh_clone = subprocess.run(["git", "clone", "-q", str(origin), str(other)],
                                  capture_output=True)
        assert sh_clone.returncode == 0, sh_clone.stderr
        # The bare origin's HEAD may name a branch that does not exist, so a
        # clone lands detached with no local `main` to push.
        sh(other, "git", "checkout", "-q", "-B", "main", "origin/main")
        sh(other, "git", "config", "user.email", "t@t")
        sh(other, "git", "config", "user.name", "t")
        (other / "unrelated.txt").write_text("someone else's work\n")
        sh(other, "git", "add", "-A")
        sh(other, "git", "commit", "-q", "-m", "PR #3")
        sh(other, "git", "push", "-q", "origin", "main")

    def test_a_remote_that_moved_refuses_before_pushing(
            self, dsns, repo, origin, task, tmp_path, trial):
        """What was verified is a merge into a base that no longer exists."""
        self.advance_remote(repo, origin, tmp_path)
        before = on_remote(origin, "main")
        rv = trial(repo, task)
        assert rv.ok, rv.reason           # the trial itself is fine; the base moved
        r = merge.merge_and_push(repo, task["task"], task["branch"],
                                 task["base_sha"], task["tip"], reverification=rv)
        assert not r.ok
        assert "has moved" in r.reason
        assert "no longer exists" in r.reason
        assert not r.pushed and not r.merged
        assert on_remote(origin, "main") == before, "something was pushed anyway"

    def test_it_does_not_need_the_checkout_to_have_fetched(
            self, dsns, repo, origin, task, tmp_path, trial):
        """The freshness comes from the clone's own fetch.

        `merge_and_push` used to fetch into the checkout so its divergence
        check saw the truth. That fetch was a write, and it is gone. This is
        the same scenario with the checkout deliberately never fetched: the
        refusal must still happen, because the question is now asked somewhere
        the console is allowed to write.
        """
        self.advance_remote(repo, origin, tmp_path)
        stale = sh(repo, "git", "rev-parse", "origin/main").strip()
        rv = trial(repo, task)
        r = merge.merge_and_push(repo, task["task"], task["branch"],
                                 task["base_sha"], task["tip"], reverification=rv)
        assert not r.ok and "has moved" in r.reason
        # Proof the checkout really was never refreshed by any of this.
        assert sh(repo, "git", "rev-parse", "origin/main").strip() == stale

    def test_a_base_merely_AHEAD_of_its_remote_is_not_refused(
            self, dsns, repo, origin, task, trial):
        """Ahead is unpushed work, not a defect.

        The verified merge descends from what is on the remote, so it is a
        legitimate fast-forward and the local commits go up with it.
        """
        (repo / "local-only.txt").write_text("not pushed\n")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-q", "-m", "local work")
        rv = trial(repo, task)
        r = merge.merge_and_push(repo, task["task"], task["branch"],
                                 task["base_sha"], task["tip"], reverification=rv)
        assert r.ok, r.reason
        assert on_remote(origin, "main") == rv.merged_sha

    def test_a_base_with_no_branch_on_the_remote_yet_is_created(
            self, dsns, repo, origin, task, trial):
        """fleet's own base branches are not all on its remote.

        Refusing here would make those tasks unmergeable; the push simply
        creates the branch, and says that is what it did.
        """
        sh(origin, "git", "update-ref", "-d", "refs/heads/main")
        rv = trial(repo, task)
        r = merge.merge_and_push(repo, task["task"], task["branch"],
                                 task["base_sha"], task["tip"], reverification=rv)
        assert r.ok, r.reason
        assert any("creates it" in d for d in r.detail)
        assert on_remote(origin, "main") == rv.merged_sha

    def test_count_itself_returns_none_when_git_fails(self, repo):
        """"I could not look" must not be identical to "they agree".

        `_count` no longer stands between a merge and a push -- the guard is
        `merge-base --is-ancestor`, and _count only supplies a number for the
        message. The property is still worth keeping: a 0 here would read as
        "in sync" in a sentence a person acts on.
        """
        assert merge._count(repo, "no-such-ref..also-missing") is None
        assert merge._count(repo, "HEAD..HEAD") == 0


# ---------------------------------------------------------------------------
# decided_via: who performed the merge, which is a third question again.
#
# MERGED_OUTSIDE was proposed as a status and does not exist. MERGED is read in
# fourteen places across eight files; a status every reader must learn is a
# large change to say something the payload can say. The task IS merged, so
# tasks.status says MERGED and the provenance lives here.
# ---------------------------------------------------------------------------

class TestDecidedVia:

    def test_it_defaults_to_console(self, dsns, repo, task, console):
        out = decide.record(task=task["task"], run_id=task["run_id"],
                            verdict="MERGED", decision=decide.ACCEPT_DECISION,
                            note="", rendered_at=time.time())
        assert out["decided_via"] == "console"

    def test_a_hand_merge_can_be_recorded_as_one(self, dsns, repo, task,
                                                 console):
        out = decide.record(task=task["task"], run_id=task["run_id"],
                            verdict="MERGED", decision=decide.ACCEPT_DECISION,
                            note="merged by hand", rendered_at=time.time(),
                            decided_via="by_hand")
        assert out["decided_via"] == "by_hand"
        row = console.execute(
            "SELECT payload FROM run_steps WHERE run_id=%s AND"
            " step_type='HUMAN_DECISION'", (task["run_id"],)).fetchone()
        assert row["payload"]["decided_via"] == "by_hand"

    def test_an_unknown_value_is_refused(self, dsns, repo, task):
        with pytest.raises(decide.VerdictNotRecorded) as exc:
            decide.record(task=task["task"], run_id=task["run_id"],
                          verdict="MERGED", decision=decide.ACCEPT_DECISION,
                          note="", rendered_at=time.time(),
                          decided_via="somehow")
        assert "not a way a decision can be arrived at" in str(exc.value)

    def test_the_status_is_MERGED_either_way(self, dsns, repo, task, console):
        """The task is merged. Provenance is not a status.

        A new status would have to be learnt by decision_outcomes'
        task_outcome and attempts_to_green, decide.py's whitelist, four places
        in morning.py, three templates, outcomes.py and precedent.py -- all to
        record something one payload field carries.
        """
        decide.record(task=task["task"], run_id=task["run_id"],
                      verdict="MERGED", decision=decide.ACCEPT_DECISION,
                      note="", rendered_at=time.time(), decided_via="by_hand")
        status = console.execute("SELECT status FROM tasks WHERE id=%s",
                                 (task["task"]["id"],)).fetchone()["status"]
        assert status == "MERGED"

    def test_the_payload_can_name_a_discarded_commit(self, dsns, repo, task,
                                                     console):
        """A payload naming only the survivor reads as though the console
        never merged. It did; the commit was built and thrown away."""
        decide.record(task=task["task"], run_id=task["run_id"],
                      verdict="MERGED", decision=decide.ACCEPT_DECISION,
                      note="", rendered_at=time.time(), decided_via="by_hand",
                      merge={"merge_commit": "a" * 40,
                             "console_merge_commit": "b" * 40,
                             "console_merge_discarded": True})
        p = console.execute(
            "SELECT payload FROM run_steps WHERE run_id=%s AND"
            " step_type='HUMAN_DECISION'", (task["run_id"],)).fetchone()["payload"]
        assert p["merge"]["console_merge_commit"] == "b" * 40
        assert p["merge"]["console_merge_discarded"] is True

    def test_an_unattended_decision_cannot_claim_a_review(self, dsns, repo, task):
        """decision_seconds is how long a REVIEW took. There was no review, so
        a rendered_at would be a duration measured against a page nobody
        rendered — the same defect as sent_at on a row nothing sent."""
        with pytest.raises(decide.VerdictNotRecorded) as e:
            decide.record(task=task["task"], run_id=task["run_id"],
                          verdict="MERGED", decision="APPROVED", note=None,
                          rendered_at=time.time(), decided_via="unattended",
                          gates={"test_bit": True})
        assert "no page and no review" in str(e.value)

    def test_an_unattended_decision_must_carry_its_gates(self, dsns, repo, task):
        """A merge nobody watched with no record of what was checked is
        unreviewable afterwards."""
        with pytest.raises(decide.VerdictNotRecorded) as e:
            decide.record(task=task["task"], run_id=task["run_id"],
                          verdict="MERGED", decision="APPROVED", note=None,
                          rendered_at=None, decided_via="unattended", gates=None)
        assert "must carry its gates" in str(e.value)

    def test_an_unattended_decision_cannot_carry_a_note(self, dsns, repo, task):
        """`note` is where a person says why. Nobody did."""
        with pytest.raises(decide.VerdictNotRecorded):
            decide.record(task=task["task"], run_id=task["run_id"],
                          verdict="MERGED", decision="APPROVED",
                          note="looks fine to me", rendered_at=None,
                          decided_via="unattended", gates={"test_bit": True})

    def test_an_unattended_merge_records_null_seconds_and_its_gates(
            self, dsns, repo, task, console):
        out = decide.record(
            task=task["task"], run_id=task["run_id"], verdict="MERGED",
            decision="APPROVED", note=None, rendered_at=None,
            decided_via="unattended",
            gates={"test_bit": True, "reviewed_by_a_person": False})
        assert out["decided_via"] == "unattended"
        assert out["decision_seconds"] is None
        assert out["note"] is None
        row = console.execute(
            "SELECT payload FROM run_steps WHERE run_id=%s AND"
            " step_type='HUMAN_DECISION'", (task["run_id"],)).fetchone()
        assert row["payload"]["gates"]["reviewed_by_a_person"] is False
        assert row["payload"]["decision_seconds"] is None
        # waited_seconds is REAL — the task did sit there.
        assert row["payload"]["waited_seconds"] > 1700
