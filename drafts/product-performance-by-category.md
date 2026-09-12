# Draft spec — group product performance by the categories the sync already writes

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Group product performance by the categories the sync already writes, on the products endpoint
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/products.py
```

## Why this is a code change and not an investigation

There is nothing left to find out. The table exists, the writer fills it, the
index was built for this exact read, and no reader was ever written.

`api/analytics/migrations/versions/v0008_product_categories.py` created
`product_categories (product_id, category)` with a composite primary key and
`ix_product_categories_category`, and said in its own comment why the index is
on `category` rather than on `product_id`: *"Reporting reads this the other way
round — 'revenue by category' scans by category, not by product."* The reporting
it was built for does not exist.

`_write_product_categories()` in `api/analytics/services/sync_engine.py` fills it
on every products batch, and it is careful work rather than a stub: it replaces
each synced product's category set wholesale (`DELETE` then `INSERT`, scoped to
the products in the batch), de-duplicates while preserving order, and skips
products whose payload did not carry the `categories` key at all, so a connector
that has not shipped v3 leaves existing rows alone rather than deleting them.
`api/analytics/models.py:171-190` declares the table and the index, and
`api/analytics/models.py:159-163` marks `products.category` display-only with the
sentence *"Reporting joins product_categories instead."*

And it does not. The string `categor` does not appear anywhere under
`api/analytics/routes/`, in any file, and `product_categories` does not appear in
`api/analytics/services/analytics_engine.py` at all. `specs/metorik-gap.md:103`
records the row as **Partial** with the same finding: *"`analytics_2.product_categories`
and `products.category` exist, and no endpoint groups by them."*

So the deliverable is a query in the service that already computes product
performance, and a third endpoint on the router that already serves it. Nothing
here needs measuring first.

## Why this is a breakdown on the products endpoint, and not a categories page

The finding this is re-scoped from named
`api/analytics/migrations/versions/v0008_product_categories.py` as a file to
edit. It is not one. It is on the protected floor under every contract in
`contracts/`, and `api/analytics/migrations/**` is protected under
`contracts/deadly-digital-platform-api.yaml` specifically. The migration is the
**evidence** that this work is wanted and that the schema for it already landed.
The table is already created, already indexed, already populated. No schema
change is required and none is permitted.

`api/analytics/routes/products.py` already serves `/products` and
`/products/acquiring`, and `platform/app/(dashboard)/analytics/products/page.tsx`
already exists with `platform/app/api/analytics/products/route.ts` proxying to it.
A third breakdown on that router lands on a surface an agency can already reach.
A `/analytics/categories` page would need `platform/**`, which is protected under
this contract and under the platform floor — no dd_api task can write it, so a
spec that asked for one would be asking for a refusal.

**This task is the API half only.** The page that renders the breakdown is a
separate `dd_frontend` task under `contracts/dd-analytics-frontend.yaml`, and it
is not in scope here. Do not touch `platform/`.

## The join, and the three ways to get it wrong

`order_items` carries `wc_product_id` (the WooCommerce id), not
`products.id`. `product_categories.product_id` references `products.id`. So the
join is three hops:

    order_items.wc_product_id  →  products.wc_product_id  →  products.id
                                                          →  product_categories.product_id

`products.wc_product_id` is unique (`api/analytics/models.py:155`), and the order
ingest upserts a narrow `products` row for every item it sees
(`api/analytics/services/sync_engine.py`, step 5), so a product that has been
ordered has a `products` row even if the catalogue sync never ran. What it will
not have in that case is any `product_categories` row — which is exactly the
population §2 has to be able to report.

Three failure modes follow from that, and each is a numbered requirement below
rather than a note, because each one produces a plausible-looking wrong number:

1. **An inner join silently drops uncategorised revenue.** The table fills from
   new syncs only — the migration refuses to backfill, on the grounds that
   splitting the flattened string would invent categories. On a tenant that has
   not re-synced its catalogue the table is **empty**, and an inner join returns
   an empty list that reads as "this store sold nothing".
2. **Category revenue does not sum to total revenue, and never will.** The
   migration measured ~98% of categorised products carrying more than one
   category. A product in three categories contributes its full revenue to all
   three. Any consumer that adds the rows up gets a number two to three times the
   truth unless the response says so.
3. **Grouping `products.category` instead.** That column is the comma-joined
   string, and the migration measured it producing **70 distinct strings** for a
   handful of real categories — buckets like
   `'Car Competitions, Closed Competitions, Featured Competitions, SUV'`. It is
   display-only. Do not group by it, do not split it, do not fall back to it.

## What to build

Five requirements. Put `spec:<id>` on a line this change adds — a comment, a
docstring, or a test name — for each of `1`, `2`, `3`, `4` and `5`; see
`contracts/checks/spec_requirements_cited.py`, which runs first under
`contracts/deadly-digital-platform-api.yaml` and reads only added lines.

### 1. A category report in `api/analytics/services/analytics_engine.py`

Add one function beside `product_report()` (`api/analytics/services/analytics_engine.py:1396`)
that takes a tenant, a bounded date range, a sort key and a limit, and returns
revenue and units grouped by category.

Constraints on the query:

* **Reuse the scope `product_report()` already uses.** The same
  `range_predicate("o.created_at")`, the same `_REVENUE_STATUSES`, the same
  `schema_exists()` guard returning empty rather than raising, the same
  `analytics_schema_name()`. Do not introduce a second notion of which orders
  count. A category breakdown whose totals disagree with the product report
  above it on the same page is worse than no breakdown.
* **Aggregate in SQL, one grouped query.** Not a product-level fetch followed by
  a Python regroup. The category index exists for this.
* **Per category, return at minimum**: `category`, `revenue`
  (`SUM(order_items.total)`), `quantity` (`SUM(order_items.quantity)`),
  `orders` (`COUNT(DISTINCT orders.id)`), `products` (count of distinct
  `wc_product_id` sold in that category in the window). The product count is
  what lets a reader tell one big seller from a broad category.
* **Sort and limit the same way `/products` does** — `revenue` or `quantity`,
  descending, with the sort key validated against a literal set rather than
  interpolated from the request.

### 2. Uncategorised revenue is a row, not a silence

Left-join, never inner-join. Every order item in scope must reach the aggregate.
Items whose product has no row in `product_categories` are reported as a single
distinct bucket with an explicit marker — a `category` of `null` with a boolean
flag, or a separate top-level key. **Not** an empty-string category, which sorts
into the list and reads as a real category named nothing.

This is the majority case today, not an edge case, and the migration says why:
the table fills from new syncs only and is *"Empty on arrival everywhere"*. A
store that has not re-synced its catalogue since migration 0008 has all of its
revenue in this bucket, and the report must say that in those words rather than
returning nothing.

### 3. State the overlap rather than hiding it

The response carries a coverage block, computed over the same window and the
same status scope, that lets a reader check the arithmetic without a second
request:

* `revenue_total` — total revenue over all order items in scope, counted once
  per item. This is the figure the per-category rows do **not** sum to.
* `revenue_categorised` / `revenue_uncategorised` — counted once per item, split
  by whether the product has any category at all. These two **do** sum to
  `revenue_total`.
* `categories_total` — how many distinct categories exist in the window, against
  `categories_returned`, so a `limit`-truncated ranking is visibly truncated.
* `multi_category_products` — distinct products in the window carrying more than
  one category. This is the size of the double count, and it is the number that
  makes the difference between `revenue_total` and the sum of the rows legible
  rather than alarming.

`api/analytics/routes/products.py:88-103` is the precedent and the convention to
follow: `/products/acquiring` returns `coverage` and `truncation` blocks with the
comment *"No silent caps"*, precisely because a ranking whose parts do not sum to
the whole is a broken report unless it says why. This report has the same
property for a different reason, and needs the same treatment.

### 4. "No category data" and "no sales" must not look alike

Both produce an empty or near-empty ranking and they mean opposite things. The
response must distinguish them with a field a consumer can branch on — whether
`product_categories` holds any rows at all for this tenant, independent of the
window.

Zero rows in the table means the catalogue has not been synced since migration
0008 and the report cannot be produced yet. Rows in the table and no revenue in
the window means the store sold nothing in those dates. The frontend task that
follows this one has to render those two differently, and it cannot if the API
collapses them.

### 5. `GET /products/categories` in `api/analytics/routes/products.py`

A third endpoint on the existing router, taking `start`, `end`, `sort_by` and
`limit`, validated exactly as `get_products()` validates them
(`api/analytics/routes/products.py:31-51`): the same `_VALID_SORT` membership
check, the same `date.fromisoformat` parse with a 400 on `ValueError`, the same
30-day default window, the same `subscription_required` dependency. Do not invent
a second date-parsing convention in a module that already has one.

Two constraints:

* **Declare it after `/products/acquiring`** and update the module docstring's
  route list. The docstring at `api/analytics/routes/products.py:1-10` records
  that `/products/acquiring` is a literal with no `/products/{id}` able to shadow
  it, and that any future route must respect that order. `/products/categories`
  is another literal, so nothing shadows anything — but the docstring is the
  place that fact is written down, and leaving it listing two routes when the
  module serves three is how the next person gets it wrong.
* **Do not change `/products` or `product_report()`.** Its response
  (`{data, total, sort_by}`) is consumed by
  `platform/app/(dashboard)/analytics/products/page.tsx` through
  `platform/app/api/analytics/products/route.ts`, and the frontend is protected
  under this contract, so a shape change here breaks a surface this task cannot
  repair.

## The test

`contracts/deadly-digital-platform-api.yaml` requires exactly one new test file
and proves it bites: `contracts/checks/new_test_bites.sh` runs it against the
tree before the change and the tree after, and a test that passes on both is
refused. Create

    api/tests/analytics/test_fleet_product_categories.py

which is the only creatable shape the contract allows — `test_fleet_*.py` under
`api/tests/analytics`. Budget is 300 lines for it, separate from the 400
production lines. `api/tests/analytics/test_sync_engine.py` is the neighbour to
read for fixture conventions — it already writes and asserts on
`product_categories` rows directly — and it must not be edited, nor must
`api/tests/analytics/test_analytics_engine.py`.

The fixture has to make the multi-category case real, because that is where every
plausible wrong implementation differs from a right one:

* a product in **two** categories, sold once → its full revenue appears under
  **both**, `revenue_total` counts it **once**, and `multi_category_products` is
  1. A test that only uses single-category products passes against an
  implementation that double-counts `revenue_total`, and is the specific failure
  §3 exists to prevent;
* a product with **no** `product_categories` row but with order items in the
  window → present in the uncategorised bucket, absent from every named category,
  and its revenue inside `revenue_uncategorised`. This is the assertion an inner
  join fails, and it is §2;
* `revenue_categorised + revenue_uncategorised == revenue_total`, asserted
  directly, with at least one of each present so neither side is trivially zero;
* an order **outside** the window, and an order inside it with a non-revenue
  status → neither reaches any bucket. This is what pins §1's reuse of
  `_REVENUE_STATUSES` and `range_predicate`;
* a tenant schema with **zero** rows in `product_categories` but non-zero
  revenue → §4's flag says the catalogue has not been synced, and the response is
  not an empty list indistinguishable from a dead store;
* more distinct categories than `limit` → `categories_returned < categories_total`
  and the truncation is visible in the response.

## What this does not do, stated so nobody reads it as doing it

**It does not touch the migration.** `api/analytics/migrations/**` is protected
under this contract, the table and its index already exist, and nothing here
wants a column. If the grouped query turns out to need an index
`product_categories` does not have, that is a separate measured proposal with a
timing in it — not something to slip into this diff. Note before reaching for
one: `ix_product_categories_category` is already there, and it was built for this
query.

**It does not backfill anything, and it must not try.** The migration's refusal
to split `products.category` back into an array is a decision, not an omission,
and its reasoning is in the file: a category *named* `"Toys, Games"` is
indistinguishable from two categories `"Toys"` and `"Games"` once joined. An
implementation that falls back to splitting that column when
`product_categories` is empty would invent categories that never existed. §4
exists so the report can say "no data" instead.

**It does not change the sync.** `api/analytics/services/sync_engine.py` is
writable under this contract and there is no reason to open it. The writer is
correct: it replaces category sets wholesale, skips products the store did not
mention, and distinguishes an absent `categories` key from an empty array. This
task reads what it writes.

**It does not add vendor or brand.** `specs/metorik-gap.md:103` names *"category
/ vendor / brand"* together and only category has a table. There is no vendor or
brand column anywhere in `products` (`api/analytics/models.py:150-168`), so those
two need the connector to send something it does not currently send. That is a
different task with a payload change in it, and closing this row to **Partial —
category only** is the honest outcome here.

**It does not build the page.** `platform/**` is protected under this contract
and under the platform floor. The breakdown becomes reachable when the
`dd_frontend` task that follows renders it on
`platform/app/(dashboard)/analytics/products/page.tsx`; until then this is an
endpoint an agency can call and not a report an agency can see. Queue that task
against `contracts/dd-analytics-frontend.yaml`, which sets `auto_merge: false`,
so a person reads the spec against the diff.
