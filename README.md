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
the platform cannot reach. `contracts/deadly-digital-platform.yaml` names
what is actually there, and a test asserts every glob in it resolves.

## Stage 2 is the runner

    python run_task.py                 claim the next queued task and run it
    python run_task.py --task 7        run that task, if it is QUEUED
    python run_task.py --no-push       leave the branch local

Invoked by hand. `systemd/` carries no unit for this and no timer is enabled:
the build order puts the timer after three tasks have gone through by hand,
and that has not happened.

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

`contracts/deadly-digital-platform.yaml` is the frontend, and that is the
whole design rather than a limitation to fix later. **Verification scope and
writable scope must match.** A contract declaring `api/**` writable while
verifying with vitest would accept a backend change on the strength of tests
that never executed it, and hand back a PASS with full provenance attached.
That is worse than no gate, because the provenance makes it convincing.

    deadly-digital-platform.yaml      platform/{app,components,lib} —
                                      tsc --noEmit and vitest run, both green
    deadly-digital-platform-api.yaml  api/{app.py,services,analytics} —
                                      compile, and a lint ratchet. No test gate,
                                      and it says so.

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
