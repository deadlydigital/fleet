"""Accept and reject: the two writes the console has.

Every test here builds a real git repository and drives the real database as
the real roles. A merge guard tested against a mocked git proves the mock
agrees with the guard, which is not the property anyone needs.

The guards are additionally verified by reversion -- see
test_reverting_guards.py -- because a guard whose test passes when the guard
is deleted is not testing the guard.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from console import decide, merge

REPO = "deadly-digital-platform"
FLOOR = ["api/tests/**", "api/pytest.ini", "api/ruff.toml", "api/alembic/**",
         "api/analytics/migrations/**", "platform/__tests__/**",
         "platform/vitest.config.ts", "platform/playwright.config.ts"]


def contract(**over) -> dict:
    c = {"work_type": "dd_feature", "repo": REPO, "base_branch": "main",
         "contract_version": 1, "writable_paths": ["api/app.py"],
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
    (r / "api" / "app.py").write_text("x = 1\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-q", "-m", "base")
    sh(r, "git", "remote", "add", "origin", str(origin))
    sh(r, "git", "push", "-q", "-u", "origin", "main")
    return r


def branch_with_change(repo: Path, name: str, body: str = "x = 2\n",
                       path: str = "api/app.py") -> tuple[str, str]:
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
                          "files_changed": ["api/app.py"], "diff_lines": 1})))
    runner.execute(
        "UPDATE tasks SET status='READY_FOR_REVIEW', branch_name=%s,"
        " completed_at=now() - interval '30 minutes' WHERE id=%s", (branch, tid))
    runner.commit()
    row = console.execute("SELECT * FROM tasks WHERE id=%s", (tid,)).fetchone()
    return {"task": row, "run_id": rid, "branch": branch,
            "base_sha": base_sha, "tip": tip}


# ---- accept: the happy path ----------------------------------------------

def test_accept_merges_pushes_and_verifies(dsns, repo, task, console):
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"])
    assert r.ok, r.reason
    assert r.merged and r.pushed and r.push_verified
    assert r.remote_sha == r.base_sha_after
    # the branch really is in main now
    assert subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                           task["branch"], "main"]).returncode == 0

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


def test_a_dirty_working_tree_refuses(dsns, repo, task):
    (repo / "api" / "app.py").write_text("uncommitted\n")
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"])
    assert not r.ok
    # Anchored, not a substring search: the conflict message also contains the
    # words "not clean", so `in r.reason` passed even with this guard removed.
    assert r.reason.startswith("the working tree is not clean")
    assert not r.merged and not r.pushed


def test_a_checkout_on_another_branch_refuses(dsns, repo, task):
    sh(repo, "git", "checkout", "-q", "-b", "somewhere-else")
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"])
    assert not r.ok and "Refusing to switch" in r.reason


def test_a_branch_whose_tip_moved_is_refused(dsns, repo, task):
    """The primary guard is now the tip, not the merge base: it is the check
    that says "this is the code that was verified", and it catches a commit
    appended after verification, which the merge-base check did not."""
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], recorded_patch="0" * 40)
    assert not r.ok and "not what was checked" in r.reason
    assert not r.merged


def test_a_conflicting_merge_records_nothing_and_leaves_the_tree_clean(
        dsns, repo, task, console):
    # main changes the same line the branch changed
    (repo / "api" / "app.py").write_text("x = 99\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "conflicting change on main")

    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"])
    assert not r.ok
    assert "conflicted" in r.reason
    assert not r.pushed
    assert sh(repo, "git", "status", "--porcelain").strip() == "", \
        "a conflicted merge left the working tree dirty"
    assert console.execute(
        "SELECT status FROM tasks WHERE id=%s",
        (task["task"]["id"],)).fetchone()["status"] == "READY_FOR_REVIEW"
    assert console.execute(
        "SELECT count(*) AS n FROM run_steps WHERE run_id=%s"
        " AND step_type='HUMAN_DECISION'", (task["run_id"],)).fetchone()["n"] == 0


def test_a_push_that_did_not_land_is_caught(dsns, repo, task, monkeypatch, console):
    """`git push` exiting 0 is a claim. The guard re-reads the remote.

    The happy-path test cannot prove this one: there the push really does
    land, so removing the check changes nothing. Here the remote is made to
    disagree, which is the only shape in which the guard matters.
    """
    real_sha = merge._sha

    def lying_sha(r, ref):
        if ref.startswith("origin/"):
            return "0" * 40
        return real_sha(r, ref)

    monkeypatch.setattr(merge, "_sha", lying_sha)
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"])
    assert not r.ok
    assert "reported success" in r.reason
    assert not r.push_verified
    assert console.execute(
        "SELECT count(*) AS n FROM run_steps WHERE run_id=%s"
        " AND step_type='HUMAN_DECISION'", (task["run_id"],)).fetchone()["n"] == 0


def test_a_merge_that_could_not_run_is_not_reported_as_a_conflict(
        dsns, repo, task, monkeypatch, console):
    """The failure mode that actually happened in production.

    ProtectSystem=strict left the repo read-only, git said "cannot lock ref
    'ORIG_HEAD': Read-only file system", and it was reported as a conflict --
    sending the reader to look at the diff instead of at the sandbox.
    """
    real = merge._git

    def failing_git(r, *args, **kw):
        # the real call is _git(repo, "-c", ..., "-c", ..., "merge", ...),
        # so match on membership rather than on the first argument
        if "merge" in args and "--abort" not in args:
            return subprocess.CompletedProcess(
                args, 128, "",
                "fatal: cannot lock ref 'ORIG_HEAD': Read-only file system")
        return real(r, *args, **kw)

    monkeypatch.setattr(merge, "_git", failing_git)
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"])
    assert not r.ok
    assert "not a conflict" in r.reason
    assert "conflicted" not in r.reason
    assert any("Read-only file system" in d for d in r.detail)
    assert not r.merged and not r.pushed
    assert console.execute(
        "SELECT count(*) AS n FROM run_steps WHERE run_id=%s"
        " AND step_type='HUMAN_DECISION'", (task["run_id"],)).fetchone()["n"] == 0


# ---- accept: the already-merged path -------------------------------------

def test_an_already_merged_branch_records_without_merging(dsns, repo, task):
    sh(repo, "git", "merge", "-q", "--no-ff", "--no-edit", task["branch"])
    r = merge.merge_and_push(repo, task["task"], task["branch"],
                             task["base_sha"], task["tip"])
    assert r.ok, r.reason
    assert r.already_merged and not r.merged
    assert any("no merge is required" in d for d in r.detail)


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
        dsns, repo, task, console, route, trial_root):
    """The whole route, end to end, as the browser drives it."""
    tid = task["task"]["id"]
    r = post_accept(route, task)
    assert r.status_code == 303, r.text
    assert r.headers["location"] == f"/tasks/{tid}"

    assert console.execute("SELECT status FROM tasks WHERE id=%s",
                           (tid,)).fetchone()["status"] == "MERGED"
    assert subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                           task["branch"], "main"]).returncode == 0

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
