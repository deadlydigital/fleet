# Draft spec — forecast new customers from the acquisition series the customers page already draws

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Forecast new customers twelve months ahead from the per-period acquisition count customer_report already returns, with a prediction interval and a stated campaign caveat on every point
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/customers.py
auto_merge: false
```

## Figures, given

Nothing below is to be measured. These are readings other people took, quoted so
that the requirements can be argued from them and cited truthfully by an agent
that has no shell, no database and no network.

| Reading | Value | Where it comes from |
|---|---|---|
| Distinct customers, and the span | 157,311 distinct `customer_id` values over 1,283 days, 2023-03-12 to 2026-09-15 | `research/metorik-report-classification-2026-09-15.md`, *Monthly — Forecasts (3 of 3)*, at `80677a2` |
| What that number is NOT | a count of distinct values, not a nullability proof — the engine counts customer-less orders as a third bucket rather than assuming there are none | `research/candidates-metorik-gap-2026-09-21.md`, this candidate's `hib_signal`, as of 2026-09-15 |
| Where the `new` count comes from | first order per `orders.customer_id`, derivable from `orders` alone; `customers.first_order_at` and `daily_metrics.new_customers` would serve too and are not needed | the same classification row |
| Forecasting code in the product | none: `[Ff]orecast` matches zero times in `api/analytics/routes/customers.py` and zero times under the customers dashboard | this candidate's probes, at `fd5a404` |
| `customer_report`'s daily statement, after task 104 | 366 ms, median of three, `EXPLAIN (ANALYZE, BUFFERS)`, **30-day window**, tenant 2 | `research/task-104-verified-and-deployed-2026-09-15.md`, *The statements, as merged* |
| `GET /api/analytics/customers` end to end | 0.70 s, median of three warm runs, **30-day window** | the same document, *The endpoints — measured, not projected* |

Both timings are 30-day. **The window this forecast needs is 1,283 days and
nobody has timed it.** That is not a footnote; it is the one open risk in the
row, and it is written out under *What this task does NOT include*.

## Why this is a code change

The series exists and the fit over it does not. `customer_report()` in
`api/analytics/services/analytics_engine.py` already returns a per-period count
of newly acquired customers, and `research/candidates-metorik-gap-2026-09-16.md`
records that *New customers over time* shipped as exactly that key. Nothing
extends it. There is no new column, no migration, and
`api/analytics/migrations/` is protected under the contract named above in any
case.

## Why this contract

`contracts/deadly-digital-platform-api.yaml` makes both declared paths writable,
caps the diff at 400 production lines, admits one new test under
`api/tests/analytics/test_fleet_*.py` that must fail against the tree before the
change, and runs `compileall`, a ruff ratchet, and `tests/unit` and
`tests/analytics` file by file.

`contracts/dd-order-filters.yaml` is the other `dd_api` contract and is not
eligible twice over: its writable set is `api/analytics/routes/orders.py` and
`api/analytics/services/order_query.py`, neither of which holds the customer
series, and it permits no new test file at all. The model in requirement 4 and
the band in requirement 5 are the whole of the work here, and work whose
correctness is a choice of arithmetic must be tested.

`contracts/dd-analytics-frontend.yaml` owns the customers page. That is a
separate draft — see *What this task must not do*.

**The helper goes in `api/analytics/services/analytics_engine.py` rather than in
a new module, and that is forced rather than preferred.** That contract
enumerates its writable paths instead of globbing them, and
`api/analytics/services/forecast.py` is not on the list. A new service file
would be outside the boundary.

## The judgement this spec makes, stated so a reviewer can disagree with it

**The series is `customer_report()`'s, aggregated, and is not re-derived.**

`research/task-102-identity-proof.sql`, BLOCK 4, holds `customer_report`'s daily
statement as SQL: it groups window orders by `created_at::date` and counts
`DISTINCT o.customer_id` filtered on the acquiring-order lookup agreeing with
that date. Two consequences follow from reading it, and requirement 1 rests on
both:

* **Its rows are days.** Unlike `revenue_report()`, which takes a granularity
  and which `drafts/sales-forecast-twelve-months.md` fits at month, this
  statement buckets by date and nothing else. A monthly series therefore has to
  be summed out of daily rows by the caller.
* **Summing them is sound, and that is a property of the statement rather than
  an assumption.** A customer's acquiring order has exactly one date, so a
  customer satisfies the `new` filter on at most one day. Distinct counts that
  cannot double-count across buckets add. This does not hold for the sibling
  `cust_all` and `cust_rev` columns in the same row — a customer who orders in
  March and April is in both — so **only the `new` key may be aggregated this
  way**, and requirement 1 says so.

The alternatives, refused with reasons:

* **A fresh `GROUP BY` over `orders`.** Faster to write and it is the defect the
  candidate's rationale exists to avoid: the value of this row is that the
  fitted history *cannot disagree* with the count the customers page renders. A
  second definition of "new customer" is two numbers for one question.
* **`daily_metrics.new_customers`.** `drafts/sales-forecast-twelve-months.md`
  gives three reasons against the stored table that apply unchanged here — no
  route reads it, it is a cache with a dirty-date repair path in
  `api/analytics/services/dirty_dates.py` and
  `api/analytics/services/metrics_repair.py`, and a fit on a cache inherits
  whatever state the cache is in. A fourth is specific to this row: **nothing in
  this fleet establishes that the stored column uses the same acquiring-order
  rule as `customer_report`'s `new`**, and the build agent must not assume it
  does.
* **`customers.first_order_at`.** The classification row names it and then says
  it is not needed. Same objection: an unverified second definition.

---

### 1. The series is the monthly sum of `customer_report()`'s `new` key, and nothing else

A helper in `api/analytics/services/analytics_engine.py` calls
`customer_report()` once over the tenant's full order span, reads the
per-period acquisition count from the rows it returns, and sums those counts
into calendar months.

It does not write its own aggregate over `orders`, does not read
`daily_metrics`, and does not touch `customers.first_order_at`. Only the
new-customer key is summed; the other customer counts in the same row are
window-distinct and do not add, and the helper must not aggregate them.

**The key's name and the row's shape are to be read from the file, not from
this spec.** `research/candidates-metorik-gap-2026-09-16.md` calls it the `new`
key of `customer_report`'s daily rows and
`research/task-102-identity-proof.sql` calls the SQL column `new_cust`; those
are two documents describing one thing and neither is the tree. Read
`customer_report()` and use what it returns.

If `customer_report()` turns out to accept a granularity by the time this is
built, pass month and skip the summing — the requirement is the source of the
numbers, not the loop.

### 2. An incomplete month is excluded from the fit and is never emitted as history

The month a request lands in is partial. A partial month acquires fewer
customers for a reason that has nothing to do with the trend: included, it drags
the line down; drawn as the last historical point, it reads as a collapse.

So the fitted series ends with the last month that had fully elapsed when the
request arrived. The excluded month is named in the response as such, with its
partial count beside it, rather than dropped silently — an absent month and an
omitted month read identically to whoever renders this.

### 3. One quantity is forecast, it is a count, and the response says so

The measure is the newly-acquired-customer count per month, carried in the
response under its own name so no reader has to infer it from magnitude.

**Emitted values are not rounded.** The fit is over integers and produces reals,
and a point estimate of 0.4 rounded to 0 beside a lower bound rounded to 0 is a
band that has disappeared. The payload carries the reals and says the measure is
a count; rounding for display is the renderer's decision, made once, where the
axis is.

Free entries need no split here and the reasoning is worth one line so nobody
redoes it: `research/metorik-report-classification-2026-09-15.md` records 66,764
zero-total orders as the legal free-entry route, and a free entry still acquires
a customer. This series counts people, not money, so the split that
`drafts/say-whether-aov-includes-free-entries.md` had to make does not arise.

### 4. The fit is an ordinary least-squares straight line, computed in plain Python

One model, stated in full so it can be checked by reading:

* index the fitted months `0 … n-1` and regress the count on the index;
* slope `Sxy / Sxx`, intercept `mean(y) - slope * mean(x)`;
* nothing else — no seasonal term, no smoothing, no differencing, no
  log-transform and no count-specific link.

**Standard library only.** The arithmetic needs `math` and nothing more. The
agent building this has Read, Edit, Write, Grep and Glob: it cannot install a
package, cannot check whether one is present, and cannot run anything that would
tell it. A fit that needs `numpy` is a fit this task cannot honestly claim to
have working.

**The same model as `drafts/sales-forecast-twelve-months.md`, deliberately.** If
that work has landed when this is built, call its helper and add nothing; if it
has not, write this one in the same shape. Two fitting routines in one module,
disagreeing on residual handling, is the outcome both drafts exist to prevent.

### 5. The band is a prediction interval derived from the fit's own residuals, and it is not clamped at zero

Every forecast point carries a lower and an upper bound, computed as the
textbook prediction interval for an OLS line:

    s   = sqrt( SSE / (n - 2) )
    se  = s * sqrt( 1 + 1/n + (x0 - mean(x))^2 / Sxx )
    band = yhat +/- z * se

with `z` a fixed constant for a 95% interval under the normal approximation. The
response carries `z`, the confidence level, `s` and `n`, so the width is
reconstructible from the payload rather than taken on trust. The
`(x0 - mean(x))^2 / Sxx` term grows with the horizon, so month twelve is visibly
less certain than month one; a constant band would be the lie this row is about.

**A lower bound below zero is reported as it falls.** A count cannot be
negative, so the temptation to clamp is stronger here than it was for revenue,
and clamping would be worse. A negative lower bound is the model saying that a
straight line with normal residuals is not a generating process for this series
— which is true, and is the most useful thing the band can tell a reader.
Clamped, it narrows the stated uncertainty at exactly the point where the model
is least believable, and it does so invisibly. The renderer may draw the axis
from zero; the payload does not lie about the arithmetic.

### 6. The campaign caveat is a field in the response, not a comment in the code

Acquisition at a prize-competition store is driven by which draws are running.
A fit with no campaign term reads the end of a promotion as a downward trend and
projects it for twelve months, and every number in requirement 5 is conditional
on that.

So the response carries a short `method` string naming the model and a stated
caveat, in text, saying that the fit has no campaign or promotion term and that
the interval covers scatter around a straight line through this history rather
than the effect of a draw being run or not run. It ships with the numbers, in
the payload, where anybody reading the series reads it too — not in a docstring
and not in a code comment, both of which reach nobody holding the chart.

This is the requirement that distinguishes this row from the other two
forecasts, and it is the reason the candidate said to ship the band wide and
label it rather than to skip the row.

### 7. Twelve monthly points, the fitted history beside them, and a refusal when the history is too short

The response carries exactly twelve forecast points, one per month after the
last fitted month, each with its period key in the format the customer series
already uses, its point estimate, its lower bound and its upper bound. No point
is emitted without a band.

Beside them: the fitted history as the list of (period, count) pairs actually
used, `n`, the slope, the intercept, the residual standard deviation, the
confidence level, `z`, the measure name from requirement 3, the excluded partial
month from requirement 2, and the caveat from requirement 6. A forecast that
arrives without the series it was fitted on cannot be argued with.

**Fewer than twenty-four complete months, or fewer than two distinct counts
among them, and the endpoint returns the history and a stated reason with the
forecast list empty** — not a flat line, not zeros, not a band of infinite
width. Twenty-four because the horizon is twelve, and extrapolating a line a
year forward from less than two years of it is the case where the band does all
the work and the point estimate none. The real tenant has about forty-two months
and never reaches this path, which is exactly why it must be built and tested
rather than assumed unreachable: a new tenant hits it on day one.

### 8. `GET /api/analytics/customers/forecast`, declared ahead of the profile route

Add the route to `api/analytics/routes/customers.py`, mounted beside the routes
already there and taking its tenant resolution on the same terms. No existing
route's response changes shape, no key is renamed, and `customer_report()`'s own
return value is unchanged — the helper calls it, it does not learn about
forecasting.

**This module has a path-parameter route, so the ordering hazard is live.**
`research/metorik-gap-2026-08-30.md` records a customer profile route in
`api/analytics/routes/customers.py` beside `/customers/top` and
`/customers/cohorts`. FastAPI matches in declaration order, so a literal
`/customers/forecast` declared after the profile route is never reached: the
request is captured by the profile handler with `forecast` as the identifier and
the caller gets a 404 or a validation error, with nothing in the diff looking
wrong. Declare the literal before it, and record it in the module docstring's
route list, which is where this module lists its endpoints — the same trap
`drafts/customer-report-csv-export.md` §4 documents for the export route.

The horizon is twelve months and is not a parameter in this task. The
order-volume row of the same batch asks for three, six and twelve, and the
helper in requirement 1 is where that argument goes when somebody takes it.

### 9. One new test, and what it must assert

One new file, `api/tests/analytics/test_fleet_customer_forecast.py`. The
contract's `creatable_paths` allows `api/tests/analytics/test_fleet_*.py` and
nothing else, no existing test may be touched, and `new_test_bites.sh` proves
the added file fails against the tree before this change.

Over fixtures whose monthly acquisition series is known, it asserts the five
properties that would otherwise ship silently:

* the monthly series the helper fits equals the month-by-month sum of
  `customer_report()`'s own per-period new counts over the same span, summed in
  the test independently (requirement 1);
* a series with a known slope recovers that slope, and the twelve point
  estimates continue it (requirement 4);
* the band at month twelve is strictly wider than the band at month one
  (requirement 5);
* a partial final month is excluded from the fit and reported separately, and
  the fitted slope is identical to the slope over the same series with that
  month absent (requirement 2);
* a twelve-month history returns the requirement 7 refusal with an empty
  forecast list, rather than twelve numbers.

A test that asserts only that the endpoint returns 200 satisfies the bite check
and establishes none of this.

---

## What this task must not do

* **No migration, no new column, no write of any kind.** The series is read.
* **No second definition of "new customer".** Requirement 1 is the whole of the
  input. An agent that writes its own `GROUP BY` over `orders` because it is
  easier than calling `customer_report()` has built the disagreement this row
  exists to avoid.
* **No change to `customer_report()`'s existing keys**, and no new argument to
  it beyond the window it already accepts. `/customers`, `/customers/top` and
  `/customers/cohorts` all ship and all have callers.
* **No second forecasting model.** Requirement 4 is the design. An agent adding
  an exponential-smoothing variant "for comparison" has built two numbers for
  one question.
* **No page and no proxy.** `platform/**` is protected under this contract. The
  candidate suggests the customers page at
  platform/app/(dashboard)/analytics/customers/page.tsx; that path is correct
  and it belongs to `contracts/dd-analytics-frontend.yaml`, not here. The
  surface is a second draft, written after this response shape exists and can be
  quoted rather than predicted. **Until that draft lands this reaches nobody**,
  which is stated rather than discovered.
* **No touching `api/app.py`, the email surface or the GDPR path.** All floored,
  none needed.

## What this task does NOT include, and must not claim

**Nobody has timed `customer_report()` over 1,283 days.** Every figure in this
document is a 30-day measurement: 366 ms for the daily statement, 0.70 s for the
endpoint, both after task 104's `LATERAL` rewrite. The forecast window is
forty-two times longer, `drafts/restrict-the-acquiring-order-cte-to-the-window.md`
records that `customer_report()` runs its acquiring-order lookup **twice per
request**, and the acquiring lookup is unbounded in history by design.

No figure for the full-span call exists in this fleet, the build agent has no
shell and no database, and a requirement asking for one would be a requirement
that cannot be cited. So it is not numbered, and the agent must not cite it,
claim it, or write a `spec:` token over it. Whoever reviews the branch should
call the endpoint once against the real tenant and read the wall-clock. If it is
slow, the fixes in order of preference are: fit on a narrower span than the full
history and say so in the payload; ask `customer_report()` for months if it
grows a granularity; and only then confront the stored table with the
same-rule question this spec refused to assume the answer to.

## Before this is queued

* **The unasked question is real and this spec does not answer it.** The
  candidate puts it plainly: whether a new-customer forecast should be
  conditioned on planned draws. HIB knows its competition calendar and DD does
  not hold it, so the honest version of this report may be one that takes a
  planned-volume input nobody has offered to supply. Requirement 6 labels that
  absence; it does not remove it. One sentence from HIB's team either promotes
  all three forecast rows above everything in the pool or kills them.
* **The band may come back embarrassingly wide, and that is the correct
  outcome.** A reviewer who wants a narrower band on a campaign-driven series is
  asking for a different model, not a different constant.
* **`auto_merge: false` is set above, against this contract's default.** The
  contract merges `dd_api` work unattended and its own header explains the
  trade. It is wrong for this one: every gate in the list can pass over a fit
  that is arithmetically clean and methodologically silly, because no check
  reads a slope. Requirements 4, 5 and 6 are the work, and they want one
  person's eyes.
* **Take this after `drafts/sales-forecast-twelve-months.md`, not before.** Both
  write `api/analytics/services/analytics_engine.py`, requirement 4 says to
  reuse that helper if it exists, and building them in parallel produces two
  fitting routines in one file that a later reader has to reconcile.
