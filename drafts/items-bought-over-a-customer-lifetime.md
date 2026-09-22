# Draft spec — how many items a customer buys over a lifetime, counted in units and saying so

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Items bought over a customer lifetime — a distribution of UNITS per customer, with the line count named beside it and the free-entry basis split
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/customers.py
```

## Why this is a code change and not an investigation

Nothing needs finding out. `research/metorik-report-classification-2026-09-15.md:815`
classifies *Items bought over customer lifetime* **A** — buildable on today's
schema — and states the derivation: *"`order_items` 4,549,662 rows joined to
`orders` by `order_id`. A line count is covered; a unit count needs `quantity`,
unmeasured."* The dagger has since been discharged.
`research/candidates-metorik-gap-2026-09-21.md` records the measurement:
*"order_items.quantity is NOT NULL on all 4,550,334 rows and non-zero on
4,550,326 of them, so a true unit count is available and not only a line
count."* There is no absent column, no absent table and no migration.

What the product cannot do is aggregate line items **per customer**. The engine
sums them per *period* — `_item_counts_cte` at
`api/analytics/services/analytics_engine.py:208` — and per *order*, in
`item_count_distribution` at `api/analytics/services/order_query.py:668`. Both
are the shape this reuses and neither is this row: a merchant can ask "how many
tickets went out last month" and "how big is a typical basket", and cannot ask
"how many tickets has a customer ever bought".

## The decision this row exists to make, made here rather than left to the build

**Units, not lines.** `item_count_distribution` answered the same question once,
for a different report, and answered it the other way — deliberately and in
writing, at `api/analytics/services/order_query.py:683`: *"THE UNIT OF THIS
DISTRIBUTION IS THE LINE, NOT THE UNIT SOLD. `order_items.quantity` exists and
is never read here."* That was right for a per-order basket-size report, where a
line is what a checkout produces. It is wrong for a lifetime total, and the
number that makes it wrong is already on file.

`research/metorik-report-classification-2026-09-15.md:553` measures the mean
quantity per line inside free-entry orders at **21.13 entries**. The same
correction records 66,764 free-entry orders carrying 73,378 line rows, placed by
15,616 distinct customers, and the overall store mean is nearer 1.57 lines an
order. So on part of this population lines and units differ by more than an
order of magnitude, and a "lines" answer would report one of HIB's free-entry
customers as having bought three things when the entry count is sixty-three.
A report titled *items bought* that returns lines has answered a different
question with a confident number.

**The vocabulary is not invented either.** `_item_counts_cte` already calls
`COALESCE(SUM(COALESCE(oi.quantity, 0)), 0)` **`items`** and `COUNT(*)`
**`lines`**, at `api/analytics/services/analytics_engine.py:242` and `:243`, and
`_item_counts` at `:252` returns both with a mean each. This report keys on
`items` because that is what this module has always called a unit count, and
carries `lines` beside it so the divergence above is visible in the response
rather than only in this document.

**And the free-entry split is the row's own `unasked_question`**, which
`research/candidates-metorik-gap-2026-09-21.md` states as *"Whether a free entry
counts as an item bought. Twenty-one free entries and one paid ticket are both
real, and putting them in one lifetime total makes an entrant look like a
buyer."* §3 below answers it: both bases, named, never collapsed — which is the
shape `free_entry_convention` at
`api/analytics/services/analytics_engine.py:282` already settled for AOV, whose
rule is that a free entry *"is a legal obligation being met correctly, not a
missing total"* and is therefore reported rather than dropped.

## Why these two files, and why not `order_query.py`

`research/candidates-metorik-gap-2026-09-21.md` suggests
`api/analytics/services/order_query.py` as well. It should stay out, and the
reason is in that module's own docstring, quoted by the function this report is
named after: *"This module lists rows and does not compute a metric."*
`item_count_distribution` lives there because it is keyed on the order-list's
`_filter_clause` and describes the rows the page beside it rendered. This report
is keyed on a customer population defined by acquisition date, it takes no
`status`, `search` or `payment_method` filter, and its neighbour is
`ltv_distribution` at `api/analytics/services/analytics_engine.py:4078`. Putting
it in the engine keeps the diff to two files and avoids giving the order-list
module a customer-population concept it has never had.

`api/analytics/routes/customers.py` is the only route module involved: it
already serves `/ltv` from the population helper this reuses.

**No migration, and none is wanted.**
`api/analytics/migrations/versions/v0015_order_items_order_covering_index.py`
built `ix_analytics_order_items_order_covering` on `(order_id, wc_product_id,
product_name, total, quantity)` — `order_id` leading, `quantity` covered — which
is exactly an index-only scan for "sum quantity per order".
`api/analytics/migrations/versions/v0014_orders_customer_created_index.py` is
the orders-by-customer-and-date path the population CTE seeks on. Both halves of
this query already have their index, and `api/analytics/migrations/` is
protected under the contract named above.

## Why this contract

`contracts/deadly-digital-platform-api.yaml` makes both files writable and is
the only contract here that requires a test — one new file under
`api/tests/analytics/test_fleet_*.py`, proven by `new_test_bites.sh` to fail
against the tree before the change. `contracts/dd-order-filters.yaml` is the
other contract that could cover a change of this size; it makes two files
writable, neither of them `api/analytics/services/analytics_engine.py`, and it
permits no new test at all. A report whose whole content is arithmetic over
4.55 million line rows, shipped with nothing asserting that arithmetic against a
fixture, is the thing that ships wrong and stays wrong. So: the API contract,
and the test it mandates.

## Where this sits in the queue

`research/candidates-metorik-gap-2026-09-21.md` says to take this after
*Orders made over customer lifetime*, whose draft is
`drafts/orders-per-customer-distribution.md`, *"whose bucket-and-tail shape it
reuses"*. That ordering is right and this spec keeps it, with one correction
stated here rather than discovered in the build: **the two reports share a
population and not an axis.** Candidate 4's axis is a small integer and its
draft buckets one value per integer with a folded tail; a lifetime unit count on
this store runs into the thousands, so §4 uses fixed magnitude edges instead —
`ltv_distribution`'s shape, not `item_count_distribution`'s.

**This change therefore depends on nothing candidate 4 adds.** The population
helper it inherits, `_ltv_population_cte` at
`api/analytics/services/analytics_engine.py:4065`, is in the tree today. If
candidate 4 has not landed when this is built, nothing here is blocked; if it
has, no line of it is edited.

## What to build

Seven requirements. Put `spec:<id>` on a line this change adds — a comment, a
docstring or a test name — for each of `1` to `7`; see
`contracts/checks/spec_requirements_cited.py`, which runs first under
`contracts/deadly-digital-platform-api.yaml` and reads only added lines.

### 1. One grouped query in `api/analytics/services/analytics_engine.py`

Add `lifetime_items_distribution()`: for one tenant and one window, how many
customers bought each quantity of items over their lifetime.

* **The population is `_ltv_population_cte()`'s, not a new one.** `start` and
  `end` select customers whose first revenue-status order falls inside the
  window; the helper's own docstring at
  `api/analytics/services/analytics_engine.py:4066` states the rule and the
  reason — *"A lifetime clipped to a month is a monthly figure wearing a
  lifetime's name."* Inheriting it is what makes this report and
  `GET /customers/ltv` describe the same people for the same arguments.
* **The totals are not clipped to the window.** A customer acquired inside it is
  counted on every item they ever bought, before and after. The docstring says
  this is inherited from the helper rather than re-arguing it.
* **The per-customer sum is its own CTE, joined back — never a join added to the
  population's `FROM`.** `_item_counts_cte`'s docstring at
  `api/analytics/services/analytics_engine.py:211` is the standing warning:
  `order_items` is many-to-one against `orders`, so a line join in the wrong
  place multiplies every order-level row by its line count, *"and that defect
  produces numbers rather than an exception"*. Here it would inflate the order
  count and the spend the population CTE already computes.
* **`LEFT JOIN`, and `COALESCE(oi.quantity, 0)`.** A customer whose orders carry
  no line rows is a real customer with zero items, not an absent one; and 8 of
  4,550,334 lines carry no non-zero quantity, which `_item_counts_cte` already
  coalesces for the same reason.
* **Grouped in SQL, in one statement per basis.** 2,889,850 orders and 4,549,662
  line rows on this tenant; counting in Python is not an option at that size.

### 2. The measure is units, the line count travels with it, and neither is called `item_count`

* `items` is the quantity sum and `lines` is the row count, matching
  `api/analytics/services/analytics_engine.py:242` and `:243` exactly. Every
  bucket field says `items`.
* **Nothing in the response is named `item_count` or `items_per_order`.**
  `_row_select`'s existing `item_count` column and the `lines:` buckets of
  `item_count_distribution` both mean *lines*, and a third meaning attached to
  a similar name is how two surfaces come to disagree while both look right.
* `lines_total` and `mean_lines_per_customer` sit in the summary beside the unit
  figures, so the divergence this spec's second section measures is readable off
  one response. They are **summary numbers only** — there is no second
  distribution keyed on lines, and the docstring says that
  `GET /orders/item-counts` at `api/analytics/routes/orders.py:372` is where a
  line-keyed distribution lives.

### 3. Two bases, both named, never collapsed

Free entries are real orders placed by real customers, and twenty-one of them is
not twenty-one purchases. The response therefore carries the distribution
**twice**:

* `all_orders` — every revenue-status order in the customer's lifetime,
  free entries included;
* `paid_orders` — the same customers, restricted to orders with a non-zero
  `total`.

The population is **identical** in both: a customer who only ever took free
entries appears in `paid_orders` with zero items rather than vanishing, because
a customer who bought nothing is a fact about the store and a dropped row is
not. That is `free_entry_convention`'s rule at
`api/analytics/services/analytics_engine.py:282` applied to a count instead of a
mean, and the response carries a `free_entry_basis` block naming both
populations in words, as that helper does.

**One CTE, two aggregations.** The per-customer CTE computes `items`,
`items_paid` and `lines` together; the two histograms come off it in a single
statement with the basis as a literal column. The expensive half is the CTE and
it is computed once.

### 4. Fixed magnitude edges, every bucket present, and the edges returned in the response

The axis is a magnitude, not a small integer, so this **does not** reuse the
one-bucket-per-value cap. `MAX_ITEM_COUNT_BUCKETS` is 20 at
`api/analytics/services/order_query.py:93`, and twenty integers is the right
head for lines per order, where the store mean is near 1.57. Over a lifetime
this store means roughly 18.4 orders a customer, and free-entry lines alone
average 21.13 units — so a twenty-integer head would put nearly the whole
population in one tail bucket, and a report whose summary is "most of your
customers bought more than twenty things" has not answered the question.

Use `ltv_distribution`'s shape instead, which already solved this for money:

* a module-level tuple of edges, `width_bucket` over it, exactly as
  `api/analytics/services/analytics_engine.py:4129` does;
* **every bucket present, zeros included** — `:4137` states why: *"an absent
  bucket and an empty one read identically on a chart and mean different
  things"*;
* bucket 0 is below the first edge and the last is open-ended; both carry a
  `null` edge rather than a made-up number;
* each bucket carries `customers` and `share`;
* **the edges are returned in the response** alongside an `edges_are_a_guess`
  flag, as `:4213` returns them. A reader who has to know the implementation to
  read the payload will eventually guess wrong.

Fixed edges rather than quantiles: a quantile edge moves with the window, so two
windows produce two axes and the curves cannot be laid over each other, which is
the comparison this report exists to support. §5's percentiles are the
protection against a badly chosen edge, because they are scale-free.

### 5. A summary that carries its own arithmetic

Per basis, over the window:

* `percentiles` — p50, p75, p90, p95, p99, leading the block.
  `api/analytics/services/analytics_engine.py:4116` gives the reason and it
  holds here: they *"are scale-free, so they stand whatever the guessed
  histogram edges turn out to be worth on this tenant"*. A long-tailed count's
  mean is not a typical customer.
* `customers_total` — **it must equal the sum of `customers` across every
  bucket.** An assertion a consumer can make.
* `items_total`, `lines_total`, and `mean_items_per_customer` and
  `mean_lines_per_customer` to two decimal places, each derived from this same
  aggregate rather than from a second query, with the docstring naming
  `customers_total` as the denominator.
* `max_items` — the largest lifetime count present, whether or not it lands
  inside the top edge.
* `customers_with_no_items` — the first bucket, named, because "bought nothing
  that counts" is the number a reader of a paid-basis report reaches for first.
* Every one of these is `None` — never `0` — for a window holding no customer at
  all. A mean over nobody is undefined, and `0.00` is a claim about a population
  that does not exist.

### 6. What the query drops is counted, not dropped silently

A distribution that silently discards rows reports the shape of what survived.

* **Orders and lines carrying no customer.** `_ltv_population_cte` requires
  `customer_id IS NOT NULL`, and
  `research/candidates-metorik-gap-2026-09-21.md` is explicit that 157,311 is a
  count of distinct values and not a coverage measure. The response carries
  `orders_without_customer` and `items_without_customer` for the window, and the
  docstring states which of NULL and zero the query treats as "no customer" and
  that the other was checked.
* **Customers acquired in the window with no revenue-status order.** Reported as
  `customers_without_revenue_order`, exactly as `ltv_distribution` reports it at
  `api/analytics/services/analytics_engine.py:4207`, and for the same reason:
  dropping them makes the median look like the store's median when it is the
  median of the customers who bought something.
* **Lines whose quantity is zero or NULL.** `lines_without_quantity`, one
  number. It is 8 rows store-wide today, and a number that small is worth
  returning precisely because a future resync could make it large without
  anything else in the response changing.

### 7. `GET /api/analytics/customers/lifetime-items` in `api/analytics/routes/customers.py`

One route, returning §2 through §6's shape.

* **Declared above `/{customer_id}`, and added to the module docstring's route
  list.** This is not a style point: `api/analytics/routes/customers.py:13` says
  *"ROUTE ORDER MATTERS"* and `:273` is the path-parameter route. FastAPI
  matches in declaration order, so this literal registered after it would bind
  `customer_id="lifetime-items"` and 422 on int parsing, with nothing in the
  diff looking wrong. `api/analytics/routes/orders.py:28` records the same trap
  as its third instance.
* **`start` and `end` parse exactly as `/ltv` parses them**, including the
  one-year default window at `api/analytics/routes/customers.py:138` and the
  400 on a bad date, so this endpoint's refusals are identical to its
  neighbours'.
* **Additive only.** No existing route's response shape changes, `/customers/ltv`
  is not touched, and nothing is written.

## The test

`contracts/deadly-digital-platform-api.yaml` mandates exactly one new test file
and `new_test_bites.sh` proves it fails against the tree before the change.
Create

    api/tests/analytics/test_fleet_lifetime_items.py

which is the only creatable shape the contract allows —
`api/tests/analytics/test_fleet_*.py`. No existing test may be edited.

Build a fixture whose arithmetic is known by hand and assert on all of it:

* a customer with one order of one line carrying `quantity: 21` lands on
  **21 items and 1 line**, and the bucket they land in is keyed on 21 (§2) —
  this is the single assertion that fails against any line-counting
  implementation, and it is the point of the whole change;
* a customer whose first order is inside the window and whose later orders are
  outside it is counted on all of them (§1);
* a customer whose first order precedes the window is in no bucket and not in
  `customers_total`;
* a free-entry-only customer appears in `paid_orders` with zero items and in
  `all_orders` with their full count, and the two `items_total` figures differ by
  exactly the free quantity (§3);
* bucket counts sum to `customers_total` on both bases, and
  `mean_items_per_customer` computed by hand over the fixture (§4, §5);
* a customer above the top edge lands in the open-ended bucket, that bucket's
  `upper` is `null`, and `max_items` exceeds the top edge (§4);
* an order with no customer attached contributes to `orders_without_customer`
  and to no bucket, and a line with `quantity` NULL contributes 0 items, is
  counted in `lines`, and appears in `lines_without_quantity` (§6);
* the per-customer order count and lifetime spend that `/customers/ltv` reports
  for the same fixture and window are **unchanged** by this call — the assertion
  that catches the fan-out `_item_counts_cte` warns about (§1);
* `GET /api/analytics/customers/lifetime-items` resolves to this handler rather
  than to the customer-detail route (§7).

A test that asserts the endpoint returns 200 satisfies the bite check and
establishes nothing.

## What this does not do

**It carries no drift block, and that is a decision rather than an omission.**
`ltv_distribution` reads `customers.total_spent` against the orders and reports
the difference; candidate 4's draft does the same for `customers.order_count`.
There is no stored per-customer item count on `api/analytics/models.py` to read
against, so there is nothing to compare and inventing a column to compare with
would be a schema change nobody asked for. The docstring says so, because an
absent drift block on a report whose two neighbours have one otherwise reads as
an oversight.

**It does not change `item_count_distribution`.** That function chose lines for
a per-order report, said so, and is correct. This report says in its own
docstring that the two differ and why, and neither is edited to match the other.

**It does not add a cohort dimension.** *Customers by order count* is a **C** row
at `research/metorik-report-classification-2026-09-15.md:822`, blocked by the
cohort engine rather than by this report's absence.

**It does not draw anything.**
`platform/app/(dashboard)/analytics/customers/page.tsx` is the surface a merchant
would read this on; `platform/**` is protected under this contract, and the
frontend half is a second draft under `contracts/dd-analytics-frontend.yaml`,
written against the shipped response the way `drafts/order-filters-frontend.md`
was. Until it lands this feature reaches nobody, and that is stated here rather
than discovered later.

## Before this is queued

* **The two bases may be far apart, and that is the result rather than a
  problem.** 15,616 customers have placed a free entry and free-entry lines
  average 21.13 units. If `all_orders` and `paid_orders` diverge sharply at the
  top of the distribution, the store's biggest "buyers" are its biggest
  entrants, and §3 is what makes that visible on the first call instead of in a
  later contradiction. Both histograms stay correct either way.
* **The edges are a guess and are labelled one.** `ltv_distribution` ships
  `edges_are_a_guess: true` for exactly this reason; nobody has measured the
  distribution of lifetime units on this tenant, because no query has ever
  computed it. §5's percentiles are what the first reader should use to decide
  whether the edges want changing, and changing them later is a one-tuple diff.
* **This merges unattended.** `auto_merge: true` under this contract. Seven
  requirements are cited by seven added lines and that is the only reader this
  change gets.
