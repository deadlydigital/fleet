# Put the order CSV export in front of a merchant — a proxy that streams it, and a control that carries the filters

```fleet-spec
work_type: dd_frontend
repo: deadly-digital-platform
contract: dd-analytics-frontend.yaml
title: Reach the deployed order CSV export from the orders page — a streaming proxy and a download control carrying the filters in force
writable_paths:
  - platform/app/(dashboard)/analytics/orders/page.tsx
  - platform/app/api/analytics/orders/export/**
```

## What is wrong

`GET /orders/export` is deployed. It was specified in `drafts/order-list-csv-export.md`
and built into `api/analytics/routes/orders.py` and
`api/analytics/services/order_query.py`: it returns `text/csv` with
`Content-Disposition: attachment; filename="orders.csv"`, it takes every filter
the order list takes, and it builds its rows from the same `WHERE` clause
`list_orders` builds — so the file and the table describe the same population by
construction rather than by coincidence.

On the frontend, the strings `csv`, `download` and `/export` appear zero times
on the orders page and zero times in its proxy. There is no route under
`platform/app/api/analytics/orders/` that reaches the endpoint and no control
that asks for it.

This is FEAT-035's family and not FEAT-035 itself. FEAT-035 is a control wired to
nothing, showing plausible unfiltered numbers. This is a capability wired to
nothing at all: written, tested, deployed, and with no door. The
`specs/metorik-gap.md` row it closes is Daily — *CSV export of orders /
customers / products* — and it closes only the order third of it. Customers and
products remain missing on both sides.

## The shape of the change

Two files. A new proxy, and the existing orders page.

**The proxy is a new file, at platform/app/api/analytics/orders/export/route.ts.**
It is not a `format=csv` branch inside `platform/app/api/analytics/orders/route.ts`,
and that is not a matter of taste. That proxy forwards a literal allowlist and
silently drops every key outside it; a page that sends `format` to a proxy that
does not forward it is precisely what `contracts/checks/proxy_passthrough.py`
refuses, and the refusal would be correct — FastAPI discards an undeclared name
with no error and no log line, so the merchant would get a JSON page of orders
where they asked for a file. The API declares a separate path. The frontend
gets a separate path.

`platform/app/api/analytics/orders/route.ts` is deliberately **absent from
`writable_paths` above**, even though `contracts/dd-analytics-frontend.yaml`
would make it writable: the boundary is what stops the branch reaching for the
easier, wrong shape.

### A note on how the two paths are written here

The declared path is the glob `platform/app/api/analytics/orders/export/**`
rather than the file, and the file is named in bold rather than in backticks
throughout this document. Both are because the directory does not exist yet:
`contracts/checks/draft_spec_shape.py` resolves a declared path or its parent
directory, and checks a backticked prose path the same way. The parent of the
glob is `platform/app/api/analytics/orders/`, which does exist. There is exactly
one file to create under it and it is named in every requirement below.

## What to build

### 1. A new proxy under the orders tree, streaming the file back unaltered

Create **platform/app/api/analytics/orders/export/route.ts**, a `GET` handler
that authenticates and resolves the tenant exactly the way
`platform/app/api/analytics/orders/route.ts` does today — the same helper, the
same import, the same failure shape for an unauthenticated or tenantless
request. Do not write a second authentication path; `platform/lib/api-auth.ts`
is protected under this contract and is to be used, not reimplemented.

**1.1 The forwarded list is the orders proxy's, minus `page` and `limit`.**
Copy the `PASSTHROUGH` shape from `platform/app/api/analytics/orders/route.ts`
verbatim — the array plus the `for (const key of …)` loop — and remove `page`
and `limit` from the copy. The API's export takes every parameter `get_orders`
takes except those two. The remainder, as of the filters shipped under
`drafts/order-filters-frontend.md`, is `start`, `end`, `status`, `search`,
`sort_by`, `sort_dir`, `payment_method`, `country`, `coupon` and `has_discount`.

Read that list out of the file rather than out of this paragraph: if the two
disagree, the file is right and this spec is stale. Forward exactly the names
that proxy forwards, less the two pager keys, and **add no name the API does not
declare** — a fifth name is discarded upstream without an error, which is how a
control comes to appear to work.

Forward, do not interpret. No defaulting `has_discount`, no uppercasing
`country`, no validating anything against a list of known values, and an empty
value is not forwarded — the same three rules the orders proxy already follows
and for the same reasons.

**1.2 The body and its headers come back untouched, and so does a non-200.**
On a 200, return the upstream response body as the
response body — streamed, not buffered into a string — carrying the upstream
`Content-Type` and `Content-Disposition` through unchanged. The API is the
author of the filename; the proxy does not invent, decorate or re-encode it.

On a non-200 the proxy returns the upstream status and the upstream JSON body
unchanged. It must not flatten a 400 into a 500, and it must not swallow the
`detail` string: requirement 3 is the whole reason that string exists, and a
proxy that replaces it with "Export failed" deletes the only actionable thing in
the response.

### 2. A download control on the orders page, carrying the filters in force

In `platform/app/(dashboard)/analytics/orders/page.tsx`, add one control — an
*Export CSV* button — to the filter row that already holds search, status, the
date range and the four filters from `drafts/order-filters-frontend.md`. It uses
the button primitive the page already imports from `platform/components/ui/button.tsx`;
this task adds no shared component.

The control sends the filter state **the table is currently showing**. Not the
draft state of a debounced input mid-keystroke, and not the state the page
loaded with. If the table in front of the merchant is the PayPal orders for
March, the file is the PayPal orders for March. The file disagreeing with the
table it was taken from is the failure this whole row exists to avoid.

**2.1 The export URL is built from a second URLSearchParams, adding no name.**
Derive it from the same object the list request is built from, drop
`page` and `limit`, and change nothing else:

```ts
const exportParams = new URLSearchParams(params)
exportParams.delete('page')
exportParams.delete('limit')
```

Two constraints, and both are mechanical rather than stylistic.

It must be a **distinct variable**, named so that `params` is not a prefix-free
substring of it — `exportParams` is fine. `contracts/checks/proxy_passthrough.py`
attributes parameters to a fetch by the variable name the fetch uses, and it
collects `.set(…)` and `.append(…)` calls for that name across the whole file
rather than within a scope. A second builder called `params` would report its
keys against `/api/analytics/orders`, and the check would fail for a drop that
is not happening.

And **no export-only key may be set on the list's own object**. Adding, say, a
`format` or a `columns` key to `params` would make the orders page send a name
`platform/app/api/analytics/orders/route.ts` does not forward — and that proxy
is not writable here, correctly. The export takes no parameter the list does not
take. If that ever stops being true, the answer is a spec that makes the orders
proxy writable, not a key smuggled onto the shared object.

**2.2 It is a `fetch` and a blob, not a bare link.** An anchor pointing at the
export path is one line and is the wrong line: on a 400 the browser navigates
away from the orders page and renders `{"detail": …}` as raw text in a tab, with
the filters gone and no way back but the back button. So the control fetches the
export URL, and on `response.ok` turns the body into a blob, names it from the
`Content-Disposition` filename the proxy passed through, and triggers the
download — revoking the object URL afterwards.

The request is not instant: the API materialises the whole body before
responding, deliberately, and 50,000 rows of seventeen columns is several
megabytes. Put the control in a busy state for the duration and do not let a
second click start a second export.

### 3. Above 50,000 rows the refusal becomes a sentence a person can act on

The API refuses a matched population above `MAX_EXPORT_ROWS` — 50,000 — with a
**400** whose `detail` names the matched count and the cap and says to narrow
the filters. It refuses rather than truncating because a silently truncated file
reconciles against nothing and the merchant has no sign of why.

That decision survives only if the person sees it. On a 400 the page renders the
`detail` string in the page's existing inline-error affordance, beside the
control, with **the filters still on screen and still set**. It is not a toast
that disappears, it is not a full-page error state, and it does not clear the
table — the merchant's next action is to narrow the date range or add a status,
and every control they need for that must still be in front of them.

Render the `detail` the API sent rather than a message composed here. It carries
the two numbers — how many matched, and the cap — and a client-side rewording
either loses them or re-derives them from a count the client should not be
deriving.

Any other non-200 gets a short generic failure in the same place. A 400 is the
only status this page claims to understand.

### 4. A header-only file is a result, not a failure

When the filters match nothing the API returns **200** with the header row and
no data rows, by requirement 3 of `drafts/order-list-csv-export.md`. That is an
answer — *these filters match no orders* is a finding a merchant is entitled to
have in a file — and the page must present it as one.

So: the file downloads, normally, with no error shown. The page must not inspect
the body, count the rows, or decide that a small response is a failure. And the
control must **not** be disabled when the table is empty or the summary count is
zero; a merchant proving to a client that a segment is empty needs the file more
than anyone.

If the page says anything at all here, it is a neutral note beside the control
that the export matched no orders — never the error affordance from requirement
3, which is where a real refusal lives and which loses its meaning the moment a
success is rendered into it.

### 5. One new test, asserting on the URL the handler received

`contracts/dd-analytics-frontend.yaml` permits **creating** exactly one file
matching `platform/__tests__/unit/analytics/test_fleet_*.test.tsx`; call it
`platform/__tests__/unit/analytics/test_fleet_orders_export.test.tsx`. Modifying
any existing test is refused, and
`platform/__tests__/unit/analytics/orders.render.test.tsx` must keep passing
untouched. `contracts/checks/new_test_bites.sh` runs the new file against the
pre-change tree and refuses the branch if it passes there.

Follow the existing orders render test: render the page, serve
`*/api/analytics/orders` and `*/api/analytics/orders/statuses` with MSW from
`platform/__tests__/fixtures/analytics/orders-list.json` and
`platform/__tests__/fixtures/analytics/orders-statuses.json`, and add a handler
for `*/api/analytics/orders/export`. Note the suffix: `contracts/checks/vitest_one_file.sh`
collects what `platform/vitest.config.ts` includes, so the file must end
`.test.tsx`.

Assert three things, and assert the first **on the URL the export handler
received**:

1. **The filters reach the export request.** Set a filter the page already has —
   a status, or a payment method — then click the control, and the export
   handler's query string carries that filter with that value, and carries no
   `page` and no `limit`. This is requirement 2.1 stated as an assertion instead
   of a comment, and it is the half that proves the file and the table describe
   the same population.
2. **A 400 shows its `detail`.** With the export handler answering 400 and a
   `detail` naming a count and the cap, that string is on screen after the click
   and the filter controls are still rendered. A test asserting only "an error
   appeared" passes against a page that threw the `detail` away.
3. **A header-only 200 is not an error.** With the handler answering 200 and a
   body of one header line, nothing from requirement 3's affordance appears.

A test that asserts only that a button renders would bite — the button is new —
and would still permit a page whose export drops every filter. Assert on the
request and on what the response produces.

## What nothing here checks, stated rather than assumed

`contracts/checks/proxy_passthrough.py` has two entries in its `PAIRS` list: the
orders page against `platform/app/api/analytics/orders/route.ts`, and the
overview page against the dashboard proxy. **It has no entry for the export
pair, and this task cannot add one** — the check lives in the fleet repository,
which `contracts/dd-analytics-frontend.yaml` cannot reach at all.

That is the hole the contract's own header names: *a NEW page under a NEW proxy,
where the passthrough check has no entry in its PAIRS list and so has nothing to
compare*. It is real here. If the export link sends `coupon` and the new proxy
forgets to forward it, the merchant downloads every order in the window while
the table beside them shows one coupon's worth, and no gate in this contract
fires. Requirement 5's first assertion is the only thing standing between that
and a merchant, which is why it asserts on the received URL rather than on the
rendered control.

Whoever merges this can close it in one line by adding the export pair to
`PAIRS` in the fleet repository, in a separate change. It is recorded here
rather than built because a contract task and a product task are two decisions.

`auto_merge` is `true` on this contract, so nobody compares this document to the
diff after the fact. `contracts/checks/spec_requirements_cited.py` runs first and
obliges the diff to cite `spec:1.1`, `spec:1.2`, `spec:2.1`, `spec:2.2`,
`spec:3`, `spec:4` and `spec:5` on added lines. That proves a claim was made, not
that it was met.

## What must not change

* **`platform/app/api/analytics/orders/route.ts`.** Not writable under the
  declared paths, and nothing here needs it. The export takes no parameter the
  list does not already send.
* **The unfiltered page.** With the control untouched, the request the page
  sends and the table it renders are byte-for-byte what they are today. The
  existing orders render test is the regression guard.
* **`platform/app/api/analytics/orders/statuses/route.ts`** and the order detail
  proxy. Neither is involved.
* **Any backend change.** `api/**` is protected under this contract. The
  endpoint, the column order, the 50,000 cap and the header-only response are
  facts to be reached, not files to edit.
* **The CSV itself.** Do not build a file in the client from the rows on the
  current page. That is a second lineage for a document whose whole value is
  that it has one, and it would silently export one page of results.

## Out of scope

* **Customer and product exports.** Named in the same `specs/metorik-gap.md`
  row, and neither exists on the API side yet — `api/analytics/routes/segments.py`
  has the only other `text/csv` response in the tree. Each is its own row with
  its own population question.
* **Chosen, reordered or custom columns.** The next row down in the same band,
  and it is a backend change first: `export_orders_csv` writes a fixed
  seventeen-column header derived from `_row_to_order`.
* **A background export for populations above the cap.** That is the answer to
  requirement 3's refusal rather than a thing to build beside it; it needs a job
  runner and somewhere to put a file, and it is queued by a person once 50,000
  turns out to be the wrong number.
* **Exporting from any other analytics page.** No other API export exists to
  reach.
* **Editing `specs/metorik-gap.md`.** It is in the fleet repository, which this
  contract cannot reach. The row shortens when this merges; that is a note for
  whoever merges.

## Why `dd-analytics-frontend.yaml`

Two contracts declare `work_type: dd_frontend`. The other,
`contracts/dd-acquiring-page.yaml`, makes only the products route, the products
page and the sidebar writable — neither declared path is inside it, so it covers
none of this work.

`contracts/deadly-digital-platform-api.yaml` is the wider boundary and is wrong
for a different reason: it is `dd_api`, and it protects `platform/**` precisely
because nothing it runs can verify a frontend change. Both files here are under
`platform/`.

So the choice is real but it is not close. What
`contracts/dd-analytics-frontend.yaml` buys is the thing this change needs most:
`platform/__tests__/unit/analytics/test_fleet_*.test.tsx` is creatable and
`contracts/checks/new_test_bites.sh` proves the added file fails against the
pre-change tree. As the section above says, that test is the only gate that can
see whether the export carries the filters.

## How a person checks it

Against the running app, signed in, on `/analytics/orders`:

1. No filters set. Click *Export CSV*. A file downloads named `orders.csv`, and
   its data-row count equals the summary count above the table.
2. Set a status and a payment method that exist. Export again. The row count
   drops and matches the new summary count. If it does not, a filter is being
   dropped between the page and the API — which is the failure nothing
   automated here can see.
3. Widen the date range until the summary count is above 50,000 and export. A
   message naming that count and the cap appears beside the control, the filters
   are still set, and the table is still there.
4. Set a filter that matches nothing. Export. A file downloads with one header
   line and no error is shown.
5. Page to 3 and export. The file is the whole filtered population, not page 3.
