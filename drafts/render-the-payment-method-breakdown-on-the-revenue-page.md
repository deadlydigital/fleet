# Render the payment-method breakdown the revenue endpoint already returns

```fleet-spec
work_type: dd_frontend
repo: deadly-digital-platform
contract: dd-analytics-frontend.yaml
title: Render the payment-method breakdown on the revenue page, including the named bucket for orders carrying no method
writable_paths:
  - platform/app/(dashboard)/analytics/revenue/page.tsx
```

## What is wrong

`specs/metorik-gap.md` files **Payment method breakdown** under *Rarely*, as
*Partial*: `payment_method` populated on 2,782,530 of 2,844,177 orders and shown
on order rows, no report grouping by it.

The backend half of that row shipped on 14 Sep 2026 from
`drafts/revenue-by-payment-method.md`. `payment_method_breakdown()` is in
`api/analytics/services/analytics_engine.py`, `api/analytics/routes/revenue.py`
calls it, and `api/tests/analytics/test_fleet_payment_methods.py` asserts on it.

**This spec is not that row and must not be confused with it.** That task built
the aggregate; this one puts it in front of a person. The string `payment` occurs
**zero times** in `platform/app/(dashboard)/analytics/revenue/page.tsx`, which is
535 lines long. The figure is computed, tested, deployed and invisible — the same
shape of gap `drafts/render-the-coupon-block-on-the-revenue-page.md` closed for
the coupon block a few days earlier, and the follow-up that draft's *What this
task must not do* section named in advance.

## Why this is one file, with no proxy change and no query

Three facts, each read out of the tree rather than assumed:

**The endpoint returns it unasked.** `api/analytics/routes/revenue.py` computes
`payment_methods = payment_method_breakdown(db, tenant.id, start_date, end_date)`
and returns it as a **top-level key beside `data` and `summary`**, taking no new
query parameter. Requirement 1 of `drafts/revenue-by-payment-method.md` refused a
`payment_limit` knob on the grounds that payment methods are a store's enabled
gateways with no `coupon_limit=0` saving to buy. So there is nothing for this page
to ask for.

**The proxy already passes it.** `platform/app/api/analytics/revenue/route.ts`
ends with `const data = await res.json()` and `NextResponse.json(data, ...)` — the
body is handed back unmodified. The block reaches the browser today. That file is
writable under this contract and is **not** in this spec's `writable_paths`,
deliberately: nothing in it needs to change, and a diff touching it would be a
file changed for no requirement.

**The page throws it away in one line.** At
`platform/app/(dashboard)/analytics/revenue/page.tsx:210` the fetch handler does

    setData({ summary: json.summary, data: json.data || [] })

which reconstructs state from two named keys and discards every other top-level
key on the response. `payment_methods` arrives in the browser, reaches that line,
and stops there. That is requirement 1 below, and it is why the coupon block —
which lives *inside* `summary` — needed no such change and this one does.

## The payload, read out of the shipped source

Quoted from `payment_method_breakdown()` in
`api/analytics/services/analytics_engine.py` and pinned by
`api/tests/analytics/test_fleet_payment_methods.py`. **Confirm every name against
those two files before writing the interface**; `api/**` is protected under this
contract and is being read, never edited.

    currency, mixed_currency
    methods[]                  payment_method, orders_all_statuses,
                               orders_revenue_statuses, revenue,
                               refunded_amount, aov
    method_limit, methods_returned, distinct_payment_methods,
    methods_not_returned
    not_returned               orders_revenue_statuses, revenue
    no_method                  null_payment_method  { orders_all_statuses,
                                                      orders_revenue_statuses,
                                                      revenue }
                               empty_payment_method { ...the same three }
                               total                { ...the same three }
    coverage                   orders_all_statuses, orders_revenue_statuses,
                               revenue, window_orders_revenue_statuses,
                               window_revenue, order_share, revenue_share

Two shapes that are not the happy path and both occur in the shipped code:
`payment_method_breakdown()` returns a **bare `{}`** when the tenant has no
analytics schema, and returns `{}` again when the aggregate row comes back
`None`. So "present" does not imply "has a `methods` array".

## The one property that cannot be invented

`no_method` and `coverage` exist because 61,647 orders — 2.17% of the table —
carry no payment method, and a `GROUP BY payment_method` drops them silently.
Percentages printed beside the remaining rows then sum to 100% of a population
that is **97.83% of the store while being printed as the store**.

The endpoint already computes `coverage.order_share` and `coverage.revenue_share`
over the window's own denominators, and splits `null_payment_method` from
`empty_payment_method` because the two behave differently downstream: the
order-list filter in `api/analytics/services/order_query.py` tests
`if payment_method:`, so an empty string is falsy, skips the predicate entirely
and returns the unfiltered list.

A page that renders `methods[]` and omits `no_method` and `coverage` reproduces
in the browser exactly the defect the API spent a requirement refusing. That is
requirement 2.3, and it is the requirement most likely to go missing, because the
table looks finished without it.

## What the user sees

On `/analytics/revenue`, below the coupon block and inside the same date window:

* a table of payment methods ranked by revenue, each with its order counts, gross,
  refunded amount and AOV;
* a line stating what share of the window's orders and money those rows cover;
* the orders carrying no method, with NULL and empty-string named separately;
* a line saying what is not in the table, when the ceiling bites;
* in a window with no orders at all: one sentence, not an empty table.

---

### 1. The top-level block survives into state

`platform/app/(dashboard)/analytics/revenue/page.tsx:210` rebuilds state from
`json.summary` and `json.data` and drops everything else. Add `payment_methods`
to that object and to the `RevenueData` interface as an **optional** field, typed
from the payload above. Locate the line by reading the fetch handler, not by the
number quoted here.

**Nothing else about the fetch changes.** The `params` built above it gain no key,
`couponLimit` behaves exactly as it does today, and the `useEffect` dependency
array is untouched. This requirement is an assignment and a type, and that is the
whole of it.

### 2. The page renders the block

All of it in the same file, reading the object the page now holds. The section
goes **below** the coupon block, above nothing, using the table and stat-line
markup the coupon section already established — this file is 535 lines and does
not need a second visual vocabulary.

**2.1 Every money figure is the API's, and every denominator is printed.** Each
row renders `payment_method`, both order counts, `revenue`, `refunded_amount`
and `aov`. Render `aov` **as returned**; do not divide `revenue` by a count in
the client. `specs/metorik-gap.md` already records a documented conflict over
which population an AOV covers, and this page's own header comment records a
fourth AOV lineage that shipped from exactly this shortcut. Money is
revenue-status only and counts carry both populations, because that is what the
engine computed. Name the currency from `currency`, and say so plainly when
`mixed_currency` is true, as the coupon section does.

**2.2 The table is the API's order, and the key is the stored string.** Rows
render in the order the payload returns them — revenue descending, tie-broken on
the method — and the page does not re-sort, re-rank, truncate or add a sort
control: the endpoint takes no sort parameter, so a header that appeared to sort
would sort the sample. The method is displayed **exactly as stored**: no
title-casing, no mapping of gateway ids to display names, no folding of `stripe`
and `Stripe` into one row. `api/tests/analytics/test_fleet_payment_methods.py`
seeds both spellings on purpose, and the order-list `payment_method` filter on
`api/analytics/routes/orders.py` is an exact, case-sensitive match, so a
prettified value is a row that clicks through to nothing.

**2.3 Coverage and the no-method bucket are rendered, and neither is optional.**
Beside the table, in prose a merchant reads:

* the share of the window's revenue-status orders and of its revenue that the
  rows above cover, from `coverage.order_share` and `coverage.revenue_share`,
  with the denominators — `coverage.window_orders_revenue_statuses` and
  `coverage.window_revenue` — printed beside them;
* the orders carrying **no** method, taking `null_payment_method` and
  `empty_payment_method` from `no_method` as **two separately labelled figures**,
  plus `no_method.total`.

Take all of these from the payload. **Do not compute any of them in the client**
by subtracting the visible rows from a total: the endpoint computes them against
the full window, and a second lineage for a figure that already has one is the
defect this page's own comments were written about.

Do not net the two no-method figures into one, and do not hide them when they are
zero — the engine reports zeros deliberately, because *checked and none* and *not
checked* are different facts. A zero bucket may be one quiet sentence rather than
two stat cards, but it must be on screen. On this tenant the coverage line reads
about 97.83%, and that number is the honest reading of the table above it.

**2.4 The tail is rendered when the ceiling bites.** When
`methods_not_returned` is greater than zero, a line under the table giving
`distinct_payment_methods`, `methods_returned`, and the orders and revenue in
`not_returned`. When it is zero, say that all methods in the window are in the
table. Both from the payload; neither computed here.

**2.5 Absent, empty-object and empty-window are three different things.** A
response with **no** `payment_methods` key at all is an older API: omit the
section entirely and do not throw. A present-but-`{}` block — which
`payment_method_breakdown()` returns for a tenant with no analytics schema — has
no `methods` array and no `coverage`, and must also render nothing rather than
crash on a property of `undefined`. A block with a `methods` array of length zero
is a real window that had no attributable orders: render the section with a
sentence, and still render the no-method bucket from requirement 2.3, because in
that window the bucket is the entire story.

The first case is not hypothetical. `platform/__tests__/fixtures/analytics/revenue-summary.json`
contains **no `payment_methods` key** — verified, the string `payment` does not
occur in it — and that fixture is protected under this contract and cannot be
updated. So `platform/__tests__/unit/analytics/revenue.render.test.tsx` renders
this page against a payload with the block absent, and it must keep passing
untouched. Guard on the key's presence before every read.

### 3. The request this page sends does not change

No new query parameter, no second fetch, no `payment_methods`-shaped state, no
control that re-requests anything. With the coupon control untouched, the URL
this page sends and every figure it renders above the new section are
byte-for-byte what they are today.

This is the requirement that makes `contracts/checks/proxy_passthrough.py`
irrelevant to this task rather than merely green: that check fails a page sending
a name its proxy drops, and this page sends no new name. It is also why
`platform/app/api/analytics/revenue/route.ts` is absent from `writable_paths`.

### 4. A test that fails without this change

One new file,
`platform/__tests__/unit/analytics/test_fleet_payment_methods.test.tsx`. This
contract's `creatable_paths` admits
`platform/__tests__/unit/analytics/test_fleet_*.test.tsx` and nothing else, the
extension must be `.test.tsx` or vitest never collects it, and
`contracts/checks/new_test_bites.sh` runs it against the tree as it was before
the change and refuses the branch if it passes there.

**No existing test file, fixture or handler may be edited.**
`platform/__tests__/**` is protected, which includes the revenue fixture and
`platform/__tests__/mocks/handlers.ts`. The new test supplies its own
`payment_methods`-bearing payload by overriding the handler from inside itself
through `platform/__tests__/mocks/server.ts`, following the pattern
`platform/__tests__/unit/analytics/test_fleet_revenue_coupons.test.tsx` already
uses against this endpoint.

Assert four things, because a test that only checks the table appears passes
against a page that prints 97.83% of the store as the store:

1. **Coverage and the no-method bucket are on screen.** Given a payload whose
   `coverage.order_share` is below 1 and whose `no_method` carries a non-zero
   NULL count **and** a different non-zero empty-string count, the rendered output
   states the coverage share and both figures, distinguishably — requirement 2.3.
   This is the assertion that makes a silent `GROUP BY` impossible to ship, and
   it is the one to write first.
2. **The stored spelling survives.** A payload carrying rows for both `stripe`
   and `Stripe` renders two rows with those exact labels, in the payload's order —
   requirement 2.2.
3. **Absent and `{}` both render nothing and neither throws.** Two payloads: one
   with no `payment_methods` key, one with `payment_methods: {}`. The section is
   absent and the page renders its existing revenue figures normally in both —
   requirement 2.5, and the half that protects the untouchable fixture.
4. **The default request is unchanged.** The first render's request to
   `/api/analytics/revenue`, asserted on the URL the MSW handler received, carries
   the same keys it carries today and no new one — requirement 3.

**Cite every requirement in the diff.**
`contracts/checks/spec_requirements_cited.py` runs first in this contract's
verification list and fails the task if a numbered requirement appears nowhere in
the lines the diff adds: `{/* spec:2.3 */}` on the coverage line, `// spec:1` on
the state assignment, and so on. The leaves are 1, 2.1, 2.2, 2.3, 2.4, 2.5, 3 and
4 — eight, and the parsed list including the parent `2` is nine, against a
`max_requirements` of 12.

---

## What must not change

* **Every figure already on the revenue page.** Gross, net, refunds, the series
  and the whole coupon section keep their names, values and positions. This block
  is additive and sits below them.
* **The date window mechanism.** The breakdown is computed over the window the
  page already asks for — same bounds, same revenue-status predicate as the gross
  figure above it. Do not give it its own dates and do not touch
  `platform/components/analytics/DateRangePicker.tsx`.
* **The coupon paging state.** `couponLimit`, `moreCodesExhausted` and the
  `lastCodesReturned` ref belong to requirement 3 of
  `drafts/render-the-coupon-block-on-the-revenue-page.md`. Nothing here reads or
  writes them.
* **No figure recomputed in the client.** Not the AOVs, not the coverage shares,
  not the tail, not the no-method total. Every one is in the payload and every one
  is computed over the full window rather than over the rows on screen.

## Out of scope

* **Any backend change.** `api/**` is protected under this contract and every
  figure this task renders is already deployed. The API files above are read.
* **The revenue proxy.** `platform/app/api/analytics/revenue/route.ts` passes the
  body through unmodified and needs no edit — see requirement 3.
* **An `/analytics/payment-methods` page and the nav slot reserving it.**
  `platform/components/layout/Sidebar.tsx` is writable only under
  `contracts/dd-acquiring-page.yaml`, whose other paths are the products page and
  the products proxy, and no contract makes a `payment-methods` page directory
  writable. `drafts/revenue-by-payment-method.md` is where that was decided; it is
  a job for a person widening a contract, not something to route around.
* **Clicking a method through to the order list.** The `payment_method` filter on
  `api/analytics/routes/orders.py` exists and works, and linking to it from here
  is the obvious follow-up and a second page's concern. Requirement 2.2 exists so
  that follow-up stays possible.
* **Fixing the empty-string blind spot in the order-list filter.** Requirement 2.3
  *reports* it. Changing `if payment_method:` in
  `api/analytics/services/order_query.py` is a change to a shipped filter's
  behaviour, on a protected path, and belongs to whoever reads the number this
  renders.
* **A chart.** A handful of gateways ranked by revenue is a table.
* **Editing `specs/metorik-gap.md`.** It is in the fleet repository, which this
  contract cannot reach. The *Rarely* row closes when this merges; that is a note
  for whoever merges.

## How it is checked

Two contracts declare `work_type: dd_frontend`. This runs under
`contracts/dd-analytics-frontend.yaml`, whose writable list covers
`platform/app/(dashboard)/analytics/revenue/**`. The other,
`contracts/dd-acquiring-page.yaml`, makes only `platform/app/api/analytics/products/**`,
`platform/app/(dashboard)/analytics/products/**` and
`platform/components/layout/Sidebar.tsx` writable, so the declared path is not
writable under it. The two `dd_api` contracts —
`contracts/deadly-digital-platform-api.yaml` and `contracts/dd-order-filters.yaml`
— are a different work_type and protect `platform/**` outright.

In the order the contract runs them:

    spec_requirements_cited.py    every numbered leaf cited in the diff
    cd platform && tsc --noEmit
    cd platform && vitest run     21 files, 319 tests
    new_test_bites.sh             via vitest_one_file.sh; the added test
                                  fails without the change
    proxy_passthrough.py          two pairs, neither of them this one, and
                                  this task sends no parameter anyway

## Before this is queued

* **The payload names above were read from the shipped source on 14 Sep 2026**,
  not inferred: `payment_method_breakdown()` in
  `api/analytics/services/analytics_engine.py` and the return statement in
  `api/analytics/routes/revenue.py`. Read them again anyway, and read
  `api/tests/analytics/test_fleet_payment_methods.py` beside them — it asserts on
  every key and is the cheapest confirmation that the wire shape has not moved.
* **The key is `payment_methods`, top-level, not inside `summary`.** The API
  spec's requirement 1 asked for it inside, and the implementation put it one
  level out because `api/tests/analytics/test_fleet_coupons.py` pins that dict's
  key set with `==`. The docstring records the change. A page that reads
  `json.summary.payment_methods` finds nothing and renders nothing, and every
  check here goes green.
* **Line 210 is the whole reason this is not a zero-line task.** Verify that
  `setData` still reconstructs state from two named keys before relying on
  requirement 1's framing; if the handler has been changed to store the response
  whole, requirement 1 collapses to the interface field and nothing else.
* **This merges with nobody reading it.** `auto_merge` is `true` on
  `contracts/dd-analytics-frontend.yaml` since 10 Sep 2026 and that file's header
  sets out the cost: seven of eight requirements can ship with every check green
  and no revert triggered, because there is nothing to revert. The `spec:N` tokens
  in the diff are the only trace. If one requirement is read against the diff by
  hand, make it 2.3 — the section looks finished without it and is wrong only to
  somebody who knows about the 61,647 orders.
* **The 2,782,530 / 2,844,177 figures are quoted from `specs/metorik-gap.md`**,
  not re-measured here. Nothing above depends on their exact values, only on the
  shape: a well-populated column with a tail large enough to matter.
