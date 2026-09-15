# Draft spec — a CSV export of the product performance report

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Export the product performance report as CSV, on the revenue-status population the report already uses
writable_paths:
  - api/analytics/routes/products.py
  - api/analytics/services/analytics_engine.py
```

## The gap, read from the tree

`text/csv` appears exactly twice under `api/analytics/routes/`: the segment
export in `api/analytics/routes/segments.py`, and `export_orders` in
`api/analytics/routes/orders.py`, which shipped on 14 September. The Daily row of
`specs/metorik-gap.md` names orders, customers **and** products; products is the
one with a report already built and no way to get it out.

`get_products` in `api/analytics/routes/products.py` declares
`limit: int = Query(20, ge=1, le=100)`, so a merchant can see the top hundred
products of a window and the rest exist only inside the database.
`product_report` in `api/analytics/services/analytics_engine.py` already returns
the complete row — `wc_product_id`, `name`, `revenue`, `quantity`, `orders`,
`unique_customers` — so the export needs no new arithmetic and no new join. It
needs the shape `api/analytics/services/order_query.py` worked out one module
over: a row cap that refuses rather than truncates, a header written before
anything can return early, and a `StreamingResponse` carrying a
`Content-Disposition`.

**Products rather than customers, and the choice was close.**
`api/analytics/routes/customers.py` has no list query to export: `/customers`
returns metrics over time and `/customers/top` returns a ranking of at most 100
rows built for a leaderboard. A customer export is a new query and a new
population argument; this one is a report that already exists escaping a
`LIMIT`.

## The one thing this spec settles rather than leaves to be discovered

**The export's population is `product_report`'s population: orders with
`status IN ('completed', 'processing')`, inside `range_predicate("o.created_at")`
for the requested window.** It is not all-status, it does not gain a `status`
parameter, and it must not become all-status on the way out of the same module.

That is not a hypothetical drift. `api/analytics/services/order_query.py` lists
orders on an **all-status** population, deliberately, and names both counts in
its summary for that reason — so an agent copying the order export's shape into a
product export is copying it across a population boundary. A product ranking is
a revenue report: a cancelled order's line items are not sales, and a file that
included them would disagree with the page it was downloaded from while looking
correct. Requirement 5 turns this into an assertion rather than a comment.

## Why `deadly-digital-platform-api.yaml`

`contracts/dd-order-filters.yaml` is the other dd_api contract on this repo and
it cannot be used here: it makes exactly `api/analytics/routes/orders.py` and
`api/analytics/services/order_query.py` writable, neither of which this work
touches, and its third check is an acceptance check written for a different
task's requirements.

`contracts/deadly-digital-platform-api.yaml` is named with its cost stated: it
makes twenty-seven files writable where this needs two. What it buys is the only
thing that makes an export trustworthy — one new
`api/tests/analytics/test_fleet_*.py` is creatable, and
`contracts/checks/new_test_bites.sh` proves the added test fails against the tree
before the change. The claim in the section above is exactly the kind a contract
forbidding tests cannot check.

That contract also sets `auto_merge: true`, so nobody reads this spec against the
diff. The requirements are numbered below and
`contracts/checks/spec_requirements_cited.py` obliges the diff to cite each of
`spec:1` through `spec:5` on an added line.

## Requirements

### 1. One window-and-sort parse in `api/analytics/routes/products.py`, used by all three routes

`get_products` and `get_product_categories` already carry the same four lines
twice — the `_VALID_SORT` membership check, `date.fromisoformat`, and the default
window of `end = date.today()` with `start = end - timedelta(days=30)` — under a
docstring saying the second one validates "exactly as `get_products()` validates
them". A third copy is how a page and its own export come to disagree about which
days they covered.

Extract a module-private helper returning `(start_date, end_date)` and raising
the existing 400s verbatim — `sort_by must be one of: …` and `Invalid date
format. Use YYYY-MM-DD.` — and call it from all three routes. Both existing
messages and both existing status codes stay byte-identical; this is an
extraction, not a correction.

Note what is **not** adopted: `_parse_range` in `api/analytics/routes/orders.py`
refuses one bound without the other, and this module accepts `end` alone and
defaults `start` 30 days back. That is this module's existing contract on a
shipped endpoint and the export inherits it, so an export with no parameters
covers the same window as the page with no parameters.

### 2. `export_products_csv` in `api/analytics/services/analytics_engine.py`, sharing one SELECT with `product_report`

Add `export_products_csv(db, tenant_id, start, end, sort_by="revenue") -> str`
beside `product_report`.

The projection, the `FROM`/`JOIN`, the `WHERE` and the `GROUP BY` are extracted
into one module-private helper that both functions call, so the population
cannot fork. The `WHERE` that helper emits is
`{range_predicate("o.created_at")} AND o.status IN {_REVENUE_STATUSES}` — the
line this whole spec is about — and the `GROUP BY oi.wc_product_id,
oi.product_name` is inherited verbatim, including its consequence: a product
renamed inside the window produces two rows, and the file reproduces what the
page shows rather than silently merging them.

The ordering is extracted the same way, preserving today's semantics exactly:
`"revenue"` sorts on `revenue DESC` and anything else on `quantity_sold DESC`.
The export appends `, oi.wc_product_id, oi.product_name` — the full group key —
so two files of the same window arrive in the same order. It does **not** add
that tiebreak to `product_report`: that ranking is `LIMIT`-ed, so a tiebreak
there changes which products fall on the 100-row boundary of a shipped endpoint,
which is a BUG-008 instance worth its own task and not a side effect of an
export.

Each row is mapped through the same dict-building code `product_report` returns,
so a column cannot be present in the JSON and absent from the file.

It returns a `str`, not a generator, for the reason `export_orders_csv` records
in its own docstring: the session from `Depends(get_db)` is not guaranteed to
outlive the handler that built the response, so a generator that queries as it
yields is a defect that appears only under a real server. Requirement 4 is what
keeps the string bounded.

### 3. The header is the report's key list, declared once and written first

Declare the column order as a module-level tuple beside the new function —
`wc_product_id`, `name`, `revenue`, `quantity`, `orders`, `unique_customers`,
in the order `product_report` returns them — and write it with `csv.writer`
before anything can return early.

A tenant with no analytics schema, and a window matching no sales, both get the
header row alone. A zero-byte download reads as a broken feature; a header with
no rows reads as "this window has no product sales", which is a finding a
merchant should be able to see. `None` is written as the empty field, which is
what `csv.writer` already does.

### 4. Too many rows is a refusal, not a truncation

A `MAX_PRODUCT_EXPORT_ROWS` constant, set to 50000, and an exception type raised
when the window exceeds it; the route turns that into a **400** naming the cap
and telling the caller to narrow the window.

Bound it by selecting `MAX_PRODUCT_EXPORT_ROWS + 1` rows and refusing if the
extra row arrives — not by a second `COUNT(*)` over a grouped subquery. The
grouped scan is the expensive half of this statement (the same shape reads every
row of `order_items` on the dashboard), and counting first would pay for it
twice to learn a number that is only ever used to refuse. The consequence is
stated rather than hidden: the detail says *more than* 50,000 products match,
because the exact count was deliberately not bought.

This cap is a bound on a body materialised in memory, not a claim about
merchants — the largest tenant has 785 acquiring products — so on today's data
it never fires, and the test drives it by monkeypatching the constant low rather
than by seeding 50,001 products. Silent truncation is the failure that matters:
a short file reconciles against nothing and looks complete.

### 5. `GET /api/analytics/products/export`, with one new test

Add the route to `api/analytics/routes/products.py`, taking `start`, `end` and
`sort_by` — and **no `limit` and no `page`**, which is the point of it — and
returning a `StreamingResponse` with media type `text/csv` and
`Content-Disposition: attachment; filename="products.csv"`, over
`iter([csv_content])`, the shape both existing exports use.

Declare it beside the other literals. There is no `/products/{id}` route in this
module today, so nothing can shadow it; the module docstring says a path-
parameter route added later must come after the literals, and adding a third
literal means that sentence now covers three. Update the route list at the top of
that docstring, which is where this module records its endpoints.

The test is one new file, `api/tests/analytics/test_fleet_products_export.py`,
created under the contract's `creatable_paths`; no existing test is touched. Seed
as `api/tests/analytics/test_orders.py` does, on a tenant id no other analytics
test uses, and assert four things:

* the declared column tuple equals the keys of a `product_report` row, so the
  header and the JSON report cannot drift apart;
* **the population.** Seed the window with sales in `completed`, `processing`
  **and** at least one `cancelled` or `refunded` order whose line items would
  move `revenue` and `quantity` if the status filter were dropped, then assert
  the parsed CSV rows equal `product_report` for the same window at a limit above
  the product count — field for field, in order. An all-status export fails this
  test, which is the whole reason it is written;
* a window matching no sales yields the header row and nothing else, and the
  body is not empty;
* a population above the cap is refused with a 400 rather than truncated, driven
  by monkeypatching `MAX_PRODUCT_EXPORT_ROWS` low.

## What must not happen

* **No change to `/products`' response.** It ships and has callers. If
  requirement 3's equality forces a choice, the CSV follows the report.
* **No new index and no migration.** The migrations tree is protected under the
  named contract, and the export runs the query the page already runs. Whether
  the item-side scan wants an index is being priced separately.
* **No second definition of the population.** A `status` parameter, an
  all-status variant "for completeness", or a second `WHERE` built in the route
  reintroduces exactly the divergence this spec exists to prevent.
* **No touching `product_category_report` or `/products/acquiring`.** Both are
  in the same two files and neither is in this change; `acquiring_products` lives
  in `api/analytics/services/acquisition.py` and stays there.
* **No unrelated tidying.** `contracts/checks/ruff_no_new_findings.py` is a
  ratchet rather than a clean-file rule, precisely so a change need not arrive
  carrying an import-sort it did not cause.

## Out of scope

* **The download button on the products page.** `platform/` is protected under
  this contract; that is `dd_frontend` work with its own spec, calling the route
  with the window and sort the page currently holds.
* **The customer export.** The third name in the same row of
  `specs/metorik-gap.md`, and it is a new query with its own population
  argument rather than a copy of this one.
* **The missing tiebreak on `product_report`'s ranking.** Real, and it decides
  which products sit on the 100-row boundary. It wants a task that can say what
  moved.
* **Streaming or a background export.** That is the answer to requirement 4's
  cap rather than a thing to build beside it, and it needs a job runner and
  somewhere to put a file.
