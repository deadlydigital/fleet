# Draft spec — average order item count over time, beside the AOV the revenue series already carries

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Average order item count over time — units and lines per order on every period row of the revenue series, over the same revenue-status population as aov
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/revenue.py
```

## Everything below is GIVEN. The build agent measures nothing

The agent that builds this has no shell, no database and no network. Every
figure here was taken from documents in the fleet repository and is cited where
it is used. **No numbered requirement asks anybody to re-derive any of it**, and
no requirement asks for a query to be timed.

| Figure | Value | Source |
|---|---|---|
| `order_items` rows | 4,550,334 | `research/metorik-report-classification-2026-09-15.md` |
| Of those, non-zero `quantity` | 4,550,326 — all but 8 | same |
| `orders` rows | 2,890,319 | same |
| Lines per order, overall | 4,550,334 / 2,890,319 ≈ 1.57 | derived from the two above |
| `order_items.sku`, `order_items.price` | NULL on every row | same, *Measured 16 September 2026* |

`order_items.quantity` and `order_items.total` are both populated; the `†`
marks that hung over this row in the 15 Sep classification are discharged in
that document's *Measured 16 September 2026* section. The candidate is
`research/candidates-metorik-gap-2026-09-16.md`, candidate 4 of the batch, at
`verified_sha` `7a09b92`, citing section `Weekly — Orders (7 of 10)` of the
classification at sha `80677a2`.

## Why this is a code change and not an investigation

Nothing has to be found out first. The report does not exist —
`research/candidates-metorik-gap-2026-09-16.md` records a probe over
`api/analytics/services/analytics_engine.py` for `avg_items|average_items|items_per_order`
expecting zero matches, and a second over `api/analytics/routes/*.py` for
`item_count|items_per_order` expecting zero — and the series it belongs in does
exist. `revenue_report()` in `api/analytics/services/analytics_engine.py`
already returns one row per period carrying `orders`, `revenue`, `net_revenue`,
`refunded_amount`, `orders_with_refund` and `aov`
(`research/refund-coverage.md` maps it at line 787 of that module, exposed as
the `data` key of `GET /api/analytics/revenue` from
`api/analytics/routes/revenue.py`). This change adds a second ratio to rows that
already exist. There is no new column, no migration, and no new endpoint.

## The two questions the candidate left open, and the answers this spec gives

`research/candidates-metorik-gap-2026-09-16.md` records an `unasked_question` on
this row — *whether it belongs on the revenue page beside AOV or on the orders
page beside the order counts, which decides whose date range it follows* — and
one on candidate 3, the distribution this is the mean of: *whether "item count"
means lines or units*. A build agent cannot settle either, so both are settled
here.

**It goes in the revenue series, and it follows the revenue window.** The
candidate's own rationale says so — *"a second ratio in the existing
revenue_report series"* — and the reason is the conflict this row must not
import. `specs/metorik-gap.md:96` records, against the revenue-over-time row,
that revenue-status filtering is applied to both sides of AOV as *documented
conflict 2.1*: a ratio is only meaningful when its numerator and its denominator
are taken over the same rows. Computed inside `revenue_report()`, the
denominator is the `orders` count that function already computes, over the
window and statuses it already applies. Computed on the orders page against a
list endpoint with its own filters, it would be a numerator from one population
over a denominator from another, which is exactly the shape 2.1 names. The
candidate's suggested paths include `api/analytics/routes/orders.py` and
`platform/app/(dashboard)/analytics/orders/page.tsx`; they are advisory, and
they are not taken.

**"Item count" means units, and lines ship beside it rather than instead of
it.** Metorik's report counts items, and `order_items.quantity` is non-zero on
all but 8 of 4,550,334 rows, so a true unit count is available. But the two
figures differ wherever a quantity exceeds one — 4,550,334 lines over 2,890,319
orders is 1.57 lines per order, and the unit mean is at least that and unknown
until it is computed — and nobody has said which number HIB reads. Both come
out of one aggregate over the same join for almost nothing, so both are
returned, each under a name that says which it is. A single key called
`avg_items` that turned out to count lines would be one metric telling two
stories, which is the failure the parity work has been closing elsewhere in
this tree.

## Why this contract

`contracts/deadly-digital-platform-api.yaml`, work_type `dd_api`. Both declared
paths — `api/analytics/services/analytics_engine.py` and
`api/analytics/routes/revenue.py` — are in its enumerated writable set and
neither is protected by it. `contracts/dd-order-filters.yaml` carries the same
work_type and repo and cannot cover this work: its whole writable set is
`api/analytics/routes/orders.py` and `api/analytics/services/order_query.py`,
so the engine module it would have to change is protected under it.

That is the mechanical answer. The reason it is also the right one is that this
contract runs `tests/unit` and `tests/analytics` per file and requires one added
test proven to fail against the tree without the change, while
`contracts/dd-order-filters.yaml` permits no new test file at all and runs an
acceptance check written for a different task. The defect this change is most
likely to ship — a join that fans an order's line rows out across the
order-level sums, inflating `revenue` and `orders` — produces numbers, not an
exception, and nothing but a test over a fixture with multi-line orders will
catch it.

## Citing the requirements

`contracts/checks/spec_requirements_cited.py` runs first under this contract and
reads only lines the diff adds. Put `# spec:N` on a line this change adds — the
line building the item aggregate, the docstring line naming a key, the test name
— for each of 1 through 6. Six requirements, against a `max_requirements` of 10.

---

### 1. Every key that exists today keeps its name, its population and its value

`orders`, `revenue`, `net_revenue`, `refunded_amount`, `orders_with_refund` and
`aov` come back from `revenue_report()` byte-identical to what they return now,
for every granularity and every window. Nothing is renamed, reordered, rounded
differently or recomputed.

**The specific way this gets broken here is fan-out.** `order_items` stands in a
many-to-one relationship to `orders`, so adding it to the `FROM` of the existing
order-level aggregate multiplies every order-level row by its line count:
`SUM(o.total)` becomes a sum over 4,550,334 rows instead of 2,890,319, `revenue`
rises, `COUNT(*)` rises, and `aov` changes. **The existing aggregate's `FROM`
and `JOIN` list does not change.** The item figures are computed in an
additional aggregate — see requirement 4 — and joined on the period key.

The discipline is the one `specs/net-revenue-after-refunds.md` established for
net beside gross and the AOV work restated: additive keys, nothing recomputed.
The frontend is protected under this contract, so a silently different number
has no way to announce itself on the page that prints it.

### 2. Each period row of `revenue_report()` carries four new keys

Every row `revenue_report()` already returns gains, beside `orders` and `aov`:

* `items` — the sum of `order_items.quantity` over the row's orders. An integer
  count of units.
* `lines` — the count of `order_items` rows against the row's orders. Distinct
  line rows, not units.
* `avg_items` — `items` divided by `orders`. The mean basket size in units, and
  the figure the report is named for.
* `avg_lines` — `lines` divided by `orders`. The mean number of distinct line
  rows per order.

The two raw sums are returned and not only the ratios, for two reasons. A
consumer that wants a window figure can compute `Σitems / Σorders` across the
series without a second query — the mean of the per-period means is not that
number, and a page that averaged the ratios would print a different figure from
the one the same code computes over the whole window. And a ratio whose terms
are visible is auditable against `orders` on the same row, which is what makes a
fan-out defect readable in the response rather than only in a test.

`avg_items` and `avg_lines` carry the same rounding treatment `aov` already
receives in this function. Do not introduce a second rounding convention;
`items` and `lines` are not rounded at all.

### 3. The population is taken from the existing filter, and an absent mean is `None`

The new aggregate is restricted to the **same rows** the existing one is: the
same window predicate, built with `range_predicate()` and `range_params()` from
`api/analytics/services/date_range.py`, and the same status constant
`_REVENUE_STATUSES` from `api/analytics/services/analytics_engine.py`. Reference
the constant. Do not write a status tuple as a literal — the research carries two
different readings of what that constant holds (`research/refund-coverage.md:122`
records `('completed', 'processing')`;
`research/candidates-aov-free-entries-2026-09-16.md:25` records
`('completed', 'processing', 'on-hold')`), and this change must not be a third.
Whatever it holds, `avg_items` and `aov` must be over one population, which is
the whole of conflict 2.1.

Three cases the arithmetic has to state rather than discover:

* **An order with no `order_items` rows stays in the denominator** and
  contributes zero items. It is an order that happened. The join to the item
  aggregate is therefore an outer one and the missing side coalesces to `0` —
  an inner join would silently drop those orders from `orders` as well if the
  aggregate were folded in, and would make `avg_items` a mean over a population
  no key on the row names.
* **A `NULL` quantity contributes `0`, not `NULL`.** Eight rows of 4,550,334
  carry no non-zero quantity and a bare `SUM` that nulls a whole period on
  account of them is the wrong answer. `items` is `0`, never `None`, and so is
  `lines`.
* **`avg_items` and `avg_lines` are `None` when the period's `orders` count is
  zero**, never `0` and never a division error. A period with no orders has no
  mean basket, and `0.0` there reads as "orders were empty" rather than "there
  were no orders". This is the no-baseline rule
  `specs/dashboard-comparison-windows.md` states for a comparison window with no
  prior: absent is reported as absent.

### 4. One additional aggregate, no per-row queries, and the existing statement's shape is preserved

The item figures come from **one** additional aggregate over the window — a CTE
or derived table grouping `order_items` joined to `orders` by the same period
expression the existing query groups by, outer-joined back onto the series on
that period key. Not a query per period row, not a query per order, and not a
Python loop issuing SQL. The period bucketing expression is reused, not
retyped: two spellings of the same granularity that disagree at a boundary
would put an order's items in one week and its total in another.

This shape is already in the tree to copy: `top_products` in
`api/analytics/services/analytics_engine.py` joins `order_items oi` to
`orders o` on `o.id = oi.order_id` under `range_predicate("o.created_at")` and
`o.status IN _REVENUE_STATUSES`, and sums `oi.quantity` there
(`research/top-products-index-pricing.md` quotes it verbatim). The join
predicate, the window and the status filter are the same three this needs.

`api/analytics/migrations/versions/v0015_order_items_order_covering_index.py`
exists in the tree and is the composite `(order_id, wc_product_id,
product_name, total, quantity)` — an index under which this aggregate can be
served without touching the heap. **Nothing here claims it is applied in any
environment, and no requirement depends on it.** `specs/v0015-order-items-covering-index.md`
records that its gate C — the real measured win — was outstanding when it was
written. Do not add an index, do not write a migration,
`api/analytics/migrations/**` is protected under this contract, and do not
write anything into the code or the tests claiming a query time.

### 5. The hourly variant inherits, and the route says what the keys mean

`revenue_report_hourly()` in `api/analytics/services/analytics_engine.py`
delegates to `revenue_report()` and inherits its keys
(`research/refund-coverage.md`). It must keep doing exactly that: **no second
implementation of this arithmetic anywhere in the module.** If it already
passes rows through untouched, this requirement costs nothing and is satisfied
by not breaking it.

`api/analytics/routes/revenue.py` documents, in the docstring of the endpoint
that returns these rows, that `avg_items` counts units and `avg_lines` counts
line rows, that both are over the revenue-status orders in the period and share
their denominator with `aov`, that `items` and `lines` are the raw sums a window
figure should be derived from, and that `avg_items` is `None` rather than `0`
for a period with no orders.

This is not decoration. The JSON is the only contract a consumer of this route
has, the frontend is protected under this contract and cannot be updated in this
diff, and whoever drafts the page will read this docstring and nothing else.
The precedent is `api/analytics/routes/products.py`, whose docstring explains
why the per-category rows deliberately do not sum — the same class of statement
about the same class of trap.

### 6. One added test, and what it has to pin

Create `api/tests/analytics/test_fleet_avg_order_items.py` — the only shape this
contract's `creatable_paths` permits. No existing test may be edited. The test
must fail against the tree without this change; `new_test_bites.sh` runs it
against both trees.

Over a fixture of revenue-status orders with **differing line counts and
quantities greater than one**, it must assert:

* `revenue`, `net_revenue`, `orders` and `aov` are exactly what the same call
  returns for a fixture of single-line orders with the same totals. **This is
  the fan-out assertion and it is the reason the test exists.** A test that
  only checked the new keys would pass against a build that inflated every
  order-level sum by its line count.
* `avg_items` equals the fixture's total units over its order count, and
  `avg_lines` equals its line-row count over the same order count, and on that
  fixture **the two differ** — seed a quantity above one, or equal values would
  pass against code that computed one figure and returned it twice.
* `items` and `lines` equal the fixture's totals, and `items / orders` equals
  `avg_items` to the rounding requirement 2 mandates.
* an order with **no** line rows is counted in `orders`, contributes `0` to
  `items` and `lines`, and pulls `avg_items` down accordingly.
* a period with no orders returns `avg_items is None` and `avg_lines is None`,
  with `items` and `lines` at `0`. This is the case a naive division writes
  `0.0` on or raises on.
* an order **outside** `_REVENUE_STATUSES`, with line rows, contributes to
  neither `items` nor `lines` nor `orders` — the same population on both sides
  of the ratio, asserted rather than assumed.

`test_diff_target` under this contract is 300 lines and is guidance, not a gate.

## Not in scope, stated so nobody reads it as included

**`revenue_summary()`.** The window aggregate behind the `summary` key of the
same endpoint. It is deliberately untouched: requirement 2 returns `items` and
`lines` per period precisely so a window mean is derivable without a second
aggregate, and adding one here would double the fan-out surface for a figure a
consumer can already compute. If a page later wants it server-side, that is a
small follow-up against this same contract.

**`dashboard_overview()`.** It carries `aov` in its `period` and `previous`
objects and is served by `api/analytics/routes/dashboard.py`. Nothing here
touches it, no comparison percentage is computed for any new key, and the
overview's two-query shape does not change.

**The page.** `platform/app/(dashboard)/analytics/revenue/page.tsx` renders this
series and nothing in this diff can reach it: `platform/**` is protected under
`contracts/deadly-digital-platform-api.yaml`, as `api/**` is under
`contracts/dd-analytics-frontend.yaml`. It is a known follow-up drafted against
the frontend contract once this has merged — it has something to render only
after this ships — and it is deliberately not a second `fleet-spec` block here.
`console/autoqueue.py` writes the whole markdown into `tasks.spec_md` for every
link of a chain and `contracts/checks/spec_requirements_cited.py` then obliges
each link's diff to cite every numbered requirement in the document, so a
two-block chain would fail both links after paying for both.

**Candidate 3, the item-count distribution.** This is the mean of that
distribution, and `research/candidates-metorik-gap-2026-09-16.md` says an
approver taking both should expect them to be one task — its own rationale adds
that the buckets are not derivable from the mean while the mean is derivable
from the buckets. If both are approved, build the distribution and take the mean
off it; this spec is what to build if only this row is taken. The two must not
be built independently into two different definitions of "item".

**Whether the unit mean and the line mean differ materially.** 1.57 lines per
order is measured; the unit mean is not, and requirement 2 is what would produce
it. Nothing above asks the build agent to establish it.

**`order_items.sku` and `order_items.price`.** NULL on every one of the
4,550,334 rows. Neither is read by anything in this change.

## Before this is queued

`auto_merge` is `true` on this contract and nobody reads a spec against a diff
on that path. The requirement most likely to ship **wrongly** is **1**: a fan-out
that inflates `revenue` and `aov` passes `compileall`, passes `ruff`, and passes
every existing test that does not pin an exact revenue figure against a
multi-line fixture. The requirement most likely to ship **unbuilt** is **5** —
a docstring is invisible to every check in the verification list, and the next
person to touch this endpoint is the one who pays for its absence. If one thing
is read against the diff, read requirement 1 against the `FROM` clause of the
existing aggregate.
