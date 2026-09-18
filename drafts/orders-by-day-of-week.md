# Draft spec — orders by day of week, bucketed in one named zone

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Orders by day of week — seven rows over the order-list population, bucketed in an explicit timezone and corrected for the unequal number of weekdays in a window
writable_paths:
  - api/analytics/services/order_query.py
  - api/analytics/routes/orders.py
```

## Everything below is GIVEN. The build agent measures nothing

The agent that builds this has no shell, no database and no network. Every figure
here was taken from documents in the fleet repository and is cited where it is
used. **No numbered requirement asks anybody to re-derive any of it**, and no
requirement asks for a query to be timed.

| Figure | Value | Source |
|---|---|---|
| `orders` rows | 2,889,850 | `research/metorik-report-classification-2026-09-15.md:705` |
| Span of `orders.created_at` | 2023-03-12 to 2026-09-15, 1,283 days | same, and the candidate's `hib_signal` |
| Orders behind each weekday bucket | ~183 weeks | `research/candidates-metorik-gap-2026-09-16.md:423` |
| `orders.created_at` type | `DateTime(timezone=True)` | `research/metorik-report-classification-2026-09-15.md:715` |
| What `range_predicate` expands to | `o.created_at >= :start AND o.created_at < :end_plus`, `end_plus` the inclusive `end` plus one day | `research/top-products-index-pricing.md:65` |

The candidate is `research/candidates-metorik-gap-2026-09-16.md:402`, at
`verified_sha` `7a09b92`, citing section *Weekly — Orders (7 of 10)* of
`research/metorik-report-classification-2026-09-15.md` at sha `80677a2`, where
the row is classified **A** — buildable on today's schema — with no dagger.

## Why this is a code change and not an investigation

Nothing has to be found out first. The column exists, it is timezone-aware, and
the report is a `GROUP BY` over an expression nobody has written yet. The
candidate records a probe over `api/analytics/routes/*.py` for
`EXTRACT\(DOW|ISODOW|day_of_week` expecting zero matches, and a second over
`platform/app/(dashboard)/analytics/orders/*.tsx` for `dayOfWeek|day of week`
expecting zero. It also records that the one day-of-week expression in the
repository is in `api/analytics/services/churn_engine.py`, grouping customer
acquisition days for a churn signal — a different report on a different column,
and not something to extend.

There is no new column, no migration, and no new table. `api/analytics/migrations/**`
is protected under `contracts/deadly-digital-platform-api.yaml` and nothing here
wants it.

## Why these two files, and not the ones the candidate suggested

The candidate's `suggested_paths` are advisory and two of the three are not
taken. They name `api/analytics/services/analytics_engine.py` beside
`api/analytics/routes/orders.py`, and those two do not meet: the engine module's
report functions are served from `api/analytics/routes/revenue.py` and
`api/analytics/routes/dashboard.py`, and they compute over the revenue-status
population, not the order list's.

This goes where the order list lives. `api/analytics/services/order_query.py`
owns the order list's SQL and its filter predicate `_filter_clause`, whose
docstring already names its consumers and states why a fresh copy of the
predicate would let two surfaces describe different rows while both looked
right. `api/analytics/routes/orders.py` is the only consumer of that service.
`drafts/item-count-distribution.md` makes the same choice for the same reason and
the two endpoints are meant to land on the same page: two cuts of the orders
page that disagreed about which orders they counted would be worse than one cut.

The third suggested path, `platform/app/(dashboard)/analytics/orders/page.tsx`,
is the bar chart, and it cannot be in this diff — see *Not in scope*.

## The two decisions this spec makes, because a build agent cannot

**One: the timezone, and it is not inherited from an unverified premise.** The
candidate's rationale says *"the granularity helper already buckets in the
tenant's zone and this must do the same"*, and its `premise` block probes
`api/analytics/services/date_range.py` for the string `GRANULARITIES`, expecting
one match. That probe establishes that a granularity helper exists. **It does not
establish that the helper applies a tenant zone**, and the one expansion of that
module quoted anywhere in the research —
`research/top-products-index-pricing.md:65`, `o.created_at >= :start AND
o.created_at < :end_plus` — carries no zone at all. So this spec does not rest on
the claim. Requirement 3 makes the zone explicit, bound as a parameter, and
returned in the response, which is true whatever the helper turns out to do. If
the build agent finds that the granularity helper does apply a zone, it must use
the same one rather than introduce a second convention — but nothing here depends
on finding it.

The report is worthless without this. `orders.created_at` is
`DateTime(timezone=True)`, so a bare extract reads UTC: with the store in
`Europe/London` under BST, an order placed at 00:30 on Monday local is stored as
23:30 Sunday UTC and files under Sunday. Across ~183 weeks that is a systematic
transfer of early-Monday trade into Sunday's bar, in one direction, invisible in
the response and unfalsifiable on the page.

**Two: what the seven rows carry.** The candidate's `unasked_question` is
*"whether an agency wants weekday by order count, by revenue, or both — and
whether it wants the average per weekday or the total, which are different
reports over an unequal number of weekdays in a window."*

*Counts, not revenue.* This report describes the order-list population, which is
every status — `api/analytics/services/order_query.py` does not filter by
revenue status, and `drafts/item-count-distribution.md` records that its module
docstring is explicit about it. A revenue sum over that population would be a
third revenue number in the product, disagreeing with `GET /api/analytics/revenue`
by the cancelled and refunded orders, and a merchant comparing the two would be
right to believe one of them broken. Weekday revenue over the revenue-status
population is a coherent report; it is a different one, over a different module,
and it is named as a follow-up below rather than smuggled in here.

*Both the total and the mean, because the window decides which is honest.* A
10-day window holds two Mondays and one Thursday. A bar chart of raw totals
shows Monday taller for a calendar reason, and nothing in the response would say
so. Requirement 4 returns the occurrence count beside the total so the consumer
can divide, and divides for it.

## Why this contract

`contracts/deadly-digital-platform-api.yaml`, work_type `dd_api`. Both declared
paths — `api/analytics/services/order_query.py` and
`api/analytics/routes/orders.py` — are in its enumerated writable set and neither
is protected by it.

**`contracts/dd-order-filters.yaml` covers these two paths exactly**, carries the
same work_type and the same repo, and is refused here on purpose. Its writable
set is precisely this pair, so it is the narrower boundary and the tempting one.
What it costs:

* it declares **no `creatable_paths`**, so no test can be added at all;
* its verification is `compileall`, `ruff_no_new_findings.py` and
  `contracts/checks/order_filters_shape.py` — an acceptance check written for the
  order-filters task, which knows nothing about this report and would pass
  whatever this diff did;
* `max_diff_lines: 150`, counted against production *and* test together.

So under that contract this ships with nothing executing the new query. The
defect this change is most likely to ship is a wrong answer, not an exception —
`EXTRACT(DOW ...)` instead of `ISODOW` shifts every bucket by one and yields
seven plausible numbers; a `GROUP BY` that returns five rows for a quiet week
yields a chart with two bars missing and no error. `compileall` and `ruff` are
blind to both. The chosen contract runs `tests/unit` and `tests/analytics` per
file and requires one added test proven by
`contracts/checks/new_test_bites.sh` to fail against the tree without this
change. That is the whole of the difference and it is the reason for the choice.

## Citing the requirements

`contracts/checks/spec_requirements_cited.py` runs first under this contract and
reads only lines the diff adds. Put `# spec:N` on a line this change adds — the
line building the weekday expression, a docstring line naming a key, a test name
— for each of 1 through 6. Six requirements, against a `max_requirements` of 10.

---

### 1. One grouped query in `api/analytics/services/order_query.py`

Add a function that, for one tenant and one filtered window, returns how many
orders fall on each day of the week. It takes the window and the zone as
parameters and chooses neither.

* **Build the predicate from `_filter_clause`, not from a new one.** This is one
  more consumer of the predicate that already serves the summary aggregate, the
  row SELECT and the CSV export, and it inherits the date bounds, the four set
  filters, `search` and `has_discount` by construction rather than by
  re-spelling them. It follows that the weekday cut describes the population the
  page beside it listed, for the same query string.
* **One statement.** A single grouped query over `orders`. Do not fetch rows and
  bucket them in Python: the unfiltered window is the whole table, 2,889,850
  orders.
* **No join.** Nothing in this report reads `order_items`, `customers` or
  `product_categories`. The count is `COUNT(*)` over `orders` rows the predicate
  admits, and a join added for any reason would fan those rows out.
* **No status filter of its own.** Status is reachable through the existing
  `status` filter, which is the caller's choice and not this function's. A
  report that quietly dropped `cancelled` orders would disagree with the count
  on the page that links to it.

### 2. Seven rows, always, numbered the ISO way

The return value carries `weekdays`: a list of **exactly seven** objects,
ordered ascending by `weekday`, where `weekday` is `1` for Monday through `7`
for Sunday.

* **ISO numbering, and `ISODOW` is what produces it.** Postgres `EXTRACT(DOW ...)`
  returns `0` for Sunday and would put Sunday first and shift every label by one
  against a Monday-start chart. The candidate's own probe pattern lists both
  spellings; only one of them is this.
* **A weekday with no orders is `orders: 0` and is present.** The `GROUP BY`
  returns rows only for weekdays that occur in the data, so the seven-row shape
  is built in Python from the grouped result, not assumed from it. A missing bar
  reads as "no data"; a zero bar reads as "no sales", and only one of those is
  the fact.
* `orders_total` — every order the predicate admits. It must equal the sum of
  `orders` across the seven rows, which is an assertion a consumer can make and
  the reason the seven rows are complete rather than sparse.

No localised day names are returned. The label is the page's business and an
English name baked into a JSON payload is an i18n decision this change has no
standing to make.

### 3. The zone is explicit, bound, validated, and named in the response

* **The bucket expression converts before it extracts.** The weekday comes from
  `o.created_at` converted into the report's zone and then extracted — an
  `AT TIME ZONE` applied to the timestamptz with the zone as a **bound
  parameter**, never a literal interpolated into the SQL string.
* **The zone is validated in Python before the query runs.** An unknown IANA
  name passed into `AT TIME ZONE` raises inside the statement and surfaces as a
  500. Construct `zoneinfo.ZoneInfo` on the name first and return **400** naming
  the field on failure, in the same place and the same style
  `_check_filter_caps` refuses an over-long filter in
  `api/analytics/routes/orders.py` — before anything is queried.
* **The default is the tenant's zone, resolved through whatever already produces
  it.** `api/analytics/services/reconciliation.py` carries the concept —
  `research/candidates-dashboard-remaining-2026-09-14.md:92` quotes
  `verify_period(db, tenant_id, m, coverage, tenant_timezone, settle_hours)` —
  and that accessor is imported and reused. **Do not write a second resolver.**
  Where the tenant has no zone set, the default is `'UTC'`.
* **The response carries `timezone`**, the IANA name the buckets were actually
  computed in, on every response including the UTC-default one. A weekday
  histogram that does not say which midnight it used is not checkable by anyone
  reading it.

### 4. `occurrences`, and where it comes from

Each of the seven rows also carries:

* `occurrences` — how many times that weekday occurs in the window;
* `avg_orders` — `orders / occurrences`, to two decimal places, and `None` when
  `occurrences` is `0`. Never `0.0` there: a weekday the window does not contain
  has no mean, and `0.0` reads as "that weekday sells nothing".

**It is counted from the window, not from the data.** A Monday on which the
store sold nothing is still a Monday and still divides. Counting distinct
observed dates would drop it and inflate Monday's mean by exactly the quiet
Mondays, which is the direction that flatters a bad weekday.

The window is whichever of these applies:

* **Both bounds supplied** — `start` and `end` as the list route parses them.
  Count weekday occurrences across the calendar days from `start` to `end`
  inclusive. Pure date arithmetic, no query.
* **No bounds supplied**, which the list route permits — the extent of the data
  the predicate admits: `MIN(created_at)` and `MAX(created_at)` taken in the
  report's zone, in the **same statement** as requirement 1's aggregate, and
  reduced to local dates. Not a second query.
* **No rows at all** — `occurrences` is `0` and `avg_orders` is `None` on all
  seven rows, with `orders_total` at `0`. An empty store is not an error.

The window predicate is inherited from `_filter_clause` exactly as the list
takes it and **no second date convention is introduced**: the bounds compare
against the stored timestamp the way `research/top-products-index-pricing.md:65`
records, while the buckets are local. The consequence is real and is accepted
rather than hidden — at the two edges of an explicit window a fraction of a
local day may fall in or out. State it in the docstring. Numerator and
denominator are taken from the same bounds, so the means stay coherent, and
changing the window convention would change every existing report and is not
this change's business.

### 5. `GET /api/analytics/orders/by-weekday` in `api/analytics/routes/orders.py`

One route, returning requirement 2's shape.

* **Declare it above `/{order_id}`.** The module docstring of
  `api/analytics/routes/orders.py` records this trap twice already — FastAPI
  matches in declaration order, so a literal path registered after the
  path-parameter route binds `order_id="by-weekday"` and 422s on int parsing.
  Both existing literal routes are pinned by a test against it and so is this
  one.
* **The list route's filters, minus the pager, plus `timezone`.** `start`, `end`,
  `status`, `search`, `payment_method`, `country`, `coupon`, `has_discount`,
  with the same types and the same descriptions `get_orders` gives them — the
  four set filters as `Optional[List[str]]`, for the reason that docstring
  spells out about a repeated parameter binding onto a bare `str` by keeping the
  last value. No `page`, `limit`, `sort_by` or `sort_dir`: an aggregate has no
  pagination and no row order to choose.
* **Reuse `_parse_range` and `_check_filter_caps`, in that module, in that
  order**, so this route's refusals are identical to the list's — both bounds or
  neither, and an over-long filter field is a 400 before anything is queried.
* **The docstring states what the JSON means**: that `weekday` is ISO 1–7, that
  `timezone` names the zone the buckets were computed in and where its default
  came from, that the population is every status unless `status` narrows it and
  therefore that this is not a revenue-status report, and that `avg_orders` is
  `None` rather than `0` for a weekday the window does not contain. The frontend
  is protected under this contract and whoever drafts the page will read this
  docstring and nothing else.

### 6. One added test, and what it has to pin

Create `api/tests/analytics/test_fleet_orders_by_weekday.py` — the only shape
this contract's `creatable_paths` permits. No existing test may be edited. The
test must fail against the tree without this change;
`contracts/checks/new_test_bites.sh` runs it against both trees.

Over a fixture whose arithmetic is known by hand, assert:

* seven rows come back in every case, ascending `weekday` 1 through 7, including
  for a window in which several weekdays have no orders at all — those rows are
  `orders: 0` and present. **This is the assertion a bare `GROUP BY` fails.**
* an order seeded on a known Monday lands in `weekday: 1`. A fixture that only
  checked the shape would pass against `EXTRACT(DOW ...)`, which puts it in
  `weekday: 2` while returning seven plausible rows.
* **the timezone assertion, and it is the reason this test exists.** Seed one
  order at a UTC instant that is a different local weekday in a non-UTC zone —
  23:30 UTC on a Sunday, read in `Europe/London` under BST, is 00:30 Monday. Call
  once with `timezone='UTC'` and once with `timezone='Europe/London'` and assert
  the order moves between `weekday: 7` and `weekday: 1`, and that the returned
  `timezone` key differs accordingly. A build that extracted without converting
  passes every other assertion here.
* an unknown zone name → **400**, with no query issued, and not a 500.
* `orders_total` equals the sum of `orders` across the seven rows; and with no
  `status` filter supplied it equals what `list_orders` reports as
  `orders_all_statuses` for the same arguments. That is requirement 1's
  shared-predicate rule as an assertion rather than a promise.
* `occurrences` over an explicit window with an unequal weekday count — a
  10-day window is the clean case — is the calendar count, and a weekday whose
  orders are zero still has a non-zero `occurrences` and an `avg_orders` of
  `0.0`. **Not `None`**: the weekday occurred and sold nothing, which is the
  distinction requirement 4 turns on.
* a weekday the window does not contain at all → `occurrences: 0` and
  `avg_orders is None`. This is the case a naive division writes `0.0` on or
  raises on.
* an empty result → seven rows, all zero, `orders_total: 0`, every `avg_orders`
  `None`.
* `GET /api/analytics/orders/by-weekday` resolves to this handler rather than to
  `get_order`, which is requirement 5's routing trap.

`test_diff_target` under this contract is 300 lines and is guidance, not a gate.

## Not in scope, stated so nobody reads it as included

**The bar chart.** `platform/app/(dashboard)/analytics/orders/page.tsx` is where
this is read, and nothing in this diff can reach it: `platform/**` is protected
under `contracts/deadly-digital-platform-api.yaml`, as `api/**` is under
`contracts/dd-analytics-frontend.yaml`. It is a follow-up drafted against the
frontend contract once this has merged — it has something to render only after
this ships — and it is deliberately not a second `fleet-spec` block here.
`console/autoqueue.py` writes the whole markdown into `tasks.spec_md` for every
link of a chain and `contracts/checks/spec_requirements_cited.py` then obliges
each link's diff to cite every numbered requirement in the document, so a
two-block chain would fail both links after paying for both.

**Weekday revenue.** Coherent, wanted, and a different report: it belongs over
the revenue-status population in `api/analytics/services/analytics_engine.py`,
served from `api/analytics/routes/revenue.py`, where it can agree with
`GET /api/analytics/revenue` instead of contradicting it. Nothing in this change
sums `orders.total`.

**Hour of day, and the day × hour heatmap.**
`research/metorik-report-classification-2026-09-15.md:716` and `:717` are the
two neighbouring **A** rows, and
`research/candidates-metorik-gap-2026-09-16.md:455` carries hour-of-day as its
own candidate that explicitly *"shares its timezone decision"* with this one. If
both are approved, requirement 3 is the part to reuse verbatim — one zone
parameter, one validation, one response key — and not to re-decide. Nothing here
extracts an hour.

**The granularity helper.** `api/analytics/services/date_range.py` is not in the
writable set and is not edited. Requirement 1 uses `_filter_clause` for the
window, which is what the order list uses, and requirement 3 owns the zone
outright. Whether the helper applies a zone of its own is not settled by this
document and no requirement above turns on the answer.

**`api/analytics/services/churn_engine.py`.** It holds the repository's only
existing day-of-week expression, over customer acquisition days for a churn
signal. It is untouched, nothing is refactored into a shared helper with it, and
the two must not be made to look like one report.

## Before this is queued

`auto_merge` is `true` on this contract and nobody reads a spec against a diff
on that path. The requirement most likely to ship **wrongly** is **3**: an
extract without a conversion compiles, lints, passes every existing test, and
returns seven confident numbers that are wrong by one bucket's worth of trade
for any store not on UTC. The requirement most likely to ship **unbuilt** is
**4** — `occurrences` is arithmetic no check can miss the absence of, and a
response carrying only totals looks complete. If one thing is read against the
diff, read requirement 3 against the `GROUP BY` expression.
