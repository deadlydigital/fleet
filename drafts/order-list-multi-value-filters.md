# Draft spec — let the order list filter on several values per field

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Accept repeated query parameters on the order list and emit IN with bound values
writable_paths:
  - api/analytics/routes/orders.py
  - api/analytics/services/order_query.py
```

## The gap

`GET /api/analytics/orders` has five filters beyond the date range and the
search box — `status`, `payment_method`, `country`, `coupon` and `has_discount`
— and every one of them takes **one** value. `specs/order-list-filters.md`
records the shape it shipped: `o.payment_method = :payment_method`,
`o.billing_country = :country`, `o.coupon_code = :coupon`, exact, one value
each, and `status` was already that way before it.

So the two questions an order list is asked first cannot be asked at all:

    completed OR processing
    PayPal OR Stripe

There is no workaround on the caller's side. Two requests return two pages with
two pagers and two summaries, and the union of two paginated result sets is not
a page — the sort is a total order ending in the primary key precisely so that
paging cannot drop rows, and stitching two pages together in the client throws
that property away.

`specs/metorik-gap.md`, Daily band, records the row *"Order filtering: status,
payment, shipping, location, customer tags, email engagement, products
contained"* as **Partial**. The note attached to it is now out of date in its
own terms — the four columns it says cannot be filtered on can be, since task 2
— and the row is still Partial, because what Metorik offers on each of those
controls is a set and what this offers is one value. This task closes the
set-versus-single half of the row. It does not close customer tags, email
engagement or products-contained, which need joins this endpoint does not make.

## Where this came from, and why it is the piece that is buildable

`research/segmentation-model-2026-09-11.md` §5 is a section written to answer
the question *"what of this recommendation fits a contract today"*, and its
answer is a refusal followed by one exception. The refusal: the first step of
the real recommendation needs a persisted filter definition, which needs a
table, which needs a migration, and every platform contract protects
`api/analytics/migrations/**` — so queueing it is a fleet-side decision about
blast radius rather than a code task. The exception is this one, and §5 names
both files, names the contract, and gives the reason that matters more than the
size: it is the only first step that survives the segmentation decision being
reversed. Under a seven-bucket model it improves the order list anyway; under an
attribute model it is the first brick of the order evaluator.

This spec is that paragraph turned into requirements. It invents no next step of
its own.

## What the filters mean afterwards

**Within one field the values are OR. Across fields they stay AND.** So

    ?status=completed&status=processing&payment_method=paypal&payment_method=stripe

is *(completed or processing) and (PayPal or Stripe)*, which is the reading
every faceted list uses and the only one a repeated query parameter can
sensibly carry. Nothing in this task expresses OR *across* fields; that needs a
predicate grammar and is the thing §5 says does not fit a contract yet.

`has_discount` stays a tri-state boolean and is deliberately not in the list:
`true` or `false` is the absence of the filter, which is what leaving it off
already means. `search` stays single — it is a prefix probe against
`billing_email` or an exact `wc_order_id` match, not set membership.

## Why `deadly-digital-platform-api.yaml` and not `dd-order-filters.yaml`

Both contracts make these two files writable, and `contracts/dd-order-filters.yaml`
is the tighter fit on paper: it narrows writable paths to exactly these two,
where the api contract opens twenty-seven. That narrowness is real and this spec
gives it up on purpose, for two reasons.

**Its acceptance check goes blind on this change rather than failing it.**
`contracts/checks/order_filters_shape.py` walks `list_orders` for
`where.append(...)` calls and inspects the argument: it fails an f-string, and
it fails a string constant that names one of the four columns without a `:` in
it. A predicate composed by a helper — which is what requirement 2 below builds,
because the number of placeholders now depends on the number of values — is an
`ast.Call` at the append site, not a constant, so the check skips it. It reports
green for a property it can no longer see. A check that cannot fail is worse
than no check, because a run that passes it reads as verified.

**It permits no new test file.** This change alters the meaning of parameters
that already exist and already have callers, so the two questions are *did it
break the single-value behaviour* and *does the multi-value behaviour do what it
says*. `contracts/deadly-digital-platform-api.yaml` answers both:
`api/tests/analytics/test_fleet_*.py` is creatable, `contracts/checks/new_test_bites.sh`
proves the added test fails against the tree before the change, and the
`tests/analytics` suite runs file by file to show nothing else moved. Under the
narrow contract neither question is asked by anything.

The cost is stated rather than waved past: twenty-seven files writable where the
work needs two. The narrower boundary is the right trade when the risk is an
agent wandering; the risk here is being wrong about a query that already ships.

That contract also sets `auto_merge: true`, so nobody reads this spec against
the diff. Requirements are numbered below and
`contracts/checks/spec_requirements_cited.py` obliges the diff to cite each of
`spec:1` through `spec:6` on an added line.

## What done means

### 1. Four filters accept a repeated query parameter, and one value still works

In `api/analytics/routes/orders.py`, `status`, `payment_method`, `country` and
`coupon` become list-valued query parameters — FastAPI collects every repetition
of the key — and `get_orders` forwards each to `list_orders` in
`api/analytics/services/order_query.py`, whose signature changes to match. Each
keeps the `description` it has; the descriptions gain "may be repeated".

**A single value must keep working unchanged.** `?status=completed` arrives as a
one-element list and produces the same page it produces today. This is not a
nicety: `platform/app/api/analytics/orders/route.ts` forwards the parameters it
knows about, the orders page sends one value per control, and
`api/tests/analytics/test_orders.py` asserts the current behaviour. All three
must be unaffected by this merge, because the frontend half is a separate task
that lands later.

The response body does not change. No new field, no changed field, no change to
the summary's shape.

### 2. The predicate is `IN` with one bound parameter per value

Add a module-private helper to `api/analytics/services/order_query.py` that,
given a column and a list of values, appends `o.<column> IN (:name_0, :name_1)`
to the `where` list and writes `params["name_0"]`, `params["name_1"]` and so on.
The column name and the index come from the call site; **no caller value is ever
interpolated into the SQL string.**

Numbered placeholders rather than a single bind of a sequence: this module
composes raw SQL and executes it through `text()`, where binding a list either
errors or casts silently unless the parameter is declared expanding, and
declaring it expanding means constructing the statement somewhere other than
where the clause is built. Numbered placeholders keep the discipline the module
already has — allow-listed columns, bound values — and add no dependency.

One value emits `IN (:name_0)` rather than `=`. One code path, and Postgres
plans a single-element `IN` as the equality it is; a branch that switches
between two spellings is two behaviours to test for one result.

### 3. Empty means absent, and `IN ()` is never emitted

Values are stripped, empty strings are dropped, and duplicates are collapsed
keeping first-seen order. If nothing survives, **no predicate is appended at
all** and the field is simply not filtered on.

This is the one way this change can produce a 500 from a URL a person can type:
`?status=` parses to a one-element list holding the empty string, and an
unguarded `IN ()` is a Postgres syntax error. Today that URL returns the
unfiltered page, and it must still.

Values are not case-normalised and not validated against a list of known ones.
That is the existing rule in `api/analytics/routes/orders.py` for `status` — a
store that starts taking a new gateway is filterable on it the same day — and an
unrecognised value returns an empty page rather than a 400.

### 4. Too many values is a refusal, not a trim

A `MAX_FILTER_VALUES` constant beside `MAX_PAGE_SIZE` in
`api/analytics/services/order_query.py`, set to 50, checked in
`api/analytics/routes/orders.py`, which returns **400** naming the field, the
count received and the cap.

Silently keeping the first fifty would return a page whose summary describes a
population the caller did not ask for, with nothing in the response saying so —
the same failure the shared `where_clause` exists to prevent. Refusing is also
how this route already handles an under-specified request: `_parse_range`
refuses a range with one bound rather than guessing.

Fifty is a bound on the parameter count, not a policy about merchants: the
largest tenant has nine payment methods and two billing countries, so no real
request comes near it.

### 5. The summary and the rows still share one WHERE clause

`list_orders` builds `where_clause` once and uses it for the summary aggregate
and for the row `SELECT`. Keep it that way — a count and a total beside a list
they do not describe is documented conflict 2.2, and this module exists partly
to not do that. Multi-value filters make it easier to break, because the natural
place to assemble an `IN` list is next to the query that selects rows.

The total order ending in the primary key stays, and `_SORTABLE` is untouched:
nothing here is a new sort column.

### 6. One new test, which fails against the tree before the change

`api/tests/analytics/test_fleet_order_multi_value_filters.py`, created under the
contract's `creatable_paths`. No existing test is touched. Seed as
`api/tests/analytics/test_orders.py` does and assert:

* **the union is the union.** Two statuses return exactly the rows the two
  single-status calls return between them, the returned `status` values are a
  subset of the two asked for, and `summary` over the two-value filter equals
  the same population rather than the unfiltered one. This is requirement 5's
  claim written as an assertion instead of a comment.
* **one value is unchanged.** A single-value call returns the same rows and the
  same summary as the equivalent call does today — requirement 1's compatibility
  claim, asserted rather than assumed.
* **an empty value is ignored.** `status=""` returns the unfiltered page: not a
  500, not an empty page.
* **over the cap is a 400**, driven by monkeypatching `MAX_FILTER_VALUES` low
  rather than by building a fifty-element URL.
* **values bind.** A value containing a quote and `);--` returns an empty page
  and raises nothing. This one bites on any interpolation that requirement 2's
  helper might reintroduce, which is the property the acceptance check under the
  other contract would have stopped watching.

## What must not happen

* **No index and no migration.** `api/analytics/migrations/**` is protected
  under the named contract and it is also not needed. The summary aggregate
  already seq-scans the table with no filter at all, so a wider predicate on
  that scan costs nothing; and two of these columns are the low-cardinality ones
  measured in `specs/order-list-filters.md` — two distinct countries and nine
  payment methods on a 2.8M-row tenant — where an index would not be chosen for
  a single value either.
* **No change to `has_discount` or `search`.** Out of this task by requirement
  1, and a "multi-value boolean" is the absence of a filter wearing a list.
* **No change to `GET /orders/statuses`.** Whether the status counts should
  respect the other filters is a real question that changes what the dropdown
  means, and `specs/order-list-filters.md` already left it out for that reason.
* **No unrelated tidying.** `contracts/checks/ruff_no_new_findings.py` is a
  ratchet rather than a clean-file rule, so a change need not arrive carrying an
  import-sort it did not cause.

## Out of scope

* **The multi-select controls on the orders page.** `platform/**` is protected
  under this contract; it is `dd_frontend` work with its own spec, and it cannot
  start until this merges. That task has one thing to check that this one
  cannot: `platform/app/api/analytics/orders/route.ts` forwards an allow-list of
  query keys, and whether its forwarding loop carries **every** repetition of a
  key or only the first decides whether a multi-select reaches the API at all.
  `platform/__tests__/unit/analytics/test_fleet_order_filters.test.tsx` is where
  the existing single-value behaviour is asserted.
* **A saved filter definition, and anything else from §3.2 of the research.**
  It needs a table and therefore a migration, which is the refusal §5 opens
  with and a fleet-side decision rather than a code task.
* **OR across different fields, ranges, and negation.** Each is a step toward a
  predicate grammar; this task deliberately stops at set membership within one
  field, which is the part that is a user gain on its own.
* **Customer tags, email engagement and products-contained.** The rest of the
  same Metorik row, each needing a join this endpoint does not make.
