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

IT CATCHES THE CHECKOUT UP FIRST, SINCE 14 Sep 2026
----------------------------------------------------
`should_deploy` reads `rev-parse HEAD` and `deploy.sh` builds images from the
working tree without moving it, so the checkout is this module's INPUT and
nothing here used to supply it. "Deploy what the fleet merged" was therefore
true only when a person had pulled, and that person was the only thing moving
the tree -- several times a day. On three of the six nights this has run, the
refusal was "already running main": the human had won the race to a job this
was supposed to be doing.

Automating the pull was not possible until now. A pull during a build moves
HEAD and fails that build AFTER the agent has been paid for and the branch
pushed -- task 96 on 14 Sep 2026, £3.29, self-inflicted at 12:15:28 and
recovered afterwards with `console.adopt`. There was no way for a program to
know a build was in flight. `console/pull.py` is that check, and it is the
whole reason the checkout can now be moved by something other than a person.

A checkout that could NOT be caught up refuses the deploy rather than shipping
the stale one -- the same argument as refusing on drift.

THE FIVE REFUSALS
------------------
1. drift-check must not say AHEAD. `api/drift-check.sh` writes OK, DRIFT
   (production is BEHIND) and AHEAD (production runs a commit that is not on
   origin/main -- DEPLOY-003). Deploying onto an AHEAD production buries
   whatever is running rather than resolving it, and the second problem is much
   harder to read than the first.

   BEHIND IS NOT THAT CASE. It is the state that means there is something to
   deploy, and refusing on it -- which this did until 15 Sep 2026 -- made the
   unit refuse exactly when it had work. Seven runs, seven refusals, nothing
   ever deployed; see the comment in `should_deploy` for what that cost. A
   status that is neither OK nor DRIFT means the container could not be asked,
   and that still refuses: nothing is known about what is running.

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

    # DRIFT IS NOT AHEAD, AND THIS REFUSED ON BOTH UNTIL 15 Sep 2026.
    #
    # api/drift-check.sh writes three statuses and its own header names what
    # each is for:
    #
    #     OK      production is the commit origin/main says it should be
    #     DRIFT   production is BEHIND -- origin/main ships code it does not
    #             have                                            (exit 1)
    #     AHEAD   production runs a commit that is NOT on origin/main, which
    #             is DEPLOY-003                                    (exit 4)
    #
    # This read `deployment.status != "OK"`, so BEHIND and AHEAD were the same
    # fact to it. They are opposite facts. Refusal 1's argument -- "deploying
    # onto a production that already disagrees with main compounds two problems
    # into one incident" -- is TRUE OF AHEAD and BACKWARDS FOR BEHIND, where
    # deploying is the thing that ENDS the disagreement.
    #
    # BEHIND IS THE STATE THAT MEANS THERE IS SOMETHING TO DEPLOY. Refusing on
    # it made this unit refuse precisely when it had work, and the next four
    # refusals below never got to run.
    #
    # WHAT IT COST, AND IT IS THE WHOLE OF WHAT THIS UNIT HAS EVER DONE.
    # `journalctl -u fleet-autodeploy.service`, 9-15 Sep 2026: seven runs,
    # seven refusals, nothing deployed, ever. Two of those seven are this rule
    # -- 14 Sep and 15 Sep -- and the trap closes on its own: any merge touching
    # api/ puts production BEHIND, the drift check notices within 15 minutes,
    # and the 04:15 timer then refuses. The only window in which this unit could
    # ever have fired is between a merge and the next drift reading, which a
    # once-daily timer will not hit. Task 104 merged at 11:05 on 15 Sep and was
    # still unshipped at 12:30; deployed by hand it took /api/analytics/revenue
    # from 7.86 s to 1.18 s.
    #
    # THE OTHER REFUSALS STILL RUN, which is why proceeding here is safe rather
    # than merely correct. A BEHIND reading passes to the staleness check, the
    # running-equals-target check, the migration check and the did-the-fleet-
    # merge-it check, and any of them may still refuse. This branch decides one
    # thing only: that being behind is not itself a reason to stay behind.
    if deployment.status == "AHEAD":
        return DeployDecision(False, (
            f"drift-check says AHEAD: production is running "
            f"{deployment.detail or '?'}, which is NOT a commit on "
            f"origin/main. That is DEPLOY-003, and it is the case this refusal "
            f"was written for -- deploying over it would bury whatever is "
            f"running rather than resolve it, and what is running needs "
            f"identifying first"))

    if deployment.status not in ("OK", "DRIFT"):
        return DeployDecision(False, (
            f"drift-check says {deployment.status}, which is neither OK nor a "
            f"reading of how far production is behind -- the container is "
            f"missing, stopped, or could not be asked. Nothing is known about "
            f"what is running: {deployment.detail or ''}"))

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
        # NAMES WHAT WAS COMPARED. This said "production is already running
        # main" until 14 Sep 2026, and `target` is the CHECKOUT's HEAD --
        # nothing here reads the remote. On a checkout behind origin/main the
        # sentence was false in the direction that matters: it reported the
        # fleet's work as shipped while it sat unbuilt on the remote, and it
        # was the reason given on three of the six nights this has run.
        #
        # `run()` fast-forwards before calling this, so the two are usually the
        # same thing now -- but "usually" is exactly what a refusal must not
        # assert. The catch-up line in the log above says whether the checkout
        # moved; this says only what it compared.
        return DeployDecision(False, (
            f"production is already running {target[:12]}, which is this "
            f"checkout's HEAD"), running=running, target=target)

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
    from . import config, db, deploys, pull

    repo = config.repo_root() / "deadly-digital-platform"

    # THE CHECKOUT IS THE INPUT, AND NOTHING USED TO MOVE IT.
    #
    # `should_deploy` reads `rev-parse HEAD` and `deploy.sh` builds images from
    # the working tree without touching it, so "deploy what the fleet merged"
    # was true only when a person had pulled first. That person was the only
    # thing moving the tree, several times a day, and on three of the six
    # nights this has run the refusal was "already running main" -- the human
    # had won the race to a job this was supposed to do.
    #
    # It could not be automated before 14 Sep 2026: a pull during a build fails
    # that build after the spend, and there was no way for a program to know a
    # build was in flight. `console.pull` is that check, and it is the whole
    # reason this call can exist. See its docstring for task 96, which is the
    # worked example and was self-inflicted.
    caught = pull.catch_up(repo, log=lambda m: log(f"  {m}"), dry_run=dry_run)
    if not caught.ok:
        # A checkout that could not be moved is not a reason to deploy the
        # stale one. Refusing here is the same argument as refusing on drift:
        # proceeding would ship something nobody asked for.
        log(f"not deploying: the checkout could not be caught up -- "
            f"{caught.reason}")
        return DeployDecision(False, caught.reason)
    if caught.already_current:
        log(f"checkout: already current at {caught.now}")
    elif dry_run:
        # Said plainly, because the decision below is made against a checkout
        # a real run would have moved first: everything after this is what
        # WOULD be decided about the tree as it stands, not about the tree the
        # deploy would build.
        log(f"checkout: {caught.was}, and a real run {caught.reason} first")
    else:
        log(f"checkout: {caught.was} -> {caught.now} "
            f"({caught.commits} commit(s))")

    found = deploys.all_deployments()
    with db.connect() as conn:
        shas = unattended_merges(conn)

    drift = found.get("api")
    decision = should_deploy(repo, drift, shas)

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
