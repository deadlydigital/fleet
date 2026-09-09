# Candidates from the Metorik gap list — 2026-09-09

Produced 2026-09-09 from `specs/metorik-gap.md` (fleet
`b198634063e5f9e3fc17467a6b6fe361013cfee3`), re-verified against
`deadly-digital-platform` at `4619a76a94b72bc0b11600991779b4f5200117b3`.

Nine candidates, unranked, none carrying a disposition. The block is at the
end; everything before it is the re-verification, which is the work.

---

## The document has rotted further than the contract's own note says

`contracts/candidate-producer.yaml` records a probe of platform HEAD `ebe016c`
on 8 Sep that found two of four Daily-band rows already wrong. The platform has
moved since — HEAD is now `4619a76` — and re-running every Daily claim at that
commit puts the count at **four of the fourteen Daily rows wrong, not two**, and
the two new ones are wrong in a way that changes what the work is rather than
removing it.

| Gap-list Daily row | What the document says | At `4619a76` |
|---|---|---|
| Order filtering | Partial — "`status`, `search`, `sort_by`, `sort_dir`. Nothing else." | **Wrong.** `api/analytics/routes/orders.py` declares `payment_method`, `country`, `coupon` and `has_discount` as query parameters (lines 62–65). |
| Net revenue | Missing — "no aggregate nets it" | **Wrong.** `api/analytics/services/analytics_engine.py` computes `net_revenue`, `refunded_amount` and `orders_with_refund` in four separate queries, added Sep 2026. |
| Compare any period, incl. YoY | Partial — "the equal-length window immediately before it … no arbitrary range and no YoY" | **Wrong.** `api/analytics/routes/dashboard.py` accepts `comparison_mode` with `previous_period`, `previous_year` and `custom`, backed by `api/analytics/services/date_range.py`. |
| Location reports (Weekly) | Partial — "no page and no frontend proxy route" | **Wrong, and now fully closed.** `platform/app/(dashboard)/analytics/geography/page.tsx` exists and three proxy routes under `platform/app/api/analytics/geography/` serve it. Not carried below. |
| CSV export | Missing — one fixed segment export | **Still true.** One `text/csv` response across `api/analytics/routes/`, in `api/analytics/routes/segments.py`. |
| Profit / COGS | Missing — no cost column | **Still true.** `api/analytics/models.py` matches none of cogs, cost, profit or margin. |
| Digests | Missing | **Still true.** No digest and no Slack reference in `api/analytics/routes/`. |
| Multi-store | Missing | **Still true.** `api/analytics/schema_context.py` derives the schema from one tenant id; the only cross-tenant page is DD staff admin. |
| Flexible segmentation | Missing — seven fixed buckets | **Still true.** `VALID_SEGMENTS` is a seven-element literal in `api/analytics/services/segment_engine.py` and `api/analytics/routes/segments.py` rejects anything outside it. |

## Three rows are wrong in the same direction, and it is not "already built"

The interesting result is that the three newly-stale Daily rows are **not
closed**. In every one of them the API gained the capability and the Next.js
layer did not carry it to a person:

* **Order filters.** `platform/app/api/analytics/orders/route.ts` forwards a
  literal `PASSTHROUGH` allowlist of eight parameters. `payment_method`,
  `country`, `coupon` and `has_discount` are not among them, and
  `platform/app/(dashboard)/analytics/orders/page.tsx` renders those fields as
  columns without offering a control that filters on them. An agency still
  cannot answer "show me the PayPal orders".

* **Net revenue.** The dashboard response carries `net_revenue` beside the gross
  figure. The string `net_revenue` does not appear anywhere under
  `platform/app/(dashboard)/analytics/`. The card on
  `platform/app/(dashboard)/analytics/page.tsx` is labelled "Total Revenue" and
  is the gross number.

* **Year-on-year.** `platform/app/api/analytics/dashboard/route.ts` forwards
  `start` and `end` and nothing else, so `comparison_mode` is dropped before it
  reaches an endpoint that would 400 on an unknown value.

That last one is worth naming precisely, because
`api/analytics/routes/dashboard.py` carries a docstring about FEAT-035 — a
defect where the page sent a range, the proxy forwarded it, and the route
discarded it silently. The fix hardened the route. The same class of defect now
sits one layer up, in the proxy, and the route's own discipline of refusing
rather than ignoring cannot see it: a parameter the proxy never sends is a
parameter the route never has the chance to reject.

**Consequence for the ranking.** Three Daily gaps that read as unbuilt reports
are in fact a proxy allowlist, a card, and a select box. That is a different
size of work from the six that genuinely have nothing behind them, and the
approval surface should be able to see which is which — so each of the nine
rationales below says which side of that line it falls on.

## What was checked and how

Every probe in the block is a `path_exists`, `path_absent` or `grep_count` from
`contracts/checks/candidate_block_shape.py`'s closed vocabulary, re-executed by
the check against the platform working tree. Counts were measured, not
estimated: `AS net_revenue` appears exactly four times in
`api/analytics/services/analytics_engine.py`, `text/csv` exactly once across
`api/analytics/routes/*.py`, and the four order-filter parameter declarations
exactly once each.

Population figures carried as `hib_signal` come from `specs/metorik-gap.md` and
are dated 2026-08-28 there. They are **not** re-measured here: this task has no
shell and no database reach, which is deliberate. Where the gap list states no
figure for a row, `hib_signal` is null rather than inferred.
`research/gap-list-open-questions.md` re-ran several of those counts on
2026-08-30 and they moved by ~2,000 orders in a day, so treat any of them as an
order of magnitude and not as a current reading.

## What I could not verify

**Whether any of this is what an agency wants.** The gap list's Agency-use
column is its author's estimate, says so, and nothing since has replaced it. No
agency was asked, no usage was measured, and the agency-partner deal is not
signed. Every "Daily" claim below inherits that, and one conversation would
replace the whole column with something real.

**That a feature marked present actually works.** The probes prove that a
parameter is declared and that a string is absent. A `payment_method` parameter declared in a route signature
is not the filter returning correct rows — the
check's own docstring makes this point and it applies to my re-verification
exactly as much as to the document's. Nothing here was exercised against a
running API or a database; there is no shell in this contract and no
credential.

**Whether the three proxy-layer gaps are as small as they look.** I read the
proxy routes and the pages' type declarations. I did not read each page's
rendering in full, so a control may exist under a name I did not grep for, and
"a card and a select box" is an estimate of size, not a measurement.

**Whether refunds are captured at all.** `research/gap-list-open-questions.md`
found four refunds in 2.85M orders and not one partial refund, and concluded
the connector may not hook WooCommerce's refund event. The net-revenue
candidate below is a rendering gap regardless, but a net figure over uncaptured
refunds is a confident wrong number, so that question sits underneath it and
the connector source is not in either repository.

**Tenant coverage.** Every population figure is tenant 2. The gap list's own
caveat about generalising from one tenant stands unchanged.

**Metorik's side.** No Metorik account, no web access in this contract, and
therefore no check that Metorik still ships any of these. The parity claim is
carried forward from the document on trust.

## The batch

```fleet-candidates
source:
  document: specs/metorik-gap.md
  sha: b198634063e5f9e3fc17467a6b6fe361013cfee3
  read_at: '2026-09-09'

ordering: unranked

unasked_question: >
  Nobody has asked HIB's team, or the unsigned agency partner, which of these
  reports they would actually open. Every band in the source document is one
  person's estimate, and the population figures carried below describe what
  HIB's store HAS rather than what anyone WANTS from it. A batch approved off
  this list is inference-backed, not evidence-backed, and one conversation with
  the prospective partner would be worth more than the whole re-verification
  above.

candidates:

  - title: Forward the four order filters the API already accepts through the Next.js proxy
    rationale: >
      The API gained payment_method, country, coupon and has_discount filters,
      but the proxy at platform/app/api/analytics/orders/route.ts forwards a
      literal eight-parameter allowlist that excludes all four, so an agency
      still cannot filter the order list on any of them. The gap list calls this
      row Partial because the API lacked the filters; it is now Partial because
      the frontend drops them. Small work, Daily use, and it is the cheapest of
      the nine.
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 4619a76a94b72bc0b11600991779b4f5200117b3
    evidence:
      - kind: document
        document: specs/metorik-gap.md
        section: 'Daily — Order filtering: status, payment, shipping, location, customer tags, email engagement, products contained'
        repo: fleet
        sha: b198634063e5f9e3fc17467a6b6fe361013cfee3
    hib_signal:
      value: payment_method populated on 2,782,530 of 2,844,177 orders (tenant 2)
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
    suggested_paths:
      - platform/app/api/analytics/orders/route.ts
      - platform/app/(dashboard)/analytics/orders/page.tsx
    probes:
      - path_exists: api/analytics/routes/orders.py
      - grep_count:
          glob: api/analytics/routes/orders.py
          pattern: 'payment_method: str = Query'
          expected: 1
      - grep_count:
          glob: api/analytics/routes/orders.py
          pattern: 'has_discount: bool = Query'
          expected: 1
      - path_exists: platform/app/api/analytics/orders/route.ts
      - grep_count:
          glob: platform/app/api/analytics/orders/route.ts
          pattern: 'payment_method|has_discount|coupon|country'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/orders/page.tsx
          pattern: 'has_discount'
          expected: 0

  - title: Show net revenue on the analytics dashboard, beside the gross figure it already sits next to in the API
    rationale: >
      dashboard_overview returns net_revenue, refunded_amount and
      orders_with_refund, computed over exactly the rows the gross figure is
      summed from. None of those three strings appears anywhere under the
      analytics pages, so the card a merchant sees is labelled Total Revenue and
      is gross. Metorik nets refunds on its main figures; DD computes the number
      and discards it at the last step.
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 4619a76a94b72bc0b11600991779b4f5200117b3
    evidence:
      - kind: document
        document: specs/metorik-gap.md
        section: 'Daily — Net revenue (gross less refunds) on the main figures'
        repo: fleet
        sha: b198634063e5f9e3fc17467a6b6fe361013cfee3
    hib_signal:
      value: refund_total non-zero on 1 of 2,844,177 orders (tenant 2)
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
    suggested_paths:
      - platform/app/(dashboard)/analytics/page.tsx
      - api/analytics/services/analytics_engine.py
    probes:
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'AS net_revenue'
          expected: 4
      - path_exists: platform/app/(dashboard)/analytics/page.tsx
      - grep_count:
          glob: platform/app/(dashboard)/analytics/page.tsx
          pattern: 'net_revenue|refunded_amount|orders_with_refund'
          expected: 0

  - title: Let the dashboard comparison window be chosen, including year-on-year
    rationale: >
      The route accepts comparison_mode with previous_period, previous_year and
      custom, validates it, and 400s on anything unknown. The proxy forwards only
      start and end, so no caller can ever reach previous_year. This is the
      FEAT-035 defect the route's own docstring describes — a parameter dropped
      silently between page and engine — relocated one layer up, where the
      route's refuse-rather-than-ignore discipline cannot see it.
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 4619a76a94b72bc0b11600991779b4f5200117b3
    evidence:
      - kind: document
        document: specs/metorik-gap.md
        section: 'Daily — Compare any period to any other, incl. year-on-year'
        repo: fleet
        sha: b198634063e5f9e3fc17467a6b6fe361013cfee3
    hib_signal: null
    suggested_paths:
      - platform/app/api/analytics/dashboard/route.ts
      - platform/app/(dashboard)/analytics/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/routes/dashboard.py
          pattern: 'comparison_mode: str = Query'
          expected: 1
      - grep_count:
          glob: api/analytics/routes/dashboard.py
          pattern: 'previous_year'
          expected: 1
      - path_exists: api/analytics/services/date_range.py
      - path_exists: platform/app/api/analytics/dashboard/route.ts
      - grep_count:
          glob: platform/app/api/analytics/dashboard/route.ts
          pattern: 'comparison_mode|compare_start|compare_end'
          expected: 0

  - title: CSV export of the order list, honouring the filters in force
    rationale: >
      There is exactly one text/csv response in the whole analytics API and it
      emits one fixed customer segment with a fixed ten-column header. No order,
      customer or product export exists, and no export route exists on the
      frontend either. Export is the first thing an agency reaches for when a
      client asks a question the dashboard does not answer, and its absence is
      visible within minutes of an evaluation starting.
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 4619a76a94b72bc0b11600991779b4f5200117b3
    evidence:
      - kind: document
        document: specs/metorik-gap.md
        section: 'Daily — CSV export of orders / customers / products; Export with chosen columns'
        repo: fleet
        sha: b198634063e5f9e3fc17467a6b6fe361013cfee3
    hib_signal: null
    suggested_paths:
      - api/analytics/routes/orders.py
      - api/analytics/services/order_query.py
      - platform/app/api/analytics/orders
    probes:
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: 'text/csv'
          expected: 1
      - path_exists: api/analytics/routes/segments.py
      - path_absent: platform/app/api/analytics/orders/export/route.ts

  - title: Scheduled digest of the dashboard to email
    rationale: >
      No digest, scheduled report or Slack code exists anywhere in the analytics
      routes. Metorik's daily email is the feature that puts an analytics product
      in front of an agency without the agency logging in, which is the only
      Daily-band row here that does not require someone to open the product at
      all. DD already sends email for campaigns and flows, so the sending path
      exists even though nothing schedules a report over it.
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 4619a76a94b72bc0b11600991779b4f5200117b3
    evidence:
      - kind: document
        document: specs/metorik-gap.md
        section: 'Daily — Digests: scheduled dashboard summary to email or Slack'
        repo: fleet
        sha: b198634063e5f9e3fc17467a6b6fe361013cfee3
    hib_signal: null
    suggested_paths:
      - api/analytics/routes
      - api/analytics/services/analytics_engine.py
    probes:
      - path_exists: api/analytics/__init__.py
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: '(?i)digest'
          expected: 0
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: '(?i)slack'
          expected: 0

  - title: Segment orders and products, not only customers into seven fixed RFM buckets
    rationale: >
      VALID_SEGMENTS is a seven-element literal and the segments route rejects
      any name outside it, so the only segmentable resource is customers and the
      only segments are the ones the RFM engine assigns. Metorik's central claim
      is that any resource can be segmented by any of its attributes, and this is
      the row an evaluation is most likely to test first. The email-side segment
      builder exists and may already express some of these filters; whether it
      can is the open question the gap list left and this does not settle.
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 4619a76a94b72bc0b11600991779b4f5200117b3
    evidence:
      - kind: document
        document: specs/metorik-gap.md
        section: 'Daily — Segment any resource by any attribute, AND/OR groups'
        repo: fleet
        sha: b198634063e5f9e3fc17467a6b6fe361013cfee3
    hib_signal:
      value: all seven RFM buckets populated on tenant 2
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
    suggested_paths:
      - api/analytics/services/segment_engine.py
      - api/analytics/routes/segments.py
      - platform/app/(dashboard)/segments/builder/page.tsx
    probes:
      - grep_count:
          glob: api/analytics/services/segment_engine.py
          pattern: 'VALID_SEGMENTS = \['
          expected: 1
      - grep_count:
          glob: api/analytics/routes/segments.py
          pattern: 'if segment_name not in VALID_SEGMENTS'
          expected: 1
      - path_exists: platform/app/(dashboard)/segments/builder/page.tsx

  - title: A cross-store roll-up for an agency holding several client tenants
    rationale: >
      Analytics is per-tenant throughout — the schema name is derived from a
      single tenant id — and the only cross-tenant page is DD staff admin, not
      an agency-facing view. An agency running ten client stores has to log in
      ten times to answer one question, and it is the daily habit that the
      unsigned partner deal would be evaluated against. Large work, named as
      such: it needs an identity that spans tenants before it needs a page.
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 4619a76a94b72bc0b11600991779b4f5200117b3
    evidence:
      - kind: document
        document: specs/metorik-gap.md
        section: 'Daily — Multi-store dashboard combining several stores'
        repo: fleet
        sha: b198634063e5f9e3fc17467a6b6fe361013cfee3
    hib_signal: null
    suggested_paths:
      - api/analytics/schema_context.py
      - api/analytics/routes
      - platform/app/(dashboard)/analytics
    probes:
      - grep_count:
          glob: api/analytics/schema_context.py
          pattern: 'def analytics_schema_name'
          expected: 1
      - path_exists: platform/app/(dashboard)/admin/tenants/page.tsx
      - path_absent: platform/app/(dashboard)/analytics/stores/page.tsx

  - title: Establish where product cost would come from, because no cost data exists anywhere
    rationale: >
      Profit reporting is a Daily row and it has nothing under it: the analytics
      models carry no cogs, cost, profit or margin field on any table, and no
      analytics route mentions either. Every other candidate here is a report
      over data DD already holds; this one is blocked on a source of data that
      does not exist and that WooCommerce does not send by default. It is listed
      because the gap list ranks it Daily, and it is flagged because building the
      report is the last step rather than the first.
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 4619a76a94b72bc0b11600991779b4f5200117b3
    evidence:
      - kind: document
        document: specs/metorik-gap.md
        section: 'Daily — Profit dashboard: revenue − COGS − ad spend − fees − fixed costs'
        repo: fleet
        sha: b198634063e5f9e3fc17467a6b6fe361013cfee3
    hib_signal: null
    suggested_paths:
      - api/analytics/models.py
      - api/analytics/migrations/versions
    probes:
      - path_exists: api/analytics/models.py
      - grep_count:
          glob: api/analytics/models.py
          pattern: '(?i)cogs|cost|profit|margin'
          expected: 0
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: '(?i)profit|cogs'
          expected: 0

  - title: Coupon and discount performance report, over a column that is already populated
    rationale: >
      coupon_code is a column on the order model, the data is there on roughly
      146k orders, the nav already reserves a slot for the page, and nothing
      aggregates any of it — the values surface only as fields on an individual
      order row. This is the Weekly row with the shortest distance between data
      DD already holds and a report an agency would open, which is why it is in a
      batch otherwise aimed at the Daily band.
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 4619a76a94b72bc0b11600991779b4f5200117b3
    evidence:
      - kind: document
        document: specs/metorik-gap.md
        section: 'Weekly — Coupon and discount performance: usage, discount total, orders, AOV with/without'
        repo: fleet
        sha: b198634063e5f9e3fc17467a6b6fe361013cfee3
    hib_signal:
      value: coupon_code populated on 146,136 orders and discount_total on 146,043 (tenant 2)
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
    suggested_paths:
      - api/analytics/routes
      - platform/app/(dashboard)/analytics
      - platform/components/layout/Sidebar.tsx
    probes:
      - grep_count:
          glob: api/analytics/models.py
          pattern: 'coupon_code = Column'
          expected: 1
      - grep_count:
          glob: platform/components/layout/Sidebar.tsx
          pattern: '/analytics/coupons'
          expected: 1
      - path_absent: platform/app/(dashboard)/analytics/coupons/page.tsx
```

---

## What this batch deliberately does not do

**It does not deduplicate against previous batches.** Per
`specs/approval-surface.md` §7 the producer cannot see them and did not look.
Several of these rows will have appeared before; that repetition is the signal
and the surface shows it.

**It does not choose a work_type.** Three of the nine are a proxy allowlist and
a card; one is blocked on data that does not exist and may be an investigation
rather than a code change. Deciding which is the draft spec's job, and the shape
of this block cannot express the guess.

**It does not carry the four rows that are now closed or misdescribed.** Order
filtering, net revenue and year-on-year appear here restated as frontend gaps
rather than as the missing-report rows the document describes; location
reporting is absent entirely, because the page and the proxy routes the document
says do not exist both now do. A parser over `specs/metorik-gap.md` would have
emitted all four unchanged.
