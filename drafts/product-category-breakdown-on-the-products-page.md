# Draft spec — make the product category breakdown reachable from the products page

```fleet-spec
work_type: dd_frontend
repo: deadly-digital-platform
contract: dd-analytics-frontend.yaml
title: Make the product category breakdown reachable from the products page
writable_paths:
  - platform/app/api/analytics/products/categories/**
  - platform/app/(dashboard)/analytics/products/page.tsx
```

## Why this is a code change and not an investigation

The API half has shipped. `api/analytics/routes/products.py:108` declares
`GET /products/categories`, and its module docstring lists the route beside
`/products` and `/products/acquiring`. `product_category_report()` at
`api/analytics/services/analytics_engine.py:1702` computes it: one grouped
query over a `labelled` CTE, a second over the same CTE for coverage, and a
third existence probe for whether the tenant holds any category data at all.
The table it reads was created by
`api/analytics/migrations/versions/v0008_product_categories.py` and indexed on
`category` for precisely this read.

Nothing reaches it. There is no directory `platform/app/api/analytics/products/categories/`
in the tree — `platform/app/api/analytics/products/` holds exactly two files,
`platform/app/api/analytics/products/route.ts` and
`platform/app/api/analytics/products/acquiring/route.ts` — and
`platform/app/(dashboard)/analytics/products/page.tsx` never requests it. The
only occurrences of the word category on that page are two comments, at lines
31–33 and in the `Product` interface commentary, recording a Category column
that was *removed* because the endpoint then had no source for one. It has one
now, on a different endpoint, and the page does not ask.

So the deliverable is a proxy and a section. There is nothing to measure first.

## Why this contract

`contracts/dd-analytics-frontend.yaml`, work_type `dd_frontend`. Both declared
paths are inside its writable globs (`platform/app/api/analytics/products/**`
and `platform/app/(dashboard)/analytics/products/**`), it links
`platform/node_modules` in so `tsc` and `vitest` can run, and it requires one
added test proven to fail against the pre-change tree. The api contract cannot
be used: it protects `platform/**` outright, and correctly — it can verify
nothing here.

**A note on the declared path, because it looks like an evasion and is not.**
The new proxy file is platform/app/api/analytics/products/categories/route.ts.
`contracts/checks/draft_spec_shape.py` accepts a declared path that does not
exist only when its *parent directory* does, and `categories/` does not exist
yet, so the file path cannot be declared and cannot be written in backticks
anywhere in this document. The directory glob is declared instead. It resolves
under the same rule — its parent, `platform/app/api/analytics/products/`, is in
the tree — and it covers exactly the one file this task creates. Do not create
anything else under it.

## What the page must not say

One property has to come out of the endpoint's own docstring and onto the
screen. From `api/analytics/routes/products.py:128-132`:

> `coverage` leads the response for the reason `/products/acquiring`'s does:
> the per-category rows deliberately do NOT sum to `revenue_total`, because a
> product in three categories is credited to all three.

Migration 0008 measured ~98% of categorised products carrying more than one
category. So on a real tenant the breakdown's rows add up to roughly two to
three times the revenue above them, **by construction and correctly**. A page
that prints those rows under a revenue total without saying so is showing an
arithmetic that does not hold, and the first person to add them up will be
right to distrust every other number on the page. `coverage.multi_category_products`
is the size of that double count and is on the wire for this reason.

## The wire shape, read from the endpoint rather than assumed

`GET /api/analytics/products/categories` takes `start`, `end`, `sort_by`
(`revenue` or `quantity`) and `limit` (1–100, default 20). **No `offset`** —
the breakdown is not paginated. It returns:

```
{
  coverage: { revenue_total, revenue_categorised, revenue_uncategorised,
              categories_total, categories_returned,
              multi_category_products, is_truncated },
  category_data_present: boolean,
  state: "catalogue_not_synced" | "no_sales_in_window" | "ok",
  categories: [ { category, is_uncategorised: false,
                  revenue, quantity, orders, products } ],
  uncategorised: { category: null, is_uncategorised: true,
                   revenue, quantity, orders, products },
  sort_by
}
```

`revenue_categorised + revenue_uncategorised == revenue_total` is the identity
that *does* hold, counted once per line. `uncategorised` is a top-level key and
not a row in `categories`, deliberately: it is the majority case on a tenant
that has not re-synced its catalogue since 0008, and ranked it would be the
first thing a small `limit` truncated away.

## What to build

Six requirements. Put `spec:N` on a line this change adds — a comment, a
`data-testid`, or a test name — for each of 1 through 6.
`contracts/checks/spec_requirements_cited.py` runs first under this contract
and reads only added lines.

### 1. The proxy

One file, platform/app/api/analytics/products/categories/route.ts, modelled on
`platform/app/api/analytics/products/acquiring/route.ts` and not on
`platform/app/api/analytics/products/route.ts` — see §6 for why that
distinction matters. Same `getServerSession` / `tenantId` 401 guard, same
`X-DD-API-Key` header from `session.user.apiKey`, same pass-through of the
backend's body and status unchanged, same `try`/`catch` returning a 500.

It forwards exactly four names: `start`, `end`, **`sort_by`** and `limit`. Not
`sort`. Not `offset` — the endpoint does not declare one and FastAPI drops an
undeclared query parameter with no error and no log line. Do not re-implement
the `sort_by` membership check or the date parse here: the backend owns them
and returns its own 400 with its own detail, which is the rule
`platform/app/api/analytics/products/acquiring/route.ts` states in its header
comment and the reason its 400 is not duplicated.

### 2. The page asks for it, over the same window

`platform/app/(dashboard)/analytics/products/page.tsx` fetches the breakdown
from the same `useEffect` that already fetches the ranking, keyed on the same
`dateRange` and the same `sortBy`, so the two cannot come to describe different
windows. `start` and `end` are the `DateRangePicker` values already in state;
`sort_by` is the existing `SortField`, whose two values are exactly the two the
endpoint accepts. `page` must **not** be in the request — the breakdown is not
paginated, and paging the ranking must not refetch or blank it.

A failure on the breakdown must not take the ranking down with it. The existing
`toast.error` path is for the ranking; the breakdown gets its own state, and
when it is absent the page renders the ranking and an explicit "could not load"
rather than a skeleton that never resolves.

### 3. The breakdown renders, with the uncategorised bucket visible

A new `Card` below the existing Product Performance table, reusing
`platform/components/ui/data-table.tsx` and `platform/components/ui/card.tsx`
as the page already does. Neither of those is writable under this contract and
neither needs to be.

Per category: the name, `revenue`, `quantity`, `orders` and `products`. The
`products` count is what separates one big seller from a genuinely broad
category and is the reason it is on the wire.

`uncategorised` is rendered as a labelled row of its own — "Uncategorised", or
the same words the API uses — and is **not** appended into `categories` as a
row with a blank name. It carries `is_uncategorised: true` and `category: null`
to be told apart by. When its revenue is non-zero it must be visible without
scrolling past a truncated ranking to find it; when it is zero it may be
omitted. Do not sort it into the ranking.

### 4. The page states that the rows do not sum

A sentence rendered beside the breakdown, not a tooltip and not a comment in
the source, saying that a product belongs to every category it is in and that
the rows therefore total more than the revenue for the period. Where
`coverage.multi_category_products` is greater than zero, render it: it is the
number that makes the discrepancy legible rather than alarming.

Render `coverage.revenue_total` beside the breakdown as the figure the rows do
not sum to, and `revenue_categorised` / `revenue_uncategorised` as the split
that does. Do **not** derive any of the three by summing the rows.

`coverage.is_truncated` — equivalently `categories_returned < categories_total`
— must be said in words when true. The precedent is
`api/analytics/routes/products.py:90-93`, "No silent caps", which is the same
argument for the same reason.

### 5. The three states render as three different things

`state` is a string with three values and each means something different:

* `catalogue_not_synced` — the tenant holds no category data at all,
  independent of the dates. The catalogue has not been synced since migration
  0008 and the breakdown cannot be produced yet. Say that, and say that a
  product sync fixes it. Do **not** render an empty table.
* `no_sales_in_window` — there is category data, and nothing sold in these
  dates. A date-range problem, not a setup problem.
* `ok` — render the breakdown.

These two failure states produce an identical near-empty payload and mean
opposite things; `product_category_report()` separates them at
`api/analytics/services/analytics_engine.py:1853-1857` specifically so a
consumer can branch, and collapsing them back into one empty table here throws
away the only reason that field exists. Branch on `state`, not on
`categories.length`.

### 6. One test, and what it has to pin

Create `platform/__tests__/unit/analytics/test_fleet_product_categories.test.tsx`
— the only shape this contract's `creatable_paths` allows, and `.test.tsx` so
`vitest` collects it. No existing test may be edited, and
`platform/__tests__/unit/analytics/products.render.test.tsx` in particular must
be left alone: it carries a deliberately failing assertion about the missing
`summary` object which is not this task's to resolve. Fixtures under
`platform/__tests__/fixtures/` are protected too, so mock the response inline
with MSW as the neighbouring analytics render tests do.

The added test must fail against the tree before this change —
`new_test_bites.sh` runs it against both — and it must assert:

* the request the page issues carries `sort_by` and carries no `offset`, and
  that `sort_by` arrives at the backend URL the proxy builds. This is the one
  assertion that would have caught the live defect in §"Not in scope" below;
* a `state` of `catalogue_not_synced` renders the setup message and a `state`
  of `no_sales_in_window` renders something visibly different — asserted as two
  cases, since one case cannot show they differ;
* a payload whose `categories` revenues sum to more than
  `coverage.revenue_total`, with `multi_category_products` above zero, renders
  the §4 sentence. A fixture where the rows happen to sum correctly would pass
  against a page that says nothing;
* a non-zero `uncategorised` appears as its own labelled row and not inside the
  ranking.

## Not in scope, stated so nobody reads it as included

**`platform/app/api/analytics/products/route.ts` drops the ranking's sort, and
this task does not fix it.** The page has sent `sort_by` since the comment at
its line 113 was written; that proxy forwards `sort` and never `sort_by`, so
the name is dropped and every ranking comes back in the endpoint's default
revenue order however the column header is clicked. It is FEAT-035 on a live
page. It is *not* fixed here because it is a one-line change to a different
file with a different blast radius and its own test, and folding it into this
diff would leave a category-breakdown task that also silently changed how the
table above it sorts. **Queue it separately.** The file is writable under this
contract. What this task owes it is §1: do not copy the bug into the new proxy.

**`contracts/checks/proxy_passthrough.py` will not check the new pair.** Its
`PAIRS` list names the orders page and the analytics overview and nothing else
— the products page is one of the 13 unchecked pairs its own docstring
enumerates. Adding an entry would be an edit to `contracts/**`, which is
protected under every contract and outside this task's boundary. So the §6
assertion about `sort_by` is the only thing standing between this proxy and the
defect in the paragraph above, and that is why it is a numbered requirement
rather than a suggestion.

**No new page, and no nav entry.** `specs/metorik-gap.md:103` records that
`Sidebar.tsx` reserves `/analytics/categories` with no page behind it. A page
at that route would need a writable path this contract does not grant and a new
entry in `PAIRS` that this task cannot add. The breakdown goes on the products
page, which an agency already reaches, and the reserved route stays reserved.

**Vendor and brand stay open.** `specs/metorik-gap.md:103` names "category /
vendor / brand" together and only category has a table behind it. Closing that
row to **Partial — category only** is the honest outcome; the other two need
the connector to send something it does not send.

**The four stat cards stay broken.** They read `data.summary`, which
`GET /api/analytics/products` never returns, and render "0 products sold,
£0.00" over a populated table. The comment at
`platform/app/(dashboard)/analytics/products/page.tsx:47-62` explains why the
page must not paper over it by summing `data` — with more products than
`limit`, the page would confidently report 20 products for a catalogue of 300.
It is an API fix. Do not attempt it here, and do not let the new coverage
figures be mistaken for it: `coverage.revenue_total` is revenue over all order
lines in the window and is not `summary.total_revenue`.

## Before this is queued

`auto_merge` is `true` on this contract and nothing downstream reads a spec
except `spec_requirements_cited.py`, which proves a claim was *made* and not
that it was *met*. The requirement most likely to ship unbuilt is §4 — it is a
sentence rather than a component, and every check here passes without it while
the page shows rows that overstate the total by three times. If one thing is
read against the diff, read that one.
