"""Deploying what merged, and the five things that stop it.

specs/unattended-operation.md §6.2.

IT INVOKES deploy.sh. IT DOES NOT REIMPLEMENT ONE.
---------------------------------------------------
`api/deploy.sh` tags rollback images from the RUNNING containers before it
builds, migrates before the code swap, asserts the alembic head in the image
against the head in the database while the old containers are still serving,
and refuses on a branched revision graph. Every one of those is a lesson
somebody paid for. A second deploy path would relearn them.

So this module decides WHETHER, and `deploy.sh` decides HOW.

THE FIVE REFUSALS
------------------
1. drift-check must be GREEN BEFORE STARTING. Deploying onto a production that
   already disagrees with main compounds two problems into one incident, and
   the second is much harder to read.

2. THE STATE FILE MUST BE FRESH. `console/deploys.py` records `checked_at`
   because a file nobody has written for an hour is the answer from whenever
   the CHECK died, not today's answer. A stale OK is not an OK.

3. NO MIGRATION IN THE DIFF. `api/alembic/**` and `api/analytics/migrations/**`
   are on the floor, so an unattended task cannot write one -- this refuses the
   case where a person did, and their commit is riding along in the range.
   deploy.sh migrates BEFORE the code swap, and an unattended migration is the
   one action here that git does not make reversible.

4. SOMETHING THE FLEET MERGED MUST BE IN THE RANGE. Otherwise the range is
   entirely human work, and a person who pushed to main did not thereby ask for
   it to be deployed at 04:00. The fleet deploys its own work; it does not
   deploy yours as a side effect of running.

5. AND IT DEPLOYS THE WHOLE RANGE ANYWAY, which is worth saying plainly rather
   than leaving to be discovered: you cannot deploy a subset of main. When the
   fleet's merge triggers a deploy, every commit ahead of production goes with
   it, including hand-written ones. The brief lists them, so what shipped is
   readable rather than inferred.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

#: A drift reading older than this is not a reading. Both cron'd checks run
#: every 15 minutes, so an hour means the check stopped rather than that
#: nothing changed.
MAX_DRIFT_AGE = timedelta(minutes=45)

#: Paths whose presence in the range makes this a person's deploy, not a
#: timer's. Both are floored, so an unattended task cannot have written one.
MIGRATION_PATHS = ("api/alembic/", "api/analytics/migrations/")


@dataclass
class DeployDecision:
    ok: bool
    reason: str = ""
    running: str = ""
    target: str = ""
    commits: list[str] = field(default_factory=list)
    unattended: list[int] = field(default_factory=list)


def _git(repo: Path, *args: str) -> Optional[str]:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip() if r.returncode == 0 else None


def should_deploy(repo: Path, deployment: Any, unattended_shas: set[str]
                  ) -> DeployDecision:
    """Whether to deploy, and the sentence saying why not.

    `deployment` is a console.deploys.Deployment; `unattended_shas` are the
    merge commits recorded with decided_via='unattended'.
    """
    if deployment is None:
        return DeployDecision(False, (
            "there is no drift reading at all, so whether production already "
            "disagrees with main is unknown -- and deploying onto a drifted "
            "production is how two problems become one incident"))

    if deployment.status != "OK":
        return DeployDecision(False, (
            f"drift-check says {deployment.status} before this started. "
            f"Production and main already disagree, and deploying now would "
            f"compound that rather than resolve it: {deployment.detail or ''}"))

    age = getattr(deployment, "age", None)
    if age is None or age > MAX_DRIFT_AGE:
        return DeployDecision(False, (
            f"the drift reading is {age} old and the check runs every 15 "
            f"minutes, so this is the answer from whenever it stopped rather "
            f"than today's. A stale OK is not an OK"))

    running = deployment.sha or ""
    target = _git(repo, "rev-parse", "HEAD") or ""
    if not target:
        return DeployDecision(False, "could not read HEAD in the checkout")
    if running == target:
        return DeployDecision(False, "production is already running main",
                              running=running, target=target)

    rng = f"{running}..{target}"
    commits = (_git(repo, "log", "--oneline", rng) or "").splitlines()
    if not commits:
        return DeployDecision(False, (
            f"nothing in {rng[:24]} -- production is not behind main in a way "
            f"this can read. It may be ahead, which is a person's problem"),
            running=running, target=target)

    touched = (_git(repo, "diff", "--name-only", rng) or "").splitlines()
    migrations = [p for p in touched
                  if any(p.startswith(m) for m in MIGRATION_PATHS)]
    if migrations:
        return DeployDecision(False, (
            f"a migration is in the range and this never deploys one "
            f"unattended: {', '.join(migrations[:4])}. deploy.sh migrates "
            f"before the code swap, and a migration is the one thing here that "
            f"reverting the commit does not undo. Run ./deploy.sh yourself"),
            running=running, target=target, commits=commits)

    in_range = {c.split()[0] for c in commits}
    mine = [s for s in unattended_shas
            if any(s.startswith(short) or short.startswith(s[:7])
                   for short in in_range)]
    if not mine:
        return DeployDecision(False, (
            f"{len(commits)} commit(s) are ahead of production and none of "
            f"them is a merge this fleet made. Pushing to main is not asking "
            f"for a deploy at 04:00 -- a person deploys their own work"),
            running=running, target=target, commits=commits)

    return DeployDecision(True, "", running=running, target=target,
                          commits=commits, unattended=sorted(mine))


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def unattended_merges(conn) -> set[str]:
    """Merge commits this fleet made with nobody watching."""
    rows = conn.execute(
        "SELECT s.payload->'merge'->>'merge_commit' AS sha"
        "  FROM run_steps s"
        " WHERE s.step_type = 'HUMAN_DECISION'"
        "   AND s.payload->>'decided_via' = 'unattended'"
        "   AND s.payload->'merge'->>'merge_commit' IS NOT NULL").fetchall()
    return {r["sha"] for r in rows if r["sha"]}


def run(*, dry_run: bool = False, log=print) -> DeployDecision:
    """Decide, then hand off to deploy.sh. Never raises."""
    from . import config, db, deploys

    repo = config.repo_root() / "deadly-digital-platform"
    found = deploys.all_deployments()
    with db.connect() as conn:
        shas = unattended_merges(conn)

    decision = should_deploy(repo, found.get("api"), shas)
    if not decision.ok:
        log(f"not deploying: {decision.reason}")
        return decision

    log(f"deploying {decision.running[:12]} -> {decision.target[:12]}, "
        f"{len(decision.commits)} commit(s), "
        f"{len(decision.unattended)} from this fleet:")
    for c in decision.commits:
        log(f"    {c}")

    if dry_run:
        log("dry run: deploy.sh not invoked")
        return decision

    # deploy.sh decides HOW. It tags rollback from the running containers,
    # migrates before the swap, and asserts the alembic head while the old
    # containers still serve -- so a failure costs the build and nothing else.
    r = subprocess.run(["./deploy.sh"], cwd=str(repo / "api"),
                       capture_output=True, text=True, timeout=3600)
    tail = (r.stdout or "")[-2000:] + (r.stderr or "")[-2000:]
    if r.returncode != 0:
        log(f"deploy.sh FAILED ({r.returncode}); production is untouched "
            f"unless it says otherwise:\n{tail}")
        return DeployDecision(False, f"deploy.sh exited {r.returncode}",
                              running=decision.running, target=decision.target,
                              commits=decision.commits,
                              unattended=decision.unattended)
    log("deployed")
    return decision
