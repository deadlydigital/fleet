# Draft spec — let the segment CSV export choose its columns

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Let the segment CSV export choose which columns it writes, validated against one declared list
writable_paths:
  - api/analytics/routes/segments.py
  - api/analytics/services/segment_engine.py
```

## The gap

`specs/metorik-gap.md` lists "Export with chosen columns, reordered, incl.
custom fields" as a Daily row. At the file it cites, the export is a fixed
shape: `export_segment_csv` in `api/analytics/services/segment_engine.py`
writes one literal header and one literal row list, and the word `columns`
appears nowhere in `api/analytics/routes/segments.py`. There is no way to ask
for a subset and no way to ask for a different order.

**The document says ten columns and there are eleven** — `email`,
`first_name`, `last_name`, `total_spent`, `order_count`, `last_order_at`,
`segment_name`, `rfm_r`, `rfm_f`, `rfm_m`, `score`. That changes nothing about
whether the row is real, and it is written down here because a reader who
counts them will otherwise wonder what else in that section was quoted rather
than read. `drafts/order-list-csv-export.md` repeats the same ten. If the
count in the tree differs again by the time this is built, **the tree wins**:
requirement 1 is "one declared list equal to what the function writes today",
not "a list of eleven names".

Unlike most rows in this family, this one widens something a merchant can
already reach. The export has a proxy at
`platform/app/api/analytics/segments/[name]/export/route.ts` and the segment
detail page at `platform/app/(dashboard)/analytics/segments/[name]/page.tsx`
fetches it, so this is not a knob on a capability with no door.

**Custom fields are not in this row.** The section title names them and
`api/analytics/services/sync_engine.py` ingests no custom order or customer
meta, so there is nothing to project. Offering a `custom:` namespace here would
be offering an empty column, which is worse than not offering it: a merchant
who asks for one and gets blanks concludes the data is missing, not that the
feature is. That half of the section is a separate row and needs ingest first.

## Why `deadly-digital-platform-api.yaml`

Both files named above are writable under
`contracts/deadly-digital-platform-api.yaml`, and no narrower contract covers
them — `contracts/dd-order-filters.yaml` is the other dd_api boundary and its
writable set is the two order files, so it cannot be used here at all.

The choice that is real is what the wide contract buys: `api/tests/analytics/`
is creatable under `test_fleet_*.py`, and `contracts/checks/new_test_bites.sh`
proves the added test fails against the tree before the change. This change's
entire risk is a header that stops describing its own rows, which is exactly
the class of defect a test catches and a reader does not — a CSV with the right
header and shifted values looks correct until somebody imports it. A contract
that permits no test would leave that unchecked.

That contract sets `auto_merge: true`, so nobody reads this spec against the
diff. Requirements are numbered below and
`contracts/checks/spec_requirements_cited.py` obliges the diff to cite `spec:1`
through `spec:5`.

## The two properties that must survive

Everything below exists to preserve these, and they are the things to check if
any detail here turns out to be wrong about the code:

* **The header the file starts with is exactly the columns the rows carry.**
  Same names, same order, same count, on every row.
* **The export's population is still the segment's population.** Choosing
  columns is a projection. It may not change which customers appear, how many
  appear, or in what order.

## The change

### 1. One declared column list, equal to what the export writes today

Add a module-level tuple to `api/analytics/services/segment_engine.py` — one
entry per column `export_segment_csv` currently writes, in the order it
currently writes them. Read the function and copy it; do not retype the list in
this document.

That tuple becomes the single definition of three things that are today three
separate literals: the set of names a caller may ask for, the default column
list, and the default order. Adding a column to the export later is then one
edit rather than three that can disagree.

### 2. `export_segment_csv` takes the columns it is to write

Give it an optional `columns` parameter. `None` means the full tuple from
requirement 1 in its declared order, so every existing caller is byte-identical
after the change — the export with no query parameter must produce exactly the
file it produces today, header included.

When `columns` is given, the header row is those names in the order given and
each data row is those values in the same order. The implementation must make
that structural rather than parallel: build each row once as a name-to-value
mapping keyed by the requirement-1 names, then emit
`[mapping[c] for c in columns]` for the header's `columns`. Two literals kept in
step by hand is the defect this replaces, and writing a second pair of them is
not a fix.

Formatting per column — how a money value, a timestamp or a `None` is
rendered — must stay attached to the column name, not to a position in a list.
A column that formats differently depending on what else was requested is the
same bug wearing a different hat.

Duplicates in `columns` are written as asked: the name appears twice in the
header and its value twice in each row. The invariant is that the header
describes the rows, and it still holds. Refusing duplicates would need a reason
beyond tidiness and there isn't one.

### 3. A repeated `columns` query parameter on the route, validated

The CSV handler in `api/analytics/routes/segments.py` — `export_segment`, the
one returning `text/csv` for a segment name — takes an optional repeated
`columns` query parameter, so `?columns=email&columns=total_spent` is a
two-column file in that order and `?columns=score&columns=email` is the same
two columns reversed.

Absent means the full list in its current order, which is requirement 2's
default reaching the wire.

**An unknown name is a 400, not a blank column.** The handler validates each
requested name against the requirement-1 tuple and, on any miss, returns 400
with a detail naming the offending value and listing the permitted names. This
is the point of the row: a typo that yields an empty column is a merchant
believing their data is missing, and a typo that yields a 400 is a merchant
fixing a URL. `?columns=` with an empty value falls out of this as a 400 for the
empty name, which is correct — a caller that sends it meant something and did
not say what.

Validation belongs in the route, before any query runs, so a bad request costs
no database work.

### 4. The population is untouched

`columns` must not reach the segment membership query, the segment resolution,
the ordering, or any row limit. The rows the export writes for a given segment
must be the same rows, in the same order, whatever `columns` says.

Concretely: the projection happens after the rows are in hand, not by rewriting
the `SELECT` list. Narrowing the SQL projection to the requested columns is the
tempting optimisation and it is refused here — it puts the column choice inside
the statement that also decides membership, which is where the two properties
above stop being independent. There is no measurement saying the wide `SELECT`
is a cost, and a task that reached for one would be making a performance
decision nobody asked for.

### 5. One new test

`api/tests/analytics/test_fleet_segment_export_columns.py`, created under the
contract's `creatable_paths`. No existing test is modified —
`api/tests/analytics/test_segment_engine.py` and
`api/tests/api/test_segments_full.py` are protected and stay untouched.

Seed a segment with at least two customers whose values differ across every
requested column, so a projection that shifts by one position cannot pass by
coincidence, and assert:

* **the header equals the rows.** For a requested subset in a non-default order,
  parse the emitted CSV and assert the header is exactly the requested names in
  the requested order, and that each data row's values are that customer's
  values for those names — read from the same source the full export uses, not
  retyped into the test.
* **the default is unchanged.** With no `columns`, the header is the
  requirement-1 tuple in its declared order and the body is what the export
  produced before the change.
* **the population is unchanged.** The set of `email` values in a one-column
  export equals the set in a full export of the same segment, and the row count
  matches the segment's customer count.
* **an unknown name is refused.** A request naming a column that does not exist
  returns 400 and the body is not a CSV.

## What must not happen

* **No custom fields.** Stated above with its reason. A `custom:` prefix, a
  passthrough of unknown names, or any "if it isn't in the list, try the meta
  table" fallback is out — and the fallback specifically would delete
  requirement 3, which is most of the value here.
* **No change to the segment's membership, RFM scoring, or ordering.** This is
  requirement 4 as a prohibition. If a column cannot be projected without
  touching the query, stop and say so rather than widening.
* **No change to the JSON customers endpoint.** The `/customers` route the
  detail page calls has callers and ships today. If a shared helper has to
  change shape to satisfy requirement 2, the CSV adapts to the JSON, not the
  other way round.
* **No new index and no migration.** `api/analytics/migrations/**` is protected
  under the named contract, and nothing here adds a query.
* **No unrelated tidying.** `contracts/checks/ruff_no_new_findings.py` is a
  ratchet rather than a clean-file rule, precisely so a change need not arrive
  carrying an import-sort it did not cause.

## Out of scope

* **A column picker on the segment detail page.** `platform/**` is protected
  under this contract; the UI is `dd_frontend` with its own spec, and it should
  send the names this route validates. Until it exists the capability is
  reachable by URL, which is the same position the order filters were in.
* **Passing `columns` through the proxy.** The Next.js route under
  `platform/app/api/analytics/segments/` is the frontend half of the same
  sentence and belongs with the picker.
* **The same parameter on the order export.** `api/analytics/routes/orders.py`
  has no export yet — `drafts/order-list-csv-export.md` is that row. When it
  lands, the mechanism here is what it should copy, and doing both at once under
  one 400-line cap is how one of them ends up with no test.
* **Ingesting custom meta.** The other half of the document's section title, and
  a change to `api/analytics/services/sync_engine.py` and the schema rather than
  to an export.
