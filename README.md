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
