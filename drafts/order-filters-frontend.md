# Carry the four order filters through the proxy and onto the orders page

```fleet-spec
work_type: dd_frontend
repo: deadly-digital-platform
title: Carry the four order filters the API already accepts through the Next.js proxy and onto the orders page
writable_paths:
  - platform/app/api/analytics/orders/route.ts
  - platform/app/(dashboard)/analytics/orders/page.tsx
```

## What is wrong

`GET /api/analytics/orders` accepts `payment_method`, `country`, `coupon` and
`has_discount`. All four are exact, all four combine with `start`, `end`,
`status` and `search` as `AND`, and all four narrow **the summary as well as
the rows** — that is the backend work specified in specs/order-list-filters.md
and shipped under `api/analytics/routes/orders.py` and
`api/analytics/services/order_query.py`.

None of them can be reached from the product, for two independent reasons:

* `platform/app/api/analytics/orders/route.ts` forwards a literal
  `PASSTHROUGH` allowlist of eight parameters — `start`, `end`, `status`,
  `search`, `page`, `limit`, `sort_by`, `sort_dir` — and silently drops every
  query key outside it. The four filter names appear nowhere in the file.
* the orders page renders payment method, billing country and coupon code as
  **columns you can read and cannot filter on**.

So the endpoint is written, tested and deployed, and an agency evaluating DD
still cannot answer *"show me the PayPal orders"*. This is the same shape as
the comparison-windows gap specified in specs/comparison-windows-frontend.md:
the API gained the capability and the Next.js layer did not carry it to a
person.

## Which Metorik behaviour this matches

specs/metorik-gap.md, Daily band: *"Order filtering: status, payment, shipping,
location, customer tags, email engagement, products contained"*, recorded as
**Partial** with the note *"The order rows carry payment method, country,
coupon and discount; they cannot be filtered on."*

The backend half of that note is already false. This task makes the rest of it
false. It does **not** close customer tags, email engagement or
products-contained, which need joins the endpoint does not make; the row stays
Partial after this merges, for a shorter list of reasons.

## What the user sees

On `/analytics/orders`, in the filter row that already holds search, status and
the date range, four more controls:

* **Payment method** — a text box. Exact match.
* **Country** — a text box taking a two-letter code. Exact match.
* **Coupon** — a text box. Exact match.
* **Discount** — a three-way select: *Any* (the default), *With a discount*,
  *Without a discount*.

Set any of them and the table, the pager **and the summary figures above the
table** all describe the same narrowed population, because the API computes the
summary over the same `WHERE` clause. The page does not have to do anything to
get that; it has to not undo it.

## What to build

### 1. The proxy forwards the four parameters

In `platform/app/api/analytics/orders/route.ts`, add `payment_method`,
`country`, `coupon` and `has_discount` to the `PASSTHROUGH` list. Keep the
forwarding loop as it is.

**Forward, do not interpret.** Do not default `has_discount`, do not uppercase
`country`, do not validate any of the four against a list of known values. The
route deliberately validates none of them — specs/order-list-filters.md §1
states the rule and the reason: *"A store that starts taking a new gateway must
be filterable on it the same day, not after a deploy."* An unrecognised value
returns an empty page, not a 400, and a proxy holding a second opinion about
the rules is a file that cannot test one.

**An empty value must not be forwarded.** `coupon=` is an exact match against
the empty string and returns nothing, which reads to a user as "there are no
orders" rather than "you cleared the box". If the existing loop already drops
empty strings — the presence tests around the eight names it forwards today —
that is the behaviour to keep; if it does not, this is the change that makes it
so, and it applies to the new four only.

**Do not add a name the API does not declare.** These four are the four. A
fifth would be discarded by FastAPI without an error or a log line, which is
FEAT-035: a control wired to nothing, showing plausible unfiltered numbers.

Nothing else in the file changes. `platform/app/api/analytics/orders/statuses/route.ts`
and `platform/app/api/analytics/orders/[id]/route.ts` are not touched.

### 2. The page sends them

In `platform/app/(dashboard)/analytics/orders/page.tsx`, the four controls join
whatever state the existing `search` and `status` controls already live in, and
they are sent the same way, debounced the same way, and persisted (or not) the
same way. Do not introduce a second mechanism for filter state beside the one
that is there.

Four rules, and the first is the one that can produce a wrong page:

**2.1 `has_discount` is three-state, not a checkbox.** *Any* sends **no
`has_discount` key at all**. *With a discount* sends `has_discount=true`.
*Without a discount* sends `has_discount=false`. A two-state checkbox that
sends `has_discount=false` when unticked is the default state of the page
silently excluding every discounted order — 146,043 orders on tenant 2 — from a
table and a summary that claim to be all orders. Absent means ignore; `false`
means "no discount". They are different requests and only one of them is the
default.

**2.2 Changing any filter resets `page` to 1.** Filtering from page 7 of an
unfiltered list into a two-page result renders an empty table over a summary
saying there are hundreds of matches. The existing controls presumably already
do this for `status` and `search`; the new four do whatever they do.

**2.3 `country` is uppercased in the control, not in the proxy.** The column
holds ISO-3166 alpha-2 in upper case — `GB` and `IE` are the only two values
present on tenant 2 per specs/order-list-filters.md §5 — and `=` in Postgres is
case-sensitive, so a user typing `gb` gets an empty page and no explanation.
Uppercasing what the box sends is an input affordance and belongs in the page.
The proxy still forwards whatever it is given, per §1.

**2.4 An empty result is not an error.** All four filters can legitimately
match nothing. Render the table's existing empty state with the filters still
visible and a way to clear them — not the error path, and not a spinner that
never resolves.

**2.5 The table cells set the filters.** Exact matching is only usable if the
user can produce the exact string, and there is no endpoint that lists the
distinct payment methods or countries in a store — `/orders/statuses` exists
and has no counterpart for these three. So make the value in the Payment,
Country and Coupon cells set the corresponding filter when clicked. It is a few
lines, it is the difference between a control an agency can use and one it can
guess at, and it costs no backend work.

### 3. Clearing

When any of the four is set, offer a way to clear them. If the page already has
such an affordance for status and search, extend it; if it does not, one
control that clears all four is enough. Do not build a chip/token UI for this.

## What the added test must assert

The contract permits **creating** exactly one file matching
`platform/__tests__/unit/analytics/test_fleet_*.test.tsx` — call it
`platform/__tests__/unit/analytics/test_fleet_order_filters.test.tsx` — and
`new_test_bites.sh` runs it against the tree as it was before this change and
refuses the branch if it passes there. **Modifying any existing test is
refused**, including `platform/__tests__/unit/analytics/orders.render.test.tsx`,
which must keep passing untouched. Follow its pattern: render the page, serve
`*/api/analytics/orders` with MSW from the fixtures at
`platform/__tests__/fixtures/analytics/orders-list.json` and
`platform/__tests__/fixtures/analytics/orders-statuses.json`.

Assert, at minimum, **on the URL the MSW handler received**:

1. **A filter reaches the request.** Typing a payment method produces a request
   whose query string carries `payment_method=` with that value. This is the
   half that proves the feature is reachable rather than merely renderable, and
   it is the assertion that fails against the pre-change tree twice over — no
   control, and a proxy that would drop the key anyway.
2. **`Any` sends nothing.** On first render, and after selecting *With a
   discount* and returning to *Any*, the request carries **no** `has_discount`
   key. Then *Without a discount* carries `has_discount=false`. The negative
   half is what makes this bite; a test that only checks `true` passes against
   a two-state checkbox, which is §2.1.
3. **The page resets.** With the pager moved off page 1, changing a filter
   produces a request carrying `page=1`.

A test asserting only that the controls render passes against nothing useful:
the controls are new, so it would bite, and it would still permit a page whose
filters are dropped by the proxy. Assert on the request.

## What must not change

* **The unfiltered page.** With none of the four set, the request the page
  sends and the table it renders are byte-for-byte what they are today. The
  existing orders render test is the regression guard and it is worth more than
  any wording improvement here.
* **The summary.** It comes from the API, already narrowed. Do not recompute a
  count or a total in the client from the rows on the current page; that is a
  second lineage for a figure that has one.
* **The columns, the sort order and the pager.** `_SORTABLE` on the backend did
  not gain these columns, so no new sort option appears.
* **The status dropdown.** Its counts come from `/orders/statuses`, which takes
  `start` and `end` only, so they describe the date window and not the four new
  filters. That is a real question about what the dropdown means and it is a
  backend change; leave the dropdown as it is and do not paper over it in the
  client.

## Out of scope

* **Any backend change.** `api/**` is protected under this contract, and every
  parameter this task sends is already deployed. `api/analytics/routes/orders.py`
  and `api/analytics/services/order_query.py` are named above as the thing being
  reached, not as files to edit.
* **A facets endpoint.** Distinct payment methods and countries, with counts,
  would turn three text boxes into selects. It is the obvious follow-up and it
  is backend work; §2.5 is the cheap substitute that needs none.
* **A discount range.** `has_discount` is a boolean on the API. A min/max needs
  a control that does not exist and a decision about whether the bound is the
  discount or the discounted total.
* **The other analytics pages**, and the order detail page at
  `platform/app/(dashboard)/analytics/orders/[id]/page.tsx`.
* **Editing specs/metorik-gap.md.** It is in the fleet repository, which this
  contract cannot reach. The row shortens when this merges; that is a note for
  whoever merges.

## How it is checked

Two contracts declare `work_type: dd_frontend`. This task runs under
`contracts/dd-analytics-frontend.yaml` — the other,
`contracts/dd-acquiring-page.yaml`, makes only the products route, the products
page and the sidebar writable, so neither path above is writable under it.

What the contract runs, in order:

    cd platform && tsc --noEmit
    cd platform && vitest run                21 files, 319 tests
    new_test_bites.sh                        the added test fails without the
                                             change and passes with it
    paired_paths.py                          the dashboard group, which this
                                             task does not touch

**Both files or neither, and no check enforces it here.** The `paired_paths`
group in `contracts/dd-analytics-frontend.yaml` covers the dashboard proxy and
the overview page, not these two. The halves are not symmetric: the proxy alone
changes nothing a user sees, and **the page alone ships four controls that
appear to work and silently return unfiltered rows** — FEAT-035 again, and the
worse of the two. Whoever queues this either adds a group for these two paths
or reads the diff for it.

## How a human checks it

`auto_merge` is **false** on this contract, so this waits for a person. Against
the running app, signed in, on `/analytics/orders`:

1. No filters set. The table, the pager and the summary read exactly as they
   did before the branch.
2. Set a payment method that exists in the Payment column. The row count and
   the summary total both drop. If the summary does not move, the parameter is
   not reaching the API — the API narrows both or neither.
3. Set *Without a discount*, then back to *Any*. The *Any* state must return
   the full population, not the `has_discount=false` one. Compare the summary
   count against step 1; they must be equal.
4. Type a payment method that does not exist. An empty table and the filters
   still on screen, not an error.
5. Page to 3, then set a country. The page returns to 1 with rows on it.
