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
