# Draft spec — how many line items an order carries, as a distribution

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Item count distribution — the number of orders at each line count, over a filtered window
writable_paths:
  - api/analytics/services/order_query.py
  - api/analytics/routes/orders.py
```

## Why this is a code change and not an investigation

The count already exists and is already correct. `api/analytics/services/order_query.py`
computes it per order inside `_row_select`, as a correlated subquery aliased
`item_count`, and hands it to the list page and the CSV export through
`_row_to_order`. What the product cannot do is say anything about that column
across more than one order: nothing groups it, nothing sums it, and there is no
endpoint that returns a shape a histogram could be drawn from.

So there is nothing to find out. The work is a `GROUP BY` over an expression
already in the file, and a route beside the three that already read that file.

`research/metorik-report-classification-2026-09-15.md:713` classifies the report
**A** — buildable on today's schema — on the strength of `order_items` holding
4,549,662 rows keyed by `order_id`. It also carries a dagger, and §3 below is
that dagger written out rather than inherited silently.

## Why this one rather than the mean

`research/metorik-report-classification-2026-09-15.md:718` lists *Average order
item count* as a separate **A** row, and it is the mean of exactly this
distribution. Building the buckets gives the mean for free — it is
`Σ(lines × orders) / Σ(orders)` over what §2 returns — and building the mean
gives the buckets not at all. For a ticket store the buckets are the answer
anyone actually wants: 4,549,662 lines over 2,889,850 orders is a mean near 1.57,
and a mean near 1.57 is consistent with "almost everyone buys one ticket and a
few buy twenty" and equally consistent with "half buy one and half buy two".
Those are different businesses and the mean cannot tell them apart.

Hence §2 returns the mean **as well**, derived from the buckets in the same
response, so the second report does not need a second query.

## Why these two files and no others

`api/analytics/services/order_query.py` owns the order list's SQL, its filter
predicate and the per-order line count this report aggregates.
`api/analytics/routes/orders.py` is the only consumer of that service and already
serves three routes from it. Nothing else is involved: this adds no column, needs
no migration, and `api/analytics/migrations/**` is protected under
`contracts/deadly-digital-platform-api.yaml` and is not wanted here.

The index this query wants already exists —
`api/analytics/migrations/versions/v0015_order_items_order_covering_index.py`
covers `order_items` by order — so the grouping has the access path it needs
without a schema decision attached to this change.

## What to build

Five requirements. Put `spec:<id>` on a line this change adds — a comment, a
docstring, or a test name — for each of `1` to `5`; see
`contracts/checks/spec_requirements_cited.py`, which runs first under
`contracts/deadly-digital-platform-api.yaml` and reads only added lines.

### 1. One grouped query in `api/analytics/services/order_query.py`

Add a function that, for one tenant and one filtered window, returns how many
orders carry each number of line items. It takes the window as parameters and
does not choose one.

Constraints on the query:

* **Build the predicate from `_filter_clause`, not from a new one.** That
  function's docstring already names its three consumers — the summary
  aggregate, the row SELECT and the CSV export — and states why a fourth copy
  would let two surfaces describe different rows while both looked right. This
  is the fourth consumer, and it inherits the date bounds, the four set filters,
  `search` and `has_discount` by construction rather than by re-spelling them.
  It follows that the distribution describes the population the page beside it
  reported, for the same query string.
* **Group in SQL, in one statement.** A CTE that reduces orders to
  `(order id, line count)` and an outer `GROUP BY` over that CTE. Do not fetch
  orders and count in Python: the filtered window can be the whole table, which
  is 2,889,850 orders against 4,549,662 line rows on this tenant.
* **`LEFT JOIN order_items`, and count the joined column.** `COUNT(i.id)` over a
  left join yields 0 for an order with no lines. An inner join, or `COUNT(*)`
  over the left join, both give the wrong answer for exactly the population §2
  has to report — the second silently, by counting the null-extended row as one
  line.
* **No status filter of its own.** This file's module docstring is explicit that
  an order list lists rows and does not compute a metric, and that nothing here
  filters by revenue status. A distribution that quietly dropped `cancelled`
  orders would disagree with the count on the page that links to it. Status is
  reachable through the existing `status` filter, which is the caller's choice
  and not this function's.

### 2. Buckets, the zero bucket, and the summary the mean comes from

The return value carries, for the window:

* `buckets` — a list of `{lines, orders}`, ordered by `lines` ascending. `lines`
  is the number of line items on an order; `orders` is how many orders had
  exactly that many. Ascending by `lines`, not by `orders`: this is a
  distribution and its axis is the line count, so a consumer plots it without
  re-sorting.
* **A `lines: 0` bucket when such orders exist, and its absence otherwise.** An
  order with no line items is a real and countable outcome, not a gap in the
  data, and it is the one bucket a wrong join silently deletes. It is also not
  hypothetical: the reconciliation work in
  `drafts/order-total-vs-line-items-residual.md` records roughly 397 orders with
  no lines at all in a comparable population.
* `orders_total` — every order in the window, which must equal the sum of the
  `orders` field over `buckets` **plus** the tail count from §4. An assertion a
  consumer can make, and the reason the tail is a count rather than a shrug.
* `mean_lines` — the mean lines per order over the window, to two decimal
  places, derived from the same aggregate rather than from a second query. It is
  the *Average order item count* row of
  `research/metorik-report-classification-2026-09-15.md:718`, and it is here so
  that report does not become a second endpoint over the same scan.
* `max_lines` — the largest line count present in the window, whether or not it
  is inside the cap §4 imposes. Without it, a truncated tail has no top.

`mean_lines` counts orders with no lines as zero-line orders, because they are
in the denominator of `orders_total`. Say so in the docstring: a mean over
"orders that have lines" is a different number and the difference is the thing a
reader will otherwise assume away.

### 3. It counts LINES, not units, and the names must say which

`order_items.quantity` exists and this report does not read it. An order with one
line of six tickets is **one** line and six units, and the two distributions are
different reports.
`research/metorik-report-classification-2026-09-15.md:713` marks this row with a
dagger for precisely this reason: lines per order is what the schema reading
covered, and `quantity`'s spread was not part of it.

So:

* The bucket key is `lines`, and every field in the response and every name in
  the code says lines. Nothing in this change is called `item_count`,
  `items_per_order`, or anything a reader can take for units.
* The function's docstring states in its first paragraph that the unit of the
  distribution is the line and that the quantity-weighted version is a separate
  report that this one does not approximate.
* It is keyed on **the same expression** the list page's existing `item_count`
  column is: an order the list renders with `item_count: 3` lands in the
  `lines: 3` bucket. That is the compatibility that matters, and it is why the
  existing column keeps its name and this one does not borrow it — the two agree
  on the number while being clear that `item_count` has always meant lines.

### 4. A bounded tail that admits what it left out

The number of distinct line counts is unbounded in principle and this is served
over HTTP, so cap `buckets` at the twenty lowest values of `lines`. Everything
above the cap is reported as a single tail object carrying:

* `min_lines` — the smallest line count folded into it;
* `orders` — how many orders are in it;
* `distinct_values` — how many distinct line counts it swallowed.

When nothing is above the cap the tail is absent, not a zero-filled object: an
absent tail says "the cap did not bite", and a zeroed one is indistinguishable
from a bug at a glance. A truncated list that does not say it was truncated reads
as a complete one, and here it would read as "no order in this store has ever had
more than twenty lines", which is a claim this change is in no position to make.

### 5. `GET /api/analytics/orders/item-counts` in `api/analytics/routes/orders.py`

One route, returning §2's shape.

* **Declare it above `/{order_id}`.** The module docstring of
  `api/analytics/routes/orders.py` records this trap twice already — FastAPI
  matches in declaration order, so a literal path registered after the
  path-parameter route binds `order_id="item-counts"` and 422s on int parsing.
  Both existing literal routes are pinned by a test against it and so is this
  one.
* **The list route's filters, minus the pager.** `start`, `end`, `status`,
  `search`, `payment_method`, `country`, `coupon`, `has_discount`, with the same
  types and the same descriptions `get_orders` gives them — the four set filters
  as `Optional[List[str]]`, for the reason that docstring spells out about a
  repeated parameter binding onto a bare `str` by keeping the last value. No
  `page`, `limit`, `sort_by` or `sort_dir`: an aggregate has no pagination and no
  row order to choose.
* **Reuse `_parse_range` and `_check_filter_caps`, in that module, in that
  order.** Both bounds or neither; an over-long filter field is a 400 before
  anything is queried. Inheriting them rather than restating them is what keeps
  this route's refusals identical to the list's.

## The test

`contracts/deadly-digital-platform-api.yaml` requires exactly one new test file
and proves it bites: `new_test_bites.sh` runs it against the tree before the
change and refuses it if it passes there. Create

    api/tests/analytics/test_fleet_item_count_distribution.py

which is the only creatable shape the contract allows —
`api/tests/analytics/test_fleet_*.py`. Budget is 300 lines, separate from the 400
production lines. `api/tests/analytics/test_fleet_order_multi_value_filters.py`
is the nearest neighbour for fixture conventions and it must not be edited.

Build a fixture whose arithmetic is known and assert on all of it:

* orders with 1, 1, 2 and 3 lines → buckets `[{1, 2}, {2, 1}, {3, 1}]`, in that
  order, ascending by `lines`;
* an order with **no** line items → a `lines: 0` bucket holding it, and
  `orders_total` counting it. This is the assertion an inner join fails and the
  one `COUNT(*)` over a left join fails differently, by putting it in `lines: 1`;
* the sum of `orders` across buckets plus the tail equals `orders_total`;
* `mean_lines` over that fixture, computed by hand in the test, including the
  zero-line order in the denominator;
* a filter — a status, or a date bound — narrows the buckets and `orders_total`
  together, and gives the same `orders_total` as `list_orders` reports as
  `orders_all_statuses` for the same arguments. That is §1's shared-predicate
  requirement as an assertion rather than a promise;
* more than twenty distinct line counts → exactly twenty buckets, a tail whose
  `distinct_values` is the remainder, and `max_lines` above the cap;
* `GET /api/analytics/orders/item-counts` resolves to this handler rather than to
  `get_order`, which is the §5 routing trap.

## What this does not do

**It does not read `order_items.quantity`.** §3 says why, and the
quantity-weighted distribution is a separate candidate with its own population
question. Adding it here would double the query and blur the one thing this
report is for.

**It does not split free entries.** The two rows in
`research/metorik-report-classification-2026-09-15.md` that carry the 16 Sep 2026
free-entry correction are *Average order gross over time* (:707) and *Order value
distribution* (:714) — both keyed on `orders.total`, where 66,764 zero-total
orders are the legal free-entry route and a reader would misread the zero bucket
as failed checkouts. This report is keyed on line counts, where a free entry is
an ordinary one-line order and nothing about it is ambiguous. A `lines: 0` bucket
is a different fact from a `total: 0` one and §2 already names it.

**It does not draw anything.** There is no page in this change.
`platform/**` is protected under this contract; the frontend half is a separate
task under `contracts/dd-analytics-frontend.yaml` and should be queued as one
once this endpoint exists.

**It does not add an index or touch a migration.**
`api/analytics/migrations/versions/v0015_order_items_order_covering_index.py` is
already the covering index over `order_items` by order. If the grouped query
turns out to want something else, that is a separate proposal with a timing in
it, and not something to fold into this diff.
