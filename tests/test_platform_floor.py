"""023: the platform tree gets a floor before it gets a contract.

The trigger's own behaviour is asserted in `023_platform_floor_assertions.sql`
against real task rows. These are the checks that need no database: that the
migration and the contracts agree, and that the enumeration
contracts/dd-analytics-frontend.yaml pays for is actually complete.

WHY THE ENUMERATION NEEDS A TEST OF ITS OWN

The frontend contract lists analytics directories one by one because 023 floors
the intervention surface inside that tree, and a floored path inside a globbed
one is a contradiction the database refuses. The cost of that is a list that
goes stale: a new directory under app/api/analytics is, silently, neither
writable nor floored -- and "outside every writable path" is a refusal a task
hits at the end of a run rather than when it is queued.

`test_every_analytics_directory_is_classified` is what turns that into a failing
test here instead. It is the same defect the migration list in
schema-drift-check.sh had twice, and it is fixed the same way: derive, do not
type.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "contracts" / "dd-analytics-frontend.yaml"
PLATFORM = Path("/home/ubuntu/deadly-digital-platform")

from tests.support import PLATFORM_FLOOR

#: What 023 adds, as opposed to the whole floor. These are the ones the
#: assertions below are about.
PLATFORM_023 = [g for g in PLATFORM_FLOOR
                if g.startswith("platform/")
                and g not in ("platform/__tests__/**", "platform/vitest.config.ts",
                              "platform/playwright.config.ts")]


@pytest.fixture(scope="module")
def contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text())


def test_the_floor_is_in_the_migration():
    """The globs the contracts must carry are the ones 023 actually inserts."""
    sql = (ROOT / "023_platform_floor.sql").read_text()
    for glob in PLATFORM_023:
        assert f"'{glob}'" in sql, f"023 does not floor {glob}"


def test_the_migration_floors_nothing_the_shared_list_does_not_know_about():
    """The other direction, which is the one that rots quietly.

    A glob added to 023 and not to tests/support.PLATFORM_FLOOR makes every
    fixture in this suite build a contract the database refuses, and the
    failure appears in a hundred tests that are about something else. 017 cost
    exactly that.
    """
    sql = (ROOT / "023_platform_floor.sql").read_text()
    inserted = set(re.findall(r"\('deadly-digital-platform',\s*'([^']+)'", sql))
    assert inserted - set(PLATFORM_FLOOR) == set(), \
        "023 floors globs tests/support.PLATFORM_FLOOR does not carry"


def test_middleware_is_floored():
    """The one a path list misses.

    platform/middleware.ts is not under app/, components/ or lib/, so the
    retired contract's three globs missed it -- by accident, not by design. It
    decides which requests reach an authenticated route at all.
    """
    assert "platform/middleware.ts" in PLATFORM_FLOOR


def test_every_floored_path_is_protected_by_the_contract(contract):
    missing = [g for g in PLATFORM_FLOOR if g not in contract["protected_paths"]]
    assert missing == [], f"the frontend contract does not protect {missing}"


def test_no_floored_path_is_writable(contract):
    """Prefix containment, the same comparison enforce_contract_floor() makes."""
    def prefix(g: str) -> str:
        return re.sub(r"\*.*$", "", g).rstrip("/")

    breaches = [
        f"{w} reaches {f}"
        for w in contract["writable_paths"] for f in PLATFORM_FLOOR
        if prefix(w) and prefix(f)
        and (prefix(w) == prefix(f)
             or prefix(f).startswith(prefix(w) + "/")
             or prefix(w).startswith(prefix(f) + "/"))
    ]
    assert breaches == [], f"the contract writes where the floor forbids: {breaches}"


def test_only_the_frontend_is_writable(contract):
    outside = [g for g in contract["writable_paths"]
               if not g.startswith("platform/")]
    assert outside == [], \
        f"this contract verifies with tsc and vitest, so {outside} is unverifiable"


def test_no_shared_ui_primitive_is_writable(contract):
    """components/ui/** renders on billing, campaigns and subscribers too, and
    ten analytics render tests would not show what a change there did to them.
    Verification scope and writable scope must match."""
    shared = [g for g in contract["writable_paths"]
              if g.startswith("platform/components/") and "/analytics/" not in g]
    assert shared == [], f"{shared} is shared across the app, not analytics-only"


@pytest.mark.skipif(not PLATFORM.exists(), reason="platform not checked out")
def test_every_writable_path_resolves(contract):
    def prefix(g: str) -> str:
        return re.sub(r"\*.*$", "", g).rstrip("/")

    missing = [g for g in contract["writable_paths"]
               if not (PLATFORM / prefix(g)).exists()]
    assert missing == [], f"the contract names paths that do not exist: {missing}"


@pytest.mark.skipif(not PLATFORM.exists(), reason="platform not checked out")
@pytest.mark.parametrize("tree", ["platform/app/api/analytics",
                                  "platform/app/(dashboard)/analytics"])
def test_every_analytics_directory_is_classified(contract, tree):
    """Every directory in the analytics trees is writable or floored, never
    neither.

    Neither is the silent state: the task is queued, the agent writes the file,
    and the boundary refuses it as "outside every writable path" at the end of a
    run that has already been paid for.
    """
    def prefix(g: str) -> str:
        return re.sub(r"\*.*$", "", g).rstrip("/")

    writable = {prefix(g) for g in contract["writable_paths"]}
    floored = {prefix(g) for g in PLATFORM_FLOOR}

    root = PLATFORM / tree
    unclassified = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        # Dynamic segments belong to their parent, which is already classified.
        if d.name.startswith("["):
            continue
        rel = f"{tree}/{d.name}"
        covered = any(rel == c or rel.startswith(c + "/") or c.startswith(rel + "/")
                      for c in writable | floored)
        if not covered:
            unclassified.append(rel)
    assert unclassified == [], (
        f"{unclassified} is in neither writable_paths nor the floor. Decide "
        f"which, in contracts/dd-analytics-frontend.yaml or in a migration.")

    # And the loose files at the root of the pages tree, which have no glob.
    for f in sorted(p for p in root.iterdir() if p.is_file()):
        rel = f"{tree}/{f.name}"
        assert rel in writable or any(rel.startswith(c + "/") for c in writable | floored), \
            f"{rel} is named by no writable path"


def test_the_creatable_glob_matches_what_vitest_collects(contract):
    """A test file vitest never collects is a test that cannot bite.

    vitest.config.ts includes `./__tests__/unit/**/*.{test,spec}.{ts,tsx}`, so
    `test_fleet_foo.tsx` is committed and never run. vitest_one_file.sh reports
    that as could-not-run rather than as a pass, but a glob that can only name a
    collected file is better than a clear failure afterwards.
    """
    assert contract["creatable_paths"] == [
        "platform/__tests__/unit/analytics/test_fleet_*.test.tsx"]

    if not PLATFORM.exists():
        pytest.skip("platform not checked out")
    include = (PLATFORM / "platform" / "vitest.config.ts").read_text()
    assert "__tests__/unit/**/*.{test,spec}.{ts,tsx}" in include, \
        "vitest's include pattern moved; the creatable glob has to move with it"


def test_the_retired_contract_is_gone():
    """Restoring the file restores platform/{app,components,lib}/** to anybody
    who types `task add` without --contract. 023 is the second refusal: those
    paths are on the floor, so the restored file could not create a task."""
    assert not (ROOT / "contracts" / "deadly-digital-platform.yaml").exists()
