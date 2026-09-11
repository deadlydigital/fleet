"""A contract may not write what its verification cannot read.

specs/auto-approval.md §9.19, and it is the same class as §9.15 and §9.16: a
check that passes by construction.

`contracts/dd-docstring-proving.yaml` makes twelve route files writable and its
verification compiles, lints and inspects exactly one of them. A task under it
may rewrite `dashboard.py` and the gate reads `revenue.py` and passes.

WHY THE TEST PINS THE SET RATHER THAN DEMANDING ZERO. Narrowing that contract
is one line and refuses strictly more, but which of its paths were a boundary
somebody meant and which are breadth nobody revisited is a decision about what
the contract is FOR — §9.13's argument, and the user's call. So the known hole
is recorded, a new one fails, and fixing the known one fails too, which is the
prompt to delete the exception along with it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CHECKS = ROOT / "contracts" / "checks"
PLATFORM = Path("/home/ubuntu/deadly-digital-platform")

#: Contracts whose verification cannot read everything they may write, as
#: measured on 11 Sep 2026. EXACT: an addition here is a new instance and
#: wants §9.19 updated with it; a removal means one was fixed.
KNOWN_HOLES = {"dd-docstring-proving.yaml"}

#: Commands that read a WHOLE TREE without naming a path, so a file the
#: contract may write is read by them whatever it is called. The distinction
#: that matters is named-path versus whole-tree, NOT named-path versus not — a
#: first pass at this missed that and wrongly flagged dd-acquiring-page.
WHOLE_TREE = (r"tsc\s+--noEmit", r"vitest\s+run",
              r"ruff\s+check\s+(?!.*\.(?:py|ts|tsx))",
              r"compileall\s+-q?\s*(?!.*\.py)")

SUITE_SCRIPTS = {"pytest_unit_per_file.sh", "vitest_one_file.sh",
                 "new_test_bites.sh"}


def _scaling_checks() -> set[str]:
    """Checks that read FLEET_CHANGED_FILES, so their reach follows the change.

    Derived by reading them, not listed: a check that gains the variable is
    covered from that moment, and a typed list would say otherwise.
    """
    out = set()
    for f in CHECKS.glob("*"):
        if f.is_file() and "FLEET_CHANGED_FILES" in f.read_text(errors="ignore"):
            out.add(f.name)
    return out


def _writable_files(globs, root: Path) -> set[str]:
    out = set()
    for g in globs or ():
        for p in root.glob(g):
            if p.is_file() and p.suffix in (".py", ".ts", ".tsx", ".sh"):
                out.add(str(p.relative_to(root)))
    return out


def unread_paths(contract: dict, root: Path) -> set[str]:
    """Files the contract may write that nothing in its verification reads."""
    writable = _writable_files(contract.get("writable_paths"), root)
    if not writable:
        return set()
    scaling = _scaling_checks()
    literals: set[str] = set()
    for cmd in contract.get("verification") or ():
        if "{changed_files" in cmd:
            return set()
        if any(re.search(p, cmd) for p in WHOLE_TREE):
            return set()
        for tok in re.findall(r"[\w./()\[\]-]+", cmd):
            base = tok.rsplit("/", 1)[-1]
            if base in scaling or base in SUITE_SCRIPTS:
                return set()
            m = re.search(r"((?:api|platform)/[\w./()\[\]-]+\.(?:py|ts|tsx))$", tok)
            if m:
                literals.add(m.group(1))
    return writable - literals


def _contracts():
    for y in sorted((ROOT / "contracts").glob("*.yaml")):
        yield y, yaml.safe_load(y.read_text()) or {}


pytestmark = pytest.mark.skipif(
    not PLATFORM.exists(), reason="the platform checkout is not on this host")


class TestNoContractOutrunsItsVerification:
    def test_the_hole_set_is_exactly_what_is_recorded(self):
        found = set()
        for y, d in _contracts():
            root = PLATFORM if d.get("repo") == "deadly-digital-platform" else ROOT
            if unread_paths(d, root):
                found.add(y.name)
        assert found == KNOWN_HOLES, (
            f"contracts whose verification cannot read what they may write "
            f"changed: {found} vs recorded {KNOWN_HOLES}. A new one is a new "
            f"instance of §9.19 — a gate that passes by construction. One that "
            f"has gone is fixed, and this exception should go with it.")

    def test_the_known_hole_is_still_the_shape_described(self):
        """If it stops being 11 of 12, §9.19's numbers are stale."""
        d = yaml.safe_load((ROOT / "contracts" / "dd-docstring-proving.yaml").read_text())
        unread = unread_paths(d, PLATFORM)
        writable = _writable_files(d.get("writable_paths"), PLATFORM)
        assert (len(unread), len(writable)) == (11, 12), (
            f"§9.19 records 11 of 12; this host says {len(unread)} of "
            f"{len(writable)}")

    def test_a_whole_tree_command_counts_as_reading_it(self):
        """dd-acquiring-page names no path and is NOT a hole: tsc --noEmit
        typechecks the whole platform. The first pass at this measurement got
        that wrong and would have filed a second instance that is not one."""
        d = yaml.safe_load((ROOT / "contracts" / "dd-acquiring-page.yaml").read_text())
        assert unread_paths(d, PLATFORM) == set()

    def test_a_changed_files_contract_is_covered_however_wide_it_is(self):
        """deadly-digital-platform-api writes 27 files and reads every one it
        is given, which is the shape the others should have."""
        d = yaml.safe_load(
            (ROOT / "contracts" / "deadly-digital-platform-api.yaml").read_text())
        assert len(_writable_files(d.get("writable_paths"), PLATFORM)) > 20
        assert unread_paths(d, PLATFORM) == set()
