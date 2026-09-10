"""What production is actually running, read from the deploy-drift state files.

BUILT, MERGED AND DEPLOYED ARE THREE STATES AND THIS MODULE IS THE THIRD
-----------------------------------------------------------------------
`tasks.status = 'MERGED'` means a person merged a branch. It says nothing
about whether the code is running, and the gap between those two has cost
real money on this system twice -- `api/drift-check.sh` names both incidents
in its header, SEC-008 live for 22 hours and a band-billing bug live in Stripe
LIVE mode for eight. Nothing in the fleet database can close that gap: no run
ever reaches DEPLOYED, deliberately, and the runner is not a deployer.

So the answer comes from outside the database, from the two cron'd drift
checks that already compare a running container to origin/main.

FRESHNESS IS PART OF THE READING, NOT A DETAIL
----------------------------------------------
A state file says `status=OK`. It does not say when. Both checks run every 15
minutes, so a file nobody has written for an hour means the CHECK stopped, and
its last answer is not today's answer -- it is the answer from whenever it
died. Rendering that as current is the same defect the check exists to catch,
one level up: a signal with no path to the bad state.

This matters here and not in theory. `/home/ubuntu/capacity-samples/` also
holds `drift-platform.state`, last written 26 Aug 2026 and reading `status=OK`.
It is NOT read by this module and its absence from the page is deliberate: it
is a superseded filename, not a check that died. `platform/drift-check.sh`
sets `DRIFT_STATE` to `drift-frontend.state`, and did so when it was written
-- so the old file is a leftover, and reporting it as a stalled monitor would
invent an alarm. Named here because the file is on disk and the next person to
find it deserves the answer rather than the question.

The path is under /home and outside the fleet repository. The console unit
runs `ProtectHome=read-only`, which permits the read and forbids the write,
which is exactly the relationship this module wants.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

#: Where api/drift-check.sh and platform/drift-check.sh keep their state.
SAMPLES = Path(os.environ.get("FLEET_DRIFT_STATE_DIR",
                              "/home/ubuntu/capacity-samples"))

#: Both checks are cron'd at */15. An hour is four missed runs -- long enough
#: that a slow box or a single failure does not cry wolf, short enough that a
#: check which has actually stopped is visible the same morning.
STALE_AFTER = timedelta(hours=1)

#: work_type -> which deployment governs it. A task's work type already says
#: which tree it touched, and the contracts enforce that: dd_api may not write
#: platform/**, dd_frontend may not write api/**. So this mapping is not a
#: guess about the diff, it is a restatement of the boundary the branch was
#: judged against.
#:
#: `dd_docs`, `research` and `draft_spec` map to None: nothing deploys. A docs
#: change and a research document have no running copy to be behind, and
#: saying "not deployed" about them would be a false alarm rather than a gap.
GOVERNED_BY: Dict[str, Optional[str]] = {
    "dd_api": "api",
    "dd_frontend": "frontend",
    # A deploy SCRIPT is not itself deployed. It is the thing that does the
    # deploying, so no deployment can be behind it -- and answering
    # NOTHING_TO_SHIP is the honest verdict rather than CANNOT_SAY, which would
    # put it in the same bucket as the frontend defect it exists to fix.
    "dd_infra": None,
    "dd_docs": None,
    "research": None,
    "draft_spec": None,
    # A candidate producer emits a document of proposed work. Nothing of it
    # runs anywhere, so there is no deployment to be behind.
    "candidate_producer": None,
}


@dataclass
class Deployment:
    """One deployment's last verified state, and when it was last verified."""
    name: str
    status: str          # OK | DRIFT | AHEAD | UNKNOWN | STALE | ABSENT
    detail: str
    sha: Optional[str]
    checked_at: Optional[datetime]
    age: Optional[timedelta]

    @property
    def usable(self) -> bool:
        """Whether this reading may be used to claim something is deployed.

        Only a fresh OK qualifies. UNKNOWN, DRIFT and STALE all mean the same
        thing to a caller asking "did my merge ship?": no, or cannot say.
        """
        return self.status == "OK"

    @property
    def short_sha(self) -> str:
        return (self.sha or "")[:12]


def _parse(path: Path, name: str) -> Deployment:
    if not path.exists():
        return Deployment(name, "ABSENT",
                          f"no state file at {path}; the drift check for "
                          f"{name} has never run on this host",
                          None, None, None)

    fields: Dict[str, str] = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip()

    checked_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age = datetime.now(timezone.utc) - checked_at
    status = fields.get("status", "UNKNOWN")
    detail = fields.get("detail", "")

    # A sha is only a sha. The api check writes the running commit here; the
    # frontend check writes a sentence explaining why it has none. Treating
    # that sentence as a commit would put prose in a <code> block and imply a
    # deployment nobody verified.
    sha = detail if len(detail) == 40 and all(
        ch in "0123456789abcdef" for ch in detail) else None

    if age > STALE_AFTER:
        return Deployment(
            name, "STALE",
            f"the drift check for {name} last wrote this file "
            f"{_ago(age)} ago and runs every 15 minutes, so it has stopped. "
            f"Its last answer was {status!r} and that answer is not current.",
            sha, checked_at, age)

    return Deployment(name, status, detail, sha, checked_at, age)


def _ago(delta: timedelta) -> str:
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    if hours >= 24:
        return f"{hours // 24}d {hours % 24}h"
    if hours:
        return f"{hours}h {rem // 60}m"
    return f"{rem // 60}m"


def ago(delta: Optional[timedelta]) -> str:
    return _ago(delta) if delta is not None else "—"


def all_deployments() -> Dict[str, Deployment]:
    """Every deployment this host can say anything about.

    Two, not three: see the module docstring on drift-platform.state.
    """
    return {
        "api": _parse(SAMPLES / "drift.state", "api"),
        "frontend": _parse(SAMPLES / "drift-frontend.state", "frontend"),
    }


def shipped(work_type: Optional[str], merged_at: Optional[datetime],
            deployments: Dict[str, Deployment]) -> tuple[str, str]:
    """Did this merged task's code reach production? Returns (verdict, why).

    Four verdicts, and the difference between the last two is the whole point
    of the module:

      NOTHING_TO_SHIP  no deployment governs this work type
      SHIPPED          a fresh OK from a check that ran AFTER the merge
      NOT_SHIPPED      a fresh check that says the running code is behind
      CANNOT_SAY       the check is UNKNOWN, STALE, absent, or last ran
                       BEFORE this merge and therefore never saw it

    The last clause is not pedantry. A check that said OK at 09:30 has said
    nothing about a branch merged at 09:35, and reporting its OK as though it
    had is how a stale reading becomes a confident wrong answer.
    """
    which = GOVERNED_BY.get(work_type or "")
    if which is None:
        return ("NOTHING_TO_SHIP",
                "no deployment governs this work type — there is no running "
                "copy for it to be behind")

    dep = deployments.get(which)
    if dep is None:
        return ("CANNOT_SAY", f"no drift check for {which}")

    if not dep.usable:
        return ("CANNOT_SAY", dep.detail or
                f"the {which} deploy check reads {dep.status}")

    if merged_at is not None and dep.checked_at is not None \
            and dep.checked_at < merged_at:
        return ("CANNOT_SAY",
                f"the {which} deploy check last ran "
                f"{dep.checked_at:%H:%M} and this merged at "
                f"{merged_at:%H:%M}, so it has not looked since")

    return ("SHIPPED", f"{which} is running {dep.short_sha}, verified "
                       f"{ago(dep.age)} ago")
