# Deploy from a ref — the checkout must stop being production

**Status: SPEC. Nothing built.** Reads: `systemd/*.service`, `console/merge.py`,
`003_tasks.sql` §7 (`guard_task_immutability`), `runner/config.py`.

---

## 0. What happened, in one paragraph

On 2026-09-09 at 07:49 the `~/fleet` checkout was switched from
`spec/daily-brief` to `track-2-foundation`. That was a deliberate instruction,
for a good reason: `console/merge.py` refuses to merge unless the checkout is
on the task's `base_branch`, and accepting task 22 required being on
`track-2-foundation`. It was typed as `git checkout`, which is a command with
no operational reputation at all.

It took out three timers. `fleet-sentry` began failing three minutes later and
failed every fifteen minutes for the rest of the morning. `fleet-brief` and
`fleet-aws-cost` would have failed at their next slots — 07:45 and 06:40 the
following day. Nothing warned, nothing alerted, and a unit that fails to
*start* writes nothing to the brief, so the brief could not have reported its
own absence.

**The action was correct and the outcome was an outage.** That gap is the
subject of this spec. A production action that looks like a git command is the
thing to design out.

## 1. Why the checkout is production

Every installed unit runs from the working tree:

```
ExecStart=/home/ubuntu/fleet/.venv/bin/python /home/ubuntu/fleet/run_brief.py
ExecStart=/home/ubuntu/fleet/.venv/bin/python /home/ubuntu/fleet/run_detector.py %i
ExecStart=/home/ubuntu/fleet/.venv/bin/python run_console.py --host 127.0.0.1 --port 8787
```

There is no deploy step, no pinned ref, and no artefact. Whatever is on disk at
`/home/ubuntu/fleet` at the moment a timer fires *is* the fleet. `git checkout`
is therefore a deployment, `git stash` is a deployment, and an interrupted
rebase is an outage.

Contract verification has the same disease one layer down: commands name
`/home/ubuntu/fleet/contracts/checks/*.py` by absolute path into this same
working tree, so a task's verification depends on which branch it is on. That
is [pin-contract-checks-by-content](pin-contract-checks-by-content.md) and is
not re-solved here — but both are the same root, and a fix here should not make
that one harder.

## 2. The collision that forces the switch

Two requirements on one directory, and they are not satisfiable together:

| Role | Requires the checkout to be on |
|---|---|
| Deployment | the branch carrying the tooling the units need |
| Merge target | the task's `base_branch` (`console/merge.py`) |

`tasks.base_branch` is **immutable by database trigger** —
`guard_task_immutability` raises `task % may not change repo or base branch`
for every status, verified 2026-09-09. So an existing task cannot be re-pointed
at whatever branch production happens to be on; the branch it names must be
kept alive and correct until that task is terminal. Consolidating branches
relieves the symptom and does not remove the collision: any future task whose
base is not the production branch reintroduces it.

## 3. What to build

**3.1 The units stop naming a working tree.** Each unit runs from an immutable
deployment path — `/opt/fleet/<sha>` or equivalent — with `/opt/fleet/current`
a symlink. `ExecStart` names `current`. Switching branches in a development
checkout then cannot affect a running unit, because no running unit reads it.

**3.2 Deploying is one command that says it is deploying.** A `fleet deploy
<ref>` that materialises the ref, runs a smoke check, and repoints the symlink
only if the smoke check passes. It must be possible to say what is deployed —
`fleet deploy --what` printing the sha and the ref it came from — because
today that question has no answer that is not "read the working tree".

**3.3 The smoke check is the sweep.** Before repointing, resolve every
installed unit against the candidate tree: entry points exist, every
`fleet-detector@<key>` key resolves, every contract check script referenced by
a live task exists. This is the sweep run by hand on 2026-09-09; it found three
broken units in under a second and it should be the thing that makes a bad
deploy impossible rather than a thing somebody thinks to run.

**3.4 A unit that fails to start is loud.** `fleet-sentry` failed 12+ times
across the morning in silence. Systemd knows; nothing asks it. `OnFailure=` on
every unit, into the same path the brief reads, so a unit that cannot start
reports that it cannot start. **This is the only item here that would have
turned the 07:49 outage into a notification**, and it is worth building even if
nothing else in this spec is.

**3.5 Merging stops needing the checkout.** Accept already builds a trial clone
(`runner.worktree.create_trial_clone`). The real merge can happen in a clone
too and be pushed, leaving the deployment to `fleet deploy`. This removes the
"checkout must be on the base branch" rule and therefore the collision in §2 —
but it is [merge-outside-the-checkout](merge-outside-the-checkout.md), and it
is listed here only because a fix for §3.1 that assumes merges keep happening
in the working tree would have to be undone by it.

## 4. Ordering

3.4 first and on its own: it is small, it is independent, and it converts this
class of failure from silent to noticed. Then 3.1–3.3 together, since a
deployment path without a deploy command is worse than neither. 3.5 last, in
its own spec.

## 5. What this deliberately does not do

**No CI, no build artefacts, no containers.** The fleet is Python run from a
directory on one box, and the failure being fixed is "the directory changed
underneath a running service", not "the directory was built wrong".

**It does not make branches unswitchable.** Development in `~/fleet` should
stay ordinary git. The point is that ordinary git stops being deployment, not
that git gets ceremony added to it.
