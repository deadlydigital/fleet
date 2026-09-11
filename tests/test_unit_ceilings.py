"""The three units that verify a branch carry ONE memory ceiling.

fleet-runner, fleet-console and fleet-automerge run the same contract
verification commands against the same branch and exist to agree about
whether it passes. On 11 Sep 2026 they carried three different answers to how
much memory that may take -- unset (infinity), 2G and 512M -- and the
disagreement surfaced as a lie: task 53's `tsc --noEmit` exited 134 (SIGABRT,
V8 out of memory) under automerge's 512M, and the accept path reported "the
branch verifies on its own and FAILS when merged into main as it stands now."

A comment saying they should match is what they had. This is a test.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

UNITS = Path(__file__).resolve().parent.parent / "systemd"

#: Every unit that runs `runner.verify.run` against a contract's commands.
#: fleet-autoapprove is deliberately NOT here: it re-executes a candidate's
#: PROBES -- path_exists and grep_count -- and never runs a contract.
VERIFYING_UNITS = ("fleet-runner", "fleet-console", "fleet-automerge")

#: MiB, the heaviest verification sequence measured 11 Sep 2026, whole and
#: inside the units' own confinement, read from the cgroup's memory.peak.
#: dd-analytics-frontend: tsc + vitest + the bite check.
#:
#: RAISE THIS WHEN IT IS RE-MEASURED, never to make a failing test pass.
MEASURED_PEAK_MIB = 961

_SUFFIX = {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 * 1024}


def _memory_max_mib(unit: str) -> float:
    text = (UNITS / f"{unit}.service").read_text()
    found = re.findall(r"^MemoryMax=(\d+)([KMGT]?)$", text, re.M)
    assert len(found) == 1, f"{unit}: expected one MemoryMax=, found {found}"
    number, suffix = found[0]
    return int(number) * _SUFFIX.get(suffix, 1 / 1048576)


class TestTheVerifyingUnitsAgree:
    def test_all_three_carry_the_same_ceiling(self):
        seen = {u: _memory_max_mib(u) for u in VERIFYING_UNITS}
        assert len(set(seen.values())) == 1, (
            f"the units that must agree about whether a branch passes carry "
            f"different memory ceilings: {seen}. A branch that verifies in "
            f"one and is killed in another is reported as a branch that "
            f"fails, which is a false statement about the diff.")

    @pytest.mark.parametrize("unit", VERIFYING_UNITS)
    def test_the_ceiling_clears_the_measured_peak(self, unit):
        """Above the measurement, with room, rather than equal to it.

        A ceiling AT the peak fails on the first run whose input is a little
        larger, and that failure arrives as a killed check rather than as an
        out-of-memory anybody recognises.
        """
        assert _memory_max_mib(unit) >= MEASURED_PEAK_MIB * 1.5, (
            f"{unit}: MemoryMax is {_memory_max_mib(unit)} MiB and the "
            f"heaviest measured verification peaks at {MEASURED_PEAK_MIB} MiB")

    @pytest.mark.parametrize("unit", VERIFYING_UNITS)
    def test_accounting_is_on_so_the_number_can_be_re_measured(self, unit):
        """`systemctl show <unit> -p MemoryPeak` from a REAL run.

        Without this the only way to re-measure is another hand-built probe
        under hand-copied properties, which is how the three ceilings drifted
        apart without anybody noticing.
        """
        text = (UNITS / f"{unit}.service").read_text()
        assert re.search(r"^MemoryAccounting=yes$", text, re.M), unit

    def test_autoapprove_is_not_held_to_this(self):
        """It ranks and re-executes probes; it never runs a contract. Holding
        it to the verification ceiling would be a number with no measurement
        behind it, which is the thing this file exists to prevent."""
        assert "fleet-autoapprove" not in VERIFYING_UNITS
        assert _memory_max_mib("fleet-autoapprove") < MEASURED_PEAK_MIB


class TestTheInstalledUnitsAreTheRepoUnits:
    """A ceiling in the repository that is not on the box is a comment."""

    @pytest.mark.parametrize("unit", VERIFYING_UNITS)
    def test_installed_matches_the_repo(self, unit):
        installed = Path("/etc/systemd/system") / f"{unit}.service"
        if not installed.exists():
            pytest.skip(f"{unit} is not installed on this host")
        assert installed.read_text() == (UNITS / f"{unit}.service").read_text(), (
            f"{unit}: /etc/systemd/system copy differs from systemd/ in the "
            f"repository, so the unit that runs is not the unit under review")
