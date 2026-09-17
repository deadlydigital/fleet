# Draft spec — a CSV export of the customer report

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Export the customer report as CSV, on the population top_customers already ranks, declared ahead of the profile route
writable_paths:
  - api/analytics/routes/customers.py
  - api/analytics/services/analytics_engine.py
```

## The gap

The Daily row of `specs/metorik-gap.md` names CSV export of orders, customers
**and** products. Orders shipped at task 67, with a proxy and a download control
at 84 and repeated filters at 96. Products shipped at task 108 —
`api/tests/analytics/test_fleet_products_export.py` is in the tree. Customers is
the one of the three that has not shipped, and
`research/candidates-metorik-gap-2026-09-16b.md` records
`api/analytics/routes/customers.py` as carrying no `StreamingResponse` and no
`text/csv` at `b29c630`.

So this is the third instance of a pattern that exists twice, in the module the
first two did not touch.

## What this spec settles, and it is not a detail

**The report to export is `top_customers()`, not `customer_report()`.**

The candidate that produced this task says the export runs "over the same
population `customer_report` already selects". That names the wrong function,
and the difference is the whole shape of the file.
`research/metorik-gap-2026-08-30.md` records `GET /api/analytics/customers` as
taking only `start`/`end` and returning **metrics**, not a list — its rows are
periods, carrying new and returning customer counts.
`GET /api/analytics/customers/top` is the row-per-customer report, and
`drafts/product-report-csv-export.md` describes it as a ranking of at most 100
rows built for a leaderboard.

A CSV sitting in a gap-list row beside an order export (a row per order) and a
product export (a row per product) is a row per customer. Exporting
`customer_report()` would produce a time series — a legitimate file, and not the
one anybody asked for, and one no merchant would recognise as "export my
customers".

That makes this work the same work task 108 did rather than a different one: a
report the product already computes, behind a `LIMIT` a merchant cannot raise,
escaping that `LIMIT` into a file. `drafts/product-report-csv-export.md` called
that choice close and said a customer export "has no list query to build on".
Read against the ranking endpoint rather than the metrics endpoint, it has one.

**The population is whatever `top_customers()` selects today, copied rather than
re-derived.** This document deliberately does not restate that function's status
filter, its window predicate, or its treatment of orders with no customer —
`api/tests/analytics/test_guest_order_populations.py` says the tree already holds
an opinion on the last of those, and a spec that retyped it from memory would be
inventing a second one. Requirement 1 makes the sharing structural so there is
nothing left to get wrong: **if this document and the tree disagree about the
population, the tree wins.**

## Why `deadly-digital-platform-api.yaml`

`contracts/dd-order-filters.yaml` is the other `dd_api` contract on this repo and
it cannot be used here: its writable set is exactly
`api/analytics/routes/orders.py` and `api/analytics/services/order_query.py`,
neither of which this work touches, and its third check is an acceptance check
written against a different task's requirements.

`contracts/deadly-digital-platform-api.yaml` is named with its cost admitted: it
makes twenty-seven files writable where this work needs two, and it runs the
analytics and unit suites rather than three checks. What it buys is the only
thing that makes an export trustworthy — one new
`api/tests/analytics/test_fleet_*.py` is creatable, and
`contracts/checks/new_test_bites.sh` proves the added test fails against the tree
before the change. Every claim in the section above is of the kind a contract
permitting no test leaves entirely unchecked: a CSV with a correct header and a
population one status wider than the page's looks right until somebody totals a
column.

That contract also sets `auto_merge: true`, so nobody reads this spec against the
diff. The requirements are numbered below and
`contracts/checks/spec_requirements_cited.py` obliges the diff to cite each of
`spec:1` through `spec:5` on an added line.

## Requirements

### 1. `export_customers_csv` in `api/analytics/services/analytics_engine.py`, sharing one SELECT with `top_customers`

Add `export_customers_csv(db, tenant_id, start, end) -> str` beside
`top_customers`, taking the same window parameters that function takes and no
others.

The projection, the `FROM`/`JOIN`, the `WHERE` and any `GROUP BY` are extracted
into one module-private helper that both functions call, so the two cannot fork.
The export differs from the ranking in exactly one respect — it applies no
`LIMIT` — and that difference is the entire feature. Read `top_customers` and
move its statement; do not write a second one that resembles it.

The ordering is extracted the same way and today's semantics are preserved
exactly. The export appends the row's identity column as a final tiebreak, so two
downloads of the same window arrive in the same order. It does **not** add that
tiebreak to `top_customers`: that ranking is `LIMIT`-ed, so a tiebreak there
changes which customers sit on the 100-row boundary of a shipped endpoint, which
is a bug worth its own task and not a side effect of an export.

Each row is mapped through the same dict-building code `top_customers` returns,
so a column cannot be present in the JSON and absent from the file.

It returns a `str`, not a generator, for the reason `export_orders_csv` records
in its own docstring: the session from `Depends(get_db)` is not guaranteed to
outlive the handler that built the response, so a generator that queries as it
yields is a defect that appears only under a real server. Requirement 3 is what
keeps the string bounded.

### 2. The header is the ranking row's key list, declared once and written first

Declare the column order as a module-level tuple beside the new function — one
entry per key `top_customers` returns, in the order it returns them. Read the
function and copy it; this document does not retype the list, because a list
retyped here is a list that can disagree with the tree.

Write it with `csv.writer` before anything can return early. A tenant with no
analytics schema, and a window in which nobody bought anything, both get the
header row alone. A zero-byte download reads as a broken feature; a header with
no rows reads as "no customer ordered in this window", which is a finding a
merchant should be able to see. `None` is written as the empty field, which is
what `csv.writer` already does.

### 3. Too many rows is a refusal, not a truncation

A `MAX_CUSTOMER_EXPORT_ROWS` constant, set to 50000 — the same number
`MAX_EXPORT_ROWS` uses for orders in `api/analytics/services/order_query.py` —
and an exception type raised when the window exceeds it; the route turns that
into a **400** naming the cap and telling the caller to narrow the window.

Bound it by selecting `MAX_CUSTOMER_EXPORT_ROWS + 1` rows and refusing if the
extra row arrives, rather than by a second `COUNT(*)` over the same scan. The
consequence is stated rather than hidden: the detail says *more than* 50,000
customers match, because the exact count was deliberately not bought.

**Unlike the product export's cap, this one is reachable.** The candidate's
`hib_signal` records 197,407 customers in `analytics_2`; the product export's cap
was defended on the grounds that the largest tenant has 785 acquiring products
and it could never fire. A wide enough window on the largest tenant will refuse
here. That is the correct behaviour and it is the reason the 400 must name the
cap and say what to do about it — a merchant who narrows the window gets a file,
and a merchant who gets a silently truncated one reconciles it against nothing
and believes it is complete. The test drives the refusal by monkeypatching the
constant low rather than by seeding 50,001 customers.

### 4. `GET /api/analytics/customers/export`, declared ahead of the profile route

Add the route to `api/analytics/routes/customers.py`, taking `start` and `end` —
and **no `limit` and no `page`**, which is the point of it — returning a
`StreamingResponse` with media type `text/csv` and `Content-Disposition:
attachment; filename="customers.csv"`, over `iter([csv_content])`, the shape both
existing exports use.

**This module has a path-parameter route and `api/analytics/routes/products.py`
did not, so the ordering hazard task 108 could ignore is live here.**
`research/metorik-gap-2026-08-30.md` records a customer profile route in this
module. FastAPI matches in declaration order, so a literal `/customers/export`
declared after a path-parameter route is never reached: the request is captured
by the profile handler with `export` as the identifier, and the merchant gets a
404 or a validation error rather than a file, with nothing in the diff looking
wrong. Declare the literal before it, and state that in the module docstring's
route list — which is where this module records its endpoints — so the next
literal added lands in the right place.

### 5. One new test, `api/tests/analytics/test_fleet_customers_export.py`

One new file, created under the contract's `creatable_paths`; no existing test is
touched. Seed as `api/tests/analytics/test_orders.py` does, on a tenant id no
other analytics test uses, and assert five things:

* the declared column tuple equals the keys of a `top_customers` row, so the
  header and the JSON report cannot drift apart;
* **the population.** Assert the parsed CSV rows equal `top_customers` for the
  same window at a limit above the customer count — field for field, in order.
  Seed the window so that the rows the shared statement excludes today are
  present and would move a column if the export widened the filter, so a
  divergence fails here rather than in a merchant's spreadsheet;
* **the route resolves to the export.** `GET /api/analytics/customers/export`
  returns `text/csv`, not a profile response and not a validation error for a
  non-numeric identifier. This is the assertion that pins requirement 4, and it
  is the one that would catch the ordering defect if a later edit moved the
  declaration;
* a window in which nobody ordered yields the header row and nothing else, and
  the body is not empty;
* a population above the cap is refused with a 400 rather than truncated, driven
  by monkeypatching `MAX_CUSTOMER_EXPORT_ROWS` low.

## What must not happen

* **No change to `/customers/top`'s response, and none to `/customers`'.** Both
  ship and both have callers — `platform/app/api/analytics/customers/top/route.ts`
  proxies the first. If requirement 2's equality forces a choice, the CSV follows
  the report.
* **No second definition of the population.** A `status` parameter, an
  "everything" variant for completeness, or a `WHERE` assembled in the route
  reintroduces exactly the divergence requirement 1 exists to prevent.
* **No new column and no new figure.** This export writes what the ranking
  already returns. A customer attribute that is not in that row today is a
  different task.
* **No new index and no migration.** `api/analytics/migrations/**` and
  `api/alembic/**` are protected under the named contract, and the export runs
  the statement the page already runs.
* **No touching `customer_report`, `cohort_analysis` or the churn surface.** The
  first two live in the same two files and neither is in this change.
* **No unrelated tidying.** `contracts/checks/ruff_no_new_findings.py` is a
  ratchet rather than a clean-file rule, precisely so a change need not arrive
  carrying an import-sort it did not cause.

## Out of scope

* **The download control on the customers page.** `platform/**` is protected
  under this contract; that is `dd_frontend` work with its own spec, and the
  order export's frontend half is already drafted at
  `drafts/order-csv-export-frontend.md` as the shape to follow.
* **Chosen columns.** The next row of `specs/metorik-gap.md` asks for exports
  with selected and reordered columns. Segments gained that at task 111 and
  orders has a draft; a customer export should gain it the same way, after it
  exists.
* **Whether the file wanted is the customer LIST or the customer REPORT.** The
  candidate raises this as its unasked question, and it is real: the segment
  export in `api/analytics/services/segment_engine.py` already writes a list of
  customers, for one of seven fixed RFM segments. This spec answers it for the
  gap-list row only — the row names orders, customers and products together, and
  the other two are entity lists — and does not merge the two exports. Whether
  one of them should absorb the other is a question for whoever can ask HIB's
  team.
* **The missing tiebreak on `top_customers`' ranking.** Real, and it decides
  which customers sit on the 100-row boundary. It wants a task that can say what
  moved.
* **Streaming or a background export.** That is the answer to requirement 3's
  cap rather than a thing to build beside it, and it needs a job runner and
  somewhere to put a file.
