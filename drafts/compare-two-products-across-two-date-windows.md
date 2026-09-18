# Draft spec — compare two products across two date windows

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Compare two products across two date windows on the products endpoint
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/products.py
```

## Why this is a code change and not an investigation

The measure was the only open question and it is answered. The candidate says
the measure must be `order_items.total` because `sku` and `price` are NULL on
every line row, and
`research/metorik-report-classification-2026-09-15.md:836` is the measurement
that establishes it: `order_items.price` and `sku` NULL on all 4,549,662 lines,
`product_name` set on all of them over 3,743 distinct `wc_product_id`. The same
document measures `order_items.total` NOT NULL on all 4,550,334 rows and
non-zero on 97.8% of them
(`research/metorik-report-classification-2026-09-15.md:443`), so the column that
has to carry the comparison is populated and the columns that cannot carry it
are empty. Nothing else needs measuring first.

The rollup exists too. `product_report` in
`api/analytics/services/analytics_engine.py` already groups `order_items`
joined to `orders` by product and returns revenue, units and order counts for
one window; `GET /products` serves it from `api/analytics/routes/products.py`.
This task asks that rollup the same question four times — two products, two
windows — and returns the four cells and the differences between them.

`specs/metorik-gap.md:94` records what exists today and it is not this:
*"`dashboard_overview()` compares the window to the equal-length window
immediately before it — a genuine like-for-like, but the only comparison there
is. No arbitrary range and no YoY."* That comparison is over the whole store,
not over a product, and its second window is derived rather than chosen. Two
chosen products over two chosen windows exists nowhere.

## Why this is the API half, and why it has to come first

The candidate is right that most of the eventual work is UI — two product
pickers, two date pickers, a side-by-side. **It cannot be built first.**
`platform/**` is protected under `contracts/deadly-digital-platform-api.yaml`,
and `api/**` is protected under both `contracts/dd-analytics-frontend.yaml` and
`contracts/dd-acquiring-page.yaml`. No single contract lets one task write both
halves, so the split is forced; and of the two halves only this one can be built
against a tree that already has what it needs. A frontend task queued first
would have two pickers and nothing to call.

So: **this task is the endpoint only. Do not touch `platform/`.** The page is a
separate `dd_frontend` task against `contracts/dd-acquiring-page.yaml`, whose
writable set is exactly the products pages and their proxy, and which sets
`auto_merge: false` so a person reads that spec against that diff. It is not in
scope here and this spec does not describe it.

## Why this contract

Two contracts in `contracts/` cover `api/analytics/routes/products.py`:
`contracts/dd-docstring-proving.yaml` and
`contracts/deadly-digital-platform-api.yaml`. Only the second covers
`api/analytics/services/analytics_engine.py` — the first protects
`api/analytics/services/**` entirely and caps the diff at 30 lines, because it
is for proving docstrings and not for adding queries. A new aggregate cannot be
written under it at all.

`contracts/deadly-digital-platform-api.yaml` is named with its cost stated: it
makes twenty-seven files writable where this needs two, and it sets
`auto_merge: true`, so nobody reads this spec against the diff. What it buys is
the thing that matters here — one new `api/tests/analytics/test_fleet_*.py` is
creatable and `contracts/checks/new_test_bites.sh` proves the added test fails
against the tree before the change. Every claim below about a zero cell, an
undefined delta or an overlapping window is exactly the kind a contract with no
test gate cannot check.

Because nobody reads the spec, `contracts/checks/spec_requirements_cited.py`
runs first and obliges the diff to cite each of `spec:1` through `spec:5` on a
line this change adds — a comment, a docstring or a test name.

## The four cells, and the four ways to get them wrong

The unit of the answer is a cell: one product, one window, one set of measures.
Two products times two windows is four cells, always four, and each of the
following produces a plausible-looking wrong one.

1. **A `GROUP BY` returns no row for a product that sold nothing.** The cell
   then renders as a hole, and a hole reads as "no data" when it means "sold
   nothing". Zero sales is the most interesting result a comparison can have and
   it is the one a grouped query silently deletes.
2. **Grouping by `(wc_product_id, product_name)`.** `product_report` does, and
   for a ranking that is defensible — a product renamed inside the window
   produces two rows and the page shows what the data says. For a comparison it
   is wrong: the product compares against half of itself, and the halves land in
   different windows if the rename happened between them.
3. **Windows of different lengths compared as though they were not.** 7 days
   against 30 days shows a fall in revenue for a product that is selling
   better. `dashboard_overview()` cannot have this bug because it derives its
   second window at equal length; this endpoint takes both from the caller and
   can.
4. **Percent change from a base of zero.** Nothing divided into something is not
   0, not 100, and not infinity. A product that sold nothing in window A and
   £4,000 in window B has an undefined percent change and a perfectly defined
   absolute one.

## What to build

Five requirements.

### 1. `compare_products()` in `api/analytics/services/analytics_engine.py`

Add one function beside `product_report`, taking a tenant, two product ids and
two bounded date ranges, and returning the four cells.

* **Reuse the population `product_report` already uses**, without forking it:
  the same `_REVENUE_STATUSES`, the same `range_predicate`/`range_params`
  convention from `api/analytics/services/date_range.py`, the same
  `schema_exists()` guard returning an empty result rather than raising, the
  same `analytics_schema_name()`. A comparison whose totals disagree with the
  `/products` ranking on the same page for the same dates is worse than no
  comparison.
* **One statement, not four.** Both products and both windows in a single
  grouped query over `order_items` joined to `orders` — the two product ids as a
  bound `IN` list, the two windows as separate predicates with distinct bound
  parameter names. `range_predicate` names its bounds `:start` and `:end_plus`
  and this query needs two pairs, so bind two pairs; derive each `end_plus` the
  way `api/analytics/services/date_range.py` derives it — the inclusive `end`
  plus one day — rather than writing a second date convention into a module
  that has one. An order placed at 23:30 on the end date is inside the window.
* **Per cell return at minimum** `revenue` (`SUM(order_items.total)`),
  `quantity` (`SUM(order_items.quantity)`) and `orders`
  (`COUNT(DISTINCT orders.id)`). `order_items.total` is the measure and the
  reason is in the evidence above: `price` and `sku` are NULL on every line row,
  so no other column can be.
* **Never interpolate a product id or a date into the SQL string.** They are
  bound parameters; the schema name is the only thing in the statement that is
  interpolated, as it already is everywhere else in this module.

### 2. Four cells always, keyed on `wc_product_id` alone

Materialise the grid in Python from whatever rows the statement returns: for
each of the two product ids and each of the two windows, a cell exists. A
product with no revenue-status line items in a window is `revenue` 0,
`quantity` 0, `orders` 0 — a row, not an absence. This is §1 of the failure list
and it is the assertion that separates this from a `GROUP BY` handed straight to
the caller.

The key is `wc_product_id` and nothing else. `product_name` is resolved for
display, not grouped on: pick it deterministically — the name on the
highest-revenue line for that product across both windows, ties broken by the
most recent `orders.created_at` — and return it once per product rather than
once per cell. If the name differs between the two windows, say so with a
field a reader can see; do not pick one silently and do not emit two products.
This is §2 of the failure list.

A product id with no row in `products` at all is a caller error and not an empty
comparison: 404, with the offending id in the message. A product id that exists
and sold nothing in either window is four zeroes and a 200. The two are
different answers and the endpoint must not collapse them.

### 3. Deltas, and the zero base

For each measure, return window B relative to window A:

* `absolute` — B minus A. Always defined, including when A is 0.
* `percent` — `(B - A) / A`, and **`null` when A is 0**. Not 0, not 100, not a
  sentinel, not an exception. This is §4 of the failure list and it is the
  single most likely wrong number in the whole feature, because the zero base is
  the case a comparison is most often opened to look at.

Compute the deltas server-side rather than leaving them to the page. The reason
is not convenience: the rounding, the zero rule and the direction of the
subtraction are the semantics of the comparison, and a second implementation of
them in TypeScript is a second place for them to differ. The frontend task that
follows renders these; it does not derive them.

### 4. A window block that makes the comparison legible

The response carries, per window, the `start` and `end` it was asked for and the
number of days it spans, and a flag for whether the two windows are the same
length. `api/analytics/routes/products.py` already returns `coverage` and
`truncation` blocks on `/products/acquiring` under the comment *"No silent
caps"*, and this is the same convention for the same reason: a number whose
basis is not stated beside it gets read against the wrong basis. This is §3 of
the failure list.

Overlapping windows are legal and are counted independently. If the two windows
overlap — or are identical — an order inside the overlap counts in both cells,
once each. Nothing is deduplicated across windows, because the windows are two
separate questions and not a partition. Identical windows are a legitimate
request that returns identical cells and zero deltas, and they must not be
special-cased into an error.

Comparing a product with itself over two windows is also legal and must not be
refused. It is the "how did this product do this month against last month"
question, it falls out of the same query and the same response shape, and
rejecting it would mean writing code to forbid something that already works.

### 5. `GET /products/compare` in `api/analytics/routes/products.py`

A further endpoint on the existing router, taking two product ids and two
`start`/`end` pairs.

* **Call the module's existing `_parse_window` helper, once per window.** It is
  already there in `api/analytics/routes/products.py` and already carries the
  `_VALID_SORT` membership check, the `date.fromisoformat` parse and the
  `Invalid date format. Use YYYY-MM-DD.` 400 that the other routes use; take the
  same `subscription_required` dependency they take. Do not write a second date
  parser into a router that has one, and do not adopt the convention in
  `api/analytics/routes/orders.py`, which refuses one bound without the other —
  a third convention in one module is how a page and its own comparison come to
  disagree about which days they covered.
* **Both windows are required.** Unlike `/products`, there is no sensible
  default second window — deriving one would rebuild `dashboard_overview()`'s
  behaviour under a name that promises the caller chose it. Missing bounds are a
  400, not a guess. Reject an `end` before its `start` with a 400 rather than
  returning an empty window that reads as no sales.
* **Declare it after `/products/acquiring`** and update the module docstring's
  route list. The router already serves four routes — `/products`,
  `/products/acquiring`, `/products/categories` and `/products/export` — and the
  docstring records that the literals must be declared before any
  `/products/{id}` that could shadow them. `/products/compare` is a fifth
  literal, so nothing shadows anything; but the docstring is where that fact is
  written down, and leaving it listing fewer routes than the module serves is
  how the next person gets it wrong.

## What must not change

**The four routes this module already serves, and their response shapes.**
`/products`, `/products/acquiring`, `/products/categories` and
`/products/export` are consumed by
`platform/app/(dashboard)/analytics/products/page.tsx` and
`platform/app/(dashboard)/analytics/products/acquiring/page.tsx`, both protected
under this contract, so a shape change here breaks a surface this task cannot
repair. Add; do not edit.

**The schema.** No new column, no migration, no index.
`api/analytics/migrations/**` is protected under this contract and nothing here
wants a column — the comparison reads `order_items.total`, `quantity`,
`order_id`, `wc_product_id` and `product_name`, and `orders.id`, `created_at`
and `status`, all of which exist and are declared in `api/analytics/models.py`.
If this query turns out to want an index `order_items` does not have, that is a
separate measured proposal with a timing in it, and
`research/top-products-index-pricing.md` is the shape such a proposal takes.
Note before reaching for one: this statement is bounded to two product ids,
which is a far smaller read than the unbounded ranking that document prices.

**`products.category` and `product_categories`.** This comparison is between two
products and does not group by anything. The category report is separate work
that has already landed.

## The test

Create

    api/tests/analytics/test_fleet_product_compare.py

which is the only creatable shape `contracts/deadly-digital-platform-api.yaml`
allows — one added `test_fleet_*.py` under `api/tests/analytics`, never a
modification to an existing test.
`contracts/checks/new_test_bites.sh` runs it against the tree before the change
and refuses it if it passes there. Budget is 300 lines, separate from the 400
production lines. Read `api/tests/analytics/test_analytics_engine.py` for
fixture conventions and do not edit it.

The fixture has to contain the cases where a wrong implementation and a right
one differ:

* a product with sales in window A and **none** in window B → four cells
  present, B's are `0`, and `percent` is `-100`. A grouped query handed straight
  back omits that cell entirely, and this is the assertion that catches it;
* a product with **no** sales in window A and sales in window B → `absolute` is
  positive and `percent` is **`null`**. Assert `is None`, not falsiness: `0`
  passes a truthiness check and is the wrong answer;
* a product **renamed** between the two windows → one product in the response,
  not two, with both names visible and the resolved name deterministic across
  repeated calls;
* **overlapping** windows with an order inside the overlap → it is counted in
  both cells. Assert the two cells' revenue, not their sum, so an implementation
  that deduplicates fails;
* **identical** windows → equal cells, `absolute` 0, `percent` 0 — and a 200,
  which pins that identical windows are not an error;
* windows of **unequal length**, 7 days against 30 → the day counts are in the
  response and the equal-length flag is false;
* an order on the **end date at 23:30** → inside the window. This is what pins
  the inclusive-end convention rather than an exclusive one;
* an order inside a window with a **non-revenue status** → in no cell. This pins
  §1's reuse of `_REVENUE_STATUSES` rather than a fresh status list;
* a product id with **no `products` row** → 404, distinct from the known-product
  four-zeroes case, which is asserted in the same test as a 200.

## What this does not do, stated so nobody reads it as doing it

**It does not build the page.** Until the `dd_frontend` task lands this is an
endpoint an agency can call and not a comparison an agency can see. Queue that
task against `contracts/dd-acquiring-page.yaml`.

**It does not add a product catalogue endpoint.** Two pickers need a list of
products to pick from, and `/products` supplies one only for a window it is
given. That is a real question for the frontend task — a wide default window
populates the pickers from data that exists — and it is not a reason to add a
catalogue endpoint here, because no measurement says a ranking over a wide
window is insufficient. If it proves insufficient, that is its own proposal.

**It does not compare categories.** The classification document files category
comparison as its own row with its own blocker —
`research/metorik-report-classification-2026-09-15.md:865`, *"Same shape through
`product_categories`, whose population the pack could not see."* Same shape is
not the same task, and its population is unmeasured where this one's is
measured. Closing the product-comparison row and leaving the category row open
is the honest outcome here.

**It does not do year-on-year as a named feature.** Two arbitrary windows can
express a year-on-year comparison and the caller is free to ask for one; nothing
in this endpoint computes last year's dates, and a `yoy: true` parameter would
be a second date convention in the same router. `specs/metorik-gap.md:94` names
YoY beside arbitrary-range comparison, and arbitrary range is the general case
that answers both.
