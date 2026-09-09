"""Every fleet unit reports its own failure.

WHY THIS FILE EXISTS
On 2026-09-09 a branch switch removed run_brief.py and two detector modules.
fleet-sentry failed every fifteen minutes for the rest of the morning;
fleet-brief and fleet-aws-cost would have failed at their next slots. Nothing
said so, and a unit that fails to START writes nothing to the brief, so the
brief could not report its own absence. The failures were found by a sweep run
by hand, hours later. systemd knew the whole time; nothing asked it.

The tests below are deliberately of two kinds. The static ones parse the real
unit files. The last one FIRES A REAL FAILURE and checks the handler ran,
because the first version of this handler was installed, looked correct, and
did nothing at all -- it named a ReadWritePaths directory that did not exist
yet and died with 226/NAMESPACE before reaching its ExecStart. Reading the
unit file would not have found that. Failing a unit did.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UNIT_DIR = ROOT / "systemd"
HANDLER = "fleet-unit-failed@.service"
SCRIPT = ROOT / "tools" / "unit-failed.sh"
INSTALLED_SCRIPT = Path("/usr/local/lib/fleet/unit-failed.sh")
INSTALLED_UNITS = Path("/etc/systemd/system")

# The unit that is the reporter, so it is exempt from reporting to itself.
EXEMPT = {HANDLER}


def fleet_units() -> list[Path]:
    return sorted(p for p in UNIT_DIR.glob("*.service") if p.name not in EXEMPT)


def section(text: str, name: str) -> str:
    """The body of one [Section], so a key is checked where it must appear."""
    m = re.search(rf"^\[{name}\]$", text, re.M)
    if not m:
        return ""
    nxt = re.search(r"^\[", text[m.end():], re.M)
    return text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]


def test_every_fleet_unit_declares_onfailure():
    units = fleet_units()
    assert units, "no unit files found; this test would pass vacuously"
    for unit in units:
        body = section(unit.read_text(), "Unit")
        assert "OnFailure=fleet-unit-failed@%n.service" in body, (
            f"{unit.name} does not report its own failure. A unit that fails "
            f"to start is silent unless it says otherwise.")


def directives(text: str) -> list[str]:
    """Directives only -- comments stripped.

    The handler's own file explains in a comment that it has no OnFailure=,
    and an assertion over the raw text cannot tell that sentence from the
    directive it describes. The same trap applies to every check below that
    looks for a key's absence.
    """
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def test_the_handler_does_not_report_to_itself():
    """A handler with OnFailure= pointing at its own template loops."""
    assert not [d for d in directives((UNIT_DIR / HANDLER).read_text())
                if d.startswith("OnFailure=")]


def test_the_handler_passes_the_unit_name_unescaped_by_systemd():
    """%i, not %I.

    %I unescapes, and unescaping turns every `-` into `/`, so the handler was
    handed `fleet/detector@dd_aws_cost.service` -- a unit that does not exist
    and that systemctl cannot look up, meaning every field it reported would
    have been empty.
    """
    body = directives(section((UNIT_DIR / HANDLER).read_text(), "Service"))
    assert any(d == "ExecStart=/usr/local/lib/fleet/unit-failed.sh %i"
               for d in body), body
    assert not [d for d in body if "%I" in d]


def test_the_handler_creates_its_directories_rather_than_asserting_them():
    """RuntimeDirectory/LogsDirectory, not ReadWritePaths.

    ReadWritePaths only grants access to a path that already exists; naming
    one that does not fails the unit with 226/NAMESPACE before ExecStart. That
    is how the first version of this handler failed -- silently, which is the
    exact defect it exists to fix.
    """
    body = directives(section((UNIT_DIR / HANDLER).read_text(), "Service"))
    assert "RuntimeDirectory=fleet-unit-failed" in body
    assert "RuntimeDirectoryPreserve=yes" in body, (
        "without this the throttle stamps vanish when the oneshot exits and "
        "every failure sends, however often the unit is failing")
    assert "LogsDirectory=fleet" in body
    assert not [d for d in body if d.startswith("ReadWritePaths=")]


def test_the_handler_reads_no_fleet_code():
    """It must survive the repository being the broken thing.

    The most likely cause of a unit failing is that the code on disk is
    broken, so a handler importing this repository has the failure it reports.
    `.env` is the one exception and is safe: it is untracked, so no git
    operation can remove it.
    """
    text = SCRIPT.read_text()
    for forbidden in ("python", "/home/ubuntu/fleet/runner",
                      "/home/ubuntu/fleet/brief", "/home/ubuntu/fleet/detectors"):
        assert forbidden not in text, (
            f"{SCRIPT.name} references {forbidden}; it must not depend on the "
            f"tree whose breakage it exists to report")
    assert "/home/ubuntu/fleet/.env" in text


@pytest.mark.skipif(not INSTALLED_SCRIPT.exists(),
                    reason="handler is not installed on this box")
def test_the_installed_copies_have_not_drifted():
    """The copy that runs lives outside the working tree, on purpose.

    That is what makes it survive a branch switch -- and it is also what lets
    it silently stop matching the version under review, so the two are tied
    together here.
    """
    assert INSTALLED_SCRIPT.read_text() == SCRIPT.read_text(), (
        f"{INSTALLED_SCRIPT} differs from {SCRIPT}")
    for unit in fleet_units() + [UNIT_DIR / HANDLER]:
        installed = INSTALLED_UNITS / unit.name
        if installed.exists():
            assert installed.read_text() == unit.read_text(), (
                f"{installed} differs from {unit}")


@pytest.mark.skipif(
    subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0
    or shutil.which("systemctl") is None
    or not INSTALLED_SCRIPT.exists(),
    reason="needs passwordless sudo and the handler installed")
def test_a_failing_unit_actually_reaches_the_handler():
    """Fire a real failure and confirm the handler ran. The real operation.

    Uses a detector instance whose key does not resolve -- the same way
    dd_api_errors failed on 2026-09-09, so this exercises the shape that
    actually happened rather than a stand-in.

    The throttle stamp is written FIRST, so the outbound Telegram message is
    suppressed and the test is silent. Everything up to the send is exercised;
    running the suite must not ping a phone.
    """
    unit = "fleet-detector@__pytest_missing_key.service"
    stamp = "/run/fleet-unit-failed/" + re.sub(r"[^a-zA-Z0-9]", "_", unit)
    log = Path("/var/log/fleet/unit-failures.log")

    subprocess.run(["sudo", "mkdir", "-p", "/run/fleet-unit-failed"], check=True)
    subprocess.run(["sudo", "tee", stamp], input=str(int(time.time())),
                   text=True, capture_output=True, check=True)

    before = subprocess.run(["sudo", "wc", "-l", str(log)],
                            capture_output=True, text=True)
    before_n = int(before.stdout.split()[0]) if before.returncode == 0 else 0

    subprocess.run(["sudo", "systemctl", "reset-failed", unit],
                   capture_output=True)
    subprocess.run(["sudo", "systemctl", "start", unit], capture_output=True)

    # Poll the LOG, not `systemctl show -p Result`. `show` on a unit that has
    # never run reports Result=success from its defaults, so a wait loop on it
    # exits instantly and every later assertion races the handler it never
    # actually waited for. The first version of this test did exactly that and
    # failed against a handler that was working correctly.
    handler = f"fleet-unit-failed@{unit}.service"
    deadline = time.monotonic() + 20
    after_n = before_n
    while time.monotonic() < deadline:
        after = subprocess.run(["sudo", "wc", "-l", str(log)],
                               capture_output=True, text=True)
        after_n = int(after.stdout.split()[0]) if after.returncode == 0 else 0
        if after_n > before_n:
            break
        time.sleep(0.5)
    else:
        journal = subprocess.run(
            ["journalctl", "-u", handler, "-n", "15", "--no-pager", "-o", "cat"],
            capture_output=True, text=True).stdout
        pytest.fail(
            f"{unit} failed but {log} never grew -- the handler did not "
            f"report it:\n{journal}")

    # And it recorded THIS unit, not merely something.
    tail = subprocess.run(["sudo", "tail", "-5", str(log)],
                          capture_output=True, text=True).stdout
    assert unit in tail, f"{log} grew but does not name {unit}:\n{tail}"

    subprocess.run(["sudo", "systemctl", "reset-failed", unit], capture_output=True)
    subprocess.run(["sudo", "rm", "-f", stamp], capture_output=True)
