# Scheduling

Installed and enabled. Reconciliation runs hourly at :20, the heartbeat every
five minutes at :30 past the boundary. To reproduce on another host:

    sudo cp fleet-detector@.service fleet-reconciliation.timer fleet-heartbeat.timer \
            /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now fleet-reconciliation.timer fleet-heartbeat.timer

To stop them without uninstalling:

    sudo systemctl disable --now fleet-reconciliation.timer fleet-heartbeat.timer

`fleet-sentry.timer` (dd_api_errors, every 15 minutes at :07 past each
quarter) is written and **not installed**. It is waiting on two things that
are one action: a Sentry organisation auth token in `.env`, and
`015_sentry_detector.sql` applied so the registry row exists. Until both are
done the detector cannot close a run OK, and the brief correctly reports the
gap rather than a zero — so installing the timer early buys a red board and
no information.

    sudo cp fleet-sentry.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now fleet-sentry.timer

`fleet-aws-cost.timer` (dd_aws_cost, 06:40 daily) is written and **not
installed**, waiting on an `fx_rate` reading for the month and `016` applied.
06:40 is before the 07:45 brief so the morning reads a fresh answer, and after
a night in which Cost Explorer finishes restating yesterday.

    sudo cp fleet-aws-cost.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now fleet-aws-cost.timer

The observation cycle is a third unit, not installed and not enabled:

    sudo cp fleet-proposer-cycle.service fleet-proposer-cycle.timer \
            /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now fleet-proposer-cycle.timer

It is `Persistent=true` and the detectors' timers are not, for opposite
reasons. A detector cannot re-derive a missed slot by running late, so
catching up buys nothing. The cycle reads current state, so a run missed
because the host was off is worth doing when it comes back: the morning's
five items are still the morning's five items an hour later.

Check with `systemctl list-timers 'fleet-*'` and
`journalctl -u 'fleet-detector@*' -f` or
`journalctl -u fleet-proposer-cycle -f`.

Timers rather than cron: the unit carries the sandboxing, the failure state is
queryable, and `systemctl list-timers` answers "when did this last run" without
a second source of truth.

Neither timer catching up matters much. A missed slot cannot be re-derived by
running late -- open_scheduled_run always derives the current slot from now()
-- so a gap is recovered by a backfill, and noticed by fleet_heartbeat.

## The runner: installed, and deliberately not enabled

    sudo cp fleet-runner.service fleet-runner.timer /etc/systemd/system/
    sudo systemctl daemon-reload

Both files are on this host and the timer is **disabled**. Enabling it is one
command and is deliberately not run here:

    sudo systemctl enable --now fleet-runner.timer

`specs/approval-surface.md` §6.1 makes three ceilings a precondition for this
timer existing at all — queue depth, the approval-time credit check, and the
per-task caps — on the argument that "the thing that prevents an overnight
batch of five branches against wrong paths is that a person types
`run_task.py`", and that the ceilings are not defence in depth on top of that
person, they *are* that person expressed as constraints. Queue depth and the
per-task caps landed in 013 and 003. The credit ceiling is 014. Until 014 is
applied to the deployed database, enabling this timer is the state §6.1 names:
no ceiling at all, the earlier one having been removed and the later one not
yet built.

Run one tick by hand at any time, timer or no timer:

    sudo systemctl start fleet-runner.service
    journalctl -u fleet-runner -f

### Why 20 minutes, and why a window

Measured on this host, from `runs`:

    draft-spec   task 21   4m05s     task 22   4m35s
    code         task  5  11m34s, 12m00s, 10m45s     task 7  13m40s

Twenty minutes clears the observed worst case by about 45%. Ten would not: no
code task has ever finished in under ten minutes, and "four to five minutes" is
only true of the draft-spec half of the queue.

The window is 02:00–04:40, nine fires, for a queue that holds five. It ends
well before `fleet-proposer-cycle` at 07:30 and `fleet-brief` at 07:45, so an
agent is never on this box alongside the cycle and every overnight branch is
settled in the database before the brief reads it.

### The interval is not a spend control, and must not be read as one

Measured, not assumed. A scratch oneshot sleeping 100s under a 30s timer, and
again under `OnCalendar` every minute:

    08:27:00.969  START pid 2635359
                  (the 08:28:00 slot elapses while it is still running)
    08:28:40.973  END   pid 2635359
    08:28:40.988  START pid 2636335      <- 15ms later, NOT 08:29:00

Two instances never ran concurrently under either form, so `claim_task()`'s
`FOR UPDATE SKIP LOCKED` is not load-bearing against the timer and the unit
needs no lock of its own. Keep the skip-locked claim regardless: it is what
protects a hand-run `run_task.py` from racing a timer fire, which the unit
cannot prevent.

But systemd **queues** the missed fire rather than dropping it, and runs it the
instant the unit goes inactive. So the interval sets a minimum gap when ticks
are short and throttles nothing at all when they are long. What bounds a day is
the window (nine fires), the queue depth (five), `max_cost_gbp` per task, and —
once applied — the monthly credit ceiling. Not the twenty minutes.

### `Persistent=false`, unlike the brief

`fleet-brief.timer` catches up because a missed brief is a gap in a series meant
to be compared. A missed runner window costs nothing to skip: the tasks are
still `QUEUED` and tomorrow's window drains them. Catching up would mean
starting to spend money at whatever hour the host came back, with nobody awake
and nothing expecting it.

### `SuccessExitStatus=0`, unlike the brief

`run_task.py` exits 0 when a branch is ready **or** when nothing was queued, 1
when the task failed, 2 on a configuration problem. The brief widens this
because a brief that could not reach a source still produces a brief. A failed
task is the opposite: it produced nothing and spent money doing it, and at
`max_attempts=1` it is terminal. It belongs in `systemctl --failed`.

`Type=oneshot` with no `Restart=` is also what makes a failure terminal on the
systemd side — a failed oneshot is not re-run, so a failing task cannot spin the
timer. The next fire claims the *next* task, because the failed one is no longer
`QUEUED`.

### The sandbox needs more exceptions than anything else here

`ProtectHome=read-only` is the default in every unit in this directory, and
`fleet-brief.service` set the pattern of opening exactly one directory and
arguing for it. This unit runs git and a subprocess agent, so it needs six:
`.fleet-worktrees`, both repository checkouts (git writes `.git/worktrees` and
branch refs — the *working trees* are never touched, and `worktree.Untouched`
asserts that after every tick), and the agent CLI's own state under `.claude`,
`.claude.json` and `.cache/claude-cli-nodejs`. Without the last three the agent
cannot start, and the tick fails with a task already claimed and its one attempt
already spent.

Proven on 8 Sep 2026: `systemctl start fleet-runner.service` claimed task 23,
created a worktree off `track-2-foundation`, ran the agent for 311s, derived the
diff, judged the boundary clean, and failed verification because the draft cited
a path that resolves nowhere — the check doing its job. Worktree removed,
checkout untouched, no second instance, unit `failed` as designed.
