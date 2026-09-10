# DD detection layer, V1

Two deterministic detectors. No model call anywhere in this package, and
there must never be one: a detector that can hallucinate produces output that
cannot be used as evidence.

    detectors/
      base.py            run lifecycle: open, evaluate, always close
      emit.py            observation insert + issue upsert, fingerprinting
      heartbeat.py       fleet_heartbeat
      reconciliation.py  dd_analytics_reconciliation
      sqlfile.py         loader for the versioned SQL below
      config.py          .env / environment
      queries/           one SQL file per query, named <key>.v<n>.sql
    run_detector.py      python run_detector.py <detector_key>
    tests/               pytest, against a throwaway local cluster
    systemd/             timers, not installed and not enabled

## Running

    .venv/bin/python run_detector.py dd_analytics_reconciliation
    .venv/bin/python run_detector.py fleet_heartbeat

Exit 0 on OK, PARTIAL or an already-executed window; exit 1 on ERROR.
`--slot-end` re-executes a specific settled slot.

## Timing

The reconciliation detector logs wall-clock per statement, per tenant, per
invariant, plus a summary at the end of the run. It is logged and never
stored: the schema has no column for it, and adding one would make a
performance note look like evidence. `journalctl -u
'fleet-detector@dd_analytics_reconciliation' | grep timing`.

## Retry

A window that closes ERROR is retried on the next invocation, up to
`max_attempts` from the registry, incrementing `attempt_count`. At the limit
it stays ERROR and `fleet_heartbeat` raises `DETECTOR_WINDOW_ABANDONED`
against it.

`reclaim_stale_detector_run()` deliberately reclaims only RUNNING rows -- a
process that died without closing its run. The ERROR case is the other half
and lives in `base.py`, because an ERROR run is an attempt that completed and
failed rather than one that vanished. Without it a single transient failure
cost that window permanently: `attempt_count` never advanced, so
`DETECTOR_WINDOW_ABANDONED` was unreachable and `max_attempts` was
configuration that did nothing, and `coverage_horizon_valid()` -- which
counts only OK and PARTIAL runs -- then refused to clear issues across the
hole.

Retrying re-executes the whole window. It cannot duplicate anything: the
unique index on `(detector_run_id, fingerprint)` makes the observation insert
a no-op, and `emit()` skips the issue upsert whenever the insert was skipped,
so `occurrence_count` is not double-counted either.

## A known trade in the evidence sample

`missing_analytics_order_sample` is pinned to v2, which adds an `OFFSET 0`
optimisation fence. v1 took 2117ms to return five rows because the planner
estimates that anti-join at `rows=1` when it really yields 29,603, concluded
no LIMIT could short-circuit, and built a hash over all 2.84M analytics rows.
The fence keeps `NOT EXISTS` a per-row filter over an ordered index-only
scan, and the LIMIT then stops after five surviving rows: 0.2ms, 23 buffers
against 137,609.

The cost is directional. It walks `woo_order_id` ascending until it finds
five offenders, so it is fast when offenders sort early and slow when they
sort late -- measured at 5.1s on the reverse ordering, worse than v1. Today's
gap is the 2026-08-18 rebuild, whose unmigrated orders are the lowest ids in
the table. A future gap from a live sync failing would be the highest ids and
would land on the slow side. If that happens, the fix is not to revert: it is
to fetch the count and the sample in one pass, which costs one anti-join
(~1.9s) regardless of where the offenders sit.

`orphaned_analytics_order_sample` has the same shape and the same exposure.
It is left at v1 because there are currently zero orphans, so there is no
data against which a rewrite could be shown to return identical ids.

## What is not in this code

* No thresholds. cadence, grace, settle_lag, evaluation_window,
  execution_timeout, coverage_mode, required_clear_runs, max_attempts and
  max_observations_per_run are read from `detector_registry` on every run.
* No severity. `route_severity(observation_type, magnitude)` decides, so
  retuning priorities is a data change.
* No window arithmetic. `open_scheduled_run()` derives the window; a direct
  INSERT into `detector_runs` is rejected by trigger, which is the point.
* No write path to deadly_digital. The role cannot write and the code does
  not try.
* No alerting. Shadow mode is the intended state. The dead-man's switch is
  not an exception: it is pinged from `on_success` and never from a `finally`
  block, so a failing run is silent by construction. The ping checks the
  response body, because healthchecks.io answers an unknown check UUID with
  HTTP 200 and `OK (not found)` -- status alone would let a mistyped or
  deleted check look healthy forever.

## Two properties worth keeping

`observations_created` is recomputed at close with
`SELECT count(*) FROM observations WHERE detector_run_id = %s`. A reclaimed
run's in-process counter starts at zero and would report a window as empty
that in fact holds everything the previous attempt already persisted.

A subject never appears in both `subjects_evaluated` and `subjects_failed`.
The coverage predicates read those arrays as a claim about what was actually
established, and a tenant the run could not read must not be able to clear
that tenant's open issues.

## Tests

    .venv/bin/python -m pytest tests/ -q

Needs a local PostgreSQL cluster. The suite builds `fleet_test` from
`001_v1_core.sql` verbatim and `dd_test` from a fixture with a hand-counted
gap, rebuilding both from templates for every test. Tests connect as
`fleet_test_detector` (member of `fleet_detector`, nothing else) and
`dd_test_reader` (SELECT only), so the triggers and grants that constrain the
real process constrain the tests too. Nothing in the suite touches production.

---

# The proposal layer, V1

Track 2. It reads track 1 and proposes. It never executes, never writes to
deadly_digital, and touches track 1's tables only with SELECT.

    proposer/
      config.py           two DSNs and cycle.yaml
      objectives.py       the quarter's objectives, read from the file
      adapter.py          what a reading is, and when it stops being usable
      detector_adapter.py the detectors adapter
      history.py          this layer's own past output
      findings.py         the computable findings
      cycle.py            rank, cut at five, write, report
      queries/            one SQL file per query, named <key>.v<n>.sql
    run_cycle.py          python run_cycle.py [--dry-run]
    review.py             python review.py [list|review|decide]
    cycle.yaml            thresholds and the finding -> objective mapping
    002_proposals.sql     proposals, proposal_evidence, decisions

`objectives-2026-Q4.yaml` is the authority on what matters. Nothing copies a
weight out of it into the database, and the cycle refuses to start if the
weights stop summing to 1.0 -- at that point ranking by weight is not
ranking.

## Three roles, because it is three jobs

    fleet_detector_reader  SELECT on track 1, and on this layer's own
                           proposals. Not on decisions.
    fleet_proposer         INSERT on proposals and proposal_evidence. It
                           cannot read a proposal back, cannot read track 1,
                           and cannot record a decision.
    fleet_console          the only principal the database accepts a decision
                           from, enforced by trigger exactly as
                           observation_verdicts is.

The cycle opens two connections on purpose. One role that could both read the
detectors and write proposals would make the read path and the write path the
same identity, and the separation is the only reason the database can say a
proposal was written by something that cannot read what it is judging.

A layer that can record its own approval is an agent marking its own work as
passing. `fleet_proposer` is absent from the decision trigger's list and
always will be.

## What the database enforces, not the application

* **A proposal with no evidence cannot exist.** A deferrable constraint
  trigger checks at COMMIT, because the evidence rows reference the proposal
  id and cannot be inserted before it. Deleting the last evidence row is
  refused by the same function.
* **Five items per cycle.** In a trigger, and deliberately not configurable.
  A cap that can be raised is a cap that will be raised on the morning the
  layer has six things it feels strongly about, and being forced to cut is
  what makes the ranking mean anything.
* **An OBSERVATION cannot carry an effort or impact estimate.** One that does
  is a recommendation wearing a disguise. V1 produces observations, so the
  check constraint is the difference between "we decided not to recommend"
  and "it cannot."
* **A proposal names an objective or it is a RISK.** The set of valid ids is
  quarterly data and is not frozen into the schema; the producer checks
  membership against the file, and `cycle.yaml` naming an objective the file
  does not contain stops the cycle before it reads anything.
* **A verdict freezes; what happened next does not.** `executed`,
  `abandoned_at` and `outcome_note` stay writable. `verdict`, `reason_code`,
  `decided_at` and `decision_seconds` do not.

## Freshness

Every adapter query declares a bound before it runs, and every reading
carries the timestamp of the newest fact it rests on. A reading past its
bound is returned marked STALE and no finding is computed from it, because a
finding built on stale evidence arrives looking exactly like a fresh one.

The bound is a property of the question. "How many issues are open" is only
as fresh as the last detector run, so its bound is registry geometry. "What
is the false-positive rate" is only as fresh as the last verdict a person
entered, so its bound is a human cadence in `cycle.yaml`. "When did each
detector last succeed" is correct whenever it is asked, and says so -- which
matters most during an outage, because it is the reading that explains why
all the others are unusable.

Staleness is judged per detector, against that detector's own cadence plus
grace, and reported for whichever is furthest past its own budget. A
heartbeat on a five-minute cadence quiet for an hour is further gone than an
hourly detector quiet for the same hour; picking the oldest timestamp instead
would report the second and miss the first.

## The findings

All five are arithmetic against a threshold in `cycle.yaml`. No model is
called anywhere in this package, and none is needed: a count of days is a
count of days, and generating a sentence about it would turn something
checkable into something that has to be trusted.

    issue_open_too_long          per severity
    detector_no_successful_run   never succeeded, or stopped succeeding
    false_positive_rate_rising   recent window against the one before it
    untriaged_observations       what the false-positive rate is starved of
    coverage_gap                 an open issue nothing can close, and why
    objective_no_activity        an objective this layer has said nothing about

Two of them can reach the same issue -- one that is both old and stuck -- and
the coverage gap wins, because it explains why the issue is still open rather
than only noting that it is. The fold is printed.

`objective_no_activity` cannot fire until the layer is older than the window
it measures. "Nothing in 14 days" is unknowable on day one, and firing it
then would fill the first fortnight with the news that it had just been
switched on.

## Ranking

Objective weight, and nothing else. No severity score, no impact estimate, no
composite -- the database refuses an observation carrying an estimate, so
this is enforced rather than intended.

Risks sort first. A RISK has no objective by construction and so cannot be
weighed at all, which leaves only "always above" or "always below"; below
means the cap can silently drop something actively breaking in favour of a
well-weighted observation. That is the one ordering rule weight does not
decide, and it is a categorical rule rather than a score.

Ties break on the finding key: arbitrary, but the same arbitrary order every
morning, so two runs over the same facts propose the same five things.

## What is cut is printed

Suppressed items, items cut by the cap, and every finding type that could not
be computed and why, all appear in the report. A layer that quietly showed
five things out of twenty would read as "here is everything", which is the
failure a cap invites.

## Review

    .venv/bin/python review.py            list undecided proposals with evidence
    .venv/bin/python review.py review     decide each in turn, timing each one
    .venv/bin/python review.py decide --proposal 7 --verdict REJECT \
                                      --reason ALREADY_KNOWN --seconds 20

Every decision carries the seconds it took. The number is not decoration:
this layer costs human attention and the only way to find out whether it
earns that is to measure it. In `review` the clock runs from the moment a
proposal finishes printing to the moment the verdict is entered. In `decide`
there is nothing to measure, so `--seconds` defaults to zero, which is an
honest zero rather than an invented duration.

Reason codes are an enum. A reason that can be spelled freely cannot be
counted, and counting rejections by reason is the only way this layer finds
out what it is bad at.

## Tests

    .venv/bin/python -m pytest tests/ -q

The same harness as track 1. `fleet_test` is built from `001_v1_core.sql` and
`002_proposals.sql` verbatim, and the tests connect as `fleet_test_reader`,
`fleet_test_proposer` and `fleet_test_console`, so the three-way separation
the design rests on is the one under test.

---

# The task runner, V1

Track 3. It takes a spec you wrote and produces a branch. It never merges and
it never deploys, and neither of those is a promise the code makes: there is
no transition in `task_transitions` that reaches a deploying state, and the
runner identity is not a member of any role that could write one.

    003_tasks.sql       tasks, the protected-path floor, the state machine
    contracts/          the acceptance contract per repo
    runner/config.py    four DSNs, and the contract loader
    fleet               fleet task add | list | status

## Stage 1 is the schema and the queue

    ./fleet task add --title "Refund reporting" --spec specs/refunds.md \
                     --objective dd-feature-parity --max-cost 3.00
    ./fleet task list
    ./fleet task status 7

The CLI connects as `fleet_console` and nothing else. `fleet_task_runner` has
no INSERT on `tasks`, so "no self-generated tasks in V1" is a grant rather
than a convention.

## Four identities, because it is four jobs

    fleet_console       writes the queue, and records every reviewed state.
    fleet_task_runner   claims a task and moves it between machine states. It
                        cannot insert a task and cannot review one.
    fleet_agent         writes PATCH_PROPOSED.
    fleet_verifier      writes VERIFICATION_RUN.

The last two are 001's, unchanged, and they are separate for the reason
`step_authority` exists: the thing that proposes a diff is not the thing that
certifies it. The runner process holds both, but never on one connection.

## What the database enforces, not the runner

* **A contract that leaves the test suite writable cannot be stored.**
  `protected_path_floor` is a table, checked by trigger at insert. Tests and
  migrations are on it. An agent that can edit the suite judging it can pass
  anything, and that rule cost several rounds in track 1; here it is a write
  that fails rather than a review that catches it.
* **A contract cannot contradict itself.** `api/**` writable with
  `api/tests/**` protected is refused, because the runner would otherwise
  have to pick a winner at diff time. The check found a real contradiction in
  the shipped contract on the first run: `api/analytics/**` swallowed
  `api/analytics/migrations/**`, and the writable set is enumerated now.
* **The boundary cannot move while work is inside it.** The acceptance
  contract is frozen once the task leaves QUEUED.
* **`spec_md` is append-only.** Rework feedback is the only learning signal
  this design has, and an update that could shorten it would lose the record
  of why the last attempt was wrong.
* **A task cannot be called ready for review without a branch and a run.**
  That is the one lie the status column could otherwise tell.
* **A run cannot outspend its task.** Without it the runner could open its own
  run with any `spend_limit_gbp` it liked and `max_cost_gbp` would be
  decoration.
* **Every task carries a bounded wall-clock cap.** `timeout_seconds` is NOT
  NULL and capped in a check constraint rather than in configuration, because
  a stuck agent burning budget in a loop is the failure this guards.

## Reusing `runs`, and the one change to 001

One task maps to one run, and the agent's steps are `PATCH_PROPOSED` and
`VERIFICATION_RUN` exactly as 001 designed them. A parallel log for this
track would be a second place for the same facts to disagree.

001 required every run to name an issue, because every run then came from a
detection. Feature work has no issue to name. `runs.issue_id` is now nullable
and `runs.task_id` exists, with a check that exactly one is set. The
alternative was a synthetic issue per task, which the coverage predicates and
track 2's findings would have read as a real open problem. This is the only
statement in 003 that alters a 001 object; the rest are additive.

Applied to a `runs` table with no rows, so no existing row had to be
revisited.

## A latent bug in 001, fixed here

001 created `step_authority` and granted it to nobody, so
`enforce_step_authority()` raised `permission denied for table
step_authority` instead of the message it was written to raise. It failed
closed, so nothing was ever unguarded, but the first agent to write a step
would have been stopped by the wrong error. 003 grants the read.

## Paths were checked, not remembered

The spec's example contract named `alembic/**`, `docker-compose.yml` and
`dd/detectors/**`. None of the three exists at those paths: migrations are
`api/alembic/**` and `api/analytics/migrations/**`, there is no compose file
at the repo root, and the detectors are in this repo, which a task against
the platform cannot reach. The shipped contracts name what is actually
there, and a test asserts every glob in each of them resolves.

## Stage 2 is the runner

    python run_task.py                 claim the next queued task and run it
    python run_task.py --task 7        run that task, if it is QUEUED
    python run_task.py --no-push       leave the branch local

**Also on a timer, and this paragraph used to say the opposite.** It said
`systemd/` carried no unit and no timer was enabled, because the build order
put the timer after three tasks had gone through by hand. Three did, the timer
went in, and this text did not move with it. `fleet-runner.timer` is enabled
and fires every 20 minutes from 02:00 to 04:40 — nine chances a night at one
task per tick, with the interval measured against real code tasks (none has
finished in under ten minutes) rather than against the draft-spec ones.

So **a task queued during the day is claimed overnight with nobody watching.**
That is the intended posture — see `specs/unattended-operation.md` — but it is
not something to discover from a branch that appeared. Queue accordingly, and
note that `auto_merge: false` in a contract stops the merge, not the run.

One task per tick. There is no loop in `run_task.py`, so two tasks are two
invocations and the cost and blast radius of an invocation stay one task
wide.

    runner/worktree.py  worktrees, and the guards around the one push
    runner/agent.py     the Claude CLI, under the runner's clock
    runner/boundary.py  the derived diff, and what it refuses
    runner/verify.py    the contract's verification commands
    runner/cycle.py     one tick

## The runner derives the diff, and the order is not the spec's

The spec's tick runs verification (step 5) before deriving the diff (step 6).
This runs them the other way round and refuses to verify a tree whose
boundary is dirty.

The reason is that a suite executed after the agent may have edited that
suite returns a result about the agent's tests rather than the project's. A
PASS obtained that way is worse than no result, because it arrives with
provenance attached. So: commit whatever the agent left, derive the diff from
git, judge it, and only then run anything.

The agent never commits and is told not to. The runner commits with `git add
-A`, which picks up deletions and files the agent simply left on disk, so
nothing it wrote sits outside the comparison. A diff derived from a commit
the agent composed would be a diff the agent chose the contents of.

Three ways to fail the boundary, kept apart because they mean different
things to whoever reads the branch:

    protected    it edited the suite, a migration, a deploy script
    outside      it edited something the contract never mentioned
    over limit   more changed lines than the contract allows

The agent is asked to end with a JSON list of what it changed. That list is
recorded next to the derived one and **no decision reads it**. Where the two
disagree, the divergence is stored on the `PATCH_PROPOSED` step, so an agent
that under-reports is visible afterwards rather than merely refused at the
time. `test_a_lying_agent_does_not_get_a_clean_boundary` is the case the
module exists for.

## The wall clock is the runner's, not the agent's

`timeout_seconds` is enforced by `subprocess` and a signal, never by asking
the agent to mind the clock -- an agent that is stuck is by definition not
going to notice. The kill goes to the process group rather than the child,
because the CLI spawns its own children and terminating only the visible
process leaves them running with the budget already spent.
`test_the_agents_children_are_killed_too` starts a real grandchild and checks
it is gone.

## It never merges and never deploys

Enforced in four places rather than promised in one:

* no transition in `task_transitions` reaches a deploying state, and
  `fleet_task_runner` is not a member of `fleet_deployer`
* `runs.status` is set to `AWAITING_HUMAN` or `FAILED` and never `DEPLOYED`
* `worktree.push` refuses the base branch, refuses a name that is not a task
  branch, never forces, and names an explicit refspec
* the checkout is snapshotted before the agent runs and compared afterwards,
  so "the working tree is never touched" is checked rather than assumed

## Four identities on four connections

    fleet_task_runner    claims the task, opens the run, records the branch
    fleet_model_gateway  reserves and settles budget
    fleet_agent          writes PATCH_PROPOSED
    fleet_verifier       writes VERIFICATION_RUN

001's `step_authority` is what makes the last two separate. One connection
holding all four would satisfy every trigger while proving nothing.

`reserve_model_budget` and `settle_model_budget` are `SECURITY DEFINER`, so
the budget trigger 003 puts on `runs` executes as `fleet_owner`. Without a
read on `tasks` that path failed with a permission error instead of the cap
it exists to enforce; the grant is in 003 and assertion C15 checks it on the
deployed database.

Cost is converted from the CLI's USD at a stated constant in `runner.yaml`,
not a live rate. Treat every cost in the database as accurate to about that.

## Contracts are scoped to what can actually verify them

**Verification scope and writable scope must match.** A contract declaring
`api/**` writable while verifying with vitest would accept a backend change on
the strength of tests that never executed it, and hand back a PASS with full
provenance attached. That is worse than no gate, because the provenance makes
it convincing.

    dd-analytics-frontend.yaml        the analytics proxies and pages,
                                      enumerated, plus four named components —
                                      tsc --noEmit, vitest run, the bite check
                                      and a paired-paths check
    deadly-digital-platform-api.yaml  api/analytics/{routes,services}, enumerated —
                                      compile, a lint ratchet, tests/unit and
                                      tests/analytics per file, and the bite check

### There is no default contract for deadly-digital-platform

`contracts/deadly-digital-platform.yaml` was it, and it is **deleted**. It
declared `platform/app/**`, `platform/components/**` and `platform/lib/**`
writable, which reaches `lib/auth.ts`, `lib/roles.ts`, `lib/csrf.ts`,
`app/api/auth/impersonate/route.ts`, `app/api/billing/checkout/route.ts` and
the campaign send route.

It was retired rather than narrowed. A wide contract standing beside a narrow
one makes the narrow one a convention rather than a boundary, because anybody
may queue a task under either -- and this one was reachable by *omission*,
since `fleet task add` fell back to `contracts/<repo>.yaml` when no
`--contract` was given. So `--contract` is now required for this repo, and
`load_contract` says why rather than reporting a missing file.

`023_platform_floor.sql` is the other half, and it is what makes the deletion a
decision rather than a tidy-up: those paths are on `protected_path_floor` now,
so restoring the file would not restore the reach. Two independent refusals for
one mistake, on the argument 018 and 019 were written with -- **unreachable by
contract is not the same as unreachable by floor.**

### Both files or neither

`paired_paths` is a contract key: within a group, every path is in the diff or
none is. `specs/dashboard-comparison-windows.md` needs it -- widening
`platform/app/api/analytics/dashboard/route.ts` without changing the label at
`platform/app/(dashboard)/analytics/page.tsx` lets the overview render
"vs previous 366 days" over a year-on-year comparison, which is worse than the
unqualified sentence task 28 exists to fix.

`024_paired_paths.sql` refuses a group that could not bite -- fewer than two
paths, no `why`, or a path outside `writable_paths`, which the task can never
change and so can never fail on. `contracts/checks/paired_paths.py` reads the
frozen contract out of `$FLEET_CONTRACT` and the diff out of git.

It establishes that both files moved. It cannot establish that the label is
right, and that is the only thing the pairing is for -- so
`dd-analytics-frontend.yaml` carried `auto_merge: false` until this had run a
few times.

**And on 10 Sep 2026 both of that contract's groups were removed**, replaced by
`contracts/checks/proxy_passthrough.py`: every parameter a page sends must be
one its proxy forwards. A pairing was a proxy for that property and was wrong
in both directions -- it refused every later single-file change once both
halves had landed (task 55, £2.25 and one attempt, for a diff that introduced
no parameter at all), and it passed a change that touched both files while
still dropping one. The key, the migration and the check above are unchanged
and are still the right shape for a pairing that genuinely holds; what was
wrong was using one where the property itself could be checked. The argument is
in the contract, above its writable list.

Neither backend command was lowered to make it pass, because neither can be
made to pass (measured 30 Aug 2026 at `921e22b`):

* `pytest api/tests/ -q` is **red by baseline everywhere**, not merely here:
  `api/CLAUDE.md` records ~81 pre-existing failures on a clean database from
  CI or a dev machine. Standing up the test Postgres changes nothing. This
  host must not run the suite at all -- it is the app host.
* `ruff check api/` reports 402 findings of which **337 are unreachable**
  from any contract: 261 in `api/tests/` and `api/alembic/`, which are
  protected paths, and 65 in files no contract makes writable. A gate that
  fails every task for a mess the task may not touch is not strict, it is
  unreachable, and an unreachable gate teaches everyone to ignore it.

Both are recorded, with what would fix them, as `TEST-004` in the platform
repository's `docs/TODO.md`.

## Lint is aimed at the change, as a ratchet

`{changed_files}` in a verification command expands to the paths **the runner
derived from git** -- never the agent's account -- with an optional suffix
filter, `{changed_files:.py}`. A check whose filter matches nothing is
recorded as *skipped* rather than passed, and **a run in which every check
skipped does not pass at all**: nothing looked at the change, so nothing was
established.

Checks also receive `FLEET_BASE_SHA`, `FLEET_HEAD_SHA` and
`FLEET_CHANGED_FILES` in the environment, from the same derivation.
`contracts/checks/ruff_no_new_findings.py` uses them to lint each changed
file at head and at base and fail only on findings the change introduced.

A ratchet rather than a clean-file rule, on evidence:
`api/analytics/routes/revenue.py` carries a pre-existing `I001`, so a
one-line docstring fix there would fail a clean-file gate for history it did
not create -- and satisfying such a gate means every task arrives carrying an
unrelated import-sort, which is the diff-widening
`specs/revenue-granularity-doc.md` explicitly forbids. **A gate that
contradicts the spec it enforces gets satisfied by widening the diff.** No
rule is disabled; the gate is pointed at the diff.

## Dependencies are linked in after the diff, never before

`node_modules` and `api/.venv` are gitignored, so a fresh worktree has
neither and `tsc` cannot start. `worktree_links` in a contract points the
worktree at the checkout's installed tree.

**The timing is the safety property, not the symlink.** The runner creates
these *after* the diff is derived and the boundary judged, so the agent never
sees them. A write through one would land outside the worktree's git index
entirely -- not merely in an ignored path -- and the derived diff would show
nothing at all. Creating it any earlier opens a hole no later check can
close. `test_the_agent_never_sees_the_linked_dependencies` is that property.

## Tests

    .venv/bin/python -m pytest tests/ -q

The same harness. `fleet_test` is built from `001_v1_core.sql`,
`002_proposals.sql` and `003_tasks.sql` verbatim, and the tests connect as
`fleet_test_task_runner`, `fleet_test_agent`, `fleet_test_verifier` and
`fleet_test_console`, so the separation the design rests on is the one under
test. `003_tasks_assertions.sql` proves the deployed grants and triggers are
the ones that behaviour was proved on.

The runner's tests use a real git repository, real worktrees and the real
four identities, with the agent faked -- deliberately hostile in several of
them. An agent that edits the suite and reports that it did not is the case
the runner exists for, and it is easier to arrange than to wait for.

---

# The decision log, V1

Track 4, if it is a track at all: it is one table, one view, four CLI commands
and one page. Fleet already recorded proposals, verdicts, tasks, runs and
costs. What it never recorded was the middle of that sequence — a proposal was
raised, **something was decided**, and work happened or did not. `tasks` was
the closest thing to a record of a choice, and it only holds the ones that were
approved: every rejection Fleet has ever produced left no trace at all.

    010_decision_log.sql   decision_log, decision_outcomes
    fleet decision …       record | list | show | backfill
    console /decisions     read-only, no form

## It is not called `decisions`, because that name is taken and correctly so

002 has a `decisions` table. It is the verdict on **one proposal** from the
proposal cycle: `UNIQUE (proposal_id)`, an enum reason code sized for counting
what that layer is bad at, and `decision_seconds` measuring what the layer
costs in human attention.

`decision_log` is the log across **every** source of a decision — a proposal, an
issue, a task, or nothing at all — with a free-text reason. Widening 002's table
to serve both would have meant dropping the UNIQUE that makes "one verdict per
proposal" true, making `proposal_id` nullable so the FK no longer says the
cycle's grading is complete, and adding free text beside the enum — at which
point the enum is optional and stops being countable. Two tables, two jobs.

## The outcome is not in the table, and there is nowhere to put one

Every outcome lives in `decision_outcomes`, a view recomputed on every read:

| field | derived from |
|---|---|
| `task_status` / `task_outcome` | `tasks.status` |
| `total_cost_gbp` / `runs_total` | **every** run of the task, not the latest |
| `attempts_to_green` | `tasks.attempts`, and **NULL until there is a green** |
| `issue_status` / `issue_outcome` | `issues` and `issue_occurrences` |

There is no `outcome` column, no `worked_out` boolean, no `cost_actual`. That
is the enforcement rather than the intention: a column someone can type into
holds what someone believed when they typed it, and a decision log whose
outcomes are self-reported is a record of intentions dressed as a record of
results. `test_writing_an_outcome_is_a_missing_column_not_a_silent_accept` is
that property, and assertion J3 checks it on the deployed database.

**A reopen outranks the current status.** An issue that was resolved, came
back, and was resolved again reads `REOPENED`, not `RESOLVED_HELD`. Reading
`issues.status` would report a decision that worked; it did not work, and the
second fix belongs to whatever decision produced it. `issue_occurrences` is the
source because it carries timestamps — `issues.reopen_count` is a counter and
cannot say whether the reopen was before this decision or after it.

**Attempts-to-green is NULL for anything that is not green.** A number there
for a task still in flight, or one abandoned, is attempts-so-far wearing the
name of a result.

**Cost is every run.** Task 5 took four runs at £5.00, £4.80, £5.57 and £4.58.
The latest is £4.58 and the answer is £19.95; the console's task list made
exactly this mistake before `spent_all_runs` existed, so the test uses those
figures.

## The reason is NOT NULL on every row, and the sentinel is reserved

Including rejections and deferrals. This is the point of the table: approval is
recoverable from the work that followed, and rejection leaves nothing behind at
all, so the rejection with a reason is the more valuable row.

Free text rather than 002's enum, because the reason a thing is rejected is
usually the part that did not fit a vocabulary chosen in advance — a forced
enum turns it into `WRONG_PRIORITY` plus a lost sentence.

Two constraints, and both are needed. `NOT NULL` alone accepts a space.
`UNRECORDED` — which the backfill uses — is refused on any row whose origin is
not `BACKFILLED`, because otherwise it becomes the way to satisfy the NOT NULL
and the constraint is decorative.

## Backfilled rows say so, on two axes

`origin` is `RECORDED` or `BACKFILLED`; `confidence` is `STATED` or `INFERRED`.
Two columns rather than one because the implication runs one way only: a
backfilled row can never be `STATED`, but a row recorded live may still be
`INFERRED` — a decision written up the following week from notes. A check
constraint encodes that asymmetry.

`fleet decision backfill` writes one decision per existing task, dated
`tasks.created_at` — **the moment the work was chosen, not the moment it
merged**, because the merge is an outcome and the view derives it. Nothing is
invented: `reason` and `decided_by` are the sentinel, `evidence` is empty
rather than filled with something synthesised to avoid looking empty, and a
repo with no product mapping stops the command instead of defaulting. It is
idempotent, and a dry run is the default.

## Who may write it

The same rule as `decisions` and `observation_verdicts`: `fleet_console` and
nothing else. `fleet_proposer` and `fleet_task_runner` are absent from the
trigger's list and hold no grant — both are things a decision is made **about**.
`fleet_detector_reader` cannot read the log for the reason 004 gave the console
its own read identity: the layer being graded does not see the grade.

The reversion check found this pair was not actually proven. The runner is
refused by two mechanisms — the missing grant and the trigger — so a test
accepting either exception passes with the trigger disabled.
`test_the_trigger_refuses_the_runner_even_when_it_holds_the_grant` grants the
runner INSERT on a throwaway database first, leaving only the trigger.

## Tests

    .venv/bin/python -m pytest tests/test_decision_log.py \
                              tests/test_decision_cli.py \
                              tests/test_console_decision_log.py -q
    .venv/bin/python tests/revert_schema_guards.py

The second is the sibling of `revert_guards.py` for SQL guards: it edits
`010_decision_log.sql`, gets the template database rebuilt from it, and
confirms the matching test fails. Ten guards, all proven. `security_invoker` on
the view is deliberately **not** in it — removing it breaks no behavioural test,
because both console roles hold the base grants either way, so it is checked in
`010_decision_log_assertions.sql` (J5) instead. A reversion case that pretended
to cover it would be the failure the script exists to find.

## A branch drift this uncovered, and closed

`decision_outcomes` is `security_invoker`, so `fleet_console` reads `issues` and
`issue_occurrences` through its own grants. It held them on the deployed
database and **not in this branch's migration files**: commits `712195d` and
`a99f17c` added `GRANT SELECT ON observations, issues TO fleet_console,
fleet_evaluator` to `001_v1_core.sql` on `master`, and `track-2-foundation` —
which carries 002 through 011, the console and the runner — had never been
merged with it. Production had the grant because the migration identity owns the
tables; a database built from these files did not, and the suite failed on
exactly that.

**Merged in `168e8bb`**, not papered over. `master` was four commits ahead: the
two grant commits, and two documentation ones. The only file conflict was
`tests/conftest.py`, where both branches had added fixtures — resolved by
keeping both, so `fleet_test_evaluator` and the four track-3 identities now
coexist.

010 still restates the two grants it depends on, narrowed to the tables its view
reads. A file should name what it depends on rather than inherit it silently
from a line two migrations away that has already gone missing once.

**`tools/schema-drift-check.sh` is what keeps it closed.** It builds a database
from 001–011 on the local cluster, fingerprints it and production at the catalog
level, and diffs. Run after this work: **790 objects each, no structural
drift.**

`pg_dump` is not usable for this — the servers are different major versions
(RDS 15.17, this box 16.x) with different owners and login roles, so every
object would differ on `OWNER TO` alone. The fingerprint compares catalog rows
instead and excludes ownership and login roles deliberately: those are
environment, not schema. It emits the server major version first, and treats a
difference confined to view-body hashes as not-comparable when the majors differ
— `pg_get_viewdef` qualifies CTE columns with the alias on 16 and not on 15, so
`observation_coverage` hashes differently while being the same view. View output
*shape* is still compared either way, through `information_schema.columns`.

Writing it caught a hole in its own first draft: the enum query said `GROUP BY 1`
over an expression containing an aggregate, so it errored on **both** sides and
the types were silently never compared. Six objects appeared the moment it was
fixed.

## `product` on proposals, and the `review.py` wiring

`proposals.product` is migration **011**. `area` was doing two jobs — three
producers set it to the product, two to the detector key, one to the literal
`fleet` — so it could not be grouped on, and `decision_log.product` had nothing
to take a value from when a decision cited a proposal.

**NOT NULL, not nullable-and-usually-set.** A proposal that cannot say what it
is about is incomplete rather than under-specified. Prompting for it at review
time pushes the gap onto the reviewer every morning; inferring it from the
evidence is a guess wearing a derivation's clothes.

**`area` is kept and not repurposed.** Two of its spellings are detector keys,
which are useful and are not products. Renaming the column would have made the
historical rows lie about which of the two things they held.

All six producers now set it:

| producer | source |
|---|---|
| `issue_open_too_long`, `detector_no_successful_run`, `coverage_gap` | the row's own `product` |
| `false_positive_rate_rising`, `untriaged_observations` | resolved through `detector_health` |
| `objective_no_activity` | `FLEET_PRODUCT` — it is a statement about this layer |

The middle pair are keyed by detector, not by product, so `_detector_products`
builds `detector_key -> set(product)` from the registry and
`_product_for_detector` **refuses a key that maps to none or to more than one**,
skipping the finding with a reason. `detector_registry` is keyed
`(detector_key, issue_key_version, product)`, so two products under one key is a
shape the schema allows; picking one would file a proposal under a product it is
not about, which is the failure `product` was added to prevent.

The backfill in 011 invents nothing: it takes the only product `issues` has ever
recorded, and **raises** if that is not exactly one. A default would file the
existing row under a product nobody chose.

**It half-applied on the first attempt, and the reason is worth keeping.**
`proposals` is append-only — 002 puts `reject_mutation()` on UPDATE, with no
fleet_admin escape — so the backfill was refused with `UPDATE on proposals
denied for listmonk`, leaving the column added and nothing else. The local
rehearsal had passed because that database held **no proposals**, so the UPDATE
never ran. *A migration whose backfill is only exercised when there is nothing
to backfill has not been exercised.* The rehearsal now seeds a proposal first,
in one transaction, because the evidence constraint is deferred to COMMIT and
psql's autocommit had silently thrown the seed away too.

011 is now wrapped in `BEGIN`/`COMMIT`, idempotent (`ADD COLUMN IF NOT EXISTS`,
guarded constraint and index), and disables `proposals_immutable` for the
backfill and re-enables it in the same transaction — so a failure anywhere rolls
the disable back and cannot leave the table writable. `ALTER TABLE ... DISABLE
TRIGGER` is the right instrument because the capability is already scoped: only
the table owner can do it, and the owner is the migration identity. Verified
afterwards on production that an UPDATE is refused again.

### Every verdict now opens a decision log entry

`review.py record()` writes both, and `--why` is required on `decide` as well as
in the interactive loop.

* **One transaction.** A verdict recorded without its log entry is precisely the
  split this work closes. The explicit `conn.commit()` afterwards is not
  redundant and the tests proved it: psycopg opens an implicit transaction on
  the first statement, so `conn.transaction()` was a SAVEPOINT inside it, and
  leaving the block released the savepoint without committing. Both rows were
  written and neither was durable.
* **Every verdict, including rejections and deferrals.** "When a verdict leads
  to action" taken literally logs approvals and drops rejections, rebuilding the
  asymmetry the log removes.
* **The enum and the sentence, both.** `reason_code` stays on `decisions` for
  counting; `--why` is what gets read in six months. Falling back to the code
  would put `ALREADY_KNOWN` in the field whose purpose is to hold what the code
  could not, so an empty `--why` is refused rather than defaulted.
* **`SKIP` logs nothing.** Skipping is not deciding, and it never reaches the
  reason prompt — a test patches `prompt_why` to fail if it does.
* **Subject, evidence and product are captured, not retyped.** The trigger takes
  the first two from the proposal; the product comes off the proposal row.

Three cases in `tests/revert_guards.py` cover this half, all proven.

## Also fixed here: `fleet task list` counted runs, not tasks

It printed 10 rows for 7 tasks and a summary reading `MERGED 8 ABANDONED 2`,
because a plain `LEFT JOIN runs` returns one row per RUN — task 5 has four. The
console hit the same thing and fixed it with a LATERAL; the CLI kept the join.
It now uses the same LATERAL, shows a `runs` column, and sums **every** run's
cost rather than the latest, which is the same understatement
`decision_outcomes` refuses.


---

# Precedent, V1 — the layer reads its own record

Fleet recorded twelve decisions and six briefs before anything read any of it
back. `decision_log` says what was chosen and why; `decision_outcomes` derives
task status and cost. Nothing consulted either. **The distinction being closed
is between a trace and a lesson:** a trace lets you replay what happened, and
Fleet had traces.

Two halves. The derivation is finished in `outcomes.py`; the cycle states the
record in `proposer/precedent.py` before it ranks anything.

## The reach fix is the largest part, and it needed no new source

`decision_outcomes` joins `tasks` on `decision_log.task_id`. 013 records the
link the other way round — the approval surface writes
`candidates.approval_decision_id` and fills in `spec_task_id` and
`work_task_id` as the tasks are created — and the view has never traversed it.

On the live record that is the difference between one decision reading as an
unknown and reading as **six tasks with three failures in them**. Following
both routes takes reach from 7 decisions and 7 tasks to **8 and 13**.

`decision_reach.v1.sql` returns one row per (decision, linked task) and labels
which route found it. They are not the same claim: `DIRECT` is a task somebody
named when recording the decision, `CANDIDATE` is a task the approval surface
created from it.

**Twelve of twenty decisions still cite nothing at all** — no proposal, no
issue, no task — and for those no outcome is derivable by any route. That is
printed rather than absorbed into a denominator.

## Merged: the status column and the repository are two claims

`tasks.status = 'MERGED'` is a word a person typed. `run_steps.payload` carries
the commits, so git can be asked independently whether the work is in the
task's base branch — preferring the merge commit over the branch tip, for the
reason below. **`MergeEvidence` returns both and never collapses
them.** A task marked MERGED whose patch is not in its base is the finding —
the merge did not happen, or it happened onto something else, or the branch was
rebuilt and the recorded sha is not what landed — and none of those is visible
from either source alone.

Two things the obvious version gets wrong, both of them live on this record:

* **The baseline comes from `tasks.base_branch`, never from a constant.** The
  platform's tasks are based on `main`; fleet's seven are based on
  `track-2-foundation`, which has no remote-tracking ref, and its one `main`
  task is against a repository whose remote branch is `master`. Hardcoding
  `origin/main` answers NO_BASELINE for eight of twelve tasks and reads like a
  data problem rather than a wrong constant.
* **A local ref answers a weaker question and is labelled.** "In `origin/main`"
  is a claim about the shared repository; "in the local `track-2-foundation`"
  is a claim about this checkout, which nobody else can see. Substituting the
  second for the first is how work that exists only on this host reads as
  landed.

Where git cannot answer — no sha recorded, no checkout, an unfetched object —
the result is `computable = False` and **never a disagreement**. Absence of
evidence must not read as evidence of contradiction.

## Deployed: `console.deploys` already had this right

No run reaches DEPLOYED, deliberately, so the database cannot answer it. The
drift state files can, and `console/deploys.py` is the only thing on this host
that parses them. `outcomes.py` imports it rather than copying it — a second
copy would be a second definition to drift, which is the trade this codebase
takes every time. If a third caller appears, lift the module to the root.

**The frontend is why the routing matters and not just the plumbing.** The
frontend and the API share a repository, so a merged frontend commit *is* an
ancestor of the running API's commit — while `drift-frontend.state` reads
`UNKNOWN`, because that container carries no `GIT_SHA` and is not instrumented.
Asking git one global question answers SHIPPED. The truthful answer is that
nobody has looked. So every task is routed through `GOVERNED_BY` to the
deployment that governs it, and only a fresh `OK` may support a claim.

Ancestry is carried beside the verdict as corroboration and **never promoted
into it** — a repository on this host knows nothing about what a container is
running. A reversion that promotes it fails
`test_ancestry_never_overrides_the_verdict`.

Today: of 13 linked tasks, **2 verified in a running container, 1 cannot be
said, 10 governed by nothing that deploys.** The drift files hold the current
sha and a `since`, no history, so the answerable question is "is this in what
is running now", never "was it deployed at the time".

## Whether anything broke afterwards is UNCOMPUTED, and that is the answer

The query is one predicate — `issues.first_seen > decided_at` — and it returns
zero for every decision in the log. **The zero is worthless.** Two detectors
are registered, both on `deadly_digital`, watching analytics order
reconciliation and detector liveness. The one issue ever recorded predates
every decision. The decisions changed CI configuration, documentation, revenue
routes and a frontend page, and nothing observes any of that.

So the count is **not computed at all**, rather than computed and hedged. The
reason names the detectors and their product, because the finding is the shape
of the observing surface and not the state of the code. A clean bill from
detectors watching something else is the "plausible brief" failure
`specs/daily-brief.md` §0 exists to prevent, one system over.

## The proposer reads it, and that is allowed only because it cannot act on it

`010` refuses `fleet_detector_reader` — the identity the cycle reads track 1
with — any sight of `decision_log`: the layer being graded does not see the
grade. The cycle now opens a **third connection** as the detector identity 012
already granted the log to, which can read it and write nothing anywhere.

That keeps the identity half of 010's rule and gives up the process half, and
saying otherwise would be dishonest: the cycle process now holds its own record
in memory. What replaces the half given up is structural.

> **Precedent is an output, never an input.**

`rank()` is not passed it, `findings.compute()` has already run by the time it
is fetched, and the suppression loop does not consult it. A proposer that
ranked on its own approval history would be optimising for approval rather than
for what is true, which is exactly what the refusal was guarding.

**That is the condition the feature was allowed under, so it is proven rather
than asserted.** Four cases in `tests/revert_guards.py`: feed the total into the
ranking, feed the rejection count into it, stop reading the log, widen `rank()`'s
signature. All four fail their test.

**The first version of that test could not catch the first two.** It seeded one
finding, and a one-item list sorts identically in every order; and its two
worlds differed only in the total, 1 and 7, both odd, so a reversion keyed on
`total % 2` sorted them the same way and passed. The crowded fixture — eight
findings against a five-item cap, so order is observable — and the two worlds
differing on **every** scalar precedent exposes are both there because the
reversion script reported it. A test whose world cannot express the failure is
not a guard.

## What it would take to be wrong

The facts are counts over rows that exist. The hazard is not that they are
false, it is that a record this size is not representative of anything, and a
true sentence read as a pattern misleads harder than a false one. Four guards,
all printed:

* **`basis:` under every block** — how many rows, over what span, how many
  backfilled, how many with no derivable outcome. The size of the record sits
  in the same place as the claim.
* **Zero rejections is printed under EVERY approval sentence, not once at the
  top.** 0 of 20, and 010 exists because "every rejection Fleet has ever
  produced left no trace at all". A log that has recorded none since is either
  unbroken agreement or a log still not receiving them, and nothing in it
  distinguishes those. Every count in those blocks is a count over approved
  decisions — only an approval produces a task — so each can be read as "this
  is how decisions turn out" by someone who never sees the missing half. **The
  repetition is the mechanism.** A caveat stated once is a caveat scrolled past.
* **Below `precedent.compare_floor` a group is listed, not compared.** The
  counts still print; the summarising sentence does not. `dd-trustworthy`'s four
  linked tasks are below it today. In `cycle.yaml` because it is a judgement and
  judgements get retuned.
* **`UNCOMPUTED` is reachable and fires.** The regression claim is refused every
  day; an empty log refuses the whole block; an unreadable log degrades to a
  reason rather than killing the morning. A guard that can never fire is
  decoration.

**No rates, no percentages, no trend, no interval.** Twelve or twenty decisions
is a record you read, not a distribution you sample.

## A correction: the merge commit was never discarded

An earlier note in this section said `console/merge.py` computes
`base_sha_after`, verifies the push against it and then discards it. **That was
wrong.** `merge.py` returns it on `MergeOutcome`, and `console/app.py:351` puts
it on the `HUMAN_DECISION` step as `merge.merge_commit`, inside the same
transaction as the status change. All four merged tasks on the live record
carry it, alongside `base_before`, `branch_tip`, `remote_sha`, `pushed` and
`push_verified`.

The mistake came from reading `merge.py` in isolation, grepping it and
`approve.py` for a write, finding none, and concluding the value was dropped —
without opening the caller. **A module that returns a value has not discarded
it; only its callers can do that.**

What was true is the part that mattered: nothing *read* it. The derivation
asked git about `patch_commit_sha`, the branch tip, which is the weaker
question. That is now fixed.

## Three commits, and only one of them is the merge

    patch_commit_sha   what the AGENT wrote — the branch tip, PATCH_PROPOSED
    merge_commit       what LANDED — base_sha_after, verified against the
                       remote before any verdict was written, HUMAN_DECISION
    base_before        where the base stood before the operation

A branch tip that is an ancestor of `main` is **consistent with** the merge and
does not identify it: the same tip is an ancestor after a merge, after a
cherry-pick, and after somebody else merged the branch. The merge commit is the
fact. `choose_sha` prefers it and `sha_kind` reports which question was
answered, so an inference never reads as a fact. Today 3 of 5 merged tasks can
be answered from the merge commit; task 5's merges predate this path and it
falls back to the tip.

**`already_merged` is part of reading the field, and the trap is live.**
`merge_commit` is `base_sha_after` — the base branch *after* the operation — and
when the branch was already in the base there was no operation, so the sha is
simply where the base stood. Task 1 carries `already_merged: true` with a
`merge_commit` of `63130ad7`, which is **"Merge branch
'docs/backend-gate-findings'"** and has nothing to do with it. Used
unconditionally, the field credits a task with another branch's merge. Two
guards in `revert_guards.py` hold both halves of the rule.

## Files

    outcomes.py                              merged (git) and deployed (drift)
    proposer/precedent.py                    the facts, the basis, the floor
    proposer/queries/decision_precedent.v1.sql   the shape of the record
    proposer/queries/decision_reach.v1.sql       both routes, and both commits
    proposer/queries/observing_surface.v1.sql    why regressions are refused
    tests/test_precedent.py                  14 tests
    tests/test_outcomes.py                   13 tests
    tests/revert_guards.py                   30 guards, all proven

No migration, no new dependency, no write anywhere, and nothing merges.
`decision_log` and `decision_outcomes` are read-only here and `010` is
untouched.

---

# dd_api_errors — the third detector

Sentry has been collecting from `deadly-digital-api` and the worker since the
DSN was set, and nothing had ever read it. Every error it holds has been
invisible: `docker logs` shows a handled exception only if something logged it,
and an unhandled one only until the buffer rolls.

## The credential is a PERSONAL token, tied to one account

`SENTRY_AUTH_TOKEN` is an `sntryu_` **user auth token** created under Settings
→ Account, carrying `event:read` and `project:read`.

**Organisation auth tokens (`sntrys_`) cannot do this job.** One was tried
first. It authenticated and read `/organizations/{org}/releases/` (HTTP 200)
while returning 403 on every issue endpoint, and Sentry named the reason in the
response header rather than leaving it to be guessed:

    WWW-Authenticate: Bearer error="insufficient_scope",
                      scope="event:admin event:read event:write"

The organisation token UI offers `org:ci` and not `event:read`, so that route
is closed rather than merely unconfigured.

**What that costs: this is a person's credential, not a service one.** It dies
with the account, it carries whatever that account can see rather than a scope
someone chose for a machine, and a leaver takes the detector with them.

**The alternative that would not:** an **internal integration** under Settings
→ Developer Settings, with Issue & Event: Read. Its token belongs to the
organisation rather than to a person and survives a change of hands. **Worth
revisiting if this account ever changes hands** — the detector needs no change
for it, only a different string in `.env`.

## The DSN cannot read, and that is why this needed a new secret

`SENTRY_DSN` in the app container is an **ingest key**. It authorises sending
events and nothing else; there is no read path through it. Reading issues needs
an organisation auth token with `event:read` — a different credential with a
different lifetime — and it lives in `fleet/.env` with every other fleet
secret. The app writes to Sentry, fleet reads from it, neither holds the
other's credential.

    SENTRY_AUTH_TOKEN=…      an org auth token with event:read
    SENTRY_ORG=…             the org SLUG, not the o… id from the DSN
    SENTRY_PROJECTS=…        comma-separated project SLUGS
    SENTRY_API_BASE=…        optional; the org is EU-hosted, so this is
                             probably https://de.sentry.io/api/0

**The numeric ids in the DSN are not slugs.** `o4510793576611840` and
`4510793592864848` identify the org and project to the ingest endpoint; the
issues API wants slugs. And a 404 from the wrong regional base is
indistinguishable from a missing project, which is why `_http_get` names the
base it used in that error rather than reporting "not found".

## The one rule, in four places

**A failed read must never become a zero**, because a zero is what the brief
turns into "no unresolved issues" — a sentence that is worst exactly when it is
wrong. It is enforced four times rather than intended once:

1. **A project that could not be read is a failed subject**, so `base.py` closes
   the run PARTIAL and the coverage predicates already know what that means. Not
   an observation of absence.
2. **Enumeration refuses to return an empty list.** Zero subjects closes a run
   OK with nothing in it, which is indistinguishable from a clean project — the
   most dangerous state available here, and the only failure the harness would
   record as success. An unconfigured detector is an ERROR, and the heartbeat
   escalates it.
3. **The brief reads the RUN, not the newest observation.** This is the one that
   matters. Yesterday's clean read recorded a real zero; today's token expired.
   Reporting yesterday's number is reporting a true figure about a moment nobody
   asked about, and it renders as reassurance.
4. **`Claim.uncomputed` has no value parameter**, so a refused claim carries no
   number for any renderer, this one or a later one, to print.

Four states, and one of them prints a number:

| newest scheduled run | claim |
|---|---|
| none | UNCOMPUTED — "…has never completed a scheduled run. This is not a report of zero errors" |
| not OK | UNCOMPUTED, carrying the run's own error text and the failed subject |
| older than cadence + grace | UNCOMPUTED — not today's answer |
| OK and fresh | COMPUTED, and a zero here is one the run **established** |

The staleness allowance is `cadence + grace` read from `detector_registry`, so
the brief and the heartbeat agree about "overdue" by construction rather than
by two numbers that drift.

## A gap in `base.py`, found by writing this

A PARTIAL run recorded **which** subject failed and not **why** — the error text
was `"1 subject(s) failed: <label>"` and the cause existed only in the process
log, which is long gone by the time the brief reports the gap the next morning.
`RunContext.mark_failed` now takes a reason and `_close_run` appends the first
one. The ERROR path already did this; only PARTIAL was silent.

## What it cannot tell you

- **Not that an error did not happen.** Sentry drops events on quota exhaustion
  and on SDK-side network failure. "0 unresolved" is a claim about Sentry.
- **Not which tenant.** `send_default_pii=False` and no tenant tag is set at any
  of the six `capture_exception` sites, so an error on HIB's revenue page
  arrives indistinguishable from any other.
- **Not whether it mattered.** Volume is a proxy for urgency, not importance: a
  loud harmless error outranks a quiet data-losing one on this scale, and
  nothing here can tell them apart.
- **Not more than one page.** At 100 issues the count is reported `capped`, a
  floor rather than a total.

## The ORGANIZATION endpoint, because the project one does not window

`/projects/{org}/{project}/issues/` **ignores `statsPeriod` for selection** —
measured 8 Sep 2026, `24h` and `14d` both returned 66 issues with `lastSeen`
going back to 10 August — and its `count` is the issue's **lifetime** total.
Magnitude built from that is "every event ever recorded against anything still
unresolved", which only ratchets upward, and the bands were sized for a daily
figure.

`/organizations/{org}/issues/` filters by the window and returns **both**: for
one issue, `count` was `24` and `lifetime.count` was `315`. So the detector
makes one org-wide call, groups by the `project.slug` Sentry returns, and
carries `lifetime_events` beside the windowed magnitude — an issue at 24 events
today and 315 since August is not the same as one at 24 events total, and a
single number cannot say which.

**This was caught by testing the endpoint the detector actually calls**, after
a first check against the org endpoint had already passed. The two disagreed
(20 issues versus 69), and the disagreement was the finding.

## Severity is on event volume, reversing what this file first argued

The first version banded on **issue count** and argued that volume is not
severity. Ruled the other way, on the case that prompted the detector:
twenty-five unresolved issues had accumulated unseen, and under an issue-count
rule that reads CRITICAL and stops there. The first thing a person needs is
whether **one of them is firing in a loop right now**, and that is a count of
events. One issue at fifty thousand events is an incident; twenty-five at one
event each is a backlog.

Both numbers are kept. `magnitude` is events and is what `routing_policy`
bands; `unresolved_issues` is in `evidence_sample` and is what the brief's
sentence leads with — *"25 unresolved Sentry issues in the API project over
9,001 event(s); largest is DD-API-1A"*.

`015` routes **1-99 MEDIUM, 100-999 HIGH, 1000+ CRITICAL**, over the 24h query
window. Guesses — nothing has read this project, so there is no distribution to
set them against and the first week of readings is the evidence. Deliberately
not tuned to make the first run look calm.

**015 was edited in place rather than superseded by an 016**, because it has
never been applied anywhere but test databases — verified against production,
which holds zero `dd_api_errors` registry rows. A forward-only 016 contradicting
an unapplied 015 leaves two files disagreeing and nothing in the database to say
which won.

## Waiting on two things that are one action

The token in `.env`, and `015_sentry_detector.sql` applied so the registry row
exists. `fleet-sentry.timer` is written and **not installed** until both are
done — until then the detector cannot close a run OK, and the brief correctly
reports the gap. Installing early buys a red board and no information.

Tests: `tests/test_sentry_detector.py` (17), `tests/test_sentry_brief.py` (11),
five reversion guards.

### Two tests that were testing nothing, and how that was found

**The HTTP stub was at the wrong layer.** The first version injected at
`fetch`, which *replaces* `_http_get` — the method that holds all the
status-code reasoning and the 404-names-the-base hint. Every assertion about
those messages was made against code that never ran. Fixed by injecting at
`urlopen` for those cases and keeping the `fetch` stub only for tests about what
an answer *means*.

**The brief harness connected differently from production.** `run_pass` passes
no `row_factory`, so `S.row()` yields tuples; the test used `dict_row`, and
`_sentry_claims`' positional unpack bound the column **names**. `status` became
the string `"status"`, every claim came back UNCOMPUTED, and the guarantee under
test appeared to hold for entirely the wrong reason. A harness that connects
differently from production tests a different program.

Both were found by `revert_guards.py`, which also caught a third: a case aimed
at a brief test whose fixture writes `detector_runs.error` directly and
therefore never exercises `base.py`'s composition at all.

---

# dd_aws_cost — a pound ceiling measured against a dollar bill

`cost-discipline` is 0.05 of the quarter and had **no evidence path at all**:
the brief printed it UNCOMPUTED on every run it ever made. Cost Explorer read
access closes that.

## What the first of the month is, and why it is not an anomaly

| 1 Sep 2026 | USD |
|---|---:|
| AWS Business Support+ | 29.00 |
| Tax | 16.25 |
| Route 53 (hosted zones) | 2.50 |
| **recurring subtotal** | **47.75** |
| ordinary day's usage | 6.88 |
| **total** | **54.63** |

It recurs — 1 Jun 76.01 (65.90 recurring), 1 Jul 77.62 (67.63), 1 Aug 74.89
(64.82), 1 Sep 54.63 (47.75) — so a day-over-day detector fires on the 1st of
every month, forever, and **a detector that fires every month is worse than
none.**

**The fix is not an exclusion list.** Business Support only appears from
August; Tax swings between 16.25 and 65.13. Any list of "recurring services"
is wrong within two months. The fix is that **the objective is monthly, so the
subject is the month** — day-one charges stop being a spike and become part of
a total. The whole class of problem disappears instead of being filtered.

## The spend figure, corrected

| month | USD |
|---|---:|
| Jun | 380.38 |
| Jul | 390.78 |
| **Aug** | **388.71** |
| Sep (measured run rate) | **≈ 255** |

September is much cheaper because a great deal was switched off: VPC
108.65 → 88.26 → **1.74** (a NAT Gateway, by that shape), and ECS, ELB, Lambda,
ElastiCache and CloudWatch all to **zero**. The run rate is $6.93/day plus
$47.75 of monthly charges.

**At $255/month the objective is decided by the exchange rate**: £204 at 1.25,
£197 at 1.30, crossing £200 at about **1.278**. That is why the currency is not
a rounding detail.

## The objective now states its unit

`objectives-2026-Q4.yaml` gained a machine-readable ceiling:

```yaml
    ceiling:
      amount: 200
      currency: GBP
      period: month
```

The statement always said "200 GBP" in prose, which is enough for a person and
nothing else — a detector had to parse a sentence or carry `200` as a literal,
and a literal in the detector is the threshold living somewhere other than the
objective that owns it. **`currency` is required and `load()` refuses a ceiling
without it**, because an implied unit is one misreading away from a 25% error
in the direction of looking fine.

## The rate is a recorded reading, not a constant

A hardcoded rate is precisely the stored number this system keeps deleting, so
`fx_rate` is a **recorded human reading** on the same terms `014` set for the
credit pool, and for the argument `014` already makes: a rate is not a decision
anybody takes, it is a fact about the world that changes continuously, and
freezing it in a function means a migration due monthly — which is a migration
that gets rubber-stamped.

**No reading for the month → the detector emits nothing and the brief says
why.** It refuses rather than comparing two different units.

**The direction is in the column name, not a label.** `USD/GBP = 1.27` is
ambiguous — dollars per pound or pounds per dollar? The two are reciprocals and
both read plausibly, so a column called `rate` beside a pair called `USD/GBP`
is a 60% error waiting to happen. The column is **`quote_per_base`**: one unit
of base buys this many units of quote, and conversion is always
`amount_in_base * quote_per_base`. A test asserts the reciprocal would have
read 162% where the correct answer is 100%.

## Magnitude is percent of the ceiling, which is what keeps the rate out of the schema

Banding on USD would put a dollar number in `routing_policy` standing in for a
pound objective — a hardcoded rate hiding in a data table, the same defect as
one in a function wearing a different hat. A percent has no currency in it, and
computing it *requires* the reading.

**100 MEDIUM, 120 HIGH, 150 CRITICAL. There is no early-warning band.** 100 is
the objective itself; anything below it is a number nobody chose. Warning ahead
of a breach needs a projection, a projection is growth detection, and growth
detection is deferred until there is more than one month of history not
distorted by the infrastructure just removed.

**Consequence, stated rather than discovered:** this reports a breach, it does
not predict one. And below the ceiling the brief can say the objective is being
met but not by how much — an observation creates an issue, and an always-open
issue for ordinary spend is noise. The percent appears once the ceiling is
crossed, which is when it starts mattering.

## A latent bug in the Sentry claim, found by building this

Brief staleness was `now() - window_end`. A detector with a settle lag
**deliberately** evaluates a window that is already old: `dd_aws_cost` has
`settle_lag` of a full day, so its newest executable window closed ~2 days ago
even when the run finished seconds ago — and the brief reported "past its
cadence and grace" about a detector that had just succeeded.

The freshness question is about the **run**, not the window, so both claims now
measure `now() - completed_at`. `_sentry_claims` carried the same rule and the
same latent bug; its `settle_lag` is five minutes, so it was invisible there and
would have surfaced the day anyone raised it.

## boto3 was undeclared

Importable in the venv, absent from `requirements.txt`, and now load-bearing. A
detector that works today and breaks on a clean rebuild is worse than one never
written. Pinned at 1.43.89.

## Waiting on

An `fx_rate` reading for the current month, and `016` applied. `fleet-aws-cost.timer`
(06:40 daily, before the 07:45 brief) is written and **not installed** until
both — until then the detector cannot close a run OK and the brief reports the
gap rather than a pass.

Tests: `tests/test_aws_cost.py` (24), five reversion guards.

---

# The candidate producer — re-verification, not parsing

Candidates existed only when a session was asked to write them by hand, so the
loop never started on its own. This is the producer `specs/approval-surface.md`
§7 states the interface for and deliberately does not solve.

## Parsing is trivial. The document is the problem.

`specs/metorik-gap.md` holds **50 data rows** — 26 Missing, 8 Partial, 14
already `Has`. Filtering to Missing/Partial leaves 34, and **those 34 are 11
days old**. Probed against platform HEAD `ebe016c` on 8 Sep 2026, four
Daily-band rows:

| row | document | HEAD |
|---|---|---|
| Order filtering — *"accepts start, end, exact status, search, sort_by, sort_dir. **Nothing else**"* | Partial | **wrong** — also `payment_method`, `country`, `coupon`, `has_discount` |
| Location reports — *"built but unreachable ... there is no page"* | Partial | **wrong** — `geography/page.tsx` exists |
| CSV export — *"the only `text/csv` is `/segments/{name}/export`"* | Missing | still true |
| Net revenue — *"no aggregate nets it"* | Missing | still true |

**Two of four**, and they are exactly the two a person caught by hand when
batch 8 was assembled. A parser reproduces both as current candidates and
nothing in the text says otherwise.

## So the check re-executes the claim

Every candidate declares predicates from a **closed vocabulary** —
`path_exists`, `path_absent`, `grep_count` — and
`candidate_block_shape.py` **re-runs them at HEAD**. A row whose claim has
stopped being true cannot be emitted. Predicates are evaluated with `pathlib`
and `re`; nothing is shelled out, so a probe cannot become an arbitrary
command, and the agent that writes one has no shell to test it with anyway.

Each row also carries `verified_sha`, checked to be a real commit. The probes
are the guard; the sha is the receipt — which is what lets a batch approved a
week later be checked against what moved rather than trusted.

### And a `premise`, which is a different claim from a probe

Required since 10 Sep 2026 (`030`, §9.9.1). A probe says what is **missing** —
the gap is real and still open. A premise says what must **already be true**
for the work to be the work described:

```yaml
premise:
  - claim: the order table renders payment_method as one of its columns
    probe: {grep_count: {glob: ..., pattern: "key: 'payment_method'", expected: 1}}
```

Candidate 38 is why. It proposed making the Payment, Country and Coupon cells
of the order table set the matching filter, and its rationale said those values
"are inert". **The table did not have those columns.** All four of its probes
held — the filter box exists, no cell is wired to it, the API takes the
parameter, the file exists — because every one of them tested the gap. The task
cost £2.25 and the agent, correctly on what it found, added three columns no
spec had asked for.

Same closed vocabulary, same `run_probe()`, executed in both places a probe is:
by `candidate_block_shape.py` when the producer emits it, and again by
`console/rank.py` **gate 6** at the approval, against the sha about to be spent
on. A failing premise is not a failing probe and gets its own rule name, because
they point opposite ways — `probes_failed` means the gap closed, drop the row;
`premise_failed` means the ground is not there, so the row is a *different piece
of work* from the one described.

The claim is required in prose as well as in predicate form. The predicate is
what runs; the sentence is what a later reader checks it **against**, and that
question — does this probe test the claim, or something adjacent — is the one
no machine here can answer.

## The §7 prohibitions are in the contract, not a prompt

| prohibition | enforced by |
|---|---|
| not set `disposition` | `agent_tools` has **no Bash**; `.env` is gitignored so absent from a fresh worktree — there is no route to the database at all |
| not write to `tasks` | the same, plus `writable_paths` is **one file** |
| not deduplicate against previous batches | the agent is given the document and the platform repo, and never `candidates` — it *cannot* see what came before |
| — | the check **refuses a block containing** `disposition`, `work_type`, `batch_id`, `spec_task_id`, `work_task_id` — the shape cannot express pre-approval |

`work_type` is refused for the reason `draft_spec_shape.py` records: `candidates`
has no work_type column, because a producer reading a findings document would
be guessing at what the draft-spec step exists to determine.

**Re-run, do not reconcile.** A batch two weeks old is a new batch. The task is
run again against the same document and never updates rows in place — the same
reason §5 keeps a `NOT_NOW` candidate's original `batch_id`: a candidate that
reappears is signal, and quietly refreshing it erases that.

**The ceiling is `--max-candidates 10`, in the contract.** Fifteen unshipped
rows against an approval batch cap of 5 is fine — listing is cheap and ticking
is the work — but a sixty-row findings document must not be able to flood the
surface, and the limit belongs to the contract rather than to whoever writes
the next document.

## `hib_relevant` does not exist

Measured before anything was built on it: **zero hits across both
repositories**, both gap documents and every research file. The only "HIB" in
`metorik-gap.md` is the word *Hibernating*, an RFM segment name. The gap list
ranks by agency-use frequency and carries no HIB column at all.

So the mechanism is built and **reports the absence rather than inventing the
data**. `hib_signal` is a required key on every candidate; `null` means the
source document declares none, and a non-null one **must carry both `value` and
`as_of`** — the age of that signal is what decides whether it can be leaned on.
If a future findings document grows an HIB column, the producer carries it
through with its date; until then every row says plainly that there is none.

## It does not rank, and has to say so

The document orders by agency-use frequency. `principles.md` ranks by what
HIB's team would open daily and puts trust above parity. Batch 8 established
that **candidate order is rank order**, so a list that looks ranked and is not
is the failure.

The block must declare `ordering: unranked`. `agency_use_band` travels inside
`evidence` as *the document's claim*, not as the producer's ordering.
`objective_ref` is where trust-versus-parity actually lands and is assigned per
row with a justification — inheriting `dd-feature-parity` from the document
header would be silently adopting the ranking the principles file rejects.

**And the block must carry `unasked_question`:** nobody has asked HIB's team
what they need. A candidate justified by an `hib_signal` is justified by what
HIB *has*, not what its team *wants*. Said once, on the block, so a batch
approved off it does not read as evidence-backed when it is inference-backed.

## What it cannot verify

Presence and absence in a repository, and nothing else. Not whether Metorik
still ships a feature, not whether merchants want one, not whether the
agency-use band is right — which is why this contract drops `WebSearch` and
`WebFetch` that `research.yaml` carries: fetching a marketing page does not make
a claim about the world checkable, it just adds a reproducibility problem to
manage. It cannot prove a feature is *complete*: `payment_method` appearing in
`orders.py` is not the filter working. It cannot tell whether a row marked
Missing is missing for a good reason, nor whether a candidate's probes test the
claim it made rather than something adjacent. `premise` narrows that last one
without closing it: the claim now has to be written beside the predicate, in
the row and on the decision, so what a reader checks is one sentence rather
than the whole rationale — a producer can still file an adjacent probe under a
true-sounding claim and this will run it, find it holds, and pass. Those are a
read, and this exists to make that read smaller, not to replace it.

## A test that named a work type by hand

`test_every_shipped_contract_matches_the_repo_it_names` exempted
`work_type == "research"` from the writable-path-must-exist rule, because a
document-producing contract names the document it is about to write. It stopped
covering that case the moment a second document-producing work type existed,
and failed `candidate_producer` for being new. Now derived, using the rule
`draft_spec_shape.py` already states: a contract may create a new **file**, but
not in a directory that does not exist.

## Not built: the ingest

The producer emits a block. Turning it into `candidate_batches` +
`candidates` rows needs `fleet_console`'s INSERT, and the producer's whole
safety argument is that it cannot write. That step is a small CLI and is
deliberately separate — until it exists the loop starts on its own and still
needs one command to close, over a verified block rather than a session writing
rows by hand.

Files: `contracts/candidate-producer.yaml`,
`contracts/checks/candidate_block_shape.py`, `tests/test_candidate_block.py`
(41), six reversion guards.

---

# The draft-spec gate, made reachable — and capped

Three draft specs (tasks 23, 24, 25) died at `draft_spec_shape.py` for what
looked like one reason. £4.23 across the three.

## Five of the six failing paths were not mistakes

| path | what it was |
|---|---|
| `api/analytics/routes/coupons.py` | a file the spec proposes to **create** |
| `api/analytics/services/coupon_report.py` | a file the spec proposes to **create** |
| `api/analytics/services/category_report.py` | a file the spec proposes to **create** |
| `routes/categories.py` | abbreviation, of a file to be created |
| `routes/orders.py` | **abbreviation** — `api/analytics/routes/orders.py` exists |
| `routes/payments.py` | abbreviation, of a file to be created |

**The check contradicted itself.** Rule 3 allows a *declared* writable path
whose parent directory exists — a spec may create a new file. The prose rule
four lines below required bare existence. Task 23 declared
`api/analytics/routes/coupons.py`, the check **accepted it there**, and then
failed the identical string for appearing in the prose. It failed for nothing
it did wrong.

So prose now gets the same rule, and an abbreviation is named as one with its
correction attached: `routes/orders.py -> api/analytics/routes/orders.py`.
Replayed against the three branches: **task 23 passes**, task 24 fails on one
path instead of two, task 25 is told exactly what to write.

## The paths pack — and the capability the prompt promised and did not deliver

Every failing path had a real sibling in the same directory. But the cause was
worse than recall, and **task 25 said so in its own document**:

> *"The `reference/deadly-digital-platform` checkout named in the task **was
> not present in this worktree** and the platform tree is outside the
> session's permitted directories, so **no path or line number below was read
> from the tree for this spec.** Every one is carried from a document in this
> repository that did read it."*

`worktree_links` are created **after** the diff is derived — deliberately, so
the agent cannot write through them. `draft-spec.yaml` declares no
`readable_repos`. So the prompt told the agent to read a checkout that does not
exist while it runs, the agent found it absent, **reported the gap correctly**,
and was failed terminally for the consequence. The prompt no longer makes that
claim, and it names the generated listing instead.

**Generated per run, outside the worktree, never committed.**

- **Per run**, because a committed listing is the wrong shape for the same
  reason the gap list was: it goes stale, nothing re-derives it, and it is
  believed while it is wrong. Generated at run start it is current by
  construction and it disappears with the worktree.
- **Never committed, for a second and harder reason.** A file in the
  repository is readable by every later task, *including ones whose contract
  makes that repository writable*. A committed listing of both trees is a
  standing index of a tree a given task was never granted — exactly the leak
  `readable_repos` exists to bound, arriving as a convenience rather than as a
  grant. **Whoever finds this generating a file every run and thinks to check
  it in: that is what it costs.**
- **Outside the worktree**, because inside it the file lands in the derived
  diff and the boundary refuses it — the trap the evidence pack solved by
  committing, which is the option ruled out above. It is exposed by
  `--add-dir`, like any other read-only tree.

**Gated on the capability, not the work type.** `read_only_trees()` derives it
from `readable_repos` and from `worktree_links` targets that are repositories,
so a contract that acquires a read-only tree later gets a listing automatically
rather than when somebody remembers to add its name to a list. A listing of a
tree the agent may already read grants nothing it could not already enumerate —
which is precisely why the gate is the capability and not the label.

One consequence worth stating: for `draft-spec` today the listing is **not a
convenience, it is the only view of the tree the contract actually delivers.**
Whether that contract should also gain `readable_repos` — so the agent can read
the files and not just their names — is a separate decision and has not been
taken here.

## The gate, reachable during the run

`contracts/checks/spec_selfcheck.sh`, exposed by a **scoped** Bash entry:

```yaml
agent_tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Bash(/home/ubuntu/fleet/contracts/checks/spec_selfcheck.sh)
```

One command, no argument wildcard. `runner.yaml` says Bash is absent by default
because an agent with arbitrary shell "would gain a way out of the worktree,"
and permits a contract to widen it per task — this widens it by exactly one
thing. The script lives under `contracts/**`, which is protected, so the agent
cannot edit the thing it is allowed to run.

**It runs the contract's FIRST verification command, not a copy of it**, so the
preview cannot drift from the gate.

## THE CAP IS SOFT. THE TERMINAL CHECK IS WHAT ENFORCES CORRECTNESS.

Read this before reading the next section, because "capped at three" is
exactly the phrase someone will remember and exactly the wrong thing to
remember.

**Three is a limit on PREVIEWS, not on attempts at correctness, and not a
guarantee of anything.** Specifically:

* the agent can **ignore the self-check entirely** — nothing requires it to
  run once, let alone three times, and a spec written without ever calling it
  reaches the terminal check exactly as before
* the cap stops a fourth *preview*. It does not stop a fourth edit: the agent
  may keep changing the document after its last self-check, unobserved, and
  what it hands over is whatever the file says when it exits
* the same-shape guard **warns and records; it does not refuse**
* passing the self-check three times is not passing the gate. The runner
  re-runs the real verification after the agent exits, on the derived diff,
  and that verdict is the only one that decides anything

So the cap is a control on **how much iterating-against-the-gate we are
willing to pay for and see**, not a control on output quality. If in six
months something is relying on "three" as a correctness property, it is
relying on the wrong thing — the property is `verification` in the contract,
run by the runner, after the agent is gone.

## The cap is 3, and the cap is the point

An agent that can run the gate can also mutate paths until it goes green —
which satisfies the check without establishing what the file is, and is worse
than the failure because it passes.

**One to discover, one to confirm the fix, one spare for a second distinct
problem.** Past that it is search, not correction, and the script says so
rather than failing silently.

Three things make the cap hold:

- the state file lives **outside the worktree**. Inside it, every invocation
  would write a file the boundary then refuses, so the act of checking would
  fail the branch. Outside, the agent cannot reach it — it has no shell but the
  one scoped command.
- **every invocation and its verdict is recorded** on the `PATCH_PROPOSED`
  step, with a `shape_changed` flag. The check reports every unresolved path
  at once, so fixing one cannot reveal another — a path present in run N and
  absent from run N-1 was **introduced**, which is the mutation signature. The
  script warns on it in as many words. It does **not** refuse: refusing would
  block a legitimate rewrite, and the terminal check enforces either way.
- the runner still runs the real verification after the agent exits. **This
  never becomes the gate; it is a preview of it.**

## `max_attempts` stays at 1

The retry machinery exists — `task_transitions` has `RUNNING -> QUEUED
'requeued below max_attempts'` — and the default is 1 in `003_tasks.sql`. It
should stay there, for now.

With the check reachable, a content failure that survives three self-checks is
a spec the agent could not write, and retrying it unchanged is the definition
of repeating something that did not work. The retry would cost another £1.30
and re-run the same reasoning from the same prompt.

**The real gap is not the number, it is that a FAILED run has no class.** Task
21 failed with a *passing* check and a clean boundary — a different failure
entirely, and one a retry might well have fixed. A retry policy that cannot
tell "the check refused the content" from "the agent timed out" will either
retry things that fail identically or refuse to retry things that would
succeed. If retries are wanted, the thing to build is failure classification,
not a bigger number — and the self-check log is the first evidence that would
feed it.

Tests: `tests/test_selfcheck.py` (22), six reversion guards.

---

# A merge refusal that reached one browser tab and nowhere else

Task 26 was accepted five times. Every POST returned 303, no `HUMAN_DECISION`
row was written, `origin/main` never moved, and `journalctl` showed nothing but
the redirect.

## Where it refused

`merge.preflight`, guard 6 of 8, reached through `merge_and_push`:

> *the deadly-digital-platform checkout is on `fix/api-suite-usable-as-a-gate`;
> this task's base is `main`, so there is nothing here to merge into.*

**The refusal was correct.** `merge.py` will not switch a branch under whoever
is using the checkout. It was also invisible everywhere a person would look.

**Neither trigger was involved.** `enforce_acceptance_boundary` and
`enforce_step_authority` are never reached, because **no INSERT is attempted**:
`accept()` returns at `if not result.ok:` and `decide.record()` is below it.
The two `run_steps` rows are not a refused insert; they are an insert that
never happened.

## Why it was silent

- **Nothing logged.** The failure branch had no log call, so the journal showed
  `POST … 303` and no reason — which reads as a successful no-op.
- **Nothing durable.** Correctly: a verdict written before a merge would be a
  claim about something that had not happened. But it left no trace at all.
- **`_OUTCOMES` is pop-once.** The reason was rendered on the next page load
  and then gone. Five refusals each overwrote the last.

## The guard: an outcome cannot be set without being logged

`_record_outcome` is now the **only** writer of `_OUTCOMES`, and it logs before
it stores — WARNING for a refusal, INFO for a success. A test asserts there is
exactly one assignment to that dict in the whole module, because a second
writer would bypass the logging and restore the silence.

This is the general shape worth naming: **a helper that silently does nothing
when its dependency is absent.** Here the absent dependency was a reader — the
toast was correct, and nobody ever loaded the page that would consume it.

## And the refusal is now shown before the button

`preflight` reads git and writes nothing, so the task page asks it on the GET
and renders a blocker above the Decide section. That turns a refusal from a
**result** into a **precondition** — the difference between a gate and a
trapdoor. If preflight itself cannot run, the page says so; it never silently
omits the blocker, which would be the same defect one layer up.

## Should it refuse at all, or offer a rebase? Refuse. There is nothing to rebase.

**A base that merely advances does not trip anything.** `preflight`'s
merge-base guard is measured and documented in its own comment: *"A base that
merely ADVANCES does not move the merge base — measured, in a toy repository:
two commits on the base, merge base unchanged. So this fires for a rebase or a
rewritten base, not for the overnight case."*

Confirmed empirically here: task 26's branch is based on `7375d0a`, `main` has
since moved to `9c16d4c` through an unrelated PR, and the trial merge was clean
and passed all three checks. **The stale base blocked nothing.** So "every task
queued before an unrelated merge will hit this" is not the case — that case is
already handled, deliberately.

**And offering a rebase would break the strongest guard in the file.** Rebasing
rewrites the branch tip, and `preflight` refuses when `tip != recorded_patch`:
*"Something has been committed to the branch since it was verified, so what
would merge is not what was checked."* A console that rebased would invalidate
the verification it is about to rely on, then merge anyway. The right answer to
a genuinely diverged branch is a new run against the new base, which the
attempt machinery already expresses.

What actually blocked task 26 was environmental and one command wide:
`git -C ~/deadly-digital-platform checkout main`.

Tests: `tests/test_console_blocker.py` (6), three in `tests/test_console.py`,
four reversion guards.

---

# The base must agree with its remote, before the merge

Task 26 was merged by the console at 20:08 into a local `main` two commits
behind `origin/main` — PR #3 had landed on GitHub at 15:37 and this checkout
had never pulled. The merge produced `39b7844`, the push was refused
non-fast-forward, and `accept()` recorded nothing, exactly as designed:
*"main and origin/main now disagree, and that is worse than either failing
alone — resolve it by hand before recording anything."*

**The refusal was right and one step late.** `merge_and_push` verified the push
against the remote *after* a merge commit existed, which is too late to prevent
what it detects. `preflight` never consulted the remote at all — no fetch, no
rev-list, no `origin/` reference anywhere in the function.

It does now, and `merge_and_push` fetches before asking, so the write path
compares against the remote as it is rather than as it was at the last fetch.

## It refuses on *behind*, not on *ahead*

Behind is the defect: merging into a base the remote has moved past builds a
commit that cannot be pushed. **Ahead is the ordinary state of a checkout with
unpushed work** — it is what the already-merged path looks like by
construction, and refusing it would make recording a local merge impossible.
The first version refused on `behind or ahead` and broke three existing tests,
which is how the distinction was found.

The count is still *reported* when both are non-zero, because "diverged" and
"behind" are different states and the message should not flatten them. The
message names the state rather than a direction:

> `main and origin/main have diverged: origin/main has 2 commit(s) this
> checkout does not. Merging into it would build a commit that cannot be
> pushed, which is what happened to task 26 on 8 Sep.`

## `_count` returns None on failure, never 0

Found by `revert_guards.py` while proving the above: the ref-existence check
was not load-bearing, because `_count` returned **0** when a range could not be
resolved — making *"I could not look"* identical to *"they agree"*, and letting
a merge proceed on a question nobody answered.

That is the same silent default as the flash, one layer down. `_count` now
returns `None`, the caller refuses with *"that is not the same as them
agreeing"*, and a repository with no remote-tracking ref is skipped explicitly
with a note rather than by accident.

## MERGED_OUTSIDE was proposed, does not exist, and was not added

**Written down so the next person who reaches for it finds the reasoning
rather than repeating it.**

The obvious way to record task 26 was a new task status meaning "merged, but
not by the console". It was proposed by name. It is in no migration, no Python
file and no template, and the deployed CHECK on `tasks.status` allows exactly
`QUEUED, RUNNING, READY_FOR_REVIEW, FAILED, ABANDONED, MERGED, REJECTED,
REWORK`.

**A note claiming it had fired and worked was also proposed, and refused.** A
path that has never existed cannot have executed, and asserting otherwise
would have put a fabricated provenance claim in the one record whose entire
argument is that it can be trusted. That refusal is the point of this section
as much as the design decision is.

**Why it was not added.** `MERGED` is read in **fourteen places across eight
files**: the CHECK and `task_transitions` in 003; `decision_outcomes`'
`task_outcome` *and* `attempts_to_green` in 010, where a new status falls
through to `IN_FLIGHT` and `NULL` and would silently misreport a merged task;
`decide.py`'s verdict whitelist; four in `morning.py`; three templates; and
`outcomes.py` and `proposer/precedent.py`, which each define
`_DELIVERED = ("MERGED",)`. A status every reader must learn is a large change
to say something one payload field can say.

**What was done instead.** The task is MERGED, because it is merged — that is
not a compromise, it is the true statement. The provenance lives in the
`HUMAN_DECISION` payload:

    decided_via            "by_hand"            (validated; console | by_hand)
    merge_commit           1a906d9…             what landed
    merge_commit_parents   [9c16d4c…, 76ae3e1…] the second is what was verified
    console_merge_commit   39b7844…             what the console built
    console_merge_base     7375d0a…             the stale base it built on
    console_merge_discarded true

The discarded commit is named deliberately: **a payload that lists only the
survivor reads as though the console never merged.** It did, at 20:08, into a
`main` two commits behind `origin/main`, and the push was refused.

`decision_log` #24 carries the account in prose; #23 carries the
analytics_1 verification gap against the same task.

**`decided_via` is the mechanism, and it did not exist either.**
`decide.record()` hardcoded `"console"`, so the only supported writer asserted
the console had acted. Recording the truth meant either lying in that field or
writing rows around the one function that keeps the step and the status
transition in a single transaction. It is a validated parameter now.

## A fix committed and not deployed is indistinguishable from a fix that does not work

The console ran for the whole of 8 September as pid 570, started 12:58:51.
Every change made that day — the outcome logging that would have made the
first silent refusal loud, the preflight blocker that would have shown it
before the button, the divergence check that would have refused the stale-base
merge outright — was committed and not running.

So the 20:08 accept failed silently for the *same* reason as the 19:25 one,
after the fix for it had been written. The journal showed `POST … 303` twice,
six hours apart, for two different underlying faults and one shared cause:
**the repository had the fix and the process did not.**

`systemctl restart fleet-console` is part of finishing a console change, not a
separate errand.
