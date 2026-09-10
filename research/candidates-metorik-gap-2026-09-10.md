# Candidates from the Metorik gap list — 10 September 2026

Produced 2026-09-10 from `specs/metorik-gap.md` (fleet `ef63f55`), re-verified
against `deadly-digital-platform` at `6fd8ddd5e4269278dc64bc80d1198a85871d6619`.

Nine candidates. `ordering: unranked` — they are printed in the order I wrote
them up, which is by document band, and that is not a ranking. Whoever loads
this reads candidate order as rank order, so it is said here as well as in the
block: **I did not rank these.**

---

## The re-verification, which is most of what this task was

The gap document says of itself that its counts "should be re-run, not quoted",
and it is right in a way that is worse than it sounds. Of the rows I opened,
**four had stopped being true**, and all four had moved in the same direction —
the platform gained something and the document did not notice.

| Document row | Document says | At `6fd8ddd` |
|---|---|---|
| Order filtering (Daily) | "accepts `start`, `end`, exact `status`, `search`, `sort_by`, `sort_dir`. Nothing else." | **Wrong.** `api/analytics/routes/orders.py:62-68` also accepts `payment_method`, `country`, `coupon` and `has_discount`. |
| Compare any period to any other (Daily) | "compares the window to the equal-length window immediately before it … No arbitrary range and no YoY." | **Wrong.** `api/analytics/routes/dashboard.py:26-46` takes `comparison_mode` (`previous_period`, `previous_year`, `custom`) plus `compare_start`/`compare_end`. |
| Net revenue (Daily) | "no aggregate nets it" | **Wrong.** `api/analytics/services/analytics_engine.py` computes `net_revenue`, `refunded_amount` and `orders_with_refund` in four report functions (lines 302, 730, 890, 1014), added Sep 2026. |
| Location reports (Weekly) | "built but unreachable … There is no page and no frontend proxy route" | **Wrong.** `platform/app/(dashboard)/analytics/geography/page.tsx` exists, `platform/app/api/analytics/geography/route.ts`, `.../cities/route.ts` and `.../areas/[area]/route.ts` exist, and `platform/components/layout/Sidebar.tsx:66` links it. **This row is closed and is not carried.** |

A fifth correction, smaller and in the other direction: the document's Daily
"Revenue over time" row carries the parenthetical *"documented conflict 2.1"*.
Conflict 2.1 was **fixed on 23 Aug 2026 (FEAT-035)** —
`api/analytics/services/analytics_engine.py:229` and the `-- 2.1: both sides
revenue-status` comments at lines 136, 876 and 1187 are the fix in place. There
is no live AOV conflict to carry.

### The pattern the corrections make, and it is the useful part

Three of the four stale rows are the same shape: **the analytics API gained the
capability and the Next.js layer did not carry it to a person.** That is not
three separate discoveries, it is one, and it is mechanically visible:

* `platform/app/api/analytics/orders/route.ts:7` holds a `PASSTHROUGH`
  allowlist — `start, end, status, search, page, limit, sort_by, sort_dir` —
  and silently drops every query parameter not on it. The four order filters
  the API added cannot reach the backend even if the page grew the controls.
* `platform/app/api/analytics/dashboard/route.ts:16-17` forwards `start` and
  `end` and nothing else. `comparison_mode` appears **nowhere** under
  `platform/`.
* `net_revenue` appears **nowhere** under `platform/`, in any file.

Three candidates below (1, 2, 3) are that one finding, split by document row
because a candidate is one row of one document and the work key depends on it.
Whoever specs them should know they may be nearly one piece of work.

---

## What I turned down, and why

`principles.md`: *"Rejections are the informative half."* These are rows I
re-verified as still true and still did not carry.

**Profit dashboard / product COGS and margin / payment gateway fees.** All
three are blocked on the same absent fact: there is no cost column anywhere in
the analytics schema — no `cost_price`, `cogs`, `stock_quantity` or `inventory`
in `api/analytics/`. This is not a report to build, it is a data source HIB
would have to supply, and `principles.md` says to prefer work whose evidence
Fleet can reach itself. It is worth a conversation, not a batch row.

**Digests, and recurring exports on a schedule.** Still true — no Slack, no
scheduled report, nothing. But a digest is a delivery mechanism for reports,
and three of the reports it would deliver do not exist yet. It sequences after
this batch, not inside it.

**Multi-store dashboard.** Still true, and I nearly labelled it
`dd-first-revenue` on the grounds that it is the one row on this list HIB's
team cannot use at all — HIB is one store. That is exactly the reason not to
carry it: `principles.md` says *"Do not justify a feature by an imagined
merchant. There is a real one."* The agency partner is unsigned. Building an
agency-only roll-up now is what `dd-feature-parity`'s own comment warns
against.

**Subscription reports and cart reports.** No subscription or cart table exists
in `deadly_digital` at all. Both are schema-and-sync projects gated on data DD
does not ingest, and the subscription one applies only to stores selling
subscriptions, which HIB does not.

**Refund reports (Weekly).** Genuinely still true, and deliberately folded into
candidate 3 rather than carried separately: both are the same underlying fact —
`refund_total` is non-zero on 1 order in 2,844,177 — and two rows arguing "do
not build over an empty column" is one argument taking two slots.

**The 0.42% that does not reconcile.** The document's Rarely tax row says
`total = SUM(order_items.total)` "holds to the penny on 99.58%" of 2,844,177
orders, and uses that to conclude there is no room for a tax term. The
conclusion is sound; the residual — roughly twelve thousand orders whose header
total does not match their line items — is not explained anywhere and nothing
reports it. It is trust-shaped and I wanted to carry it, but the document
states it as a percentage and leaves the count in no section, so I could not
give `coverage` both numbers without multiplying one out and presenting an
arithmetic result as a measurement. It is in *What I could not establish*
instead.

---

## The candidates

```fleet-candidates
source:
  document: specs/metorik-gap.md
  sha: ef63f55
  repo: fleet

ordering: unranked

objectives_considered: >
  Weighed dd-trustworthy against dd-feature-parity on every row, because
  principles.md ranks trust above parity and says a row where the product
  reports a wrong or misleading number outranks a row where it reports no
  number. Eight rows are parity: each is a report or filter that is simply
  absent from a person's reach, and nothing DD currently displays about them is
  incorrect. One row is not. Candidate 3 is dd-trustworthy because the API
  already returns net_revenue from four endpoints and it equals gross revenue in
  every window on every tenant, since refund_total is non-zero on one order in
  2,844,177 — that is a figure that is already wrong rather than a figure that
  is missing, and its deliverable is refund coverage in the sync, which is
  dd-trustworthy's own signal. I also considered dd-first-revenue for the
  multi-store roll-up, which is the only row here HIB's team cannot use at all,
  and rejected the row rather than the label: the agency partner is unsigned, so
  that value is an assumption about a counterparty who has not agreed to
  anything. cost-discipline is not served or threatened by any of these; they
  are all query work over tables that already exist.

unasked_question: >
  Nobody has asked HIB's team, or the unsigned agency partner, which of these
  reports they would actually open. Every coverage figure below describes what
  HIB's store HAS, not what anyone WANTS from it, and the two are different
  claims: payment_method being populated on 97.83% of orders says a payment
  method report is possible, not that anybody would look at it twice. The gap
  document's whole Agency-use column is one person's estimate with no agency
  behind it, and it says so. DD also has no telemetry that could answer this by
  observation — deadly_digital holds no event, session, page-view or activity
  table on any schema — so it cannot be inferred later from usage either. One
  conversation with HIB's team, asking which three of these they would open in
  their first week, would replace the ordering of this entire batch with
  something measured, and it is by far the cheapest thing on this page.

candidates:

  - title: Carry the four order filters the API already accepts through the Next.js proxy and onto the orders page
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 6fd8ddd5e4269278dc64bc80d1198a85871d6619
    rationale: >
      The gap document says order filtering accepts "nothing else" beyond
      status, search and the date range. That stopped being true:
      api/analytics/routes/orders.py accepts payment_method, country, coupon and
      has_discount, all exact, all narrowing the summary as well as the page.
      None of them reaches the backend from the product, because
      platform/app/api/analytics/orders/route.ts drops every parameter outside a
      PASSTHROUGH allowlist that predates them, and the orders page renders
      payment_method, billing_country and coupon_code as columns you can look at
      but not filter on. The work is a proxy allowlist and four controls over an
      endpoint that is already written and already tested — the smallest
      distance between an agency evaluating DD and a filter it expects.
    evidence:
      - document: specs/metorik-gap.md
        sha: ef63f55
        repo: fleet
        section: "Daily — Order filtering: status, payment, shipping, location, customer tags, email engagement, products contained"
    suggested_paths:
      - platform/app/api/analytics/orders/route.ts
      - platform/app/(dashboard)/analytics/orders/page.tsx
      - api/analytics/routes/orders.py
    hib_signal:
      value: payment_method populated on 2,782,530 of 2,844,177 orders on tenant 2; billing_country on 2,840,035; coupon_code on 146,136, which is most orders carrying no coupon rather than data missing
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: payment_method
        populated: 2782530
        total: 2844177
    probes:
      - path_exists: api/analytics/routes/orders.py
      - path_exists: platform/app/api/analytics/orders/route.ts
      - path_exists: platform/app/(dashboard)/analytics/orders/page.tsx
      - grep_count:
          glob: api/analytics/routes/orders.py
          pattern: has_discount
          expected: 3
      - grep_count:
          glob: platform/app/api/analytics/orders/route.ts
          pattern: payment_method|country|coupon|has_discount
          expected: 0

  - title: Carry the dashboard's selectable comparison window, including year-on-year, through to the analytics page
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 6fd8ddd5e4269278dc64bc80d1198a85871d6619
    rationale: >
      The document records this as Partial on the grounds that the dashboard
      compares only against the equal-length window immediately before. That is
      no longer where the code is: api/analytics/routes/dashboard.py takes a
      comparison_mode of previous_period, previous_year or custom, validates
      compare_start and compare_end against the mode rather than silently
      ignoring them, and the response names the window actually compared and its
      span. Year-on-year exists and is unreachable — comparison_mode appears
      nowhere under platform/, and the dashboard proxy forwards start and end
      only. Metorik's period comparison is a headline feature and DD's is
      finished, tested and invisible.
    evidence:
      - document: specs/metorik-gap.md
        sha: ef63f55
        repo: fleet
        section: "Daily — Compare any period to any other, incl. year-on-year"
    suggested_paths:
      - platform/app/api/analytics/dashboard/route.ts
      - platform/app/(dashboard)/analytics/page.tsx
      - api/analytics/routes/dashboard.py
    hib_signal: null
    probes:
      - path_exists: api/analytics/routes/dashboard.py
      - path_exists: platform/app/api/analytics/dashboard/route.ts
      - grep_count:
          glob: api/analytics/routes/dashboard.py
          pattern: COMPARISON_MODES
          expected: 3
      - grep_count:
          glob: platform/app/api/analytics/dashboard/route.ts
          pattern: comparison_mode|compare_start|compare_end
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/page.tsx
          pattern: comparison_mode|previous_year
          expected: 0

  - title: Establish refund coverage before any surface shows net_revenue, which the API already returns equal to gross
    repo: deadly-digital-platform
    objective_ref: dd-trustworthy
    verified_sha: 6fd8ddd5e4269278dc64bc80d1198a85871d6619
    rationale: >
      The document says nothing in DD nets revenue of refunds. That is now
      wrong: analytics_engine.py computes net_revenue, refunded_amount and
      orders_with_refund in four report functions. The problem is what those
      figures currently say. refund_total is non-zero on 1 order in 2,844,177,
      so net_revenue equals revenue in every window on every tenant, and an API
      field named net_revenue that is silently gross is a wrong number rather
      than a missing one — which is the case principles.md ranks above every
      parity row on this page. The frontend has not surfaced it yet, so the
      cheap correction is still available and the order matters: establish
      whether the empty history is the backfill artefact empty-columns.md traced
      it to, and whether the connector hooks WooCommerce refund events at all
      (which decides whether partial refunds on completed orders are captured),
      before a tile that says "Net revenue" goes in front of anybody.
    evidence:
      - document: specs/metorik-gap.md
        sha: ef63f55
        repo: fleet
        section: "Daily — Net revenue (gross less refunds) on the main figures"
      - document: specs/empty-columns.md
        sha: ef63f55
        repo: fleet
      - document: specs/refund-hook.md
        sha: ef63f55
        repo: fleet
    suggested_paths:
      - api/analytics/services/analytics_engine.py
      - api/analytics/services/sync_engine.py
      - api/analytics/services/order_query.py
    hib_signal:
      value: refund_total non-zero on 1 of 2,844,177 orders on tenant 2, which empty-columns.md traces to backfill coverage rather than a broken sync
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: refund_total
        populated: 1
        total: 2844177
    probes:
      - path_exists: api/analytics/services/analytics_engine.py
      - path_exists: api/analytics/services/sync_engine.py
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: AS net_revenue
          expected: 4
      - grep_count:
          glob: platform/app/(dashboard)/analytics/page.tsx
          pattern: net_revenue
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/revenue/page.tsx
          pattern: net_revenue|refunded_amount
          expected: 0

  - title: Add a CSV export of orders, customers and products beside the one segment export that exists
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 6fd8ddd5e4269278dc64bc80d1198a85871d6619
    rationale: >
      Still true at HEAD, and I checked it the way the document did rather than
      by quoting: there is exactly one text/csv response in the whole analytics
      API, at api/analytics/routes/segments.py:86, and it emits one fixed
      customer segment with a fixed column list. No order, customer or product
      export exists on either side, and there is no export proxy route under
      platform/app/api/analytics/orders/. Export is the feature an agency
      reaches for when a report does not answer its question, so it is the one
      that decides whether a missing report is an inconvenience or a wall.
    evidence:
      - document: specs/metorik-gap.md
        sha: ef63f55
        repo: fleet
        section: "Daily — CSV export of orders / customers / products"
    suggested_paths:
      - api/analytics/routes/orders.py
      - api/analytics/routes/segments.py
      - api/analytics/services/order_query.py
      - platform/app/api/analytics/orders/route.ts
    hib_signal: null
    probes:
      - path_exists: api/analytics/routes/segments.py
      - path_exists: platform/app/api/analytics/segments/[name]/export/route.ts
      - path_absent: platform/app/api/analytics/orders/export/route.ts
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: text/csv
          expected: 1

  - title: Decide whether analytics segmentation stays seven fixed RFM buckets or becomes attribute-based
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 6fd8ddd5e4269278dc64bc80d1198a85871d6619
    rationale: >
      Still true. VALID_SEGMENTS in segment_engine.py is a literal list of seven
      names assigned from an NTILE(5) RFM score, routes/segments.py rejects
      anything outside it with a 400, and only customers are segmentable at all.
      Metorik's central claim is that any resource can be segmented by any of its
      attributes, so this is the widest single gap on the document and also the
      most expensive, which is why it is phrased as a decision rather than a
      build. The document flags one thing it did not check that would narrow it:
      whether the email side's rule builder can express analytics filters. That
      is a read, and it should happen before anything is designed.
    evidence:
      - document: specs/metorik-gap.md
        sha: ef63f55
        repo: fleet
        section: "Daily — Segment any resource (orders, customers, products, coupons, subscriptions, carts) by any attribute, AND/OR groups"
    suggested_paths:
      - api/analytics/services/segment_engine.py
      - api/analytics/routes/segments.py
      - platform/app/(dashboard)/analytics/segments/page.tsx
    hib_signal:
      value: all seven RFM buckets populated on tenant 2, so the fixed scheme works on HIB's data and the gap is expressiveness rather than emptiness
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage: null
    probes:
      - path_exists: api/analytics/services/segment_engine.py
      - path_exists: api/analytics/routes/segments.py
      - grep_count:
          glob: api/analytics/services/segment_engine.py
          pattern: VALID_SEGMENTS
          expected: 2
      - grep_count:
          glob: api/analytics/routes/segments.py
          pattern: VALID_SEGMENTS
          expected: 3

  - title: Build the coupon and discount performance report the sidebar already reserves a slot for
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 6fd8ddd5e4269278dc64bc80d1198a85871d6619
    rationale: >
      Still true. The string "coupon" appears in the whole of
      api/analytics/routes/ only as the order-list filter added recently — three
      occurrences, all in orders.py — so no endpoint aggregates by it, and
      Sidebar.tsx:47 still lists /analytics/coupons among pages that do not
      exist. The data is there: coupon_code and discount_total are populated on
      146,136 and 146,043 orders, and that 5.14% is not thin data, it is the
      share of orders that used a coupon, which is the thing the report exists to
      measure. The 93-order difference between the two columns is worth a look
      while somebody is in there.
    evidence:
      - document: specs/metorik-gap.md
        sha: ef63f55
        repo: fleet
        section: "Weekly — Coupon and discount performance: usage, discount total, orders, AOV with/without"
    suggested_paths:
      - api/analytics/routes/orders.py
      - api/analytics/services/order_query.py
      - platform/components/layout/Sidebar.tsx
      - platform/app/(dashboard)/analytics/revenue/page.tsx
    hib_signal:
      value: coupon_code populated on 146,136 of 2,844,177 orders on tenant 2, and discount_total on 146,043 — the 5.14% is orders that used a coupon, not missing data
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: coupon_code
        populated: 146136
        total: 2844177
    probes:
      - path_absent: api/analytics/routes/coupons.py
      - path_absent: platform/app/(dashboard)/analytics/coupons/page.tsx
      - path_exists: platform/components/layout/Sidebar.tsx
      - grep_count:
          glob: platform/components/layout/Sidebar.tsx
          pattern: /analytics/coupons
          expected: 1

  - title: Group product performance by the categories analytics_2.product_categories already holds
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 6fd8ddd5e4269278dc64bc80d1198a85871d6619
    rationale: >
      Still true, and stronger than the document puts it: the string "categor"
      does not appear anywhere in api/analytics/routes/ at all, in any file, so
      nothing in the API groups or filters by category even though migration
      v0008 created product_categories with a unique key and an index on
      category precisely to make category reporting possible. Sidebar.tsx:49
      reserves /analytics/categories and no page exists. A table built for a
      report, an index built for a report, and no report — this is the cheapest
      row on the page.
    evidence:
      - document: specs/metorik-gap.md
        sha: ef63f55
        repo: fleet
        section: "Weekly — Product performance by category / vendor / brand"
    suggested_paths:
      - api/analytics/routes/products.py
      - api/analytics/migrations/versions/v0008_product_categories.py
      - platform/app/(dashboard)/analytics/products/page.tsx
      - platform/components/layout/Sidebar.tsx
    hib_signal: null
    probes:
      - path_exists: api/analytics/migrations/versions/v0008_product_categories.py
      - path_exists: api/analytics/routes/products.py
      - path_absent: platform/app/(dashboard)/analytics/categories/page.tsx
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: categor
          expected: 0
      - grep_count:
          glob: platform/components/layout/Sidebar.tsx
          pattern: /analytics/categories
          expected: 1

  - title: Report customer lifetime value as a distribution and a retention curve, not only by acquisition source
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 6fd8ddd5e4269278dc64bc80d1198a85871d6619
    rationale: >
      Still Partial, and the document's description holds: routes/sources.py
      computes average_ltv by acquisition source over a 365-day lookback, and the
      string "ltv" appears in no other route file, so there is no LTV
      distribution, no retention curve and no LTV report that is not conditioned
      on a source. Worth flagging for whoever specs it: every LTV figure in
      sources.py reads customers.total_spent, a stored derived column, and
      principles.md is explicit that a stored copy of a derived value should be
      read before it is trusted — a distribution is exactly the report that would
      make a drift in that column visible.
    evidence:
      - document: specs/metorik-gap.md
        sha: ef63f55
        repo: fleet
        section: "Weekly — Customer lifetime value"
    suggested_paths:
      - api/analytics/routes/customers.py
      - api/analytics/routes/sources.py
      - api/analytics/services/analytics_engine.py
      - platform/app/(dashboard)/analytics/customers/page.tsx
    hib_signal: null
    probes:
      - path_exists: api/analytics/routes/sources.py
      - path_exists: platform/app/(dashboard)/analytics/customers/page.tsx
      - grep_count:
          glob: api/analytics/routes/sources.py
          pattern: average_ltv
          expected: 2
      - grep_count:
          glob: api/analytics/routes/customers.py
          pattern: ltv
          expected: 0

  - title: Group orders by payment method into the report the sidebar reserves and no endpoint serves
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 6fd8ddd5e4269278dc64bc80d1198a85871d6619
    rationale: >
      Still true. payment_method now reaches the order list as a filter as well
      as a column, but nothing aggregates by it, Sidebar.tsx:48 reserves
      /analytics/payment-methods and the page does not exist. Carried in the band
      the document gives it — Rarely — rather than promoted because the data
      happens to be good. One thing the spec must decide rather than discover in
      production: 61,647 orders carry no payment method, so a breakdown either
      names that bucket or quietly reports on 97.83% of the store as though it
      were all of it.
    evidence:
      - document: specs/metorik-gap.md
        sha: ef63f55
        repo: fleet
        section: "Rarely — Payment method breakdown"
    suggested_paths:
      - api/analytics/routes/orders.py
      - api/analytics/services/order_query.py
      - platform/components/layout/Sidebar.tsx
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
      - path_exists: api/analytics/routes/orders.py
      - path_exists: platform/components/layout/Sidebar.tsx
      - grep_count:
          glob: platform/components/layout/Sidebar.tsx
          pattern: /analytics/payment-methods
          expected: 1
```

---

## The bands, stated so the spread is visible rather than inferred

Five Daily, three Weekly, one Rarely. That is the shape of the rows I could
re-verify and judge worth doing, not a target: the document's Daily band holds
seven Missing-or-Partial rows and I carried five of them, turning down the
profit dashboard and the digest for the reasons above, and closing the location
row outright because it has landed. The Rarely row is carried in its own band
even though its coverage figure is the strongest on the page, because the band
is the document's estimate of how often an agency opens the thing and the
coverage is a fact about HIB's data — promoting a row because its column is
well populated would be answering the second question with the first.

## What I could not establish

1. **Whether anybody wants any of this.** Said at length in the block's
   `unasked_question` and repeated here because it is the largest limit on the
   page. Nothing below the band column in this batch is measured demand.

2. **That a "Has" or a live capability actually works.** Everything here was
   established by reading code at `6fd8ddd`. `comparison_mode` being accepted
   by a route signature is not year-on-year comparison returning correct
   numbers, and `net_revenue` appearing in four SQL statements is not four
   correct SQL statements. Nothing was exercised against a running API and no
   query was run against the production database for this batch.

3. **Every population figure is quoted, not re-run.** The coverage objects
   above carry `as_of: 2026-08-28` for that reason: they are the gap document's
   figures, thirteen days old, measured on tenant 2 only. `deadly_digital` also
   holds `analytics_1`, and a column empty on tenant 2 may be populated there.
   I had no database access and could not re-derive a single one of them.
   Anything a ranker decides using them is deciding on a fortnight-old
   observation.

4. **The 0.42% of orders that do not reconcile to their line items.** Around
   twelve thousand orders on tenant 2, by the document's own arithmetic. I could
   not turn it into a `coverage` object without computing the numerator myself
   from a percentage, which would present arithmetic as measurement, so it is
   not a candidate. It is the single thing on this page I would most like a SQL
   client for, and it is trust-shaped rather than parity-shaped.

5. **Whether candidates 1, 2 and 3 are three pieces of work or one.** They are
   three rows of the document and are emitted as three candidates for that
   reason. They are also one defect — the proxy layer not carrying what the API
   gained — and if all three are approved separately the third spec will find
   the first two already did most of its work.

6. **Whether the email-side segment builder can express analytics filters.**
   Carried forward from the document unresolved; it is the one read that could
   make candidate 5 much smaller, and I did not do it.
