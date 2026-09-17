# Draft spec — let the product CSV export choose its columns, as the segment export already can

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Accept a repeated columns query parameter on the product CSV export, validated against the declared column tuple
auto_merge: false
writable_paths:
  - api/analytics/routes/products.py
  - api/analytics/services/analytics_engine.py
```

## READ THIS BEFORE QUEUEING IT — a protected test refuses this change today

`api/tests/analytics/test_fleet_products_export.py` pins the export handler's
signature by exact set equality. In `test_the_export_carries_no_limit`, at line
246 of the file as read for this spec:

```python
params = inspect.signature(export_products).parameters
assert "limit" not in params and "page" not in params
assert set(params) == {"tenant", "db", "start", "end", "sort_by"}
```

The whole of this change is a sixth parameter named `columns` on that handler.
There is no way to accept a query parameter without appearing in that set — a
`Depends` wrapper is still a parameter, and reading the raw query would add
`request` instead. So the set assertion fails on any implementation of
requirement 3, and `contracts/deadly-digital-platform-api.yaml` runs
`contracts/checks/pytest_unit_per_file.sh` over `tests/analytics`, which is the
directory that file is in.

**The build agent cannot fix it and must not try.** `api/tests/**` is protected
under every contract in `contracts/` that touches this repository — the named
one, `contracts/dd-order-filters.yaml`, `contracts/dd-utm-source-alias.yaml`,
`contracts/dd-docstring-proving.yaml`, `contracts/dd-analytics-frontend.yaml`,
`contracts/dd-acquiring-page.yaml`, `contracts/dd-index-migration.yaml` and
`contracts/dd-infra.yaml`. The file is an existing file, so the named contract's
`creatable_paths` glob `api/tests/analytics/test_fleet_*.py` does not reach it
either: creating is permitted, modifying is not. Queued as-is, this task
produces a correct branch, fails one check it is forbidden to touch, and dies.

**What unblocks it is one line, changed by a person, before this is queued:**
add `"columns"` to that set. Keep the line above it — `"limit" not in params and
"page" not in params` is the assertion that test is actually named for, and it
stays true. That edit is not numbered as a requirement here, and must not be,
because the agent that reads this spec has no permission to make it; a spec must
not number work its own agent has no tools to perform.

If this reaches an agent with the assertion still reading as above, **stop and
say so in the reply rather than editing the test or working around it.** A
branch that explains why it could not be built is useful; one that quietly edits
the suite that judges it is not.

`auto_merge: false` is set for the same reason. The precondition is outside the
branch, so a person should confirm it was met — and confirm that the amended
assertion still forbids `limit` and `page` — before this merges.

## The gap

`specs/metorik-gap.md` lists "Export with chosen columns, reordered, incl.
custom fields" as a Daily row. Three CSV exports exist and one of them honours
it: task 111 gave `export_segment` in `api/analytics/routes/segments.py` a
repeated `columns` parameter, validated in `_validate_export_columns` against
`SEGMENT_EXPORT_COLUMNS`, returning 400 and naming the permitted columns on a
typo.

`GET /api/analytics/products/export` is handled by `export_products` in
`api/analytics/routes/products.py` and takes `start`, `end` and `sort_by` and
nothing else. The word `columns` appears nowhere in that module. The file it
writes is one shape for everybody: `export_products_csv` in
`api/analytics/services/analytics_engine.py` writes `PRODUCT_EXPORT_COLUMNS` as
the header and then, once per row, `[product[column] for column in
PRODUCT_EXPORT_COLUMNS]`.

**This is smaller than the segment change was**, because the two things that
change had to build already exist here:

* the declared tuple. `PRODUCT_EXPORT_COLUMNS` is module-level in
  `api/analytics/services/analytics_engine.py`, and
  `api/tests/analytics/test_fleet_products_export.py` already pins it equal to
  the JSON report's key list.
* the name-to-value mapping. `_row_to_product` returns a dict keyed by exactly
  those names, and both the JSON report and the CSV are built from it. There is
  no parallel second literal to keep in step.

So the work is a projection over a mapping that is already there, plus the
validator in `api/analytics/routes/segments.py` copied one module across. **If
the tree and this document disagree about the tuple's name, length or order, the
tree wins**: requirement 1 is "the columns the export writes today, in the order
it writes them", not "a tuple of six names".

**No frontend reaches this export, and that is different from the segment
case.** The segment export has a proxy the detail page calls. Under
`platform/app/api/analytics/products/` there are three routes —
`platform/app/api/analytics/products/route.ts`,
`platform/app/api/analytics/products/acquiring/route.ts` and
`platform/app/api/analytics/products/categories/route.ts` — and no export among
them, so the download is reachable only by calling the API directly. That makes
this a knob on a capability whose door is not built yet. It is still worth
building in this order: the picker on
`platform/app/(dashboard)/analytics/products/page.tsx` is a `dd_frontend` row
that needs a validated parameter to send to, and the validation is the half that
decides whether a typo is a 400 or a silently empty column.

**Custom fields are not in this row.** The section title names them and
`api/analytics/services/sync_engine.py` ingests no custom product or order meta,
so there is nothing to project. Offering a `custom:` namespace would be offering
an empty column, and a merchant who asks for one and gets blanks concludes the
data is missing rather than the feature. That half of the section needs ingest
first and is a separate row.

## Why `deadly-digital-platform-api.yaml`

It is the only contract in `contracts/` that makes both files writable.
`contracts/dd-order-filters.yaml` writes the two order files;
`contracts/dd-utm-source-alias.yaml` writes `api/analytics/routes/sources.py`
and one service module outside the analytics tree; `contracts/dd-docstring-proving.yaml`
does make `api/analytics/routes/products.py` writable, but its work type is
`dd_docs`, it does not cover `api/analytics/services/analytics_engine.py`, and
it exists to prove docstrings rather than to change behaviour.

The cost is stated: twenty-seven files writable where this needs two. What it
buys is the only thing that makes the change trustworthy —
`api/tests/analytics/test_fleet_*.py` is creatable, and
`contracts/checks/new_test_bites.sh` proves the added test fails against the
tree before the change. This change's entire risk is a header that stops
describing its own rows, which is exactly the defect a reader does not catch: a
CSV with the right header and shifted values looks correct until somebody
imports it. A contract permitting no test would ship that unchecked.

## The two properties that must survive

Everything below exists to preserve these, and they are what to check if any
detail here turns out to be wrong about the code:

* **The header the file starts with is exactly the columns the rows carry.**
  Same names, same order, same count, on every row, including the header-only
  file an empty window produces.
* **The export's population is still `product_report`'s population.** Choosing
  columns is a projection. It may not change which products appear, how many,
  or in what order.

## The change

### 1. `export_products_csv` takes the columns it is to write

Give it an optional `columns` parameter, appended after `sort_by` so every
existing positional call site is unaffected. `None` means
`PRODUCT_EXPORT_COLUMNS` in its declared order.

When `columns` is given, the header row is those names in the order given and
each data row is those values in the same order. `_row_to_product` already
returns the mapping this needs, so the row emission becomes
`[product[column] for column in selected]` with `selected` being the same list
the header was written from — one list, read twice. Do not build a second
literal keyed by position; two lists kept in step by hand is the defect this
whole row exists to prevent, and writing a fresh pair of them is not a fix.

Per-column value handling stays attached to the column name rather than to a
position. `_row_to_product` already types each value (`float(r[2])` for
`revenue`, the raw integers elsewhere) and `csv.writer` renders `None` as the
empty field; a column that formatted differently depending on what else was
requested would be the same bug wearing a different hat.

Duplicates in `columns` are written as asked — the name appears twice in the
header and its value twice in each row. The invariant is that the header
describes the rows, and it still holds. Refusing duplicates would need a reason
beyond tidiness and there isn't one.

### 2. Absent `columns` is byte-identical to today's file

The export with no `columns` query parameter must produce exactly the bytes it
produces today: same header, same rows, same order, for a populated window, for
a window with no sales, and for a tenant with no analytics schema. This is the
regression that matters, because the export ships and the parameter does not yet
exist, so every caller alive today is this case.

### 3. A repeated `columns` query parameter on the route, validated

`export_products` in `api/analytics/routes/products.py` takes an optional
repeated `columns` query parameter, so `?columns=name&columns=revenue` is a
two-column file in that order and `?columns=revenue&columns=name` is the same
two reversed. Absent means requirement 2's default reaching the wire.

**An unknown name is a 400, not a blank column.** Validate each requested name
against `PRODUCT_EXPORT_COLUMNS` and, on the first miss, raise 400 with a detail
naming the offending value and listing the permitted names. `_validate_export_columns`
in `api/analytics/routes/segments.py` is that function already written, against
the same tuple shape and with the reasoning in its docstring; copy its structure
rather than inventing a second convention, including the `?columns=` empty-value
case, which falls out as a 400 for the empty name.

Validation runs in the route, before `_parse_window` reaches the database and
before any query, so a bad request costs no database work. It sits alongside the
existing `sort_by` and date 400s from `_parse_window`, which are unchanged —
this module's both-bounds-optional convention stays exactly as it is.

### 4. The population, the ordering and the row cap are untouched

`columns` must not reach `_product_rollup_select`, `_product_order_clause`, the
`range_predicate` window, the `_REVENUE_STATUSES` filter, or the `cap + 1` probe
that raises `ProductExportTooLarge`. Concretely:

* the projection happens after the rows are in hand, not by rewriting the
  `SELECT` list. Narrowing the SQL projection to the requested columns is the
  tempting optimisation and it is refused here: it puts the column choice inside
  the statement that also decides membership, which is where the two properties
  above stop being independent. No measurement says the wide `SELECT` costs
  anything, and a task reaching for one would be making a performance decision
  nobody asked for.
* `MAX_PRODUCT_EXPORT_ROWS` bounds the rows the window matches, so a
  single-column request is refused at exactly the same population a full request
  is. The cap is not a bound on file size and must not start behaving like one.
* the refusal still happens before any projection, so an over-cap window is a
  400 whatever `columns` says.

### 5. One new test

`api/tests/analytics/test_fleet_products_export_columns.py`, created under the
contract's `creatable_paths`. No existing test is modified: the one-line
amendment to `api/tests/analytics/test_fleet_products_export.py` is a
precondition a person makes before this is queued, described above and
deliberately not part of this diff.

Seed products whose values differ across every column — the existing seed in
`api/tests/analytics/test_fleet_products_export.py` is the model, and its
cancelled-order products are what make a population regression visible — so that
a projection shifted by one position cannot pass by coincidence. Assert:

* **the header equals the rows.** For a requested subset in a non-default order,
  parse the CSV and assert the header is exactly the requested names in the
  requested order, and that each data row's values are that product's values for
  those names, read from `product_report` rather than retyped into the test.
* **the default is unchanged.** With no `columns`, the body is byte-identical to
  the body the same call produces without the parameter — requirement 2, over a
  populated window and over an empty one.
* **the population is unchanged.** The `name` values of a one-column export equal
  the `name` values of a full export of the same window, in the same order, for
  both `sort_by` values.
* **an unknown name is refused.** A request naming a column that does not exist
  returns 400, the detail names the offending value and the permitted columns,
  and the body is not a CSV.
* **the cap does not move with the projection.** With
  `MAX_PRODUCT_EXPORT_ROWS` monkeypatched below the seeded population, a
  one-column request is refused exactly as a full one is.

## What must not happen

* **No edit to any existing file under the `api/tests/` tree.** Creating the one
  new file named in requirement 5 is the only thing this change does there.
  Stated at the top with its reason; it is the boundary, not a preference.
* **No custom fields.** A `custom:` prefix, a passthrough of unknown names, or
  any "if it isn't in the list, try the meta table" fallback is out — and the
  fallback specifically would delete requirement 3, which is most of the value
  here.
* **No new parameter beyond `columns`.** No `limit`, no `page`, no `status`. The
  export's lack of a row limit is the point of it, and its revenue-status
  population is what keeps the file agreeing with the page.
* **No change to `GET /api/analytics/products` or to `product_report`.** The
  JSON report ships and the page calls it. If a shared helper has to change
  shape, the CSV adapts to the JSON, not the other way round — and
  `_row_to_product` in particular is shared with the JSON route and should not
  need to change at all.
* **No new index and no migration.** `api/analytics/migrations/**` is protected
  under the named contract, and nothing here adds a query.
* **No unrelated tidying.** `contracts/checks/ruff_no_new_findings.py` is a
  ratchet rather than a clean-file rule, precisely so a change need not arrive
  carrying an import-sort it did not cause.

## Out of scope

* **A column picker on the products page.** `platform/**` is protected under this
  contract; `platform/app/(dashboard)/analytics/products/page.tsx` is a
  `dd_frontend` row with its own spec, and it should send the names this route
  validates.
* **A proxy route for the export.** There is none under
  `platform/app/api/analytics/products/` today. Building one is the frontend half
  of the same sentence and belongs with the picker.
* **The order export.** `api/analytics/routes/orders.py` is the third surface and
  it is covered by `drafts/order-export-chosen-columns.md`, which needs its own
  spec run re-done rather than a new row. Doing both under one 400-line cap is
  how one of them ends up with no test.
* **Ingesting custom meta.** The other half of the document's section title, and
  a change to `api/analytics/services/sync_engine.py` and the schema rather than
  to an export.
