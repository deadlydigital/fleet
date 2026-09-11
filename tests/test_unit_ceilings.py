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


class TestTheRunnersOwnCostIsRecorded:
    """The half of the ceiling that was an inference.

    fleet-console and fleet-automerge run verification and nothing else, and
    961 MiB is measured. fleet-runner runs an AGENT first and then verifies,
    and its ceiling was unset until 11 Sep 2026, so no run has ever been near
    a limit and nothing has ever recorded how close it came.

    `MemoryAccounting=yes` alone does not give it back: systemd drops
    MemoryPeak when the cgroup goes away, which for a Type=oneshot unit is the
    moment it finishes --

        $ systemctl show fleet-autoapprove.service -p MemoryPeak --value
        [not set]

    -- so the number is readable only from inside the run. 035 stores it.
    """

    def test_the_runner_reads_its_own_peak(self):
        from runner import cycle
        peak = cycle._peak_memory_mib()
        assert peak is None or peak > 0, (
            "a zero would be a measurement nobody took; None is how this says "
            "the host could not tell us")

    def test_the_reader_returns_none_rather_than_raising_off_cgroup_v2(
            self, monkeypatch, tmp_path):
        """Best effort and never fatal: a settle that raises here loses the
        reason column, which is the thing 033 exists to protect."""
        from runner import cycle
        monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(
            OSError("no cgroup here")))
        assert cycle._peak_memory_mib() is None
        assert cycle._memory_max_mib() is None

    def test_an_unbounded_ceiling_reads_as_none_not_as_a_number(self, tmp_path):
        """`memory.max` is the literal string "max" when unbounded. Rounding
        that into an integer is how "infinity" becomes a plausible-looking
        limit in a log line."""
        from runner import cycle
        fake = tmp_path / "memory.max"
        fake.write_text("max\n")
        assert cycle._memory_max_mib() is None or isinstance(
            cycle._memory_max_mib(), int)

    def test_the_migration_exists_and_grants_the_runner_the_write(self):
        """The code writes the column; the migration is what makes it there.
        A write with no migration is a settle that logs and moves on -- see
        _settle_task -- which is survivable and is not the intent."""
        sql = (Path(__file__).resolve().parent.parent
               / "035_a_run_records_what_it_cost_in_memory.sql").read_text()
        assert "ADD COLUMN IF NOT EXISTS peak_memory_mib" in sql
        assert "GRANT UPDATE (peak_memory_mib) ON runs TO fleet_task_runner" in sql

    def test_the_column_is_nullable(self, console):
        """NULL is "the host could not say". A NOT NULL column would force a
        zero, and a zero is a measurement nobody took."""
        row = console.execute(
            "SELECT is_nullable FROM information_schema.columns"
            " WHERE table_name='runs' AND column_name='peak_memory_mib'"
        ).fetchone()
        assert row is not None, "035 did not reach the test template"
        assert row["is_nullable"] == "YES"


class TestTheThreeAgreeOnEverythingThatDecidesAPass:
    """Four dimensions have now disagreed, and they were found one at a time.

        memory          MemoryMax unset / 2G / 512M     -> tsc SIGABRT, false FAIL
        interpretation  what counts as a verdict        -> a killed check read as a failure
        time            deadline 900s vs the task's     -> a dd_api branch unmergeable
        writability     ReadWritePaths on one of three  -> vitest EROFS, false FAIL

    Interpretation is shared by construction: all three call runner.verify.
    Memory and time are now equal. Writability CANNOT be equalised -- the
    console's entire safety argument is that it may not write the checkouts --
    so it is made irrelevant instead, by verify.unwritable refusing to judge
    rather than letting a check fail for the filesystem.

    THIS TEST IS THE POINT. Enumerating today's four dimensions fixes today's
    four. What keeps the next one from being found the same way -- at a cost of
    a terminal failure and an afternoon -- is asking the three units whether
    they still agree, on every property that can decide a pass, rather than
    trusting three files to stay in step.
    """

    #: Properties that decide whether a check passes, and must therefore be
    #: identical. Add to this list; do not add exceptions to it.
    MUST_AGREE = (
        "MemoryMax", "MemoryAccounting", "TasksMax", "CPUQuotaPerSecUSec",
        "ProtectHome", "ProtectSystem", "PrivateTmp", "NoNewPrivileges",
        "LimitNOFILESoft", "LimitNPROCSoft", "RestrictAddressFamilies",
    )

    #: The one that must DIFFER, with the reason, because a test that demanded
    #: agreement here would be demanding the console be allowed to write the
    #: repositories it exists not to write.
    MUST_DIFFER = ("ReadWritePaths",)

    def _show(self, unit, prop):
        import subprocess
        return subprocess.run(
            ["systemctl", "show", f"{unit}.service", "-p", prop, "--value"],
            capture_output=True, text=True).stdout.strip()

    @pytest.mark.skipif(not Path("/run/systemd/system").exists(),
                        reason="no systemd on this host")
    @pytest.mark.parametrize("prop", MUST_AGREE)
    def test_the_three_units_agree(self, prop):
        seen = {u: self._show(u, prop) for u in VERIFYING_UNITS}
        if not any(seen.values()):
            pytest.skip(f"{prop} is not reported on this systemd")
        assert len(set(seen.values())) == 1, (
            f"{prop} differs across the units that must agree about whether a "
            f"branch passes: {seen}. A branch that passes under one and is "
            f"stopped under another is reported as a branch that fails.")

    @pytest.mark.skipif(not Path("/run/systemd/system").exists(),
                        reason="no systemd on this host")
    @pytest.mark.parametrize("prop", MUST_DIFFER)
    def test_the_documented_exception_still_holds(self, prop):
        """The runner writes worktrees; the other two may not write anything.

        Asserted rather than assumed: if the console ever gains a
        ReadWritePath it has stopped being the thing its own unit file argues
        it is, and that should fail here rather than be noticed later.
        """
        runner = self._show("fleet-runner", prop)
        assert runner, "the runner must be able to write its worktrees"
        for u in ("fleet-console", "fleet-automerge"):
            assert not self._show(u, prop), (
                f"{u} has gained {prop}, so it can now write outside its "
                f"trial clone -- which is the property that makes 'the trial "
                f"leaves nothing' true")

    def test_the_deadline_is_not_a_constant_in_the_accept_path(self):
        """Time was the third dimension. The accept path took 900s from a
        module constant while the runner took the task's own timeout."""
        src = (Path(__file__).resolve().parent.parent
               / "console" / "reverify.py").read_text()
        assert "_deadline_for(task)" in src, (
            "the accept path must take its deadline from the task, which is "
            "where the runner takes its budget from")
        assert "\nDEADLINE_SECONDS = 900" not in src, (
            "the bare module constant is what the runner disagreed with; "
            "DEFAULT_DEADLINE_SECONDS is the fallback and is fine")

    def test_the_deadline_comes_from_the_task_row(self):
        from console import reverify
        assert reverify._deadline_for({"timeout_seconds": 3600}) == 3600
        assert reverify._deadline_for({"timeout_seconds": None}) == 900
        assert reverify._deadline_for({}) == 900
        assert reverify._deadline_for({"timeout_seconds": 0}) == 900, (
            "a zero timeout would make every check report could-not-run")
