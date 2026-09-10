"""024: both files or neither.

Two halves, and they fail differently.

  the DATABASE refuses a group that cannot bite -- a path outside
  writable_paths, fewer than two paths, or no `why`. Those are all shapes that
  would sit in a verification list looking like a gate while passing
  unconditionally, which is this codebase's recurring failure rather than a
  new one.

  the CHECK refuses a diff that landed half a group.

The trigger's behaviour is also asserted in 024_paired_paths_assertions.sql
against real task rows; what is here is the Python-visible half plus the check
script, which the SQL cannot reach.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from tests.support import PLATFORM_FLOOR

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "contracts" / "checks" / "paired_paths.py"
REPO = "deadly-digital-platform"

PROXY = "platform/app/api/analytics/dashboard/route.ts"
PAGE = "platform/app/(dashboard)/analytics/page.tsx"


def contract(**over) -> dict:
    c = {
        "work_type": "dd_frontend",
        "repo": REPO,
        "base_branch": "main",
        "writable_paths": ["platform/app/api/analytics/dashboard/**",
                           PAGE],
        "protected_paths": list(PLATFORM_FLOOR),
        "verification": ["true"],
        "max_diff_lines": 200,
        "max_cost_gbp": 3.00,
    }
    c.update(over)
    return c


def add(console, **over) -> int:
    fields = {"title": "t", "spec_md": "# t", "repo": REPO, "base_branch": "main",
              "acceptance_contract": json.dumps(contract(**over)),
              "max_cost_gbp": "3.00"}
    row = console.execute(
        "INSERT INTO tasks (title, spec_md, repo, base_branch,"
        " acceptance_contract, max_cost_gbp)"
        " VALUES (%(title)s, %(spec_md)s, %(repo)s, %(base_branch)s,"
        " %(acceptance_contract)s, %(max_cost_gbp)s) RETURNING id",
        fields).fetchone()
    console.commit()
    return row["id"]


GOOD = [{"why": "the proxy widening and the label must land together",
         "paths": [PROXY, PAGE]}]


# ---- what the database refuses --------------------------------------------

def test_a_well_formed_pair_is_accepted(dsns, console):
    assert add(console, paired_paths=GOOD) > 0


def test_a_contract_with_no_pairs_is_unaffected(dsns, console):
    """This key adds a rule for the contracts that use it and changes nothing
    for the ones that do not. Every other contract in contracts/ is one."""
    assert add(console) > 0


def test_a_pair_reaching_outside_writable_paths_is_refused(dsns, console):
    """The check-that-cannot-fail, and it is the whole reason the database
    knows about this key.

    A path the task may not write is never in the diff, so "both or neither" is
    satisfiable only by writing neither -- forever, green, while reading as a
    gate that forces two files to move together. A typo does the same thing and
    looks identical.
    """
    with pytest.raises(psycopg.errors.RaiseException,
                       match="not inside any writable path"):
        add(console, paired_paths=[
            {"why": "looks right", "paths": [PROXY,
                                             "platform/components/ui/card.tsx"]}])


def test_a_group_of_one_is_refused(dsns, console):
    with pytest.raises(psycopg.errors.RaiseException,
                       match="fewer than two paths"):
        add(console, paired_paths=[{"why": "alone", "paths": [PROXY]}])


def test_a_group_with_no_why_is_refused(dsns, console):
    """The refusal text is what the agent reads. Without a `why` it is told
    that something is wrong and not what to do, and what it does then is drop
    one of the two files and try again."""
    with pytest.raises(psycopg.errors.RaiseException, match="has no why"):
        add(console, paired_paths=[{"paths": [PROXY, PAGE]}])


def test_an_empty_why_is_refused_like_a_missing_one(dsns, console):
    with pytest.raises(psycopg.errors.RaiseException, match="has no why"):
        add(console, paired_paths=[{"why": "   ", "paths": [PROXY, PAGE]}])


# ---- what the check refuses -----------------------------------------------

def sh(cwd, *args) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    sh(r, "git", "init", "-q", "-b", "main")
    sh(r, "git", "config", "user.email", "t@t")
    sh(r, "git", "config", "user.name", "t")
    for p in (PROXY, PAGE, "platform/app/api/analytics/orders/route.ts"):
        f = r / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("// base\n")
    sh(r, "git", "add", "-A")
    sh(r, "git", "commit", "-q", "-m", "base")
    return r


def base_sha(repo: Path) -> str:
    return sh(repo, "git", "rev-parse", "HEAD").stdout.strip()


def commit(repo: Path, paths: list[str]) -> None:
    for p in paths:
        (repo / p).write_text("// changed\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "change")


def run_check(repo: Path, base: str, contract_json: str | None,
              ) -> subprocess.CompletedProcess:
    env = dict(os.environ, FLEET_BASE_SHA=base)
    if contract_json is None:
        env.pop("FLEET_CONTRACT", None)
    else:
        env["FLEET_CONTRACT"] = contract_json
    return subprocess.run(["python3", str(CHECK)], cwd=repo, env=env,
                          capture_output=True, text=True)


PAIRED = json.dumps({"paired_paths": GOOD})


def test_both_halves_landing_passes(repo):
    base = base_sha(repo)
    commit(repo, [PROXY, PAGE])
    r = run_check(repo, base, PAIRED)
    assert r.returncode == 0, r.stdout
    assert "1 landed whole" in r.stdout


def test_half_a_pair_is_refused_and_names_the_missing_file(repo):
    base = base_sha(repo)
    commit(repo, [PROXY])
    r = run_check(repo, base, PAIRED)
    assert r.returncode == 1
    assert f"MISSING  {PAGE}" in r.stdout
    assert "the proxy widening and the label must land together" in r.stdout


def test_the_other_half_is_refused_too(repo):
    """Not symmetric by accident: widening the proxy alone is the failure the
    spec describes, and changing the page alone is a label describing a mode
    the proxy cannot request."""
    base = base_sha(repo)
    commit(repo, [PAGE])
    r = run_check(repo, base, PAIRED)
    assert r.returncode == 1
    assert f"MISSING  {PROXY}" in r.stdout


def test_touching_neither_passes_and_says_it_established_nothing(repo):
    base = base_sha(repo)
    commit(repo, ["platform/app/api/analytics/orders/route.ts"])
    r = run_check(repo, base, PAIRED)
    assert r.returncode == 0, r.stdout
    assert "No group was touched" in r.stdout


def test_a_deletion_counts_as_touching_the_file(repo):
    """FLEET_CHANGED_FILES drops deletions, which is why this check asks git
    itself rather than reading that variable.

    Deleting one half and leaving the other alone is a half-landed change, and
    a check built on FLEET_CHANGED_FILES would see nothing at all and pass.
    """
    base = base_sha(repo)
    (repo / PAGE).unlink()
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-q", "-m", "delete one half")
    r = run_check(repo, base, PAIRED)
    assert r.returncode == 1, r.stdout
    assert f"MISSING  {PROXY}" in r.stdout


def test_no_contract_is_could_not_run_not_a_pass(repo):
    base = base_sha(repo)
    commit(repo, [PROXY])
    r = run_check(repo, base, None)
    assert r.returncode == 2
    assert "FLEET_CONTRACT is not set" in r.stdout


def test_a_contract_declaring_no_pairs_is_could_not_run(repo):
    """A contract that runs this check and declares nothing has a gate in its
    verification list that cannot fail. Refused as could-not-run, which
    verify.Verification and console.automerge both read as "nothing was
    established" rather than as a pass."""
    base = base_sha(repo)
    commit(repo, [PROXY])
    r = run_check(repo, base, json.dumps({"paired_paths": []}))
    assert r.returncode == 2
    assert "nothing for this check to establish" in r.stdout


def test_no_base_sha_is_could_not_run(repo):
    commit(repo, [PROXY])
    env = dict(os.environ, FLEET_CONTRACT=PAIRED)
    env.pop("FLEET_BASE_SHA", None)
    r = subprocess.run(["python3", str(CHECK)], cwd=repo, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert "FLEET_BASE_SHA is not set" in r.stdout


# ---- and the contract that uses it ----------------------------------------

#: The second group, added 10 Sep 2026. The orders proxy forwards six
#: parameters and api/analytics/routes/orders.py has accepted four more since
#: task 2, so the page half alone ships controls that appear to work.
ORDERS_PROXY = "platform/app/api/analytics/orders/route.ts"
ORDERS_PAGE = "platform/app/(dashboard)/analytics/orders/page.tsx"


def _shipped_groups():
    import yaml
    c = yaml.safe_load(
        (ROOT / "contracts" / "dd-analytics-frontend.yaml").read_text())
    return c["paired_paths"], c["writable_paths"]


def _group_for(groups, *paths):
    """The group naming exactly these paths, or None.

    Found BY ITS PATHS rather than by position. This test asserted
    `len(groups) == 1` and indexed `groups[0]`, so adding a second group failed
    it -- not for a pairing being wrong, but for a pairing being new. That is
    the same defect test_every_shipped_contract_matches_the_repo_it_names had:
    a rule written against the cases that happened to exist, refusing the next
    one for arriving.
    """
    want = sorted(paths)
    return next((g for g in groups if sorted(g.get("paths") or []) == want), None)


def test_the_shipped_contract_pairs_the_two_files_task_28_named():
    groups, _ = _shipped_groups()
    g = _group_for(groups, PROXY, PAGE)
    assert g is not None, "the dashboard pair is not in the contract"
    assert g["why"].strip()


def test_the_shipped_contract_pairs_the_orders_proxy_and_page():
    """The half that is dangerous is the PAGE half, which is why this exists.

    The proxy alone accepts parameters nothing sends and changes nothing a user
    sees. The page alone renders four filter controls, the proxy drops what
    they set, and the table returns every row with a summary that agrees with
    it -- a control wired to nothing, which is worse than a control that is
    missing because the missing one is visible.

    tsc and vitest cannot catch that: both halves compile, and the page's own
    tests pass against a proxy that ignores the parameters.
    """
    groups, _ = _shipped_groups()
    g = _group_for(groups, ORDERS_PROXY, ORDERS_PAGE)
    assert g is not None, "the orders pair is not in the contract"
    assert g["why"].strip()


def test_every_shipped_group_could_actually_bite():
    """024's own rules, held against the file rather than only the database.

    The trigger refuses these at INSERT, which is one task too late to be a
    useful place to find out: the contract is edited by a person queueing work,
    and this fails in the suite they run before they queue it.
    """
    groups, writable = _shipped_groups()
    prefixes = [w.split("*", 1)[0].rstrip("/") for w in writable]
    for i, g in enumerate(groups, 1):
        assert len(g.get("paths") or []) >= 2, f"group {i} pairs nothing"
        assert (g.get("why") or "").strip(), f"group {i} has no why"
        for path in g["paths"]:
            assert any(path == pre or path.startswith(pre + "/")
                       for pre in prefixes), (
                f"group {i} names {path}, which is outside writable_paths -- "
                f"the task cannot write it, so the pair is satisfied by "
                f"writing neither and the check cannot fail")


def test_the_shipped_contract_does_not_merge_unattended():
    """paired_paths.py establishes that both files moved. It cannot establish
    that the label is right, and that is the one thing the pairing exists for.
    Until a spec has run under this a few times, a person looks."""
    import yaml
    c = yaml.safe_load(
        (ROOT / "contracts" / "dd-analytics-frontend.yaml").read_text())
    assert c["auto_merge"] is False
