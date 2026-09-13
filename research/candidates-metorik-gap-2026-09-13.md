# Candidates from the Metorik gap list — 13 September 2026

Batch 14. Produced from `specs/metorik-gap.md`, read in the worktree for this
task at fleet `baa5d04`, and re-verified against `deadly-digital-platform` at
`71a60e61f9ca8df61351b8c43fb4f9880a2bfaf8` (`main`, read from
`.git/refs/heads/main`; every probe below reads the working tree at that
checkout).

**Seven candidates**, `ordering: unranked`. They are printed grouped by the
file pair they would edit, which is neither the document's band order nor a
ranking. Candidate order is read as rank order by whoever loads this, so it is
said here as well as in the block: **I did not rank these.**

---

## 1. What this run is for, and why it is not the last three

Gate 2 was removed on 13 September 2026 (`specs/auto-approval.md` §9.11a). Until
today a row outside the newest producer batch was held as `older_batch`, so a
new batch shelved the pool by existing. It no longer does, and two things follow
that point in opposite directions.

Nothing here suppresses anything. A row I do not carry stays in the pool and is
judged on its own probes; a row I do carry wins only if it is better, and only
once both rows have passed every gate.

And **a row with no premise can no longer be approved at all**. Sixteen of the
eighteen open rows predate the `premise` key and are unapprovable for that
reason alone, whatever their probes say. So the single most valuable thing this
run does is give the live work a premise — a claim in words about what must
ALREADY be true, with one predicate from the closed vocabulary under it. Three
of the seven rows below are old work re-emitted with today's paths, probes and
premise, which `specs/approval-surface.md` §7 says is the repair. None of them
is an edit to an old row.

## 2. The two rows that were one sentence from shipping

Both were confirmed open in the checkout by hand this morning, both re-execute
at HEAD, and both were held only because they carry no premise.

**c21 — net revenue beside gross on the analytics dashboard.** Carried as
candidate 1, and the ground has moved in its favour since it was written.
`dashboard_overview()` now returns `net_revenue`, `refunded_amount` and
`orders_with_refund` from the same query as gross revenue, over the identical
revenue-status rows (`api/analytics/services/analytics_engine.py:302-330`), and
the proxy at `platform/app/api/analytics/dashboard/route.ts:44` hands the
response body back unmodified. All three figures already arrive at the page.
`platform/app/(dashboard)/analytics/page.tsx` mentions `net_revenue` zero times
and the string `refund` zero times, case-insensitively, across 568 lines. This
is now a one-file frontend row: no proxy change, no query, nothing to compute.

c31 was approved for this work and its tasks merged. What they established is
refund coverage in the engine — `GREATEST(orders.refund_total,
EXCLUDED.refund_total)` on re-sync and the three keys travelling together — not
the figure on a surface. The gap the document names is still open.

**c37 — payment-method breakdown.** Carried as candidate 2, re-scoped. The page
the old row names, `platform/app/(dashboard)/analytics/payment-methods/page.tsx`,
does not exist and **cannot be created by any contract**: the frontend contract
enumerates the page directories it may write and that is not one of them. So the
row names `api/analytics/routes/revenue.py` and
`api/analytics/services/analytics_engine.py`, where the string `payment_method`
appears zero times in either file, and puts the breakdown on the reachable
`/analytics/revenue` surface beside the coupon block that shipped there. c50 was
approved for this in batch 13 and its spec task 66 FAILED; that is one prior
attempt on this work_key, and the repeat-failure stop is two.

## 3. The five rows no batch has re-emitted since 9 September

Re-verified one at a time. Two are carried, three are dropped, and the drops are
about the work rather than about the paperwork.

**c18 — export with chosen columns rather than a fixed header. CARRIED as
candidate 3, and its ground changed underneath it.** When c18 was written there
was no order export at all. There is one now: `GET /orders/export`
(`api/analytics/routes/orders.py:135`) streams the filtered order list as
`text/csv` from `export_orders_csv()`, and the header is one module-level tuple,
`ORDER_EXPORT_COLUMNS` in `api/analytics/services/order_query.py:75`, seventeen
columns in a fixed order for every caller. So the row stops being "build an
export" and becomes "let the export that shipped choose its columns", which is
a smaller, better-grounded piece of work than the one that sat in batch 8. The
old row carried no probes; this one carries three and a premise.

**c25 — segment orders and products, not only customers. DROPPED as written and
CARRIED as its buildable descendant, candidate 6.** As written it names
`platform/app/(dashboard)/segments/builder/page.tsx`, which no contract on this
repo makes writable, so no task can be queued for it however it is ranked.
`research/segmentation-model-2026-09-11.md` §4 recommends against
resource-generic segmentation on the evidence of these two stores and §5 names
the first buildable step: let the order list filter on several values per field
instead of one exact match. That step has **not** shipped —
`api/analytics/services/order_query.py` still builds four `o.<column> = :param`
clauses and `List[str]` appears zero times in `api/analytics/routes/orders.py`.

**c24 — scheduled digests of the dashboard. DROPPED, and not only for its
path.** It names `api/analytics/routes`, a directory, which is the shape
`specs/candidate-paths-must-be-buildable.md` §1 describes and which can never
match a glob. Rewriting the path does not save it. A digest needs something that
runs on a timer and something that delivers; `api/worker.py` is protected by both
platform contracts, `api/services/email_sender.py` is on `protected_path_floor`,
and every one of the api contract's twenty-seven writable files is reached from
a request. There is no writable file in any contract that a schedule could call.
This is a person's change, not unattended work.

**c26 — cross-store roll-up for an agency. DROPPED, for a reason deeper than its
paths.** It names `api/analytics/schema_context.py`, which is not one of the api
contract's twenty-seven files, plus two directories. Beyond that: analytics is
per-tenant throughout, through `analytics_schema_name(tenant.id)`, so a roll-up
is a new cross-tenant surface and therefore a new route module — and the api
contract **enumerates files and carries no glob**, so no new module in
`api/analytics/routes/` can be written by any task at all. The value of the row
also rests on the agency partner, who has not signed; `principles.md` forbids
inventing a counterparty's habits.

**c27 — profit dashboard: revenue, COGS, ad spend, fees. DROPPED, and the
rationale rather than the gate should be what says so.** There is no cost column
anywhere in the analytics schema — `analytics_2.products` is
`id, wc_product_id, name, sku, price, category, status` — so the work needs a
product-cost column, a column needs a schema change, and a schema change here is
floored: nothing under the analytics migrations tree may be written, by any
contract, however the row is scoped. Naming that file and letting gate 5 find it
is how this row has spent four days. It is recorded here as a refusal instead.
The prior question is anyway not a schema one: cost data is a feed HIB would
have to supply, and nobody has been asked for it.

## 4. What shipped since batch 12, and the three endpoints it left unreachable

Four of batch 12's six rows are now built, and I checked each rather than
assuming it:

| Batch 12 row | At `71a60e6` |
|---|---|
| CSV export of the order list | **Shipped**, api side. `orders.py:135`, `order_query.py:280`, `MAX_EXPORT_ROWS = 50000`, a 400 rather than a truncated file. |
| Coupon and discount performance | **Shipped**, api side. `revenue_summary()` returns a `coupons` block with per-code rows, a server-clamped `coupon_limit`, a `not_returned` tail and eight named disagreement counts. |
| Product categories | **Shipped**, api side. `GET /products/categories` (`api/analytics/routes/products.py:108`) with coverage and a `state` that separates "no category data" from "no sales". |
| Header-vs-line-items residual | **Shipped**. `order_items` now appears in `api/analytics/services/reconciliation.py`. |
| Multi-value order filters | **Not shipped.** Carried as candidate 6. |
| Payment-method breakdown | **Not shipped.** Carried as candidate 2, and it is c37. |

**And three of the four that shipped reach nobody.** This is the api→frontend
carry gap — FEAT-035's family — which batch 12 declared spent on the evidence of
the proxies as they then stood. It is not spent; it reopened the moment the API
moved:

* the order export has no proxy route and no control on the orders page
  (`csv`, `download` and `/export` all appear zero times in
  `platform/app/(dashboard)/analytics/orders/page.tsx`);
* the coupon block is in the `/revenue` payload and the string `coupon` appears
  zero times in both `platform/app/(dashboard)/analytics/revenue/page.tsx` and
  `platform/app/api/analytics/revenue/route.ts`;
* `/products/categories` has no proxy under
  `platform/app/api/analytics/products/` and the products page never requests it.

Candidates 4, 5 and 7 are those three. They are the cheapest rows in this batch
by a distance — the number is computed, correct and paid for, and what is
missing is the last few lines that put it in front of somebody.

## 5. The buildable-path predicate, applied to every row before it was written

`specs/candidate-paths-must-be-buildable.md` states it: a path is buildable when
**at least one contract for the repo makes it writable and does not protect
it.** The shape check does not ask this yet — it asks whether the path resolves,
and a directory resolves — so it was applied by hand here, per row, against
`contracts/*.yaml` with `repo: deadly-digital-platform`.

    1  platform/app/(dashboard)/analytics/page.tsx          dd-analytics-frontend
    2  api/analytics/routes/revenue.py, analytics_engine.py deadly-digital-platform-api
    3  api/analytics/routes/orders.py, order_query.py       deadly-digital-platform-api
    4  .../analytics/orders/page.tsx, api/.../orders/route.ts   dd-analytics-frontend
    5  .../analytics/revenue/page.tsx, api/.../revenue/route.ts dd-analytics-frontend
    6  api/analytics/routes/orders.py, order_query.py       deadly-digital-platform-api
    7  .../analytics/products/page.tsx, api/.../products/route.ts dd-analytics-frontend

Every path is a FILE that exists today, every one is inside one contract's
`writable_paths`, and none is on any contract's `protected_paths` or on
`protected_path_floor`. No row names a directory, a migration, or a file outside
every boundary.

**One wrinkle, stated here once so no rationale has to carry it twice.**
Candidates 4 and 7 each need a NEW proxy file —
`platform/app/api/analytics/orders/export/route.ts` and
`platform/app/api/analytics/products/categories/route.ts`. Both are writable:
`dd-analytics-frontend.yaml` grants `platform/app/api/analytics/orders/**` and
`platform/app/api/analytics/products/**` as directory globs, and
`runner/boundary.py` permits an ADDED path that matches a writable glob. Neither
can be listed in `suggested_paths`, because `candidate_block_shape.py` requires
a suggested path or its parent directory to exist and these parents do not yet.
So each row names the existing proxy beside the new one and says in its
rationale where the new file goes. A draft that puts a CSV branch inside the
existing `orders/route.ts` instead would send a `format` parameter that
`contracts/checks/proxy_passthrough.py` finds the proxy does not forward, and
fail — which is the specific mistake the rationale is written to prevent.

## 6. What I turned down, and why

`principles.md`: *"Rejections are the informative half."*

**Everything in §3's three drops**, which are not repeated here.

**Refund reports, and the nullable `refund_total` column.**
`research/refund-coverage.md` returned an explicit no-go on reporting refunds as
a rate: the column is `NOT NULL DEFAULT 0` and the writer coerces an absent
field to zero, so no query can separate a store with no refunds from a store
whose refunds were never reported. The repair is a nullable column, which is a
schema change on the floor. Candidate 1 is deliberately narrower than that
thread and survives it: it renders `refunded_amount` and `orders_with_refund`
BESIDE the net figure, so the page says "no refund is recorded against these
orders" rather than "refunds netted to nothing", which is the distinction the
engine's own docstring insists on and the one this data cannot otherwise carry.

**A digest, a scheduled export, a multi-store roll-up, subscriptions, carts,
device, variation and custom-meta reporting.** Turned down for the reasons batch
12 gave, re-verified and unmoved: no scheduler a contract may write, no
subscription or cart table, no device field, no variation id, and
`research/gap-list-open-questions.md` measures `order_items.sku` at 0 of
4,488,746.

**Net revenue on the revenue page.** `revenue_report()` carries `net_revenue`
per period and `platform/app/(dashboard)/analytics/revenue/page.tsx` never
mentions it, so this is real and it is a second row on a file candidate 5
already claims. Held back rather than emitted: two rows on one page serialise
behind gate 3 for no gain, and the next batch can carry it once candidate 5 has
landed or lapsed.

**Orders by currency, and multi-currency.** Every order on both tenants is GBP,
so the report renders one line.

**A trust row.** I looked for one and could not write one. The four trust threads
this document has produced are each unbuildable for a stated reason: the
nullable refund column is a migration, the `analytics_engine.py` docstring
correction changes no behaviour and so cannot pass `new_test_bites.sh`, the
segment-sync defect lives in files no contract makes writable, and the
header-versus-line-items residual has now shipped. All seven rows below are
therefore parity, and the block's `objectives_considered` argues that rather
than asserting it.

## 7. The candidates

```fleet-candidates
source:
  document: specs/metorik-gap.md
  sha: baa5d04
  repo: fleet

ordering: unranked

objectives_considered: >
  Weighed dd-trustworthy against dd-feature-parity row by row, because
  principles.md ranks trust above parity and objectives-2026-Q4.yaml warns that
  dd-feature-parity without a baseline "ranks build another report forever" and
  that parity work "must not outrank correctness work by default". Every row
  here is parity, and that is the shape of the defect batch 9 was refused for,
  so it is argued rather than asserted. I looked for a trust row and the four
  trust threads this gap list has produced are each unbuildable today: the
  nullable refund_total column that would make a refund rate interpretable is a
  schema change on the protected floor, the analytics_engine docstring
  correction changes no behaviour and so cannot pass the added-test gate, the
  segment-sync defect named in research/segmentation-model-2026-09-11.md lives
  in files no contract makes writable, and the header-versus-line-items residual
  that WAS the trust row of batch 12 has shipped. Candidate 1 is the closest
  thing to a correctness row and I have labelled it parity honestly: the
  dashboard's Revenue figure is gross and correctly labelled gross, so this adds
  a figure rather than fixing a wrong one, and it carries a trust CONSTRAINT
  instead — net must ship beside refunded_amount and orders_with_refund or the
  page starts telling two stories about a store with no recorded refunds. I
  considered dd-first-revenue for the multi-store roll-up and rejected the row
  rather than the label: the agency partner is unsigned, so the row's value is
  an assumption about a counterparty who has agreed to nothing. cost-discipline
  is neither served nor threatened; every row is query or render work over data
  that already exists and none adds a fixed monthly cost.

unasked_question: >
  Nobody has asked HIB's team, or the unsigned agency partner, which of these
  reports they would open. Every coverage figure below describes what HIB's
  store HAS, not what anybody WANTS from it, and the two are different claims:
  payment_method being populated on 97.83% of orders says a breakdown is
  possible, not that anyone would read it twice. The gap document's whole
  Agency-use column is one person's estimate with no agency behind it and says
  so, and DD holds no event, session or page-view table on any schema, so this
  cannot be settled later by observation either. One conversation asking which
  three of these they would open in their first week would replace the ordering
  of this entire batch with something measured. There is a sharper version of it
  for this batch specifically: three of these seven rows exist only because a
  shipped endpoint reaches no page, and nobody has said whether the reports
  already on those pages get opened at all.

candidates:

  - title: Show net revenue after refunds beside gross on the analytics overview
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 71a60e61f9ca8df61351b8c43fb4f9880a2bfaf8
    rationale: >
      The gap document's first Daily finding is that nothing in DD nets revenue
      of refunds. Half of it is closed: dashboard_overview() returns net_revenue,
      refunded_amount and orders_with_refund computed in one query over exactly
      the rows gross revenue is summed from, and the dashboard proxy returns the
      API's body unmodified, so all three figures already arrive at the browser.
      The overview page throws them away — net_revenue appears zero times in it
      and so does the string refund, case-insensitively, in 568 lines. This is
      one file, no proxy change and no query. The trust constraint is the whole
      of the spec's difficulty and must be stated in it: net ships BESIDE gross
      and beside the other two keys, never instead of gross, because
      net_revenue == revenue is the common case on this data and has to read as
      "no refund is recorded against these orders" rather than "refunds netted
      to nothing" — the engine's own docstring makes that distinction and a page
      that renders one number without the count collapses it. c31 was approved
      for this work and merged the engine half; it established refund coverage
      and did not surface the figure.
    evidence:
      - document: specs/metorik-gap.md
        sha: baa5d04
        repo: fleet
        section: "Daily — Net revenue (gross less refunds) on the main figures"
      - document: research/refund-coverage.md
        sha: baa5d04
        repo: fleet
        section: "what the refund_total column can and cannot be asked"
    suggested_paths:
      - platform/app/(dashboard)/analytics/page.tsx
    hib_signal:
      value: refund_total is non-zero on 1 of 2,844,177 orders on tenant 2, traced to backfill coverage rather than a broken sync — which is exactly why the count of refunded orders must be rendered beside the money, since the figure a merchant will usually see is zero
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: refund_total
        populated: 1
        total: 2844177
    probes:
      - path_exists: platform/app/(dashboard)/analytics/page.tsx
      - grep_count:
          glob: platform/app/(dashboard)/analytics/page.tsx
          pattern: 'net_revenue|refunded_amount|orders_with_refund'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/page.tsx
          pattern: '[Rr]efund'
          expected: 0
    premise:
      - claim: >
          The dashboard endpoint already returns net_revenue together with
          refunded_amount and orders_with_refund from one query, so this work
          renders three figures the response carries rather than computing any
          of them.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: '"orders_with_refund": int'
            expected: 4
      - claim: >
          The dashboard proxy hands the API's response body back unmodified, so
          the three keys reach the page today and no proxy change is part of
          this work.
        probe:
          grep_count:
            glob: platform/app/api/analytics/dashboard/route.ts
            pattern: 'NextResponse\.json\(data'
            expected: 1

  - title: Break revenue down by payment method, naming the orders that carry none
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 71a60e61f9ca8df61351b8c43fb4f9880a2bfaf8
    rationale: >
      Still true and re-measured: payment_method reaches the order list as a
      filter, a column and a clickable cell, and nothing aggregates by it — the
      string appears zero times in revenue.py and zero times in
      analytics_engine.py. Two things the spec must decide rather than let the
      implementation discover. First, 61,647 orders carry no payment method, so
      the breakdown either names that bucket or quietly reports on 97.83% of the
      store as though it were all of it — the same scruple the coupon block that
      shipped applies with its not_returned tail. Second, it belongs on
      revenue.py beside that coupon block and on the /analytics/revenue page
      that already exists: Sidebar.tsx reserves /analytics/payment-methods, that
      directory is in no contract's writable set, and a candidate naming it can
      only be refused. Carried in the band the document gives it, Rarely, rather
      than promoted because its column happens to be the best populated on the
      page — the band estimates how often somebody opens the thing and the
      coverage is a fact about HIB's data, and promoting on the second would
      answer the first question with the wrong evidence.
    evidence:
      - document: specs/metorik-gap.md
        sha: baa5d04
        repo: fleet
        section: "Rarely — Payment method breakdown"
    suggested_paths:
      - api/analytics/routes/revenue.py
      - api/analytics/services/analytics_engine.py
    hib_signal:
      value: payment_method populated on 2,782,530 of 2,844,177 orders on tenant 2, leaving 61,647 with none — a breakdown must name that bucket rather than drop it
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: payment_method
        populated: 2782530
        total: 2844177
    probes:
      - path_absent: platform/app/(dashboard)/analytics/payment-methods/page.tsx
      - grep_count:
          glob: api/analytics/routes/revenue.py
          pattern: 'payment_method'
          expected: 0
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'payment_method'
          expected: 0
      - grep_count:
          glob: platform/components/layout/Sidebar.tsx
          pattern: '/analytics/payment-methods'
          expected: 1
    premise:
      - claim: >
          payment_method is already declared as an exact query parameter on both
          the order list and the order export, so the values a breakdown groups
          by are values the product already treats as a dimension.
        probe:
          grep_count:
            glob: api/analytics/routes/orders.py
            pattern: 'payment_method: str = Query'
            expected: 2

  - title: Let the order export choose its columns instead of emitting one fixed header
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 71a60e61f9ca8df61351b8c43fb4f9880a2bfaf8
    rationale: >
      Re-verified rather than quoted, and the ground has moved since this row was
      first written in batch 8. There is now an order export — GET /orders/export
      streams the filtered list as text/csv — and its header is a single
      module-level tuple, ORDER_EXPORT_COLUMNS, seventeen columns in a fixed
      order for every caller, written before anything can return early and read
      back once per row. The word columns appears nowhere in the route module, so
      there is no way to ask for a subset or a different order. That is the gap
      the document names, and it is now a small widening of working code rather
      than a new feature: a repeated query parameter, validated against the same
      tuple so an unknown name is a 400 rather than a blank column, defaulting to
      the full tuple in its current order when the parameter is absent. Two
      properties must survive and belong in the spec: the header the file starts
      with is exactly the columns the rows carry, and the export's population is
      still the page's population through the shared where-clause. Custom fields
      are NOT in this row — the sync ingests no custom meta, so offering them
      would be offering an empty column.
    evidence:
      - document: specs/metorik-gap.md
        sha: baa5d04
        repo: fleet
        section: "Daily — Export with chosen columns, reordered, incl. custom fields"
    suggested_paths:
      - api/analytics/routes/orders.py
      - api/analytics/services/order_query.py
    hib_signal: null
    probes:
      - path_exists: api/analytics/services/order_query.py
      - grep_count:
          glob: api/analytics/routes/orders.py
          pattern: 'columns'
          expected: 0
      - grep_count:
          glob: api/analytics/services/order_query.py
          pattern: 'ORDER_EXPORT_COLUMNS'
          expected: 3
    premise:
      - claim: >
          A working order export already exists on this route, so this widens an
          endpoint that ships a file today rather than introducing exporting to
          the order list.
        probe:
          grep_count:
            glob: api/analytics/routes/orders.py
            pattern: '@router\.get\("/export"\)'
            expected: 1

  - title: Put the order CSV export in front of a merchant — proxy route and a download control
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 71a60e61f9ca8df61351b8c43fb4f9880a2bfaf8
    rationale: >
      The API half of the document's Daily CSV-export row shipped and reaches
      nobody. GET /orders/export returns text/csv with every filter the order
      list takes, and on the frontend the strings csv, download and /export
      appear zero times on the orders page and zero times in its proxy. This is
      FEAT-035's family — a capability that exists, is deployed, and has no door.
      The work is a proxy route that streams the CSV back with its
      Content-Disposition intact, and a control on the orders page that links to
      it carrying the filters currently in force, so the file and the table
      describe the same population. The new proxy belongs at
      platform/app/api/analytics/orders/export/route.ts, which the frontend
      contract makes writable through its platform/app/api/analytics/orders/**
      glob; it is not in suggested_paths only because the shape check requires a
      suggested path's parent directory to exist. It must be a new file rather
      than a format branch inside the existing orders proxy: a page sending a
      parameter that proxy does not forward is exactly what
      proxy_passthrough.py refuses. Two behaviours the spec must name: the 400
      the API raises above 50,000 matched rows has to become a message a person
      can act on, and the header-only file for a filter matching nothing must
      not be presented as a failure.
    evidence:
      - document: specs/metorik-gap.md
        sha: baa5d04
        repo: fleet
        section: "Daily — CSV export of orders / customers / products"
    suggested_paths:
      - platform/app/(dashboard)/analytics/orders/page.tsx
      - platform/app/api/analytics/orders/route.ts
    hib_signal: null
    probes:
      - path_absent: platform/app/api/analytics/orders/export/route.ts
      - grep_count:
          glob: platform/app/(dashboard)/analytics/orders/page.tsx
          pattern: 'csv|Download|download|/export'
          expected: 0
      - grep_count:
          glob: platform/app/api/analytics/orders/route.ts
          pattern: 'export_orders|/export|csv'
          expected: 0
    premise:
      - claim: >
          The API endpoint this row would expose already exists and already
          returns a CSV media type, so the frontend carries a working export
          rather than waiting on one.
        probe:
          grep_count:
            glob: api/analytics/routes/orders.py
            pattern: 'media_type="text/csv"'
            expected: 1
      - claim: >
          Every filter the export accepts is already forwarded by the orders
          proxy for the list, so the download can reuse the filter values the
          page is holding without introducing a parameter name the frontend has
          never sent.
        probe:
          grep_count:
            glob: platform/app/api/analytics/orders/route.ts
            pattern: "'payment_method', 'country', 'coupon', 'has_discount'"
            expected: 1

  - title: Render the coupon and discount block the revenue endpoint already returns
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 71a60e61f9ca8df61351b8c43fb4f9880a2bfaf8
    rationale: >
      The Weekly coupon row is built in the API and invisible in the product.
      revenue_summary() returns a coupons block — per-code rows ranked by
      discount total, a server-clamped coupon_limit, a not_returned tail that
      accounts for every code left out, and eight named disagreement counts
      between coupon_code and discount_total — and the string coupon appears
      zero times in both the revenue page and the revenue proxy. The block
      arrives in the payload at its default limit today, so the page can render
      it with no API change at all; forwarding coupon_limit is the only proxy
      work, and it is what lets a reader ask for more than twenty codes. Two
      things the spec must carry from the payload rather than invent: the tail
      must be shown, because a top-20 over 65,444 codes covers 0.03% of them and
      a table that does not say so reads as the whole store, and an empty block
      must render as "no coupon orders in this window" rather than as nothing.
      It must not name Sidebar.tsx or a /analytics/coupons page — that directory
      is in no contract's writable set, so the reserved nav slot cannot be filled
      by an unattended task however this is cut.
    evidence:
      - document: specs/metorik-gap.md
        sha: baa5d04
        repo: fleet
        section: "Weekly — Coupon and discount performance: usage, discount total, orders, AOV with/without"
    suggested_paths:
      - platform/app/(dashboard)/analytics/revenue/page.tsx
      - platform/app/api/analytics/revenue/route.ts
    hib_signal:
      value: coupon_code populated on 146,136 of 2,844,177 orders on tenant 2 and discount_total on 146,043 — the 5.14% is the share of orders that used a coupon rather than missing data, and the engine now counts the 93-order disagreement between the two columns explicitly
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: coupon_code
        populated: 146136
        total: 2844177
    probes:
      - path_absent: platform/app/(dashboard)/analytics/coupons/page.tsx
      - grep_count:
          glob: platform/app/(dashboard)/analytics/revenue/page.tsx
          pattern: 'coupon'
          expected: 0
      - grep_count:
          glob: platform/app/api/analytics/revenue/route.ts
          pattern: 'coupon'
          expected: 0
      - grep_count:
          glob: platform/components/layout/Sidebar.tsx
          pattern: '/analytics/coupons'
          expected: 1
    premise:
      - claim: >
          The revenue endpoint already computes the coupon block server-side and
          already accepts the parameter that sizes it, so the page renders a
          payload it receives rather than asking for a report to be built.
        probe:
          grep_count:
            glob: api/analytics/routes/revenue.py
            pattern: 'coupon_limit'
            expected: 3

  - title: Let the order list filter on several values per field instead of one exact match
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 71a60e61f9ca8df61351b8c43fb4f9880a2bfaf8
    rationale: >
      Re-emitted rather than edited, and still not built. The order route takes
      status, payment_method, country, coupon and has_discount, the proxy
      forwards all of them and the page offers controls — but every one is a
      single exact value: order_query.py builds four o.<column> = :param clauses
      and nothing emits an IN list, so "completed or processing" and "PayPal or
      Stripe", which are the first two things anyone asks an order list for,
      cannot be expressed. This is candidate 25's buildable descendant rather
      than my own invention of a next step: research/segmentation-model-2026-09-11.md
      §5 names exactly this as the largest piece of its recommendation that fits
      a contract today, names both files, and notes it is the only first step
      that survives the segmentation decision being reversed. Accepting a
      repeated query parameter and emitting IN with bound parameters keeps
      order_query.py's existing discipline — allow-listed fields, bound values, a
      total order ending in the primary key so paging cannot drop rows — and adds
      no module. Under the api contract rather than dd-order-filters.yaml, whose
      shape check is pinned to the single-value form task 2 delivered.
    evidence:
      - document: specs/metorik-gap.md
        sha: baa5d04
        repo: fleet
        section: "Daily — Order filtering: status, payment, shipping, location, customer tags, email engagement, products contained"
      - document: research/segmentation-model-2026-09-11.md
        sha: baa5d04
        repo: fleet
        section: "5. The first buildable task, and its contract"
    suggested_paths:
      - api/analytics/routes/orders.py
      - api/analytics/services/order_query.py
    hib_signal:
      value: payment_method populated on 2,782,530 of 2,844,177 orders on tenant 2 across nine distinct payment methods, so a multi-value gateway filter has something to discriminate between
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: payment_method
        populated: 2782530
        total: 2844177
    probes:
      - grep_count:
          glob: api/analytics/services/order_query.py
          pattern: 'o\.(status|payment_method|billing_country|coupon_code) = :'
          expected: 4
      - grep_count:
          glob: api/analytics/routes/orders.py
          pattern: 'List\[str\]'
          expected: 0
    premise:
      - claim: >
          The four filters already exist on the route as single-value exact
          query parameters, so this work widens filters that are there rather
          than adding filters that are not.
        probe:
          grep_count:
            glob: api/analytics/routes/orders.py
            pattern: 'payment_method: str = Query'
            expected: 2

  - title: Make the product category breakdown reachable from the products page
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 71a60e61f9ca8df61351b8c43fb4f9880a2bfaf8
    rationale: >
      The Weekly product-performance-by-category row is built in the API and
      reaches nobody. GET /products/categories returns revenue and units grouped
      by category with a coverage object and a state that separates "no category
      data" from "no sales", and on the frontend there is no proxy under
      platform/app/api/analytics/products/ for it and the products page never
      requests it — the only mentions of the word category on that page are two
      comments recording a column that was removed. The work is a proxy route
      and a breakdown on the existing products page. The new proxy belongs at
      platform/app/api/analytics/products/categories/route.ts, writable through
      the contract's platform/app/api/analytics/products/** glob and absent from
      suggested_paths only because the shape check requires a parent directory
      that does not exist yet. One property must come from the endpoint's own
      docstring into the page: the per-category rows deliberately do NOT sum to
      the revenue total, because a product in three categories is credited to
      all three, so a page that prints them under a total without saying so
      shows an arithmetic that does not hold.
    evidence:
      - document: specs/metorik-gap.md
        sha: baa5d04
        repo: fleet
        section: "Weekly — Product performance by category / vendor / brand"
    suggested_paths:
      - platform/app/(dashboard)/analytics/products/page.tsx
      - platform/app/api/analytics/products/route.ts
    hib_signal: null
    probes:
      - path_absent: platform/app/api/analytics/products/categories/route.ts
      - grep_count:
          glob: platform/app/api/analytics/products/route.ts
          pattern: 'categor'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/products/page.tsx
          pattern: '/api/analytics/products/categories'
          expected: 0
    premise:
      - claim: >
          The category endpoint exists and is mounted on the products route
          module, so this row exposes a report that already answers rather than
          asking for the report to be written.
        probe:
          grep_count:
            glob: api/analytics/routes/products.py
            pattern: '@router\.get\("/products/categories"\)'
            expected: 1
```

---

## 8. File contention, and an order to approve these in

Rows 3 and 6 both sit on `api/analytics/routes/orders.py` and
`api/analytics/services/order_query.py`; rows 1, 4, 5 and 7 are each on a
different page and proxy and contend with nothing. Gate 3 holds a candidate
whose suggested path a live task declares, so the two api rows serialise rather
than collide — the cost is a night, not a row. If the order matters to whoever
ticks these:

    1  net revenue on the overview       analytics/page.tsx            no contention
    4  order export, reachable           orders page + orders proxy    no contention
    5  coupon block, reachable           revenue page + revenue proxy  no contention
    7  categories, reachable             products page + products proxy no contention
    2  payment-method breakdown          revenue.py, analytics_engine.py
    6  multi-value order filters         orders.py, order_query.py
    3  export column selection           orders.py, order_query.py     (after 6)

The four reachability rows are first because each is the cheapest possible
version of a finished capability, and because a report nobody can open is worth
exactly what an absent one is.

## 9. What I could not establish

1. **Whether anybody wants any of this.** Said at length in the block's
   `unasked_question` and repeated because it is the largest limit on the page.
   Nothing here is measured demand: the Agency-use band that orders the source
   document is one person's estimate, no agency has been asked, and DD holds no
   telemetry that could answer it later.

2. **That any capability I read actually works.** Everything was established by
   reading the checkout at `71a60e6`. `AS net_revenue` appearing four times in
   `api/analytics/services/analytics_engine.py` is not four correct SQL
   statements, and a mounted `/products/categories` is not a report that returns
   the right rows. Nothing was exercised against a running API and no query was
   run against production — this contract has no shell and no credential.

3. **Every population figure is quoted, not re-run.** Each `coverage` object
   carries `as_of: 2026-08-28`: these are the gap document's figures, sixteen
   days old, tenant 2 only. `deadly_digital` also holds `analytics_1`, which
   behaves differently enough that
   `research/EVIDENCE-refund-coverage-manifests.md` is largely about the
   difference. Anything decided on these numbers is decided on a fortnight-old
   observation of one store.

4. **Whether the three unreachable endpoints are unreachable by decision.** I
   established that no page requests them. I did not establish that nobody
   intended it that way — a draft may exist, or the frontend half may be queued
   under a task row I cannot see from here, and candidates 4, 5 and 7 would then
   duplicate work already in flight. Gate 3 catches that at approval time
   against live tasks, which is the check I am relying on rather than one I ran.

5. **Whether `71a60e6`'s working tree is its commit.** Probes read the tree and
   `verified_sha` names the ref. I cannot run `git status` under this contract,
   so a dirty checkout would make the two describe slightly different things.
   The same caveat applied to batches 9 through 12 and is stated rather than
   assumed away.

6. **The premise probes are predicates, not proofs of the sentence above them.**
   `'"orders_with_refund": int'` appearing four times in the engine establishes
   that four functions return that key; the claim it sits under is that the
   DASHBOARD function is one of them. I read the function and it is
   (`analytics_engine.py:328`), but the check re-executes the predicate and not
   the reading, and that gap is the one `candidate_block_shape.py`'s own
   docstring says the premise key moves rather than closes.

7. **Whether c24's digest and c26's roll-up are wrong or merely unqueueable.** I
   dropped both on buildability — no writable scheduler, no new api module —
   and that is a statement about this system, not about the work. Both may be
   right for DD and neither can be an unattended task; if somebody wants them,
   they need a person and a contract written for them.

8. **Metorik's side.** No account and no web access in this contract, so nothing
   here checks that Metorik still ships any of these features. The parity claim
   throughout is inherited from `research/metorik-gap-2026-08-30.md`'s retrieval
   dates, read on 30 August 2026.
