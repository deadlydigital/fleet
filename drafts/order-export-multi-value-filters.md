# Draft spec — let the order CSV export take several values per filter, as the list already does

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Accept repeated query parameters on the order CSV export, with the list route's cap
writable_paths:
  - api/analytics/routes/orders.py
```

## The gap, read off the two route signatures

`api/analytics/routes/orders.py` declares two handlers over one population.

`get_orders` declares `status`, `payment_method`, `country` and `coupon` as
`Optional[List[str]]`, each described as "may be repeated", and calls
`_check_filter_caps` on all four before it queries — a count above
`MAX_FILTER_VALUES` is a 400 naming the field, the count and the cap, rather
than a silent trim.

`export_orders`, forty lines further down the same file, declares the same four
as bare `str`.

FastAPI binds a repeated query parameter onto a `str` field by taking the **last**
value. So `?status=completed&status=processing` filters the table on both and the
file on `processing` alone — a 200, no warning, and a
`Content-Disposition: attachment; filename="orders.csv"` that claims to be the
orders. The cap does not apply either: the export never calls
`_check_filter_caps`, so a hundred repetitions of `country` are not refused, they
are silently reduced to one.

**The code already states the guarantee this breaks.** `export_orders`' own
docstring says *"The file's population is the population the page reported, which
is the whole point."* The module docstring of
`platform/app/api/analytics/orders/export/route.ts` says the same thing from the
other side: *"The file and the table have to describe the same population, and
they only do that if the same string reaches the same WHERE clause by both
routes."* Neither is true for a repeated parameter today.

## It is LATENT, and that is the reason to do it now rather than the reason to skip it

Nothing in the product can currently send a repeat. The orders page builds its
query with `params.set(...)` — one value per control — and derives the export
URL from that same `URLSearchParams`; both proxies,
`platform/app/api/analytics/orders/route.ts` and
`platform/app/api/analytics/orders/export/route.ts`, read each key with
`searchParams.get(key)`, which returns the first value and drops the rest. A
multi-value request cannot reach either API route through the UI. Reaching it
takes a hand-written URL against the API.

So this is not a live incident and this spec does not claim it is. It is a
divergence between two signatures that must not diverge, sitting one function
apart, in a file whose docstrings assert they agree.

The multi-select on the orders page is queued frontend work — it is the named
out-of-scope item of `drafts/order-list-multi-value-filters.md`, and its whole
job is to start sending repeats. The moment it lands, every export taken from a
multi-selected table is quietly wrong, and it is wrong in the failure mode that
is hardest to notice: a plausible file, in the right order, with the right
columns, describing a narrower population than the page it was taken from. Fixing
the export first costs one route signature. Fixing it after costs a frontend
task's worth of exports nobody knows to distrust.

## Why the work is small

The query layer is already done, and was done for this. `api/analytics/services/order_query.py`
declares `FilterValues = Optional[Union[str, Sequence[str]]]` with the comment
*"A bare `str` is still accepted and means a one-element set: `export_orders_csv`
and every existing caller pass one."* `export_orders_csv` already declares all
four filters as `FilterValues` and already builds its predicate through
`_filter_clause`, the same helper `list_orders` uses, which runs the values
through `_clean_filter_values` and `_append_in` and emits `IN (:name_0, …)`.

Hand `export_orders_csv` a list today and it does the right thing. The only thing
that stops a list arriving is the route's own annotation.

What must move is therefore the route signature and the cap check, both of which
already exist twenty lines away in the same file. **`api/analytics/services/order_query.py`
is not declared writable by this spec**, deliberately: the service layer needs no
change, and a task that could edit it could "fix" this by changing the query
instead of the signature.

## Why `deadly-digital-platform-api.yaml` and not `dd-order-filters.yaml`

Both contracts make `api/analytics/routes/orders.py` writable, and they are
different boundaries rather than two spellings of one.

`contracts/dd-order-filters.yaml` is the tighter fit on paper — two files
writable where this needs one, against twenty-seven. It is refused for two
reasons, and the first is decisive.

**Its acceptance check cannot see this change at all.**
`contracts/checks/order_filters_shape.py` inspects exactly two functions,
`get_orders` and `list_orders`, and asserts that the four parameters are
declared, accepted, forwarded and bound. Neither function changes here. The check
would report `ok:` on a diff that did nothing, and on a diff that broke the
export, with equal confidence. Under that contract nothing in the verification
list would ever read `export_orders`.

**It permits no new test file.** The question this change has to answer is
whether the file and the table describe the same rows for a repeated parameter,
and the only thing that can answer it is an assertion.
`contracts/deadly-digital-platform-api.yaml` makes
`api/tests/analytics/test_fleet_*.py` creatable, `contracts/checks/new_test_bites.sh`
proves the added test fails against the tree before the change, and
`tests/analytics` runs file by file to show
`api/tests/analytics/test_fleet_orders_export.py` and
`api/tests/analytics/test_orders.py` did not move.

The cost is stated rather than waved past: twenty-seven files writable where this
work needs one, and a 400-line cap for a change that should be nearer forty. The
narrow boundary is the right trade when the risk is an agent wandering; here the
risk is shipping a signature change that looks right, and the narrow contract's
own check is blind to it.

That contract also sets `auto_merge: true`, so nobody reads this spec against the
diff. Requirements are numbered below and
`contracts/checks/spec_requirements_cited.py` obliges the diff to cite each of
`spec:1` through `spec:4` on an added line.

## What done means

### 1. The export's four set filters accept a repeated query parameter

In `api/analytics/routes/orders.py`, `export_orders`' `status`,
`payment_method`, `country` and `coupon` become `Optional[List[str]] = Query(None, ...)`,
matching `get_orders` parameter for parameter — same type, same default, same
description text with "may be repeated" appended, exactly as the list route's
descriptions read now.

`has_discount` stays a tri-state `bool` and `search` stays a single `str`, for
the reasons `list_orders`' docstring already gives: the third state of the
boolean is the absence of the filter, and a prefix probe against `billing_email`
is not set membership.

**A single value must keep working unchanged.** `?status=completed` arrives as a
one-element list, reaches `export_orders_csv` as a one-element list, and
`_clean_filter_values` treats it identically to the bare string that arrives
today. This is what `platform/app/api/analytics/orders/export/route.ts` sends,
what `api/tests/analytics/test_fleet_orders_export.py` asserts, and what every
existing caller does; none of them may be affected by this merge.

Nothing else about the response changes: same `StreamingResponse`, same
`text/csv`, same `orders.csv` filename, same header row, same column order from
`ORDER_EXPORT_COLUMNS`, same `ExportTooLarge` → 400.

### 2. The export refuses an over-long filter field, exactly as the list does

`export_orders` calls `_check_filter_caps` with the same four keyword arguments
`get_orders` passes it, before `_parse_range` and before any query, and inherits
its 400 verbatim — same field name, same received count, same
`MAX_FILTER_VALUES` read off the module rather than bound at import.

The existing function is called, not copied and not re-implemented. A second cap
with its own message is two behaviours to keep in step, and the reason the cap
refuses rather than trims — a response describing a population the caller did not
ask for, with nothing saying so — is *more* acute for a file than for a page: a
page is looked at, a CSV is reconciled against something else weeks later.

### 3. The two signatures are pinned as one list minus the pager, where the next person will read it

The relationship is currently true and unwritten, which is how it came to be
false. Record it in `api/analytics/routes/orders.py` at both ends: the module
docstring, beside the existing `ROUTE ORDER MATTERS` note, and `export_orders`'
docstring, which already says *"Every filter `GET /orders` takes, minus
`page`/`limit`"* and can now say that the **types** match too, not only the
names.

This is the same statement `platform/app/api/analytics/orders/export/route.ts`
makes about its own `PASSTHROUGH` array — "that one's copy with the pager keys
removed and NOTHING added" — and the API side is where it belongs, because the
API is what the proxy is told to read against.

No new abstraction. A shared `Depends` object holding the filter parameters would
remove the duplication and is out of scope: it changes how both routes are
constructed, it is a larger diff than the defect, and `get_orders` is the
endpoint with callers.

### 4. One new test, which fails against the tree before the change

`api/tests/analytics/test_fleet_export_multi_value_filters.py`, created under the
contract's `creatable_paths`. No existing test is touched. Seed as
`api/tests/analytics/test_fleet_orders_export.py` does, and assert:

* **the file and the table agree on a repeated parameter.** Request the list and
  the export with the *same* two-value filter — `?status=completed&status=processing`
  — and assert the CSV's `wc_order_id` column is exactly the set the list
  reports, and that its data-row count equals the list's
  `summary.orders_all_statuses`. This is the docstring's claim written as an
  assertion instead of a sentence, and it is the one that fails today: the
  export currently returns the `processing` rows alone.
* **across fields is still AND.** Two statuses and two payment methods together
  export `(completed OR processing) AND (one OR the other)`, not the union of
  four.
* **one value is unchanged.** A single-value export returns the same body it
  returns today, byte for byte, including the header row.
* **an empty value is ignored.** `?status=` exports the unfiltered population
  rather than 500ing on `IN ()` — `_clean_filter_values` already guarantees this
  and the test is what keeps requirement 1 from routing around it.
* **over the cap is a 400**, driven by monkeypatching `MAX_FILTER_VALUES` low
  rather than by building a fifty-element URL, matching how
  `api/tests/analytics/test_fleet_order_multi_value_filters.py` drives the same
  cap on the list route.

## What must not happen

* **No change to `api/analytics/services/order_query.py`.** It is not declared
  writable. `export_orders_csv` already takes `FilterValues` on all four filters
  and already goes through `_filter_clause`; if this change appears to need the
  service layer, the diagnosis is wrong.
* **No change to `get_orders`, `list_orders` or the JSON list's response.** They
  are the behaviour this change is making the export match. If the two disagree
  about anything, the export moves.
* **No index and no migration.** `api/analytics/migrations/**` is protected under
  the named contract, and the export runs the query the page already runs.
* **No second definition of a filter, and no validation of values.** Unrecognised
  values return an empty file rather than a 400, exactly as they return an empty
  page — the rule `api/analytics/routes/orders.py` already states for `status`.
* **No unrelated tidying.** `contracts/checks/ruff_no_new_findings.py` is a
  ratchet rather than a clean-file rule, so a change need not arrive carrying an
  import-sort it did not cause.

## Out of scope

* **Both proxies, and the multi-select on the orders page.** `platform/**` is
  protected under the named contract. The export proxy reads
  `searchParams.get(key)` and forwards with `params.set(key, value)`, so it
  carries one value per key and would drop the rest; so does the list proxy. That
  is `dd_frontend` work, it is the same change in both files, and it belongs with
  the multi-select that makes a repeat exist. This task is what makes the API
  ready for it, and it must merge first — a proxy that forwards repeats to an
  export that keeps the last one is the bug in a place nobody will look for it.
* **A shared filter-parameter dependency for the two routes.** Requirement 3's
  refusal, recorded here so it is a decision rather than an omission.
* **The customer and product exports.** Named in the same
  `specs/metorik-gap.md` band and neither exists yet; each is its own row.
* **`GET /orders/statuses`.** It takes no filters at all, and whether its counts
  should respect them is the open question `specs/order-list-filters.md` already
  left alone.
