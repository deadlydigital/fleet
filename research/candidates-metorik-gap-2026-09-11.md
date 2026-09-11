# Candidates from the Metorik gap list — 11 September 2026

Batch 12. Produced from `specs/metorik-gap.md`, read in the worktree for this
task at fleet `082ed53`, and re-verified against `deadly-digital-platform` at
`2ce6f50c1ddcc406e5f1f08af41af2e4f67e6e7b` (`main`, read from
`.git/refs/heads/main`; every probe below reads the working tree at that
checkout).

**Six candidates**, `ordering: unranked`. They are printed grouped by the file
pair they would edit, which is neither the document's band order nor a ranking.
Candidate order is read as rank order by whoever loads this, so it is said here
as well as in the block: **I did not rank these.**

Six rather than nine, on purpose. Batch 10 emitted nine and two shipped code;
four were stopped by something about the row rather than by the work being
wrong. Every row below names existing files, all inside one contract's writable
set, none on the protected floor, and none whose natural implementation is a new
module. That is the whole of what this batch tried to do better.

---

## 1. What moved, and what this batch does not carry because it has closed

`main` moved a great deal on 11 Sep, and three of batch 10's rows are now
finished work rather than gaps.

| Row | Batch 10 said | At `2ce6f50` |
|---|---|---|
| Order filters through the proxy (c29) | `platform/app/api/analytics/orders/route.ts` drops `payment_method`, `country`, `coupon`, `has_discount` | **Closed.** `PASSTHROUGH` now carries all twelve names, the page has four controls (`.../analytics/orders/page.tsx:509-569`) and the Payment, Country and Coupon cells set their own filter (`:118-148`). The §2.5 task 53 shipped unbuilt is built. |
| Comparison windows through the proxy (c30) | `comparison_mode` appears nowhere under `platform/` | **Closed.** `platform/app/api/analytics/dashboard/route.ts` forwards `comparison_mode`, `compare_start`, `compare_end`; the page has the select and the custom range (`.../analytics/page.tsx:284-379`). c30's own probe — that proxy greps to 0 — is why it stopped holding. |
| Refunds surviving a re-sync (c31) | the upsert writes `0.00` over a captured refund | **Closed.** `api/analytics/services/sync_engine.py:560` is `refund_total = GREATEST(orders.refund_total, EXCLUDED.refund_total)`, with the `spec:1.1` and `spec:1.3` citations in place. |

A fourth, from batch 9 and 10: the **Location reports** row stays closed. The
geography page reaches all three endpoints — `/geography`, `/cities` and
`/areas/{area}` — at `.../analytics/geography/page.tsx:207,231,249`.

**And one row I expected to carry and could not, because it is already reached.**
Batch 9 and 10 both treated the segment CSV export as part of the Daily "CSV
export" gap. `platform/app/(dashboard)/analytics/segments/page.tsx` does only
fetch the list — but `.../segments/[name]/page.tsx:84,102` calls both
`/customers` and `/export`. The segment export is built, proxied and reachable.
Only the *order* export is missing, which is what candidate 2 carries.

### The api→frontend carry gap is closed, and that is why this batch is api-side

Batch 9 and 10's central finding was one defect in three disguises: the API
gained a capability and the Next.js layer did not carry it. That finding is
spent. I checked every analytics proxy that takes parameters —
`revenue`, `products`, `customers`, `sources`, `geography` — and each forwards
exactly what its page sends. There is no second FEAT-035 sitting in the tree
today. Every remaining row on the gap document needs the API half built first,
so five of the six below are `dd_api` and none of them spans the api/frontend
line.

---

## 2. Two structural facts that decided what a row could be

Neither is refused by `candidate_block_shape.py`, and between them they
eliminated four rows I had written before checking.

**A `dd_api` task must change behaviour, because a documentation-only change
cannot pass its gate.** `contracts/checks/new_test_bites.sh:114` fails a change
that adds no test matching `api/tests/analytics/test_fleet_*.py`, and a test
that passes against the pre-change tree fails at `:203`. So there is no route
under `contracts/deadly-digital-platform-api.yaml` for a correction whose whole
content is prose. That killed the best small trust row I had:
`research/refund-coverage.md` found the docstring at
`api/analytics/services/analytics_engine.py:961-964` off by one — it says three
of tenant 2's four refunds sit outside `('completed','processing')` and implies
the fourth is seen, when the fourth is `status = 'refunded'` and is equally
outside — and asked for it in the `dd_api` follow-up. `dd-docstring-proving.yaml`
is the contract for prose corrections and its writable set is twelve *route*
files; `analytics_engine.py` is not one of them. **No contract in `contracts/`
can carry that fix**, and it is recorded here rather than emitted as a row that
could only fail.

**A new report page cannot be written by any contract.**
`dd-analytics-frontend.yaml` enumerates the page directories it may write —
`churn`, `customers`, `geography`, `orders`, `products`, `revenue`, `segments`,
`sources`, plus `page.tsx` and `layout.tsx`. `platform/app/(dashboard)/analytics/coupons/`,
`.../categories/` and `.../payment-methods/` — the three slots `Sidebar.tsx:47-49`
reserves — are in none of them, and `platform/components/layout/Sidebar.tsx`
itself is writable only under `dd-acquiring-page.yaml`, whose other two globs are
the products page and its proxy. So the three reserved sidebar slots **cannot be
filled by an unattended task at all**, and a candidate that names one is c34's
refusal again in a new costume. Candidates 3, 4 and 5 therefore put their
endpoints on `revenue.py` and `products.py`, where a reachable surface already
exists, and say so in their rationales rather than leaving the draft agent to
discover it at £2 a discovery.

---

## 3. Where batch 10's nine rows went, and what this batch does with each

    c29  order filters        APPROVED  shipped      closed above; not carried
    c30  comparison windows   PENDING   probes stale closed above; not carried
    c31  refund re-sync       APPROVED  shipped      closed above; not carried
    c32  CSV export           PENDING   untried      CARRIED as candidate 2, re-verified
    c33  segmentation         APPROVED  shipped as research/segmentation-model-2026-09-11.md
                                                     its §5 IS candidate 1
    c34  coupon report        APPROVED  draft refused: two contracts
                                                     CARRIED as candidate 3, re-scoped to one
    c35  category report      PENDING   names a migration
                                                     CARRIED as candidate 4, without the migration
    c36  LTV distribution     NOT_NOW   two failed drafts, abandoned
                                                     NOT carried — see below
    c37  payment methods      PENDING   untried      CARRIED as candidate 5, re-scoped

**c36 is the one I deliberately leave where a person put it.** A `NOT_NOW` is
the only veto in this system that costs one click, gate 1 refuses to overrule
it, and `specs/auto-approval.md` §13 records £8.02 of failed drafts against that
row with the work sitting unmerged on `fleet/task-62.2`. Re-proposing it under a
new candidate id would hand the same work_key back to a ranker that already
counts two prior failures against it. The right next move on LTV is somebody
cutting `fleet/task-62.2` into pieces by hand, which §13.3 says nothing in this
loop can do.

## 4. The twelve rows held in batches 8 and 9, and what happens to them now

Twelve rows have been held every night under gate 2 as `older_batch`, which
`specs/auto-approval.md` §9.11 says assumes a newer batch re-verified them.
**This batch is a newer producer batch over the same document, so for these rows
the assumption is now true rather than assumed** — and the honest report is that
it carries almost none of them forward, for reasons that are about the rows:

* **c20, c21, c22 (order filters, net-revenue card, dashboard comparison).**
  All three are the api→frontend carry gap of §1, and all three have **shipped**.
  They are superseded by work in production, not by a batch.
* **c17, c23 (CSV export).** Still true; carried forward re-verified as
  candidate 2 — one `text/csv` response in the whole analytics API, at
  `api/analytics/routes/segments.py:86`.
* **c25 (segment orders and products).** Answered rather than carried:
  `research/segmentation-model-2026-09-11.md` §4 recommends against
  resource-generic segmentation on the evidence of these two stores and names
  the first buildable step, which is candidate 1.
* **c24, c26, c28.** These are the rows §9.19 and `console/rank.py` gate 6
  report as `unwritable_path`: they name `api/analytics/routes`, a **directory**,
  and `api/analytics/schema_context.py`, which is not one of the api contract's
  twenty-seven files. Nothing about a new batch repairs a row whose path cannot
  be queued. **They stay held, and the reason is the path, not the batch.**
* **c27 (where product cost would come from).** Still true and still turned
  down for the reason batch 10 gave: there is no cost column anywhere in the
  analytics schema, so this is a data source HIB would have to supply.

---

## 5. What I turned down, and why

`principles.md`: *"Rejections are the informative half."*

**Net revenue on a surface.** `research/refund-coverage.md` returned an explicit
**no-go**, and `research/EVIDENCE-refund-coverage-manifests.md` — 54 manifest
periods, refund totals agreeing in every one — did not lift it. The load-bearing
argument is untouched: `refund_total` is `NOT NULL DEFAULT 0` and the writer
coerces an absent field to zero, so the column has no state meaning "not
reported" and no query can tell a quiet store from a silent build. On top of
that, every refund either tenant reports sits outside `('completed','processing')`,
so `net_revenue == revenue` is **structural**, and Requirement 4's legibility
sentence — "no refunds recorded in this window" — would be shown over a store
that does have recorded refunds. That is a wrong number rather than a missing
one, which `principles.md` ranks above every parity row on this page. It is
carried here as a refusal precisely so the next producer does not re-derive it.

**Refund reports (Weekly).** Same fact, same no-go. A refund rate over a column
whose zeros cannot be interpreted is the same wrong number with a time axis.

**Fixing the `refund_total` "not reported" hole.** The real repair is a nullable
column, which is a migration, and `api/analytics/migrations/**` is on
`protected_path_floor`. No contract can make it writable. This is the single
most important item on the whole refund thread and **no fleet task can touch
it** — the same wall c35 hit, arrived at from the other side.

**Adding the test that the three refund keys travel together.** There is no test
anywhere covering `net_revenue`, `refunded_amount` or `orders_with_refund`, so a
later edit dropping one of the four would merge clean. It is still not a
candidate: `new_test_bites.sh` requires the added test to **fail** against the
pre-change tree, and a test asserting behaviour that already works passes there.
A test-only task fails its own gate. This needs a person, or a contract that
distinguishes a regression test from a proving one.

**The segment sync dropping rules and mailing everybody**
(`research/segmentation-model-2026-09-11.md` §1.6). Genuinely trust-shaped and
the most severe thing I read all day. Its three files are
`platform/app/api/segments/preview/route.ts`, `.../refresh/route.ts` and
`api/app.py:7942`. `api/app.py` is on the email floor; the other two are in no
contract's writable set. Unqueueable, and the document already asks for a
`public.segments` census before anything is decided.

**Profit / COGS / gateway fees**, **digests and scheduled exports**,
**multi-store**, **subscriptions and carts**, **device, variation and custom-meta
reporting**: turned down for the reasons batch 10 gave, which I re-verified and
which have not moved. No cost column, no subscription or cart table, no device
field, and an unsigned agency partner whose habits `principles.md` forbids
inventing.

**Orders by currency.** Still Partial and still not worth a row:
`research/EVIDENCE-metorik.md` puts every order on both tenants in GBP, so the
report renders one line. The gap document's own *Never* band gives the same
reason for multi-currency; the Rarely row inherits it.

**Variation-level and SKU reporting.** `research/gap-list-open-questions.md`
measured `order_items.price` and `order_items.sku` at **0 of 4,488,746**. This
moves from Rarely to impossible until the connector sends the fields, and it is
a connector question rather than a report.

---

## 6. The candidates

```fleet-candidates
source:
  document: specs/metorik-gap.md
  sha: 082ed53
  repo: fleet

ordering: unranked

objectives_considered: >
  Weighed dd-trustworthy against dd-feature-parity row by row, because
  principles.md ranks trust above parity and objectives-2026-Q4.yaml warns in
  its own comments that dd-feature-parity without a baseline "ranks build
  another report forever" and that parity work "must not outrank correctness
  work by default". Five rows are parity: each is a report or a filter simply
  absent from a person's reach, and nothing DD displays about them today is
  incorrect. Candidate 6 is dd-trustworthy and is the only row here whose
  deliverable is a number the product currently cannot check: the gap document
  rests two of its Rarely verdicts on the header total matching the sum of the
  line items on 99.58% of orders, and nothing in the API reports the residual,
  so roughly twelve thousand orders disagree with their own line items and no
  surface says so. I wanted more trust rows than one and could not write them:
  the net-revenue thread returned a no-go, the nullable refund column is a
  migration on the protected floor, the analytics_engine docstring correction
  fits no contract because it changes no behaviour, and the segment-sync defect
  lives in files no contract makes writable. Those four are in the rejection
  section rather than emitted as rows that could only fail. I considered
  dd-first-revenue for the multi-store roll-up and rejected the row rather than
  the label, on batch 10's argument: the agency partner is unsigned, so its
  value is an assumption about a counterparty who has agreed to nothing.
  cost-discipline is neither served nor threatened by any of these; they are
  query work over tables that already exist, and none adds a fixed cost.

unasked_question: >
  Nobody has asked HIB's team, or the unsigned agency partner, which of these
  reports they would open. Every coverage figure below describes what HIB's
  store HAS, not what anyone WANTS from it, and the two are different claims:
  coupon_code being populated on 5.14% of orders says a coupon report is
  possible, not that anybody would read it twice. The gap document's whole
  Agency-use column is one person's estimate with no agency behind it and says
  so, and DD holds no event, session or page-view table on any schema, so this
  cannot be settled later by observation either. One conversation asking which
  three of these they would open in their first week would replace the ordering
  of this entire batch with something measured, and it remains by far the
  cheapest thing on this page. A second unasked question is narrower and newer:
  research/segmentation-model-2026-09-11.md names a census of public.segments as
  the condition under which its recommendation — and therefore candidate 1's
  standing as a first step — is wrong, and nobody has run that SELECT.

candidates:

  - title: Let the order list filter on several values per field instead of one exact match
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 2ce6f50c1ddcc406e5f1f08af41af2e4f67e6e7b
    rationale: >
      The gap document says order filtering accepts "nothing else" beyond status,
      search and the date range, and that has been wrong since task 2: the route
      takes payment_method, country, coupon and has_discount, the proxy forwards
      them and the page offers controls. The residual gap is that every one of
      them is a single exact value — order_query.py builds four
      `o.<column> = :param` clauses and nothing emits an IN list — so "completed
      or processing" and "PayPal or Stripe", which are the first two things
      anyone asks an order list for, cannot be expressed. This is not my
      invention of a next step: research/segmentation-model-2026-09-11.md §5,
      shipped from candidate 33, names exactly this as the largest piece of its
      recommendation that fits a contract today, names both files, and notes it
      is the only first step that survives the segmentation decision being
      reversed. Accepting a repeated query parameter and emitting IN with bound
      parameters keeps order_query.py's existing discipline — allow-listed
      fields, bound values, a total order on every paginated read — and adds no
      module. Under the api contract rather than dd-order-filters.yaml, whose
      order_filters_shape.py check is pinned to the shape task 2 delivered.
    evidence:
      - document: specs/metorik-gap.md
        sha: 082ed53
        repo: fleet
        section: "Daily — Order filtering: status, payment, shipping, location, customer tags, email engagement, products contained"
      - document: research/segmentation-model-2026-09-11.md
        sha: 082ed53
        repo: fleet
        section: "5. The first buildable task, and its contract"
    suggested_paths:
      - api/analytics/routes/orders.py
      - api/analytics/services/order_query.py
    hib_signal:
      value: payment_method populated on 2,782,530 of 2,844,177 orders on tenant 2, across nine distinct payment methods, so a multi-value gateway filter has something to discriminate between
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: payment_method
        populated: 2782530
        total: 2844177
    probes:
      - path_exists: api/analytics/routes/orders.py
      - path_exists: api/analytics/services/order_query.py
      - grep_count:
          glob: api/analytics/services/order_query.py
          pattern: "o\\.(status|payment_method|billing_country|coupon_code) = :"
          expected: 4
      - grep_count:
          glob: api/analytics/routes/orders.py
          pattern: "List\\[str\\]"
          expected: 0
    premise:
      - claim: >
          The four order filters already exist on the route as single-value exact
          query parameters, so this work widens a filter that is there rather
          than adding one that is not.
        probe:
          grep_count:
            glob: api/analytics/routes/orders.py
            pattern: "payment_method: str = Query"
            expected: 1

  - title: Add a CSV export of the order list beside the one segment export that exists
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 2ce6f50c1ddcc406e5f1f08af41af2e4f67e6e7b
    rationale: >
      Re-verified the way the document did rather than quoted: there is exactly
      one text/csv response across api/analytics/routes/*.py, at segments.py:86,
      and it emits one fixed customer segment with a fixed ten-column header. No
      order, customer or product export exists on either side. I nearly dropped
      this row on the belief that the segment export was unreachable too; it is
      not — the segment detail page calls both /customers and /export — so the
      gap is precisely the order list and nothing else. The export should reuse
      list_orders' existing where-clause rather than growing a second query, so
      an export and the page it was taken from describe the same population;
      that is the same conflict-2.2 argument the summary already answers. Export
      is what an agency reaches for when a report does not answer its question,
      which is what decides whether a missing report is an inconvenience or a
      wall. The download link on the orders page is a second, frontend-only
      piece of work under a different contract and is not in this row.
    evidence:
      - document: specs/metorik-gap.md
        sha: 082ed53
        repo: fleet
        section: "Daily — CSV export of orders / customers / products"
    suggested_paths:
      - api/analytics/routes/orders.py
      - api/analytics/services/order_query.py
    hib_signal: null
    probes:
      - path_exists: api/analytics/routes/segments.py
      - path_absent: platform/app/api/analytics/orders/export/route.ts
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: "text/csv"
          expected: 1
    premise:
      - claim: >
          list_orders already computes one where-clause that governs the rows and
          the summary together, so an export can reuse it and describe the same
          population the page showed.
        probe:
          grep_count:
            glob: api/analytics/services/order_query.py
            pattern: "def list_orders"
            expected: 1

  - title: Report coupon and discount performance from the revenue endpoint, not from a new coupons module
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 2ce6f50c1ddcc406e5f1f08af41af2e4f67e6e7b
    rationale: >
      Still true and re-measured: the string coupon appears in the whole of
      api/analytics/routes/ only as the order-list filter in orders.py, and not
      once in analytics_engine.py, so nothing aggregates by it. The row is
      re-scoped rather than repeated. Candidate 34 was approved and its draft
      refused because its paths spanned two contracts, and task 23 before it
      failed proposing api/analytics/routes/coupons.py, which the api contract
      cannot express because it enumerates twenty-seven existing files and no
      glob (specs/auto-approval.md §15). So this names revenue.py and
      analytics_engine.py: both are in the api contract's writable list, the
      revenue endpoint already returns a summary object over a window that a
      usage, discount-total, orders and AOV-with-versus-without breakdown
      belongs in, and /analytics/revenue is a page that already exists and can
      show it. It must not name Sidebar.tsx or a coupons page: that directory is
      in no contract's writable set, so the reserved nav slot cannot be filled
      by an unattended task however the row is cut.
    evidence:
      - document: specs/metorik-gap.md
        sha: 082ed53
        repo: fleet
        section: "Weekly — Coupon and discount performance: usage, discount total, orders, AOV with/without"
    suggested_paths:
      - api/analytics/routes/revenue.py
      - api/analytics/services/analytics_engine.py
    hib_signal:
      value: coupon_code populated on 146,136 of 2,844,177 orders on tenant 2 and discount_total on 146,043 — the 5.14% is the share of orders that used a coupon rather than missing data, and the 93-order difference between the two columns is worth a look while somebody is in there
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: coupon_code
        populated: 146136
        total: 2844177
    probes:
      - path_absent: api/analytics/routes/coupons.py
      - path_absent: platform/app/(dashboard)/analytics/coupons/page.tsx
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: "coupon"
          expected: 0
      - grep_count:
          glob: api/analytics/routes/revenue.py
          pattern: "coupon|payment_method"
          expected: 0
      - grep_count:
          glob: platform/components/layout/Sidebar.tsx
          pattern: "/analytics/coupons"
          expected: 1
    premise:
      - claim: >
          coupon_code is a stored column on the analytics order model, so the
          report is an aggregate over data the sync already writes rather than a
          new field to capture.
        probe:
          grep_count:
            glob: api/analytics/models.py
            pattern: "coupon_code"
            expected: 1

  - title: Group product performance by the categories the sync already writes, on the products endpoint
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 2ce6f50c1ddcc406e5f1f08af41af2e4f67e6e7b
    rationale: >
      Still true, and stronger than the document puts it: the string categor does
      not appear anywhere in api/analytics/routes/, in any file, and
      analytics_engine.py never mentions product_categories — so nothing in the
      API groups or filters by category even though the sync maintains the table
      wholesale, replacing each synced product's category set and deliberately
      skipping products the store did not mention. A table the sync keeps
      current, an index built for a report, and no report. Re-scoped from
      candidate 35 in one specific way: that row named
      api/analytics/migrations/versions/v0008_product_categories.py, which is on
      protected_path_floor, and gate 5 can only ever refuse it. The migration is
      evidence, not a file to edit. products.py already serves two endpoints and
      the products page already exists, so this adds a third breakdown to a
      reachable surface rather than a /analytics/categories page, which no
      contract can write.
    evidence:
      - document: specs/metorik-gap.md
        sha: 082ed53
        repo: fleet
        section: "Weekly — Product performance by category / vendor / brand"
    suggested_paths:
      - api/analytics/routes/products.py
      - api/analytics/services/analytics_engine.py
    hib_signal: null
    probes:
      - path_absent: platform/app/(dashboard)/analytics/categories/page.tsx
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: "categor"
          expected: 0
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: "product_categories"
          expected: 0
      - grep_count:
          glob: api/analytics/routes/products.py
          pattern: "@router.get"
          expected: 2
    premise:
      - claim: >
          The sync engine writes and maintains the product_categories table on
          every product batch, so a category breakdown reads data that is being
          kept current rather than a table populated once and abandoned.
        probe:
          grep_count:
            glob: api/analytics/services/sync_engine.py
            pattern: "_write_product_categories"
            expected: 2

  - title: Break revenue down by payment method, naming the orders that carry none
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: 2ce6f50c1ddcc406e5f1f08af41af2e4f67e6e7b
    rationale: >
      Still true. payment_method reaches the order list as a filter and a column
      and now as a clickable cell, but nothing aggregates by it — the string
      appears nowhere in revenue.py or analytics_engine.py. Carried in the band
      the document gives it, Rarely, rather than promoted because its column
      happens to be the best populated on the page; the band is an estimate of
      how often an agency opens the thing and the coverage is a fact about HIB's
      data, and promoting on the second would be answering the first question
      with the wrong evidence. Two things the spec must decide rather than
      discover in production. First, 61,647 orders carry no payment method, so
      the breakdown either names that bucket or quietly reports on 97.83% of the
      store as though it were all of it. Second, it belongs on revenue.py beside
      the coupon breakdown and on the existing /analytics/revenue page:
      Sidebar.tsx reserves /analytics/payment-methods and that directory is in no
      contract's writable set, so a page there cannot be built unattended.
    evidence:
      - document: specs/metorik-gap.md
        sha: 082ed53
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
      - path_exists: api/analytics/routes/revenue.py
      - grep_count:
          glob: api/analytics/routes/revenue.py
          pattern: "coupon|payment_method"
          expected: 0
      - grep_count:
          glob: platform/components/layout/Sidebar.tsx
          pattern: "/analytics/payment-methods"
          expected: 1
    premise:
      - claim: >
          payment_method is already an exact filter declared on the order list
          route, so the values a breakdown would group by are values the product
          already treats as a dimension.
        probe:
          grep_count:
            glob: api/analytics/routes/orders.py
            pattern: "payment_method: str = Query"
            expected: 1

  - title: Reconcile each order's header total against the sum of its line items, and report the residual
    repo: deadly-digital-platform
    objective_ref: dd-trustworthy
    verified_sha: 2ce6f50c1ddcc406e5f1f08af41af2e4f67e6e7b
    rationale: >
      The gap document retires two Rarely rows — tax and shipping — on one piece
      of arithmetic: total equals the sum of order_items.total to the penny on
      99.58% of 2,844,177 orders, leaving no room for a tax or shipping term.
      The conclusion is sound and the residual is not explained anywhere. Roughly
      twelve thousand orders disagree with their own line items, nothing in the
      API reports it, and two of the document's status verdicts stand on the
      other 99.58%. The reconciliation service is the right place and it does not
      do this: the string order_items does not appear in reconciliation.py at
      all, which already compares the store's own asserted totals against the
      platform's copy per manifest period and surfaces the result through
      /manifest/status. This adds an internal consistency check beside the
      existing external one — the store's word against DD's copy is a different
      question from DD's own header against DD's own lines, and only the second
      can be answered without the connector. It is the one row here whose output
      is a number the product currently cannot check about itself, which is why
      it is labelled dd-trustworthy rather than parity.
    evidence:
      - document: specs/metorik-gap.md
        sha: 082ed53
        repo: fleet
        section: "Rarely — Tax reporting / Shipping revenue and shipping-cost rules"
      - document: research/EVIDENCE-refund-coverage-manifests.md
        sha: 082ed53
        repo: fleet
        section: "Reading 1 — the store's refund total against the platform's, per period"
    suggested_paths:
      - api/analytics/services/reconciliation.py
      - api/analytics/routes/manifest.py
    hib_signal:
      value: the gap document states the header-to-line-items identity holds on 99.58% of 2,844,177 orders on tenant 2 and gives no count for the residual anywhere; coverage is null rather than a ratio because multiplying the percentage out would present arithmetic as a measurement
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage: null
    probes:
      - path_exists: api/analytics/services/reconciliation.py
      - path_exists: api/analytics/routes/manifest.py
      - grep_count:
          glob: api/analytics/services/reconciliation.py
          pattern: "order_items"
          expected: 0
      - grep_count:
          glob: api/analytics/routes/manifest.py
          pattern: "manifest/status"
          expected: 2
    premise:
      - claim: >
          The reconciliation service already compares the store's own asserted
          period totals against the platform's stored copy, so this extends a
          working comparison rather than introducing the idea of one.
        probe:
          grep_count:
            glob: api/analytics/services/reconciliation.py
            pattern: "source_refund_total"
            expected: 5
```

---

## 7. File contention, and the order to approve these in

Three rows sit on `analytics_engine.py` and two on `order_query.py`. That is not
carelessness: the api contract enumerates twenty-seven files and there is exactly
one aggregate service among them. Gate 3 holds a candidate whose suggested path a
live task declares, so with a pace of one per night these serialise rather than
collide, and each is released when the one ahead of it merges. The cost is a
night, not a row. If the order matters to whoever ticks these:

    1  multi-value order filters     orders.py, order_query.py
    2  CSV export of the order list  orders.py, order_query.py      (after 1)
    6  header-vs-line-items residual reconciliation.py, manifest.py  (no contention)
    3  coupon and discount           revenue.py, analytics_engine.py
    5  payment-method breakdown      revenue.py, analytics_engine.py (after 3)
    4  product categories            products.py, analytics_engine.py

Candidate 6 contends with nothing and can run beside any of them.

## 8. What I could not establish

1. **Whether anybody wants any of this.** Said at length in the block's
   `unasked_question` and repeated because it is the largest limit on the page.
   Nothing below the band column in this batch is measured demand.

2. **That any capability I read actually works.** Everything here was
   established by reading the checkout. `PASSTHROUGH` carrying twelve names is
   not twelve working filters, and `AS net_revenue` appearing four times is not
   four correct SQL statements. Nothing was exercised against a running API, and
   no query was run against the production database for this batch — this
   contract has no shell and no credential.

3. **Every population figure is quoted, not re-run.** Each `coverage` object
   carries `as_of: 2026-08-28`: they are the gap document's figures, fourteen
   days old, tenant 2 only. `deadly_digital` also holds `analytics_1`, and
   `research/EVIDENCE-refund-coverage-manifests.md` shows how differently the
   two behave — tenant 1's manifests cover 2.7% of the orders in their own span.
   Anything a ranker decides on these numbers is deciding on a fortnight-old
   observation of one store.

4. **The residual in candidate 6 is a percentage, not a count.** The document
   states 99.58% and leaves the numerator in no section. I have kept batch 10's
   scruple and left `coverage: null` rather than multiplying it out, so the
   "roughly twelve thousand orders" in the rationale is arithmetic and is
   labelled as such. Settling it needs one `SELECT`, and it is the query I would
   most like to have run.

5. **Whether `2ce6f50`'s working tree is its commit.** Probes read the tree;
   `verified_sha` names the ref. I could not run `git status` under this
   contract, so a dirty checkout would make the two describe slightly different
   things. The same caveat applied to batches 9 and 10 and is stated rather than
   assumed away.

6. **Whether candidate 1 is still the right first step.**
   `research/segmentation-model-2026-09-11.md` §4.2 names the condition under
   which its own recommendation is wrong — a `public.segments` census showing
   material use of the six unresolvable fields — and could not run it. If that
   number is large, the right first move is repairing the email side, and
   candidate 1 drops from "first brick" to "harmless improvement to the order
   list". It is still worth building in that world; it is just not the same
   argument.

7. **Metorik's side.** No account, no web access in this contract, and therefore
   no check that Metorik still ships any of these. The parity claim throughout
   is inherited from `research/metorik-gap-2026-08-30.md`'s retrieval dates.
