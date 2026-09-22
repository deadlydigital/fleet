# Draft spec — how many orders a customer makes over a lifetime, as a bucketed distribution

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Orders per customer over a lifetime — the number of customers at each order count, on the population the LTV report already defines
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/customers.py
```

## Why this is a code change and not an investigation

Nothing needs finding out. `research/metorik-report-classification-2026-09-15.md:812`
classifies *Orders made over customer lifetime* **A** — buildable on today's
schema — and states the whole of the derivation: *"A count per
`orders.customer_id` across 157,311 customers, bucketed. One `GROUP BY`, no
per-customer dimension to choose."* There is no absent column, no absent table,
and no modelling decision underneath it.

What the product cannot do is say anything about the shape of that count.
`research/metorik-report-classification-2026-09-15.md:806` lists `order_count`
among the eleven columns on `customers`, and
`research/candidates-metorik-gap-2026-09-21.md:462` records that DD ranks on it
and that `api/analytics/services/segment_engine.py` and
`api/analytics/services/churn_engine.py` read it — so a per-customer order
count is already a first-class figure here. Nothing buckets it. A merchant can
ask "who are my top customers" and cannot ask "how many of my customers ever
came back", which is the report.

## Both halves of this are already written, and neither of them is this

`research/candidates-metorik-gap-2026-09-21.md:82` puts it plainly:
*"`ltv_distribution` buckets money; `item_count_distribution` buckets lines per
order. Both are the pattern this row reuses, and neither is this row."*

* **The population half.** `_ltv_population_cte()` in
  `api/analytics/services/analytics_engine.py` settles what "a customer in this
  window" means — membership is the customer's *first* revenue-status order
  falling inside the window, and the lifetime measured for them is never
  clipped to it. `drafts/ltv-distribution-and-retention-curve.md` §1.2 is the
  argument: *"A 'lifetime' value windowed to a month is a monthly value with a
  misleading name."* That argument is about money and applies without
  alteration to a count.
* **The bucket half.** `item_count_distribution()` in
  `api/analytics/services/order_query.py:668`, served as `GET /orders/item-counts`
  from `api/analytics/routes/orders.py:357`, settled the cap at twenty buckets
  and the named `tail` object that says what the cap swallowed.
  `drafts/item-count-distribution.md` §4 is the argument: *"A truncated list
  that does not say it was truncated reads as a complete one."*

Reusing both is the point of taking this row now. The only decision left is the
one §3 makes, and it is forced by a number rather than chosen.

## Why `dd_api`, these two files, and this contract

The gap is an absent computation. `contracts/deadly-digital-platform-api.yaml`
makes `api/analytics/services/analytics_engine.py` and
`api/analytics/routes/customers.py` writable, and its verification — the
requirement citation check, compileall, ruff-no-new-findings, both pytest
suites, and one added test proven to fail without the change — is what can judge
a new aggregate. `contracts/dd-order-filters.yaml` is the other contract that
could cover a route change of this size; it permits no new test file at all, and
an arithmetic report that nothing asserts against a known fixture is exactly the
thing that ships wrong and stays wrong. So: the API contract, and the test it
mandates.

**No migration, and none is wanted.** The count is `COUNT(*)` over `orders`
grouped by customer, and `api/analytics/migrations/versions/v0014_orders_customer_created_index.py`
is already the index over orders by customer and creation time, which is the
access path this query seeks on. `api/analytics/migrations/versions/v0015_order_items_order_covering_index.py`
is not involved — this report does not touch `order_items`, and that is the
whole of the difference between it and candidate 7.

**No page.** `platform/app/(dashboard)/analytics/customers/page.tsx` is the
surface a merchant would read this on, it is protected under this contract, and
it is a second draft written against the shipped response the way
`drafts/order-filters-frontend.md` was. `drafts/ltv-distribution-and-retention-curve.md`
sets out at length why a two-link chain fails here —
`contracts/checks/spec_requirements_cited.py` gives every link the whole draft
and obliges each to cite every requirement in it — and nothing about that has
changed. Until the second draft lands, this feature reaches nobody, and that is
stated here rather than discovered later.

**Name it so the candidate retires itself.** The probes on
`research/candidates-metorik-gap-2026-09-21.md:495` look for
`orders_per_customer|order_count_distribution|orders-per-customer` in
`api/analytics/routes/customers.py` and `order_count_distribution|lifetime_order_count`
in `api/analytics/services/analytics_engine.py`, expecting zero of each today.
The names below are chosen to match, so the next sweep retires this row on the
tree rather than on a task status.
`research/candidates-metorik-gap-2026-09-21.md:42` is the reason that is worth a
sentence: *"A failed task row is not a claim that the work does not exist."*

## What to build

Seven requirements. Put `spec:<id>` on a line this change adds — a comment, a
docstring, or a test name — for each of `1` to `7`; see
`contracts/checks/spec_requirements_cited.py`, which runs first under
`contracts/deadly-digital-platform-api.yaml` and reads only added lines.

### 1. One grouped query in `api/analytics/services/analytics_engine.py`

Add `order_count_distribution()`: for one tenant and one window, how many
customers made each number of orders over their lifetime.

* **The population is `_ltv_population_cte()`'s, not a new one.** `start` and
  `end` select customers whose first revenue-status order falls inside the
  window. Inheriting it rather than re-spelling it is what makes this report and
  `GET /customers/ltv` describe the same people for the same arguments, and a
  fourth definition of "a customer in this window" is the thing the shared CTE
  exists to prevent.
* **The count is not clipped to the window.** A customer acquired inside it is
  counted on all of their orders, before and after. §1 of the LTV draft settled
  this and the docstring should say it is inherited rather than re-argue it.
* **Group in SQL, in one statement.** A CTE reducing to `(customer, order
  count)` and an outer `GROUP BY` over it. The population is 2,889,850 orders
  across 157,311 customers
  (`research/candidates-metorik-gap-2026-09-21.md:479`); counting in Python is
  not an option at that size.
* **The measure is revenue-status orders**, consistent with the population rule
  that admitted the customer. The all-status order total for the same population
  is reported once as a number (§4), not as a second distribution — the tree's
  rule is that both populations are named and never collapsed, and one named
  number satisfies it at a tenth of the cost.

### 2. Buckets are one per value up to twenty, and a value with nobody in it is present

`buckets` is a list of `{orders, customers}`, ascending by `orders`. `orders` is
the lifetime order count; `customers` is how many customers had exactly that
many. Ascending by the count, not by the population: the axis of a distribution
is its measure.

* **Every integer from 1 to the cap is present, with `customers: 0` where
  nobody landed.** A gap in a numeric axis reads as missing data, which is the
  point `drafts/ltv-distribution-and-retention-curve.md` §2.3 makes about empty
  histogram buckets. This differs from the `lines: 0` bucket in
  `drafts/item-count-distribution.md` §2 and the docstring should say why rather
  than leave the divergence to be read as an oversight.
* **There is no `orders: 0` bucket, and that is a property rather than an
  omission.** A customer enters the population by having a revenue-status order,
  so zero is unreachable by construction. Customers with none are counted in §5
  instead, where they are a fact about the population and not a bucket in the
  curve.

### 3. The tail is bucketed, because here the tail is where the store lives

`drafts/item-count-distribution.md` §4 capped buckets at twenty and folded the
rest into one `tail` object. Reuse the cap and the object; do **not** reuse the
single number inside it.

`research/candidates-metorik-gap-2026-09-21.md:479` measures 2,889,850 orders
over 157,311 distinct `customer_id` values — a mean near 18.4 — and says the
consequence in its own words: *"high enough that the interesting part of this
distribution is its tail and a naive twenty-bucket cap would fold most of the
population into it."* On lines per order the tail was a rounding error. Here it
may be the majority, and a report whose single summarising number is "most of
your customers are somewhere above twenty" has not answered the question it was
asked.

So `tail` carries:

* `min_orders` — the smallest count folded into it, which is the cap plus one;
* `customers` — how many customers are in it;
* `distinct_values` — how many distinct order counts it swallowed;
* `ranges` — the tail bucketed again at coarser, **fixed** edges, one entry per
  range carrying its lower edge, its upper edge, and its customer count. The
  final range is open-ended above and says so by carrying a null upper edge
  rather than a large number.
* The edges are **returned in the response**, not assumed by the reader, for
  the reason `drafts/ltv-distribution-and-retention-curve.md` §2.3 gives: a
  reader who has to know the implementation to read the payload will eventually
  guess wrong.

Fixed edges rather than quantiles, and this is the row's `unasked_question`
(`research/candidates-metorik-gap-2026-09-21.md:487`) being answered rather than
inherited: *"Whether the buckets should be fixed widths or quantiles ... nobody
has said which HIB would read."* Fixed, because a quantile bucket's edges move
with the window, so two windows produce two axes and the curves cannot be laid
over each other — which is the comparison the report exists to support. The
protection against a badly-chosen edge is §4's percentiles, which are scale-free
and cannot be made useless by a guess.

### 4. A summary that carries its own arithmetic

Beside the buckets, for the window:

* `customers_total` — every customer in the population. **It must equal the sum
  of `customers` across `buckets` plus the tail's `customers`.** An assertion a
  consumer can make, and the reason §3's tail is counted rather than shrugged
  at.
* `orders_total` — revenue-status orders summed over the population, and
  `orders_total_all_statuses` beside it. The gap between them is the §1 rule
  made visible in one subtraction.
* `mean_orders` — to two decimal places, derived from this aggregate rather
  than from a second query, with the docstring naming `customers_total` as its
  denominator.
* `percentiles` — p50, p75, p90, p95, p99. The mean of a long-tailed count is
  not a typical customer, and `research/candidates-metorik-gap-2026-09-21.md:465`
  says the store has only that mean today: *"the shape of the repeat-buying
  curve is the report and DD has only its mean."* Shipping the same mean in a
  new place would not be this row.
* `max_orders` — the largest count present, whether or not it is inside the cap.
* `one_order_customers` and `repeat_customers` — the first bucket and everything
  above it, named. This is the single number the report is usually read for, and
  making a consumer derive it from the list invites two surfaces to derive it
  differently.

### 5. Both excluded populations are named and counted

A distribution that silently drops rows reports the shape of what survived.

* **Orders carrying no customer.** `research/candidates-metorik-gap-2026-09-21.md:482`
  is explicit that 157,311 is a count of distinct values and **not** a coverage
  measure: *"No coverage ratio ... not a measure of how many orders carry a
  `customer_id`."* Nobody in this fleet has established how many orders in the
  window have no customer attached, or whether a guest order arrives with a null
  or with a zero. The response carries that count as `orders_without_customer`
  for the window, and the docstring states which of null and zero the query
  treats as "no customer" and that the other was checked. This is the one number
  in the change that nobody can predict, which is the reason to return it rather
  than to assume it is small.
* **Customers in the window with no revenue-status order.** They are outside the
  population by §1 and counted as `customers_without_revenue_order`. Dropping
  them silently makes the median look like the store's median when it is the
  median of the customers who bought something — `drafts/ltv-distribution-and-retention-curve.md`
  §1.4, for the same reason, on the same population.

### 6. `customers.order_count` is read against the orders, and never repaired

The stored column is the reason this report is worth building and is not the
source it is built from. `principles.md` is explicit: *"Read a field before
storing a derived copy of it. A stored value that looked obviously right has
twice turned out to mean something else."*

The response carries a drift block over the same population: how many customers
were compared, how many have a stored `order_count` differing from the computed
one, the largest absolute difference, and the signed difference of the two
totals. It is present with zeros when the column agrees everywhere — an absent
block reads as "not checked", and the difference between those two is the point.

**No `UPDATE`, no backfill, no write of any kind.** A column that turns out to
be wrong is a separate decision someone makes holding this report.
`specs/parked-platform-defects.md` §2 is the standing example of what happens
when a shipped figure and a stored column disagree and nothing says so: the
sources page's `average_ltv` still reads `customers.total_spent` while
`GET /customers/ltv` reads the orders, *"and neither surface says so"*. This
requirement is that sentence not being written again about `order_count` —
and it is deliberately not a proposal to change
`api/analytics/routes/sources.py`, which that file parks for reasons no task
under this contract can satisfy.

### 7. `GET /api/analytics/customers/orders-per-customer` in `api/analytics/routes/customers.py`

One route, returning §2 through §6's shape.

* **Declare it above any path-parameter route in the module.** FastAPI matches
  in declaration order, so a literal path registered after a `/{...}` route
  binds the segment as that parameter and fails on type coercion.
  `api/analytics/routes/orders.py` carries this trap in its own module docstring
  and `drafts/item-count-distribution.md` §5 had to pin it with a test; a
  customer-scoped module serving
  `platform/app/(dashboard)/analytics/customers/[id]/page.tsx` has such a route,
  so the same pin applies here rather than being hoped past.
* **`start` and `end` on the same terms as the routes already in the file**,
  using that module's existing range parsing and its existing validation, in the
  order it already calls them. Inheriting the refusals is what keeps this
  endpoint's 400s identical to its neighbours'.
* **Additive only.** No existing route's response changes shape, and
  `GET /customers/ltv` is not touched.

## The test

`contracts/deadly-digital-platform-api.yaml` mandates exactly one new test file
and `new_test_bites.sh` proves it fails against the tree before the change.
Create

    api/tests/analytics/test_fleet_lifetime_order_counts.py

which is the only creatable shape the contract allows —
`api/tests/analytics/test_fleet_*.py`. The test budget is 300 lines and is
separate from the 400 production lines. No existing test may be edited.

Build a fixture whose arithmetic is known by hand and assert on all of it:

* customers with 1, 1, 2 and 5 lifetime orders → `customers` of 2, 1, 0, 0, 1 in
  the `orders` 1 to 5 buckets, in that order, with the `orders: 3` and
  `orders: 4` buckets **present** and zero (§2);
* a customer whose first order is inside the window and whose later orders are
  outside it is counted on all of them (§1) — this is the assertion a
  window-clipped query fails, and it is the one requirement here that is
  inherited rather than invented;
* a customer whose first order precedes the window is absent from every bucket
  and from `customers_total`;
* buckets plus tail equals `customers_total`, and `mean_orders` computed by hand
  over that fixture (§4);
* more than twenty distinct counts → exactly twenty buckets, a `tail` whose
  `distinct_values` is the remainder, `ranges` summing to the tail's
  `customers`, and `max_orders` above the cap (§3);
* an order with no customer attached is in `orders_without_customer` and in no
  bucket (§5);
* a fixture where `customers.order_count` deliberately disagrees with the orders
  → a populated drift block, and the stored column unchanged after the call
  (§6);
* `GET /api/analytics/customers/orders-per-customer` resolves to this handler
  rather than to the customer-detail route (§7).

A test that asserts the endpoint returns 200 satisfies the bite check and
establishes nothing.

## What this does not do

**It does not bucket `customers.order_count`.** That would be one `GROUP BY` and
the whole report, cheaply — and it would be a distribution of a stored derived
column that nobody has ever read against its source. §6 exists because building
the report from `orders` costs almost nothing extra here and turns an unchecked
column into a measured one.

**It does not count items.** *Items bought over customer lifetime*
(`research/metorik-report-classification-2026-09-15.md:815`) is candidate 7 and
is the same query with a join to `order_items` and a lines-versus-units decision
attached, which `drafts/item-count-distribution.md` §3 had to spend a whole
requirement on. Taking this row first is deliberate: it settles the population,
the cap and the tail convention for a count, and candidate 7 then inherits three
decisions instead of making them again.

**It does not produce a cohort matrix.** *Customers by order count* is a **C**
row at `research/metorik-report-classification-2026-09-15.md:822` — the same
count cohorted by acquisition month — and it is blocked by the cohort engine
rather than by this report's absence.

**It does not draw anything and it does not add a time series.** One window, one
distribution, one route. The surface is a second draft under
`contracts/dd-analytics-frontend.yaml`, which can typecheck and render-test it.

## Before this is queued

* **`orders_without_customer` may be a large number and that is a result.** If a
  substantial share of orders carry no customer, then the mean of 18.4 that this
  row's signal rests on is an artefact of dividing all orders by the customers
  who have one, and §3's cap is calibrated against a figure that does not mean
  what it appears to. §5 is what makes that visible on the first call instead of
  in a later contradiction; the buckets stay correct either way, because they are
  computed over a population defined by orders that do have a customer.
* **This merges unattended.** `auto_merge: true` under this contract, and
  `contracts/deadly-digital-platform-api.yaml` says in its own comments that a
  dd_api task implementing four of five numbered requirements merges with every
  check green and nobody reading the spec. Seven requirements are cited by
  seven added lines and that is the only reader this change gets.
