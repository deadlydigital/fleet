# Draft spec — let the order CSV export choose its columns, instead of one fixed header for every caller

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Accept a repeated columns query parameter on the order CSV export, validated against the declared column tuple
writable_paths:
  - api/analytics/routes/orders.py
  - api/analytics/services/order_query.py
```

## The gap, re-read rather than quoted

`specs/metorik-gap.md` lists "Export with chosen columns, reordered, incl.
custom fields" as a Daily row, and the ground under that row has moved since it
was written. When `drafts/order-list-csv-export.md` was drafted there was no
order export at all; there is one now. `GET /api/analytics/orders/export` is
handled by `export_orders` in `api/analytics/routes/orders.py` and streams the
filtered list as `text/csv`.

What it emits is one shape for everybody. The header is a single module-level
tuple, `ORDER_EXPORT_COLUMNS` — seventeen names in a fixed order — written
before anything can return early and read back once per row, so the file is the
same seventeen columns in the same order whether the caller wanted two of them
or all of them. The word `columns` appears nowhere in the route module: there
is no parameter to ask for a subset, and none to ask for a different order.

That is the whole of the gap, and it is now a small widening of working code
rather than a feature. The tuple already exists, the population already comes
from the shared where-clause, and the rows are already built as a mapping. What
is missing is a way for the caller to name which of those names it wants.

**Where the tuple lives, read rather than recalled.** Requirement 3 of
`drafts/order-list-csv-export.md` declared it in
`api/analytics/services/order_query.py`, beside `export_orders_csv`, and the
candidate confirms it is module-level and outside the route module. Both files
are writable here, so the build should open them and work where the tuple
actually is rather than moving it to match this paragraph. **If the tree and
this document disagree about its name, its length or its order, the tree
wins** — requirement 1 is "one declared tuple, equal to what the export writes
today", not "a tuple of seventeen names".

## Why `deadly-digital-platform-api.yaml` and not `dd-order-filters.yaml`

Two contracts make exactly these two files writable and they are different
boundaries, not two spellings of one.

`contracts/dd-order-filters.yaml` narrows writable paths to the two files this
work needs, which fits the shape of the change. It also permits **no new test
file** — `api/tests/**` is protected under it and it declares no
`creatable_paths` — caps the diff at 150 lines, and its third verification
command is `contracts/checks/order_filters_shape.py`, an acceptance check
written against a different task's requirements. Under it, this change ships
untested.

`contracts/deadly-digital-platform-api.yaml` is chosen, and the cost is stated:
it makes twenty-seven files writable where this work needs two, which is wider
than the work. What it buys is the only thing that makes this change
trustworthy. `api/tests/analytics/test_fleet_*.py` is creatable, and
`contracts/checks/new_test_bites.sh` proves the added test fails against the
tree before the change. The entire risk here is a header that stops describing
its own rows — a CSV with the right header and shifted values looks correct
until somebody imports it, which is exactly the class of defect a test catches
and a reader does not.

That contract sets `auto_merge: true`, so nobody reads this spec against the
diff. Requirements are numbered below and
`contracts/checks/spec_requirements_cited.py` obliges the diff to cite each of
`spec:1` through `spec:5` on an added line.

## The two properties that must survive

Everything below exists to preserve these, and they are what to check if any
detail here turns out to be wrong about the code:

* **The header the file starts with is exactly the columns the rows carry.**
  Same names, same order, same count, on every row.
* **The export's population is still the page's population**, through the same
  where-clause the list route uses. Choosing columns is a projection: it may
  not change which orders appear, how many appear, or in what order.

**Custom fields are not in this row.** The section title in
`specs/metorik-gap.md` names them, and `api/analytics/services/sync_engine.py`
ingests no custom order meta, so there is nothing to project. Offering a
`custom:` namespace would be offering an empty column, which is worse than not
offering it: a merchant who asks for one and gets blanks concludes their data
is missing, not that the feature is. That half of the section needs ingest
first and is a separate row.

## The change

### 1. The declared tuple becomes the vocabulary, not just the header

`ORDER_EXPORT_COLUMNS` is today read once, as the header. Make it the single
definition of three things: the set of names a caller may ask for, the default
column list, and the default order. Do not add a second list of permitted
names anywhere — two literals kept in step by hand is the defect this change
must not introduce.

If the tuple is not already equal to the keys of the mapping each row is built
from, that equality is the thing to establish first, because requirements 2 and
3 both stand on it. Do not retype the seventeen names into new code and do not
reorder them.

### 2. `export_orders_csv` writes the columns it is given

Give the CSV builder in `api/analytics/services/order_query.py` an optional
`columns` parameter. `None` means the full tuple in its declared order, so
every existing caller gets a byte-identical file — the export with no query
parameter must produce exactly what it produces today, header included.

When `columns` is given, the header row is those names in the order given and
each data row is those values in the same order. Make that structural rather
than parallel: build each row once as a name-to-value mapping keyed by the
requirement-1 names, then emit `[mapping[c] for c in columns]` for the same
`columns` the header was written from. A second pair of hand-aligned literals
is not a fix.

Per-column rendering — how a money value, a timestamp or a `None` becomes a
field — stays attached to the column name, never to a position in a list. A
column that renders differently depending on what else was requested is the
same defect wearing a different hat. `None` stays the empty field, as it is
today.

Duplicates are written as asked: a name requested twice appears twice in the
header and its value twice in each row. The header still describes the rows, so
the invariant holds and refusing duplicates would need a reason beyond
tidiness.

### 3. A repeated `columns` query parameter, validated before any query runs

`export_orders` in `api/analytics/routes/orders.py` takes an optional repeated
`columns` query parameter, so `?columns=wc_order_id&columns=total` is a
two-column file in that order and `?columns=total&columns=wc_order_id` is the
same two columns reversed. Declare it the way `get_orders` declares its
repeatable filters — `Optional[List[str]]` with `Query(None)` — rather than as
a bare `str`, which FastAPI binds by silently taking the last value.

Absent means the full tuple in its current order: requirement 2's default
reaching the wire.

**An unknown name is a 400, not a blank column.** Validate every requested name
against `ORDER_EXPORT_COLUMNS` and, on any miss, return 400 with a detail
naming the offending value and listing the permitted names. This is the point
of the row: a typo that yields an empty column is a merchant believing their
data is missing; a typo that yields a 400 is a merchant fixing a URL.
`?columns=` with an empty value falls out of the same rule as a 400 for the
empty name, which is right — a caller that sends it meant something and did not
say what.

Cap the number of requested values as this module already caps filter values,
through `_check_filter_caps` against `MAX_FILTER_VALUES` if that helper takes
the list cleanly, or a plain comparison against the same constant if it does
not. Requirement 2 permits duplicates, so the list is not bounded by seventeen,
and the body is materialised in memory under a 50,000-row ceiling; an uncapped
repeat count reopens the size question that ceiling exists to close.

Validation happens in the route, before the query, so a bad request costs no
database work — the same ordering `_parse_range` already follows when it
refuses a half-specified range.

### 4. The population is untouched

`columns` must not reach the where-clause, the sort, the row cap, or the
summary aggregate. The orders the file lists must be the same orders in the
same order whatever `columns` says.

Concretely: the projection happens after the rows are in hand, not by rewriting
the `SELECT` list. Narrowing the SQL projection to the requested names is the
tempting optimisation and it is refused here — it puts the column choice inside
the statement that also decides membership, which is where the two properties
above stop being independent. No measurement says the wide `SELECT` costs
anything, and a task reaching for one would be making a performance decision
nobody asked for.

The `MAX_EXPORT_ROWS` refusal is counted on the population, so it fires on
exactly the requests it fires on today; asking for one column is not a way past
it. An empty population still returns the header row alone, and that header is
the requested columns rather than the full tuple.

### 5. One new test file

`api/tests/analytics/test_fleet_order_export_columns.py`, created under the
contract's `creatable_paths`. No existing test is modified —
`api/tests/analytics/test_fleet_orders_export.py` and
`api/tests/analytics/test_orders.py` are protected and stay untouched, and
`contracts/checks/new_test_bites.sh` refuses a change that adds more than one
test file.

Seed as `api/tests/analytics/test_orders.py` does, with at least two orders
whose values differ in every requested column, so a projection that shifts by
one position cannot pass by coincidence. Assert:

* **the header equals the rows.** For a subset requested in a non-default
  order, parse the CSV and assert the header is exactly the requested names in
  the requested order, and that each data row carries that order's values for
  those names — read from the same source the full export uses, not retyped.
* **the default is unchanged.** With no `columns`, the header is
  `ORDER_EXPORT_COLUMNS` in its declared order and the body is what the export
  emits without the parameter.
* **the population is unchanged.** For one filter combination matching a strict
  subset, the set of `wc_order_id` values in a one-column export equals the set
  in a full export with identical filters, and the row counts match.
* **an unknown name is refused.** A request naming a column that is not in the
  tuple returns 400 and the body is not a CSV.

## What must not happen

* **No custom fields.** Stated above with its reason. A `custom:` prefix, a
  passthrough of unrecognised names, or any "if it is not in the tuple, try the
  meta table" fallback is out — and the fallback specifically would delete
  requirement 3, which is most of the value here.
* **No change to the JSON list route.** `get_orders` ships and has callers. If
  a shared helper must change shape for requirement 2, the CSV adapts to the
  JSON, never the other way round.
* **No second definition of the column set.** A permitted-names list that is
  not `ORDER_EXPORT_COLUMNS` reintroduces exactly the drift requirement 1
  exists to prevent.
* **No new index and no migration.** `api/analytics/migrations/**` is protected
  under the named contract, and this change adds no query.
* **No unrelated tidying.** `contracts/checks/ruff_no_new_findings.py` is a
  ratchet rather than a clean-file rule, precisely so a change need not arrive
  carrying an import-sort it did not cause.

## Sequencing, and one sibling that touches the same handler

`drafts/order-export-multi-value-filters.md` rewrites the same handler's filter
parameters from bare `str` to `Optional[List[str]]` and routes them through
`_check_filter_caps`. The two changes are independent in behaviour — this one
adds a parameter that does not exist yet — but they edit the same signature in
`api/analytics/routes/orders.py`, so whichever lands second rebases onto the
first. If that one has landed, requirement 3's declaration and cap should match
what it established rather than inventing a parallel idiom.

## Out of scope

* **A column picker on the orders page.** `platform/**` is protected under this
  contract; the UI is `dd_frontend` with its own spec, and it should send names
  this route validates. Until it exists the capability is reachable by URL,
  which is where the order filters started too.
* **Forwarding `columns` through the proxy.**
  `platform/app/api/analytics/orders/export/route.ts` is the frontend half of
  the same sentence, and whether it already passes unknown query parameters
  through is a question for that row rather than an assumption for this one.
* **Ingesting custom order meta.** The other half of the document's section
  title, and a change to `api/analytics/services/sync_engine.py` and the schema
  rather than to an export.
* **The same parameter on the segment export.**
  `drafts/segment-export-chosen-columns.md` is that row and it names the same
  mechanism. Doing both under one 400-line cap is how one of them ends up
  without a test.
