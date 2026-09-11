# Draft spec — a CSV export of the order list, beside the one export that already exists

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Export the filtered order list as CSV, from the same where-clause the list page uses
writable_paths:
  - api/analytics/routes/orders.py
  - api/analytics/services/order_query.py
```

## The gap, re-read rather than quoted

There is exactly one `text/csv` response anywhere under `api/analytics/routes/`.
It is `export_segment` in `api/analytics/routes/segments.py`, it takes no
parameters beyond the segment name, and it emits a fixed ten-column customer
header built by `export_segment_csv` in
`api/analytics/services/segment_engine.py`. No order export, no customer export
and no product export exists on the API side.

That export is reachable — the segment detail page calls both `/customers` and
`/export` — so this row is not "exports are unwired". It is narrower than that
and it is exactly one thing: **the order list has no export.** Export is what an
agency reaches for when a report does not answer its question, which is what
decides whether a missing report is an inconvenience or a wall, and the order
list is the page most likely to be asked a question the page itself cannot
answer.

The download link on the orders page is frontend work under `dd_frontend` and is
not in this spec. See *Out of scope*.

## Why `deadly-digital-platform-api.yaml` and not `dd-order-filters.yaml`

Two contracts make these two files writable, and they are different boundaries
rather than two spellings of one.

`contracts/dd-order-filters.yaml` narrows writable paths to exactly the two
files named above, which fits — but it permits **no new test file**, caps the
diff at 150 lines, and its third verification command is
`contracts/checks/order_filters_shape.py`, an acceptance check written for a
different task's requirements. Running it against this change asks a question
this change does not answer.

`contracts/deadly-digital-platform-api.yaml` is chosen instead, and the cost is
stated: it makes twenty-seven files writable where this work needs two, which is
wider than the work. What it buys is the only thing that makes an export
trustworthy — `api/tests/analytics/test_fleet_*.py` is creatable, and
`contracts/checks/new_test_bites.sh` proves the added test fails against the
tree before the change. A CSV whose population silently disagrees with the page
it was taken from is the failure this whole row is trying to avoid, and a
contract that forbids a test cannot notice it. The narrower boundary would be
the right trade if the risk here were wandering; the risk here is being wrong.

That contract also sets `auto_merge: true`, so nobody reads this spec against
the diff. Requirements are numbered below and
`contracts/checks/spec_requirements_cited.py` obliges the diff to cite each of
`spec:1` through `spec:5` on an added line.

## The shape of the change

`list_orders` in `api/analytics/services/order_query.py` already builds its
filter predicate once and uses it twice — for the summary aggregate and for the
row `SELECT` — under a comment naming conflict 2.2: the summary must describe
the page's own population rather than some wider one. An export is a third
consumer of that same clause, and the whole point of it is that the file and the
page describe the same rows. So the clause is extracted, not copied.

### 1. The filter clause is built in one place and used by both the list and the export

Extract the `where`/`params` construction from `list_orders` — the block from
`where = ["1 = 1"]` down to the `has_discount` branch — into a module-private
helper in `api/analytics/services/order_query.py` returning
`(where_clause, params)`. `list_orders` calls it; the new export calls it with
the same keyword arguments and gets a byte-identical predicate.

No second query, and no second copy of the filter semantics. The two behaviours
that must survive the extraction unchanged are the `search` split (a digit
string matches `wc_order_id` exactly, anything else is an `ILIKE` prefix on
`billing_email`) and `has_discount is not None` — `False` is the filter "orders
with no discount", not an absent filter. Both are load-bearing and both are easy
to lose in a move.

### 2. A new service function returns the CSV body as a string

Add `export_orders_csv` to `api/analytics/services/order_query.py`, taking the
same filter keywords as `list_orders` plus `sort_by`/`sort_dir`, and returning a
`str`.

It reuses `_order_clause`, so the file arrives in the order the reader saw and
carries the same total-order tiebreak on `o.id` — not decoration, and BUG-008 is
why it is in the existing code. It reuses the row `SELECT` of `list_orders`
verbatim except for dropping `LIMIT`/`OFFSET`, and maps each row through
`_row_to_order`, so a column cannot be present in the JSON list and absent from
the file.

It returns a string rather than a generator, and that is deliberate rather than
lazy. `export_segment` builds the whole body first and hands
`StreamingResponse` an `iter([csv_content])`; the session from
`Depends(get_db)` is not guaranteed to outlive the handler that created the
response, so a generator that queries as it yields is a defect that only appears
under a real server. Requirement 4 is what keeps that string bounded.

### 3. The header is the key list of `_row_to_order`, asserted rather than retyped

Declare the column order once as a module-level tuple in
`api/analytics/services/order_query.py` and write it as the header row. The
tuple must equal `list(_row_to_order(row))` for any row — the seventeen keys
`id`, `wc_order_id`, `status`, `total`, `currency`, `payment_method`,
`billing_email`, `created_at`, `billing_city`, `billing_postcode`,
`billing_country`, `discount_total`, `refund_total`, `coupon_code`,
`customer_id`, `customer_name`, `item_count` in the order that function returns
them.

Each data row is that mapping's values in that order, with `None` written as the
empty field. When the filtered population is empty, or when
`schema_exists` is false for the tenant, the response is the header row alone
and not a zero-byte body: an empty download reads as a broken feature, and
"these filters match no orders" is a finding the merchant should be able to see.

### 4. Too many rows is a refusal, not a truncation

A `MAX_EXPORT_ROWS` constant beside `MAX_PAGE_SIZE`, set to 50000. The export
runs the summary aggregate first — the one `list_orders` already runs, through
the same helper from requirement 1 — and when `orders_all_statuses` exceeds the
cap the route returns **400** with a detail naming the matched count and the cap
and telling the caller to narrow the filters.

Silent truncation is the failure mode that matters here, because a merchant
reconciling an export against the page's summary would find two numbers that
disagree with no sign of why. Refusing is also how this file already handles an
under-specified request: `_parse_range` in `api/analytics/routes/orders.py`
refuses a range with one bound rather than guessing "from here onwards". The cap
exists because tenant 1 has ~680,000 orders and the body is materialised in
memory; 50,000 rows of seventeen columns is a few megabytes, and raising it is a
decision for a person with a measurement, not for this task.

### 5. `GET /api/analytics/orders/export`, declared before the id route, with one new test

Add the route to `api/analytics/routes/orders.py`, taking every query parameter
`get_orders` takes except `page` and `limit`, parsing dates through the existing
`_parse_range`, and returning a `StreamingResponse` with media type `text/csv`
and `Content-Disposition: attachment; filename="orders.csv"` — the same response
shape `export_segment` uses.

**It must be declared before `@router.get("/{order_id}")`.** FastAPI matches in
declaration order; a literal path registered after the path-parameter route
binds `order_id="export"` and 422s on int parsing. The module docstring in
`api/analytics/routes/orders.py` already says so for `/statuses`, and this is the
second instance of the same trap.

The test is one new file, `api/tests/analytics/test_fleet_orders_export.py`,
created under the contract's `creatable_paths`. No existing test is touched.
Seed as `api/tests/analytics/test_orders.py` does and assert three things:

* the declared column tuple equals the keys `_row_to_order` returns, so the
  header and the JSON list cannot drift apart;
* for a filter combination that matches a strict subset — a `status` plus a
  `has_discount=False`, say — the CSV data-row count equals
  `list_orders`' `summary.orders_all_statuses` for the identical arguments, and
  the `wc_order_id` values are the same set. This is requirement 1's claim
  stated as an assertion rather than as a comment;
* a population above the cap is refused with 400 rather than truncated. Drive
  this by monkeypatching `MAX_EXPORT_ROWS` low rather than by seeding 50,000
  rows.

## What must not happen

* **No new index and no migration.** `api/analytics/migrations/**` is protected
  under the named contract. The export runs the query the page already runs.
* **No change to the JSON list's response.** If requirement 3's equality forces
  a choice, the CSV follows the JSON, never the other way round — the page ships
  and has callers.
* **No second definition of a filter.** A parameter the export accepts that
  `list_orders` does not, or vice versa, reintroduces exactly the divergence
  this spec exists to prevent.
* **No unrelated tidying.** `ruff_no_new_findings.py` is a ratchet, not a
  clean-file rule, precisely so that a change does not have to arrive carrying
  an import-sort it did not cause.

## Out of scope

* **The download button on the orders page.** `platform/` is protected under
  this contract and the work is `dd_frontend` with its own spec. It should call
  the route with the filters the table currently holds.
* **Customer and product exports.** Named in the same section of
  `specs/metorik-gap.md`, and each is its own row with its own population
  question. Doing three at once under a 400-line cap is how one of them gets no
  test.
* **Streaming or a background export for the whole table.** That is the answer
  to requirement 4's cap rather than a thing to build alongside it, and it needs
  a job runner and a place to put a file. A person queues it when 50,000 rows
  turns out to be the wrong number.
* **Any change to the segment export.** It is the precedent this copies, not a
  thing to refactor; touching it puts `api/analytics/services/segment_engine.py`
  in a diff that has no test covering segments.
