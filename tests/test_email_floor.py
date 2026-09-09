"""The email floor: Fleet does not go near email, as a refusal.

specs/unattended-operation.md §2. These are the checks that do not need a
database — the trigger's own behaviour is asserted in
`017_email_floor_assertions.sql`, against a real task row.

WHY THE NEW-FILE GUARD IS NOT A SEPARATE CHECK

§2.3 of the spec proposed a check refusing any diff that ADDS an email-domain
file, because a floor lists paths that exist and cannot stop
`api/services/email_sender_v2.py` being created.

Enumerating `writable_paths` removed the need for it. `runner.boundary.enforce`
refuses any changed path matching no writable glob, and with no wildcard in the
list there is no path an agent can create that matches one. The guard is
redundant *while the list stays enumerated*, so the test that matters is the
one asserting it stays that way — `test_no_wildcard_in_writable_paths` below.
Reintroduce a glob and that test fails, naming the guard as the thing now owed.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "contracts" / "deadly-digital-platform-api.yaml"
PLATFORM = Path("/home/ubuntu/deadly-digital-platform")

from tests.support import PLATFORM_FLOOR

#: The five globs 017 puts on protected_path_floor for the EMAIL surface.
#: Kept separate from PLATFORM_FLOOR because the email-specific assertions are
#: about these and not about the erasure paths 018/019 added beside them.
EMAIL_FLOOR = [
    "api/app.py",
    "api/services/email_sender.py",
    "api/worker.py",
    "api/analytics/routes/interventions.py",
    "api/analytics/services/trigger_router.py",
]

#: The WHOLE floor, for the checks that are about reachability rather than
#: about email. This was a second copy of the floor until 018 added a glob to
#: one and not the other -- the same duplication PLATFORM_FLOOR exists to end.
FLOOR = PLATFORM_FLOOR


@pytest.fixture(scope="module")
def contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text())


def test_the_floor_is_in_the_migration():
    """The globs the contract must carry are the ones 017 actually inserts."""
    sql = (ROOT / "017_email_floor.sql").read_text()
    for glob in EMAIL_FLOOR:
        assert f"'{glob}'" in sql, f"017 does not floor {glob}"


def test_every_floored_path_is_protected_by_the_contract(contract):
    """Otherwise no task using this contract can be created at all.

    The database refuses it — `contract for X does not protect Y` — so this
    test exists to make that a failure at review rather than at 03:00.
    """
    missing = [g for g in FLOOR if g not in contract["protected_paths"]]
    assert not missing, f"the contract does not protect {missing}"


def test_no_floored_path_is_writable(contract):
    """The half of the floor that holds for work already in flight."""
    bad = [w for w in contract["writable_paths"] if w in FLOOR]
    assert not bad, f"the contract makes floored paths writable: {bad}"


def test_no_wildcard_in_writable_paths(contract):
    """The property that makes §2.3's new-file guard unnecessary.

    A wildcard here lets an agent CREATE a file nobody enumerated, including
    one whose name says email. If this test fails, either restore the
    enumeration or build the guard the spec describes — but not neither.
    """
    globbed = [w for w in contract["writable_paths"] if "*" in w]
    assert not globbed, (
        f"{globbed} is a wildcard, so an unenumerated file can be created. "
        f"specs/unattended-operation.md §2.3 owes a new-file guard if this "
        f"is intentional.")


def test_app_py_is_not_writable(contract):
    """19,300 lines, 180 endpoints, 39 of them email. The whole reason for §2."""
    assert "api/app.py" not in contract["writable_paths"]


def test_api_services_is_not_writable(contract):
    """It holds email_sender.py and template_renderer.py, which renders email
    templates and injects open-tracking pixels."""
    assert not [w for w in contract["writable_paths"]
                if w.startswith("api/services/")]


@pytest.mark.skipif(not PLATFORM.exists(), reason="platform checkout not present")
def test_every_writable_path_resolves(contract):
    """An enumerated list can go stale in a way a glob cannot.

    A path that no longer exists is not a security problem, but it is a task
    that fails on a boundary violation for a file the spec was right about.
    """
    missing = [w for w in contract["writable_paths"] if not (PLATFORM / w).exists()]
    assert not missing, f"writable paths that no longer exist: {missing}"


@pytest.mark.skipif(not PLATFORM.exists(), reason="platform checkout not present")
def test_the_enumeration_covers_the_analytics_tree_it_claims_to(contract):
    """Every analytics route and service is either writable or floored.

    Enumeration's failure mode is silent omission: a file that is neither
    writable nor floored is simply unreachable, and the next spec naming it
    fails a boundary check for a reason nobody wrote down.
    """
    writable = set(contract["writable_paths"])
    floored = set(FLOOR)
    for d in ("api/analytics/routes", "api/analytics/services"):
        for p in sorted((PLATFORM / d).glob("*.py")):
            if p.name == "__init__.py":
                continue
            rel = str(p.relative_to(PLATFORM))
            assert rel in writable or rel in floored, (
                f"{rel} is neither writable nor floored — it is unreachable, "
                f"and nothing says why")
