# Draft spec — restrict the acquiring-order CTE to the window's customers, in all three copies

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Restrict the acquiring-order CTE to the window's customers in revenue_report, revenue_summary and customer_report, then consider the LATERAL form
writable_paths:
  - api/analytics/services/analytics_engine.py
```

## What is wrong

`GET /api/analytics/revenue` takes **7.60s** and `GET /api/analytics/customers`
takes **7.12s** at a 30-day window on a quiet box. The dashboard, at the same
window and on the same box, takes **1.73s**.

Instrumented, the revenue endpoint issues nine statements and **two of them are
7,220ms of 7,706ms**. Both are the same DISTINCT ON acquiring-order CTE that
`specs/acquired-order-lookup-per-customer.md` replaced in
`_query_period_stats` — one copy in `revenue_report()`, one in
`revenue_summary()`. `customer_report()` holds a **third** copy and executes it
twice, for **7,192ms of its 7,194ms**. The non-SQL portion of these two
endpoints is **6ms** and **2ms**. There is nothing else to find here: the SQL is
the endpoint.

All three functions are in `api/analytics/services/analytics_engine.py`.

### These copies are worse than the form the dashboard had before task 100

The dashboard's old CTE at least restricted itself to the customers active in
the window. **These three do not restrict it to anything.** The consequence, per
execution:

| | |
|---|---|
| index entries walked in `ix_analytics_orders_customer_created` | **2,885,651** |
| customers produced | **156,981** |
| customers the outer join can ever match | **21,579** |
| waste | **7.3×** more rows than the query can use |
| buffers | **2.79M** |
| time | **3,750 ms** |

The index is chosen. The index is used. It is walked **in full**, because
nothing in the CTE tells it where to stop — so the acquiring order is computed
for every customer the tenant has ever had, and 135,402 of those rows are
discarded by a join that was never going to match them.

### Both suspicions this was filed against are refuted by the measurement

Say this plainly in the branch, because the candidate was filed on two guesses
and the instrumentation killed both:

* **Not the coupon block, and not the payment-method breakdown.** Together they
  are **442ms — 5.7%** of the revenue endpoint.
* **Not this week's growth.** The two dominant statements date from **23 Aug
  2026** (`7b4c283`, `fa0f96d`), not from the 884 lines added this week.

`research/candidates-revenue-acquired-cte-2026-09-14.md` §"Daily — the
acquiring-order CTE is unrestricted in three places" carries the instrumented
run.

### And do NOT assume an index

`specs/neither-half-works-alone.md` is the cautionary half of this and it does
not apply the way it looks like it does. There, the index alone changed no plan
and the rewrite alone was *worse*. Here the index
(`ix_analytics_orders_customer_created`, added by
`api/analytics/migrations/versions/v0014_orders_customer_created_index.py`) is
**already chosen and already walked end to end**. A second index cannot help a
plan that is reading the right index too much. Anything under
`api/analytics/migrations/**` is protected by this contract in any case, and a
branch that proposes an index has misread the plan.

## The order of work, and it is not negotiable

**First the restriction, then the LATERAL form.** They are separable and they
must be separated, because they have different risk and different evidence:

1. **Restriction** is a change of *which customers* the CTE computes. It is
   small, it is the whole of the 7.3×, and its correctness argument is that the
   discarded rows were discarded anyway.
2. **LATERAL** is a change of *how* each customer's acquiring order is found. It
   is the change task 100 made, it is worth 14× *after* an index makes it
   possible, and its effect here is unknown until the restriction has shrunk the
   input.

Measure after step 1 before deciding step 2. If the restriction alone brings
these statements into the range the dashboard now sits in, requirement 5 is
satisfied by reporting that and the LATERAL rewrite is a separate, later task —
three more call sites rewritten for an unmeasured gain is not what this asks
for.

## Requirements

### 1. `revenue_report()`'s acquiring-order CTE is restricted to the window's customers

The CTE must compute the acquiring order only for customers that appear in the
window the function was asked about — the same restriction the dashboard's
pre-task-100 form had and this one lacks. Derive that customer set from the
window rows the function already computes; do not add a second pass over
`orders` to obtain it.

### 2. `revenue_summary()`'s copy is restricted the same way

Same change, same function file, separate call site. It is a separate
requirement because it is a separate statement in the instrumented run and
carries its own share of the 7,220ms.

### 3. `customer_report()`'s copy is restricted, and BOTH of its executions are

`customer_report()` runs its copy **twice** per request. Both executions must be
restricted. A branch that fixes one and leaves the other has cut 3,596ms of
7,192ms and will read as a fix.

Do not attempt to make it run once instead of twice as part of this task. If the
second execution is redundant, that is a finding to state in the branch and a
task to queue, not a change to smuggle in beside this one.

### 4. The answer is identical, row for row, and that is the correctness condition

The semantics that must survive the restriction, each of which is load-bearing
and none of which may be dropped:

* **History stays unbounded.** "Acquiring order" means the customer's earliest
  revenue-status order **over all time**. Restricting *which customers* are
  computed is not the same as restricting *which of their orders* are
  considered, and confusing the two is the one way this change can silently
  break. The inner query keeps having no date predicate.
* **Revenue-status only.** `status IN ('completed', 'processing')`, the same
  filter the surrounding aggregate uses, so the new-customer population matches
  the population revenue is summed from.
* **The tiebreak stays `created_at, id`.** Two orders at the same instant must
  resolve the same way on every run.
* **Nothing else in these three functions moves.** Not the coupon block, not the
  payment-method breakdown, not the granularity bucketing, not the net-revenue
  or refund columns. This is one CTE in three places.

### 5. The identity is PROVED on production data, the way task 100's requirement 3 was

Run each of the three endpoints' full result against the tree before the change
and against the tree after it, on a real tenant schema, for at least one 30-day
window and one window that spans a period boundary, and show they agree **row
for row** — not summary-for-summary. A faster query returning a different
`new_customers` (or a different new-vs-returning split, or a different per-period
row) is not this task.

State in the branch which schema and which windows were used. An identity claim
with no named dataset is the claim task 100 was made to avoid.

### 6. Report the measurement after the restriction, before touching LATERAL

Give, per statement, the before and after execution time and buffer count on the
same box and the same window as the figures above, and the index-entry count the
plan now walks. Then state, as a decision with the numbers beside it, whether
the LATERAL form is still worth making. If it is, implement it under requirement
7; if it is not, say so and leave requirement 7 unbuilt with that reason.

### 7. The LATERAL form, only if requirement 6's measurement justifies it

If built: replace `DISTINCT ON (a.customer_id) … ORDER BY a.customer_id,
a.created_at, a.id` with a `LATERAL` subquery carrying `ORDER BY o.created_at,
o.id LIMIT 1` per customer, exactly as `_query_period_stats` now does in the
same file. `LIMIT 1` is what lets the index stop after one entry; without it the
plan reverts to reading every row for those customers.

Requirement 4's identity condition applies unchanged, and requirement 5's proof
must be re-run — not reused from the restriction step.

### 8. One new test, and it fails against the tree before the change

Create **one** file, `api/tests/analytics/test_fleet_acquired_cte_window.py`.
This contract's `creatable_paths` admits `api/tests/analytics/test_fleet_*.py`
and nothing else; every existing file under `api/tests/**` is protected and none
may be edited.

The test must **bite** — `new_test_bites.sh` runs it against the tree before the
change and requires it to fail there. A test that only asserts the numbers are
correct passes before and after and proves nothing. What discriminates is the
*population the CTE computes*: build a tenant with customers who have orders
**outside** the window and customers who have orders **inside** it, and assert
that the acquiring-order computation touches only the second group — the
existing `api/tests/analytics/test_fleet_acquired_per_customer.py` is the
precedent for how task 100 made an equivalent property observable, and the
approach there should be reused rather than reinvented.

Alongside that, assert the identity of requirement 4 on the same fixture: a
customer whose first-ever order predates the window is still classified by that
first order and not by their first order *in* the window. That is the case a
careless restriction breaks.

## What this does not cover

* **Whether the three copies should become one shared helper.** Factoring them
  is permitted if it falls out cleanly within this contract's 400 production
  lines, and it is not required. The three call sites derive their window
  customer set differently, and a helper that papers over that difference is
  worse than three correct copies. Do not make de-duplication the goal and the
  restriction a side effect.
* **The 442ms.** The coupon block and the payment-method breakdown stay exactly
  as they are. They were the suspicion; they are not the defect.
* **The remaining non-SQL time.** There is 6ms and 2ms of it. There is nothing
  there.
* **`api/analytics/routes/revenue.py` and `api/analytics/routes/customers.py`.**
  Neither changes. The response shape is identical by requirement 4, so no route
  and no frontend page moves — which is also why neither is declared writable
  above.
* **An index.** See above. The index exists, it is chosen, and it is the thing
  being over-walked.

## How this will be checked

`deadly-digital-platform-api.yaml` runs, in order: the requirement-citation
check, `compileall` on the changed Python, ruff with no new findings,
`tests/unit` per file, `new_test_bites.sh`, and `tests/analytics` per file (34
files, 675 tests). Cite the numbered requirements above in the diff — the first
check reads the spec and reports requirements cited nowhere, and it is the only
check that reads it at all.

`api/CLAUDE.md` forbids suite and directory pytest runs on this host; the
per-file runner exists for that reason and is what the contract calls.

## Objectives

`dd-trustworthy`. Two analytics pages take over seven seconds each, and 94% of
that is a question the database is being asked about 135,402 customers whose
answer is thrown away.
