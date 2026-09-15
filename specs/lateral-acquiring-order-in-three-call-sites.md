# Restrict AND rewrite the acquiring-order lookup in revenue_report, revenue_summary and customer_report

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Restrict and rewrite the acquiring-order CTE to a LATERAL lookup in revenue_report, revenue_summary and customer_report
writable_paths:
  - api/analytics/services/analytics_engine.py
```

## This is task 102's requirement 7, and the measurement it was conditional on

Task 102 asked for the restriction first and the `LATERAL` form only if a
measurement justified it. The restriction was built, on branch
`fleet/task-102`, and it is **correct** — proved identical row for row on
production across four windows. The measurement was then taken by hand and it
justifies the rewrite. Task 102 is ABANDONED and this task replaces it: the
`LATERAL` form contains the restriction, so this is one change rather than two.

**Everything in the next section is GIVEN. Do not attempt to measure anything.**
You have no shell, no database and no interpreter — `Read`, `Edit`, `Write`,
`Grep` and `Glob`, and nothing else. Task 102 failed on exactly this point: its
spec numbered two requirements that required production measurements, the agent
correctly refused to claim figures it could not take, and the gate refused the
branch. Cite the numbers below as stated facts; they were measured on 15 Sep
2026 and are recorded in `fleet:research/task-102-measurement-2026-09-15.md`.

## The measurement, as a given

`analytics_2`, 2,888,640 orders, 157,258 customers. `revenue_report`,
granularity=day, window `2026-08-15 .. 2026-09-15`, medians of three runs of
`EXPLAIN (ANALYZE, BUFFERS)`:

| form | execution |
|---|---|
| unrestricted `DISTINCT ON` — what is on `main` today | 5,787 ms |
| restricted `DISTINCT ON` — task 102's branch | 3,595 ms |
| restriction plus `LATERAL … LIMIT 1` — what this task builds | 454 ms |

The restricted `DISTINCT ON` never touches `ix_analytics_orders_customer_created`.
It sorts 1,728,430 rows to disk — 50,784 kB, external merge — for 3,087 ms of
its 3,635. Restricting WHICH CUSTOMERS are computed does not bound how much of
their history is read, and the window's 21,379 customers hold 1.73M
revenue-status orders between them.

The `LATERAL` form stops the index after one entry per customer:
`rows=1, loops=21619`. Both halves are needed; neither alone gets there.

## The three call sites

All in `api/analytics/services/analytics_engine.py`, which is this contract's
only writable file:

* `revenue_report()`
* `revenue_summary()`
* `customer_report()` — which runs its lookup **twice** per request, once for
  the daily series and once for the window totals

`_query_period_stats` already has the `LATERAL` form from task 100. Read it and
reuse its shape rather than inventing one.

## Requirements

### 1. The acquiring-order lookup in all three functions is bounded to the window's customers

Derive the customer set from the window rows the function already computes; do
not add a second pass over `orders` to obtain it. The same restriction in all
three.

### 2. The lookup is a LATERAL subquery with LIMIT 1, not a DISTINCT ON

Replace `DISTINCT ON (a.customer_id) … ORDER BY a.customer_id, a.created_at,
a.id` with a `LATERAL` subquery carrying `ORDER BY o.created_at, o.id LIMIT 1`
per customer, exactly as `_query_period_stats` now does in the same file.
`LIMIT 1` is what lets the index stop after one entry; without it the plan
reverts to reading every row for those customers.

### 3. customer_report's BOTH executions are converted

It runs its lookup twice per request. A branch that converts one and leaves the
other has done half the work and will read as a fix. Build the CTE string once
and interpolate it into both statements, so the two cannot drift.

Do not attempt to make it run once instead of twice. If the second execution is
redundant, say so in your reply and it becomes its own task.

### 4. The answer is identical, row for row

The semantics that must survive, each load-bearing:

* **History stays unbounded.** "Acquiring order" means the customer's earliest
  revenue-status order **over all time**. The `LATERAL` subquery carries no
  date predicate. Bounding which customers are looked up is not bounding which
  of their orders are considered, and confusing the two is the one way this
  breaks silently.
* **Revenue-status only.** `status IN ('completed', 'processing')`, the same
  filter the surrounding aggregate uses.
* **The tiebreak stays `created_at, id`.** `ORDER BY o.created_at, o.id LIMIT 1`
  resolves two orders at the same instant the same way on every run, which is
  what `DISTINCT ON (…) ORDER BY a.customer_id, a.created_at, a.id` did.
* **Nothing else moves.** Not the coupon block, not the payment-method
  breakdown, not the granularity bucketing, not the net-revenue or refund
  columns. One lookup in three places.

### 5. One new test, and it fails against the tree before the change

Create **one** file, `api/tests/analytics/test_fleet_acquired_lateral.py`. This
contract's `creatable_paths` admits `api/tests/analytics/test_fleet_*.py` and
nothing else; every existing file under `api/tests/**` is protected and none
may be edited.

The test must **bite** — `new_test_bites.sh` runs it against the tree before
the change and requires it to fail there. Asserting the figures are correct
passes before and after and proves nothing. What discriminates is the
**population the lookup computes**: build a tenant with customers whose orders
fall outside the window and customers whose orders fall inside it, and assert
the lookup touches only the second group. `api/tests/analytics/test_fleet_acquired_per_customer.py`
is how task 100 made an equivalent property observable; reuse that approach
rather than reinventing it.

Alongside that, pin requirement 4's identity on the same fixture: a customer
whose first-ever order predates the window is still classified by that first
order and not by their first order *in* the window. That is the case a careless
restriction breaks.

## What this task does NOT include, and it is the point of this section

**The production identity proof is not yours and must not be attempted.** You
have no database. Requirement 4 is discharged for review by
`fleet:research/task-102-identity-proof.sql`, which a person runs against
`analytics_2` before this is accepted — the same four windows, the same
row-for-row comparison, re-run against the `LATERAL` form rather than reused
from the restriction. Do not cite it, do not claim it, and do not write a token
over it.

**No new measurement.** The figures above are given. If your change makes a
claim about performance, attribute it to the measurement above rather than
presenting it as your own.

**No index.** `ix_analytics_orders_customer_created` already exists and is what
the `LIMIT 1` uses. Anything under `api/analytics/migrations/**` is protected by
this contract, and a branch that proposes an index has misread the plan.

**No route or frontend change.** The response shape is identical by requirement
4, so `api/analytics/routes/revenue.py` and `api/analytics/routes/customers.py`
do not move, which is why neither is declared writable.

## How this will be checked

`deadly-digital-platform-api.yaml` runs, in order: the requirement-citation
check, `compileall` on the changed Python, ruff with no new findings,
`tests/unit` per file, `new_test_bites.sh`, and `tests/analytics` per file.

Cite the numbered requirements above in the diff with `spec:<id>` on lines you
ADD — every one of the five is work you can do with the tools you have, which
is the difference between this spec and the one it replaces.

## Objectives

`dd-trustworthy`. Two analytics pages take over seven seconds each, and the
change that fixes it is one lookup in three places.
