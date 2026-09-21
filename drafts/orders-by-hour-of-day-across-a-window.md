# Draft spec — the twenty-four-hour trading profile across a window, which is not the hourly series DD already has

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Return the hour-of-day order profile across a whole window on the orders router — twenty-four buckets, zero-filled, with the bucketing timezone named in the response
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/orders.py
```

## What this is, and why the hour support already in the tree is not it

`api/analytics/routes/revenue.py` accepts `granularity=hour`, and
`api/analytics/services/analytics_engine.py` carries a helper documented as
*"Generate hourly revenue data for a single day — used when granularity=hour"*
(`specs/revenue-granularity-doc.md` quotes it). That helper delegates to
`revenue_report()` and inherits its keys (`research/refund-coverage.md`), and
`api/analytics/services/date_range.py` bounds the whole path with
`MAX_DAYS_FOR_HOUR`, which caps an hour-bucketed request at a single day.

That is **a chronological series**: twenty-four points, each one a distinct
instant, ordered in time, for one date. Asked for a 30-day window it does not
return a coarser version of this report — it refuses, on purpose, because 720
points is not a chart.

The Metorik row is a different shape entirely. *Orders by hour of day* is a
**cyclic profile**: twenty-four buckets over a whole window, where the 09:00
bucket holds every order placed between 09:00 and 10:00 on **any** day in that
window. It answers "when in the day does this store sell", and the answer is
more trustworthy the longer the window is — the opposite of the relationship the
existing hour path has with window length. No endpoint in
`api/analytics/routes/` returns it.

The distinction matters because the cheapest-looking implementation is the wrong
one. Adding `hour_of_day` to `_VALID_GRANULARITIES` in
`api/analytics/routes/revenue.py` and raising or bypassing `MAX_DAYS_FOR_HOUR`
would put a non-chronological, fixed-length, repeating-key result into a
response every existing consumer reads as a time series ordered by date. That is
requirement 4 below, stated as a prohibition because it is the shortest path from
here to a broken page.

## Why this is a code change and not an investigation

Nothing needs measuring first. `api/analytics/models.py` declares
`orders.created_at` as `DateTime(timezone=True)` — the column carries the time
and not only the date, which is the single fact the report depends on, and
`research/metorik-report-classification-2026-09-15.md` §*Weekly — Orders (7 of
10)* classifies the row **A** on exactly that ground: *"As above — the column
carries the time, not just the date."* The same reading records 2,889,850 orders
spanning 2023-03-12 to 2026-09-15, 1,283 days, so each of the twenty-four
buckets has roughly 120,000 orders behind it on tenant 2. No bucket is sparse
enough to be noise.

No new column. No migration — `api/analytics/migrations/**` is protected under
`contracts/deadly-digital-platform-api.yaml`, and nothing here wants one: an
hour extract over `orders.created_at` reads a column that already exists on
every row.

## Why this contract, and why not the narrow one

`contracts/dd-order-filters.yaml` also carries `work_type: dd_api` and also
makes `api/analytics/routes/orders.py` writable, and it is the wrong choice
here for two reasons. Its other writable file is
`api/analytics/services/order_query.py`, not
`api/analytics/services/analytics_engine.py` — and
`api/analytics/services/order_query.py` builds the order **list**, row by row
with filters and pagination, while every windowed aggregate in this codebase
lives in `api/analytics/services/analytics_engine.py` beside the window
predicate and the status constant this report has to share. More decisively, it
permits **no new test file** and runs three checks, none of which executes a
test. `contracts/deadly-digital-platform-api.yaml` requires one added test and
proves it fails without the change. A twenty-four-bucket aggregate with a
timezone decision in it, shipped untested, is the kind of report that is wrong
by one hour for a year before anybody notices.

## What could not be read for this spec, stated plainly

**No read-only checkout of `deadly-digital-platform` was present in the worktree
this spec was written in.** The runner supplied a generated listing of every
file in the tree, which is the authority for which files exist, and every path
below is taken from it. The *contents* below — `MAX_DAYS_FOR_HOUR` in
`api/analytics/services/date_range.py`, `GRANULARITIES` beside it,
`range_predicate()` / `range_params()`, `_REVENUE_STATUSES`, the docstring
quoted above — come from `research/candidates-metorik-gap-2026-09-16.md`,
`research/refund-coverage.md`, `research/top-products-index-pricing.md` and
`specs/revenue-granularity-doc.md`. No line number is given for any of them,
deliberately. **Locate every symbol by name before relying on it**, and where
this spec asserts what an existing helper does, read it and follow what it
actually does.

## The timezone decision, which is shared and must be made once

This is the one real decision in the work, it is identical to the one the
day-of-week cut faces, and getting it wrong is undetectable in a passing test
suite that does not look for it.

`orders.created_at` is timezone-aware, which means it is stored as an instant.
An hour-of-day bucket is a **local** concept: a UK store's 20:00 peak is 19:00
UTC for half the year and 20:00 UTC for the other half, so a profile bucketed in
UTC smears every evening peak across two adjacent buckets and reports a shape
the store does not have.

`api/analytics/services/date_range.py` already owns date bucketing for these
reports and already has an answer to this question — whatever that answer is.
Find it and use it. Do not introduce a second zone rule in
`api/analytics/services/analytics_engine.py`; a report whose buckets are in one
zone sitting on a page whose window bounds were resolved in another will
disagree with the order list at the window edges and there will be no way to see
why from the response.

Two consequences that are requirements rather than notes:

* **If the helper buckets in UTC**, this report buckets in UTC too, and says so
  in the response rather than presenting UTC buckets as local trading hours. A
  correct report that names its zone is useful; an ambiguous one is not.
* **Whatever the zone is, the response names it.** Requirement 3.

## What to build

Five requirements. Put `spec:<id>` on a line this change adds — a comment, a
docstring, or a test name — for each of `1`, `2`, `3`, `4` and `5`; see
`contracts/checks/spec_requirements_cited.py`, which runs first under
`contracts/deadly-digital-platform-api.yaml` and reads only added lines.

### 1. One grouped query in `api/analytics/services/analytics_engine.py`

Add one function to that module — beside the other windowed aggregates, not in a
new module — taking a tenant, a bounded date range, and returning the hour-of-day
profile.

* **One grouped query.** An hour extract over `orders.created_at` and a
  `GROUP BY` on it. Not twenty-four queries, not a fetch of the window's orders
  regrouped in Python. On 2,889,850 rows the Python version is not a style
  preference.
* **Reuse the existing scope, by reference.** The same
  `range_predicate("o.created_at")` and `range_params(start, end)` from
  `api/analytics/services/date_range.py`, and the same `_REVENUE_STATUSES`
  constant from `api/analytics/services/analytics_engine.py`. Reference the
  constant; do not write a status tuple as a literal. Two readings of what it
  holds are recorded in the research — `research/refund-coverage.md` has
  `('completed', 'processing')` — and this change must not become a third. Note
  that `range_predicate` expands to a half-open window, `>= :start AND
  < :end_plus` with `end_plus` the inclusive `end` plus one day, which is what
  keeps whole local days in and is the reason requirement 2's occurrence count
  is computable at all.
* **Per bucket, return at minimum**: `hour` (integer 0–23), `orders`
  (`COUNT(DISTINCT o.id)`), `revenue` (`SUM(o.total)`) and the occurrence count
  of requirement 2. Revenue is the same `GROUP BY` and costs nothing extra, and
  without it the report cannot answer whether the busiest hour is also the
  best hour — which is usually the question behind the question.
* **The same `schema_exists()` guard the neighbouring aggregates use**, returning
  an empty result rather than raising on a tenant whose analytics schema has not
  been created.

### 2. Twenty-four buckets always, and the denominator travels with them

**Every hour from 0 to 23 appears in the response, every time**, with zeroes for
the hours the store did not sell in. A `GROUP BY` returns rows only for hours
that have orders, and a bar chart fed twenty-one rows either draws twenty-one
bars — silently relabelling 04:00 as 05:00 — or has to know to zero-fill, which
puts the same rule in two places. Fill it here, in the service, once. A shop
that closes overnight is the normal case, not an edge case.

Each bucket also carries **how many times that hour occurred in the window** —
the count of local dates in the window contributing to it — so that a mean per
occurrence is derivable by the caller without a second request. Two reasons this
is not decoration:

* **The unequal-denominator trap.** Because the window is whole local days, most
  windows give every hour the same occurrence count, and a reader will assume
  that always holds. Across a DST transition it does not: in the tenant's local
  zone one hour occurs twice on the spring-forward date and another occurs not at
  all, so over a year the two ends of that transition have different
  denominators. A profile that reports totals with no denominator hides it; one
  that reports the denominator lets a reader see it.
* **Totals and means are different reports** and the caller has to be able to
  choose. Return the totals and the occurrence count. **Do not** return a
  pre-averaged figure as the only value.

An hour whose occurrence count is zero — possible only at a DST boundary in a
short window — reports `orders: 0` and its occurrence count as `0`, not `None`
and not a missing bucket.

### 3. The response names the zone it bucketed in

A top-level field carrying the timezone the hour extract was evaluated in, as a
string, alongside the window bounds. Not inferred by the caller, not documented
only in a docstring.

The whole value of this report is the claim "this store sells at 20:00", and
that sentence is false in a different zone. `platform/app/(dashboard)/analytics/orders/page.tsx`
renders in the browser's zone by default, so a frontend that is not told will
label UTC buckets with local hour names and be wrong by up to a whole working
day's shape. The field is what lets the page say *20:00 (Europe/London)* instead
of `20`.

### 4. This is not a granularity, and the existing hour path is not touched

Stated as a prohibition because it is the change a reasonable implementer makes
by default.

* **Do not add a value to `_VALID_GRANULARITIES` in
  `api/analytics/routes/revenue.py`.** That set feeds a chronological series, and
  a consumer that sorts it by date and plots it gets nonsense from a repeating
  key.
* **Do not change `MAX_DAYS_FOR_HOUR` in
  `api/analytics/services/date_range.py`**, or the bound it enforces, or its
  callers. It is correct for the report it guards: 720 chronological points is
  not a chart, and this report does not go through it. Raising it to make room
  for this work would break the existing endpoint's protection and would be a
  behaviour change wearing this diff.
* **Do not change the hourly revenue helper or `revenue_report()`.** Their
  response shape is consumed through `api/analytics/routes/revenue.py`, and
  `platform/**` is protected under this contract, so a shape change here breaks a
  surface this task cannot repair.

The new report shares the window predicate and the status constant with those
functions, and nothing else.

### 5. `GET /orders/…` on `api/analytics/routes/orders.py`

One new endpoint on the existing router, taking the same `start` and `end`
parameters, parsed and validated **exactly the way the routes already in that
module parse and validate them** — the same `date.fromisoformat` handling with a
400 on `ValueError`, the same default window when they are absent, the same
subscription dependency. Do not invent a second date-parsing convention in a
module that already has one.

Two constraints:

* **Declare the literal path before any parameterised route on the same prefix.**
  `platform/app/(dashboard)/analytics/orders/[id]/page.tsx` exists, so the module
  serves a per-order detail route; read `api/analytics/routes/orders.py` and
  place the new literal ahead of anything that could capture it as an id.
  `api/analytics/routes/products.py` records this convention in its own module
  docstring for `/products/acquiring`, and that docstring exists because it is
  easy to get wrong.
* **Update the module docstring's route list**, for the same reason. A module
  docstring that lists the routes and then does not is how the next person gets
  the ordering wrong.

Do not build the page. `platform/**` is protected under this contract and under
the platform floor, so no `dd_api` task can write
`platform/app/(dashboard)/analytics/orders/page.tsx`. The chart is a separate
`dd_frontend` task under `contracts/dd-analytics-frontend.yaml`, which sets
`auto_merge: false` so a person reads the spec against the diff. Until it lands
this is an endpoint an agency can call and not a report an agency can see.

## The test

`contracts/deadly-digital-platform-api.yaml` requires exactly one new test file
and proves it bites: `contracts/checks/new_test_bites.sh` runs it against the
tree before the change and the tree after, and a test that passes on both is
refused. Create

    api/tests/analytics/test_fleet_orders_by_hour.py

which is the only creatable shape the contract allows — `test_fleet_*.py` under
`api/tests/analytics`. Budget is 300 lines for it, separate from the 400
production lines. Read a neighbour in `api/tests/analytics/` for the tenant-schema
fixture conventions. No existing test file may be edited.

The fixture must place orders at chosen times of day, not at a chosen date, which
is the thing that separates this test from every other windowed-aggregate test in
the suite:

* **Two orders at the same clock hour on different dates** land in the **same**
  bucket. This is the whole report, and an implementation that buckets by
  timestamp rather than by hour-of-day fails only this assertion.
* **All twenty-four buckets present** on a fixture where the store sold in three
  of them — the other twenty-one are `0`, not absent. Assert the length is 24 and
  assert on a specific empty hour by key. Requirement 2, and it is the assertion
  an implementation returning raw `GROUP BY` rows fails.
* **An order at 23:30 and one at 00:30 on the following date** sit in buckets 23
  and 0 and neither leaks into the other. This pins the extract against an
  off-by-one in the boundary handling.
* **An order outside the window, and one inside it carrying a non-revenue
  status** — neither reaches any bucket. This pins requirement 1's reuse of
  `range_predicate` and `_REVENUE_STATUSES` rather than a hand-written window.
* **An order on the window's final date** is included. `range_predicate` is
  half-open on `end_plus`, so an implementation that reimplements the bound as
  `<= :end` drops the last day, and a report whose whole subject is time of day
  is exactly where that goes unnoticed.
* **The occurrence count** on a fixture whose window is a known number of whole
  days equals that number for a bucket with orders and for one without.
  Requirement 2's denominator.
* **The zone field is present and is the zone the buckets were computed in** —
  assert it against an order whose placement differs between UTC and the tenant
  zone, so the assertion fails if the field is a hard-coded string beside a
  different computation. Requirement 3.

## What this does not do, stated so nobody reads it as doing it

**It does not build the day-of-week cut**, and it does not build the day × hour
heatmap. Those are candidates 5 and 7 of
`research/candidates-metorik-gap-2026-09-16.md` and are separate tasks. This one
is listed after the weekday cut deliberately: they share the timezone decision,
so whichever lands first should settle it in
`api/analytics/services/date_range.py` terms and the second should inherit it
rather than restate it. If the weekday cut has already merged when this is built,
**read what it did and match it** — two time-shape reports on one page bucketing
in two different zones is worse than either one being absent.

**It does not split by source, channel or campaign.** The candidate carries that
as an open question — whether the profile is wanted for the store's own trading
hours or for ad scheduling, which is what would decide it — and nobody has
answered it. A one-dimensional profile is the Metorik row; adding a second
dimension on a guess is a different report and a larger diff.

**It does not add an index and it does not write a migration.**
`api/analytics/migrations/**` is protected under this contract. If the grouped
query turns out to need an index on `orders.created_at` that does not exist, that
is a separate measured proposal with a timing in it, not something to slip into
this diff — and no line of this change or its test may claim a query time that
was not measured.

**It does not change the order list.** `api/analytics/services/order_query.py`
serves the filtered, paginated list through the same router and has its own
notion of which orders are shown, including statuses this aggregate excludes. It
is writable under this contract and there is no reason to open it. An hour
profile whose counts disagree with the list above it is a support ticket; say in
the endpoint docstring that this report is over revenue-status orders, so the
disagreement is documented rather than discovered.
