# Draft spec — the orders heatmap, weekday by hour, as a dense 168-cell grid

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Orders heatmap, day of week by hour of day — 168 cells over the order list's own filtered population, with the weekdays the window actually contains
writable_paths:
  - api/analytics/services/order_query.py
  - api/analytics/routes/orders.py
```

## Why this is a code change and not an investigation

Nothing has to be found out first. The column is there and it carries the time:
`research/metorik-report-classification-2026-09-15.md:717` classifies *Orders
heatmap (day × hour)* as bucket **A** — buildable on today's schema — on the
strength of `orders.created_at` being `DateTime(timezone=True)`, the same
reading that carries the two one-dimensional rows at `:715` and `:716`. No new
column, no migration, no new table.

What the product cannot do is bucket that column two ways at once. The candidate
records a probe over `api/analytics/routes/*.py` for `heatmap` expecting zero
matches and a second over the orders page expecting zero, and the classification
work found the only `DOW` expression in the repository inside
`api/analytics/services/churn_engine.py`, grouping customer acquisition days for
a churn signal — a different report on a different column, and not something to
generalise from.

The work is two extracts in one `GROUP BY` over a predicate that already exists,
plus one route beside the ones that already read it.

## Why this rather than the two one-dimensional cuts

`research/candidates-metorik-gap-2026-09-16.md` emits *Orders by day of week*
(candidate 5), *Orders by hour of day* (candidate 6) and this grid (candidate 7)
as three rows, and says at line 92 that they overlap heavily and that an approver
should be able to take one and defer the others.

**The grid is the one to take, and the direction of the derivation is why.** The
seven weekday totals are this response's row marginals and the twenty-four hour
totals are its column marginals; both fall out of 168 numbers with no second
query. Neither marginal produces the grid, and neither shows the thing an agency
opens the report for: a Friday-evening peak is a slightly tall Friday in one bar
chart and a slightly tall 19:00 in the other, and is a single dark cell here.

So this spec deliberately does **not** also ship a weekday endpoint and an hour
endpoint. If candidates 5 and 6 are approved later they should be served from
this aggregate rather than from two more scans of the same table — and, more
importantly, must not be built against a different population, which would put
three reports of the same orders on the same page disagreeing about how many
there were.

Against a fully-landed 5 or 6 this change would be smaller still, which is what
the candidate means by *almost free*. Neither has a draft spec in `drafts/` and
neither has been built, so nothing is being duplicated today.

## Everything below is GIVEN. The build agent measures nothing

The agent that builds this has no shell, no database and no network. Every figure
here is taken from documents in this repository and cited where it is used, and
**no numbered requirement asks anybody to re-derive any of it** or to time a
query.

| Figure | Value | Source |
|---|---|---|
| `orders` rows | 2,889,850 | `research/metorik-report-classification-2026-09-15.md` |
| Span | 1,283 days, 2023-03-12 to 2026-09-15 | same |
| `orders.created_at` | `DateTime(timezone=True)` | same, `:715` |
| Orders per cell on this tenant, mean | roughly 17,000 over 168 cells | candidate 7's `hib_signal`, `research/candidates-metorik-gap-2026-09-16.md` |
| Line items | 4,549,662 rows | same document |

The candidate is `research/candidates-metorik-gap-2026-09-16.md`, candidate 7 of
that batch, at `verified_sha` `7a09b92`, citing section `Weekly — Orders (7 of
10)` of the classification at sha `80677a2`.

`order_items` is listed only to be dismissed: this report counts orders, and
nothing in this change joins to the line items at all.

## Why these two files, and why not the engine

The candidate's suggested paths are advisory and they are `api/analytics/services/analytics_engine.py`,
`api/analytics/routes/orders.py` and `platform/app/(dashboard)/analytics/orders/page.tsx`.
The middle one is taken. The other two are not, and the reasons are different.

**The aggregate goes in `api/analytics/services/order_query.py`, not in
`api/analytics/services/analytics_engine.py`, because of which orders it must
count.** The engine's report aggregates are revenue aggregates: they apply a
revenue-status filter, which is right for money and wrong here. This grid is
rendered beside an order list, and `drafts/item-count-distribution.md` records
that the module docstring of `api/analytics/services/order_query.py` is explicit
that an order list lists rows and does not filter by revenue status. A heatmap
built in the engine would silently drop `cancelled` and `pending` orders and then
sit on a page whose own count includes them — two numbers over the same window
disagreeing, with nothing on the screen to say why. That is the shape
`specs/metorik-gap.md` calls documented conflict 2.1, and it is cheaper to refuse
here than to explain later.

It also buys the filters for free. `api/analytics/services/order_query.py` owns
`_filter_clause`, whose docstring names its consumers and says why a second copy
of the predicate would let two surfaces describe different rows while both looked
right (`drafts/order-export-multi-value-filters.md`,
`drafts/item-count-distribution.md`). Built there, the heatmap describes exactly
the rows the list beside it reported, for the same query string, by construction.

**The page is not in this change.** `platform/**` is protected under
`contracts/deadly-digital-platform-api.yaml`, so nothing here can reach
`platform/app/(dashboard)/analytics/orders/page.tsx`. The grid component and the
colour scale the candidate calls the real cost are a separate task under
`contracts/dd-analytics-frontend.yaml`, queued once this endpoint exists and
deliberately not a second `fleet-spec` block in this document: `console/autoqueue.py`
copies the whole markdown into every link of a chain and
`contracts/checks/spec_requirements_cited.py` then obliges each link's diff to
cite every numbered requirement in it, so a two-block chain fails both links
after paying for both.

## Why this contract

`contracts/deadly-digital-platform-api.yaml`, work_type `dd_api`. Both declared
paths are in its enumerated writable set and neither is protected by it.

`contracts/dd-order-filters.yaml` carries the same work_type and the same repo
and its writable set is *exactly* these two files, so it covers them too. It is
the wrong one, and not narrowly:

* it permits **no new test file at all** — it declares no `creatable_paths` — so
  this report would ship with nothing covering it;
* its verification is `compileall`, `ruff_no_new_findings.py` and
  `order_filters_shape.py`, an acceptance check written for the order-filters
  task and about that task's parameters. Nothing in it runs a test;
* `max_diff_lines: 150`, against 400 here with the mandated test budgeted
  separately.

The defect this change is most likely to ship is a grid that is uniformly wrong
by one column or shifted by one day, because two of PostgreSQL's weekday
extracts are numbered differently (requirement 3). That produces plausible
numbers, not an exception. `compileall` and `ruff` cannot see it, and
`order_filters_shape.py` is not looking at it. Only a test over a fixture whose
timestamps were chosen by hand catches it, and only one of these two contracts
lets this change add one.

## Citing the requirements

`contracts/checks/spec_requirements_cited.py` runs first under this contract and
reads only lines the diff adds. Put `spec:N` on a line this change adds — a
comment, a docstring line, a test name — for each of 1 through 6. Six
requirements, against a `max_requirements` of 10.

---

### 1. One grouped query in `api/analytics/services/order_query.py`

Add a function that, for one tenant and one filtered window, returns the number
of orders in each (weekday, hour) cell. It takes the window as parameters and
does not choose one.

* **Build the predicate from `_filter_clause`, not from a new one.** This is that
  helper's next consumer and it inherits the date bounds, the four multi-value
  set filters, `search` and `has_discount` by construction rather than by
  re-spelling them.
* **One statement, both extracts in one `GROUP BY`.** A weekday expression and an
  hour expression over `orders.created_at`, grouped together, aggregated in SQL.
  Not one query per weekday, not twenty-four queries, and not rows fetched into
  Python and counted there: the filtered window can be the whole table, which is
  2,889,850 orders on this tenant.
* **No status filter of its own**, for the reason the file argument above gives.
  Status is reachable through the existing `status` filter, which is the caller's
  choice and not this function's.
* **No join to `order_items`.** The measure is a count of orders. A join would
  fan each order out across its line rows and inflate every cell by the order's
  line count, and with 4,549,662 lines over 2,889,850 orders the inflated grid
  would still look entirely plausible.

### 2. One timezone convention, taken from the tree and named in the response

A weekday-by-hour grid is a statement about local time. Bucketed in the wrong
zone a UK store's Sunday evening leaks into Monday, and the cell a merchant would
act on is the one that moves.

* **Use the convention `api/analytics/services/date_range.py` already applies to
  the window** — the same helpers the rest of this population's SQL uses,
  `range_predicate()` and `range_params()`, whose bounds are named `:start` and
  `:end_plus` (`research/top-products-index-pricing.md`,
  `drafts/compare-two-products-across-two-date-windows.md`). Whatever zone the
  bucketing resolves to, the window predicate and the bucket expressions resolve
  to the **same** one. An order must not be able to fall inside the window under
  one rule and into a cell under another.
* **Do not introduce a second timezone convention, and do not add a `timezone`
  parameter.** The candidate asserts that the existing granularity helper buckets
  in the tenant's zone; nothing in this repository verifies that, and this spec
  does not require it to be true. It requires there to be exactly one answer in
  the tree and this report to use it.
* **The response names the zone it bucketed in**, as a string, on the top-level
  object. A grid of 168 numbers with no stated zone is not interpretable by the
  page that renders it or by the person reading the page, and this is the one
  field that makes the difference between the two readings visible rather than
  arguable.

### 3. A dense grid, with the weekday numbering stated

The response carries **all 168 cells, always**, as a flat list ordered by weekday
then hour, each cell `{weekday, hour, orders}`.

* `hour` is `0`–`23`.
* `weekday` is **ISO: 1 = Monday through 7 = Sunday.** State it in the
  docstring and assert it in the test. This is the requirement that exists
  because `EXTRACT(DOW ...)` numbers Sunday `0` and `ISODOW` numbers Monday `1`;
  picking one and documenting the other rotates the entire grid by a day, and
  every number in it stays a believable order count.
* **Dense, not sparse.** A cell with no orders in it is present with `orders: 0`.
  A consumer drawing a 7×24 grid should not have to reconstruct the missing
  cells, and a grid that omits its empty cells cannot distinguish them from the
  no-data case requirement 4 introduces.
* `orders_total` — every order in the filtered window — sits beside the cells and
  **must equal their sum**. That is the assertion that catches a fan-out, a
  dropped bucket and an off-by-one window bound, and it is the reason it is
  returned rather than left to the caller to add up.

### 4. Zero and no-data are different, and the window decides which

This is the question `research/candidates-metorik-gap-2026-09-16.md` leaves
open on this row — *whether an empty cell should render as zero or as no-data* —
and it is settled here rather than by the build agent.

**Both, and the window is what separates them.** A 10-day window contains two
Fridays and one Sunday. Every Sunday cell in it is drawn from half the
opportunity of every Friday cell, and a raw count grid over an unequal number of
weekdays reports that asymmetry as a trading pattern. A 3-day window contains
four weekdays that did not occur at all, and their rows are not quiet — they are
absent.

So the response also carries `weekday_days`: for each of the seven weekdays, how
many times that weekday occurs in the window, counted as distinct local calendar
dates under requirement 2's zone.

* A cell whose weekday has `weekday_days > 0` and no orders is `orders: 0`. Real,
  measured, empty.
* A cell whose weekday has `weekday_days == 0` is `orders: null`. The window
  contains no such day; there is nothing to have counted.

`weekday_days` is also what makes an average per weekday derivable by a consumer
without a second endpoint, which is the *total or average* question candidate 5
raises about its own row. This change returns counts and the denominator, and
computes no average itself.

The precedent is DD's own: the candidate's premise for this row is that the
cohort matrix at `platform/app/(dashboard)/analytics/customers/cohorts/page.tsx`
already distinguishes a zero cell from an absent one, so the convention exists
and the page has rendered it before.

### 5. `GET /api/analytics/orders/heatmap` in `api/analytics/routes/orders.py`

One route, returning requirement 3's shape.

* **Declare it above `/{order_id}`.** The module docstring of
  `api/analytics/routes/orders.py` records this trap twice already — FastAPI
  matches in declaration order, so a literal path registered after the
  path-parameter route binds `order_id="heatmap"` and 422s on int parsing. The
  existing literal routes are pinned by a test against it; so is this one.
* **The list route's filters, minus the pager.** `start`, `end`, `status`,
  `search`, `payment_method`, `country`, `coupon`, `has_discount`, with the same
  types and the same descriptions `get_orders` gives them — the four set filters
  as `Optional[List[str]]`, for the reason that docstring spells out about a
  repeated parameter binding onto a bare `str` and keeping only the last value.
  No `page`, `limit`, `sort_by` or `sort_dir`: an aggregate has no pagination and
  no row order to choose.
* **Reuse `_parse_range` and `_check_filter_caps`, in that module, in that
  order.** Both bounds or neither; an over-long filter field is a 400 before
  anything is queried. Inheriting them rather than restating them is what keeps
  this route's refusals identical to the list's.
* **The docstring states what the JSON means**: the weekday numbering, the zone,
  that `orders: null` is a weekday the window does not contain while `0` is an
  empty one, and that the cells sum to `orders_total`. The frontend is protected
  under this contract and cannot be updated in this diff, so whoever drafts the
  page will read this docstring and nothing else. The precedent is
  `api/analytics/routes/products.py`, whose docstring explains why its
  per-category rows deliberately do not sum.

### 6. One added test, and what it has to pin

Create `api/tests/analytics/test_fleet_orders_heatmap.py` — the only shape this
contract's `creatable_paths` permits, and it must fail against the tree without
this change, which `new_test_bites.sh` checks by running it against both. No
existing test may be edited. `test_diff_target` is 300 lines, separate from the
400 production lines, and it is guidance rather than a gate.

Over a fixture whose timestamps are chosen by hand, assert:

* an order placed at a known local weekday and hour lands in **that** cell, for
  at least one weekday that distinguishes the two numbering schemes — a Sunday
  and a Monday order together pin requirement 3, and a test that only used a
  Wednesday would pass against a grid rotated by six days;
* the response always carries 168 cells, ordered by weekday then hour, whatever
  the window;
* the cells sum to `orders_total`, and `orders_total` equals what `list_orders`
  reports as `summary.orders_all_statuses` for the same arguments. That is
  requirement 1's shared-predicate claim as an assertion rather than a promise;
* a window of fewer than seven days gives `orders: null` — not `0` — on every
  cell of a weekday it does not contain, and `weekday_days: 0` for that weekday;
* a window containing two Fridays and one Sunday reports `weekday_days` of 2 and
  1 respectively, with both weekdays' counts unadjusted;
* a filter — a `status`, or a date bound — narrows the cells and `orders_total`
  together;
* an order with several line items contributes **1** to its cell. This is the
  fan-out assertion and it fails loudly against a query that joined
  `order_items`;
* `GET /api/analytics/orders/heatmap` resolves to this handler rather than to
  `get_order`, which is requirement 5's routing trap.

## Not in scope, stated so nobody reads it as included

**Revenue per cell.** The measure is an order count. A money grid would need the
revenue-status population and would therefore disagree with this one cell by
cell, which is the whole of the file argument above. If it is wanted it is a
separate row with that conflict written into its spec.

**Daylight saving.** A local day on which the clocks change has 23 or 25 hours,
so one hour bucket on two days a year is served by no orders or by two hours of
them. Nothing here models that, no cell is rescaled for it, and no requirement
mentions it beyond this paragraph. At 1,283 days and roughly 17,000 orders per
cell the effect is far below anything the report is read for, and a correction
would be a second convention for requirement 2 to contradict.

**Any index or migration.** `api/analytics/migrations/**` is protected under this
contract. The aggregate is a scan of the window under the existing predicate;
nothing in this change claims a query time, and no requirement depends on one. If
the grouping turns out to want an access path, that is a separate proposal with a
measurement in it.

**The page.** Stated once above and repeated because it is the half a reader is
most likely to assume: there is no grid component and no colour scale in this
diff, and `platform/app/(dashboard)/analytics/orders/page.tsx` is untouched.

**Candidates 5 and 6.** No weekday endpoint and no hour endpoint is added. They
are this response's marginals and the section above says why that direction is
the one to build.

## Before this is queued

`auto_merge` is `true` on this contract and nobody reads a spec against a diff on
that path. The requirement most likely to ship **wrongly** is **3**: a grid
rotated by a day passes `compileall`, passes `ruff`, passes every existing test,
sums correctly to `orders_total`, and is wrong in the only way that matters. The
requirement most likely to ship **unbuilt** is **4** — returning `0` everywhere is
less code than distinguishing the two cases, and the difference is invisible
until somebody runs a five-day window. If one thing is read against the diff,
read the weekday expression against requirement 3's stated numbering.
