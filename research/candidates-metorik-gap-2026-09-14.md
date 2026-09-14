# Candidates from the Metorik gap list — 14 September 2026

Batch 15. Produced from `specs/metorik-gap.md`, read in the worktree for this
task at fleet `da496f8`, and re-verified against `deadly-digital-platform` at
`ab65311885b65cb6e6cf2f0085678f18ac7f8220` (`main`, read from
`.git/refs/heads/main`; every probe below reads the working tree at that
checkout).

**Six candidates**, `ordering: unranked`. They are printed in the order I
happened to establish them, which is neither the document's band order nor a
ranking. Candidate order is read as rank order by whoever loads this, so it is
said here as well as in the block: **I did not rank these.**

> **Edited by hand, 14 September 2026, after the load refused this document.**
> It emitted five candidates; it now carries six. See "What was edited, and
> why" immediately below — the change is recorded rather than tidied away,
> because the rest of the document is the producer's and this part is not.

---

## 0. What was edited, and why

`console.load_candidates` refused the block this run emitted:

    REFUSED: 2 problem(s) in the block; nothing was written:
      - candidate 2: evidence sections name more than one band (['daily', 'rarely'])
      - candidate 3: evidence sections name more than one band (['daily', 'weekly'])

The loader's rule is that a candidate has one frequency, because *"picking the
first would be a way of not noticing that the document disagrees with itself"*.
**The producer could not have known.** `contracts/checks/candidate_block_shape.py`
— the gate its contract makes it pass — carries no band validation at all, so a
block can pass verification, merge, and then be unloadable. That is being fixed
separately; it is not a fault of this run.

The two refusals were not the same shape, and are not repaired the same way.

**Candidate 2 was two pieces of work and is now two rows.** It merged net
revenue (a Daily row) and the payment-method block (a Rarely row) on the
strength of §3 below — same page, same payload, same render-only change. Split
along the band line into *"Render the net-revenue figures…"* and *"Render the
payment-method breakdown…"*, each citing one band, each keeping the probes and
premises that belong to it, and the `hib_signal` divided at the same seam: the
refund_total reading to the first, the payment_method coverage to the second.

**This overrides §3 for that pair, deliberately.** Two rows now name
`analytics/revenue/page.tsx`. What §3 was protecting is gate 3 (`path_overlap`),
which holds any candidate whose path a non-terminal task declares — so the
second row waits for the first to finish rather than colliding with it. The
protection is in the ranker, not in the batch's shape.

**Candidate 3 was one piece of work and is still one row.** It cites the Daily
export row as its gap and cited *"Weekly — Product sales and trends"* as
supporting evidence that `product_report` already returns a complete row shape.
There is no second piece of work to split out, so splitting it would have
invented one. The Weekly citation was removed instead. **The claim it supported
is not lost**: the rationale still states it, and the candidate's first premise
proves it by probe (`product_report` appears twice in `api/analytics/routes/products.py`).

Nothing else was touched: no probe, no premise, no rationale except where the
split required one sentence to move, and no row was added or dropped beyond
candidate 2 becoming two.

---

## 1. The five rows that shipped, checked in the tree rather than taken on trust

The task spec for this run names five gap-list rows merged into platform `main`
between 13 Sep 21:58 and 14 Sep 10:03 and forbids re-proposing them. It also
says that if a probe of mine finds one of those gaps still open, that is a
finding to state rather than a row to emit. So I probed all five before writing
anything. **None of them is still open**, and there is no finding of that kind
to report:

| Shipped row | What I read at `ab65311` |
|---|---|
| net revenue beside gross on the analytics overview (c21) | `platform/app/(dashboard)/analytics/page.tsx` now matches `net_revenue\|refunded_amount\|orders_with_refund` 18 times and `[Rr]efund` 29 times, against 0 and 0 when batch 14 wrote the row. |
| coupon and discount block on the revenue page | `coupon` appears 62 times in `platform/app/(dashboard)/analytics/revenue/page.tsx` and 3 times in `platform/app/api/analytics/revenue/route.ts`, against 0 and 0. |
| revenue broken down by payment method (c37) | `payment_method_breakdown()` exists in `api/analytics/services/analytics_engine.py` and `api/analytics/routes/revenue.py` returns `payment_methods` as a top-level key. |
| the order CSV export reachable from the orders page | `platform/app/api/analytics/orders/export/route.ts` exists and `platform/app/(dashboard)/analytics/orders/page.tsx` matches `csv\|Download\|download\|/export` 8 times, against 0. |
| product performance by category, reachable from the products page | `platform/app/api/analytics/products/categories/route.ts` exists and `categor` appears 70 times on the products page, against 2 comments about a removed column. |

Two more of batch 14's rows are **not** in that list and I checked them too,
because "not shipped" is a claim as much as "shipped" is:

* **Multi-value order filters (batch 14 candidate 6) HAVE shipped on the API**,
  and nobody recorded it as a gap-list row. `api/analytics/routes/orders.py`
  now declares `status`, `payment_method`, `country` and `coupon` as
  `Optional[List[str]] = Query` — four of them — and
  `api/analytics/services/order_query.py` carries a `FilterValues` type,
  a `MAX_FILTER_VALUES` cap and an `IN`-list builder. That row is closed, and
  §4.1 and §5 below are what is left of it.
* **Export column selection (batch 14 candidate 3) has not shipped.** `columns`
  still appears zero times in `api/analytics/routes/orders.py` and
  `ORDER_EXPORT_COLUMNS` is still one seventeen-column module-level tuple. It is
  real work and I am deliberately not carrying it this batch; §5 says why, and
  the reason is not that it has stopped being real.

## 2. Paths: a file, writable, unprotected — applied per row before it was written

`specs/candidate-paths-must-be-buildable.md` states the predicate and the task
spec restates it: a path is buildable when **at least one contract for the repo
makes it writable and does not protect it**. `candidate_block_shape.py` does not
ask this — it asks whether the path resolves, and a directory resolves — so it
was applied by hand, per row, against `contracts/*.yaml` with
`repo: deadly-digital-platform`.

    1  api/analytics/routes/orders.py, services/order_query.py    deadly-digital-platform-api
    2  platform/app/(dashboard)/analytics/revenue/page.tsx        dd-analytics-frontend
    3  api/analytics/routes/products.py, analytics_engine.py      deadly-digital-platform-api
    4  api/analytics/routes/segments.py, segment_engine.py        deadly-digital-platform-api
    5  platform/app/(dashboard)/analytics/sources/page.tsx        dd-analytics-frontend

Every path is a FILE that exists today, every one is named in one contract's
`writable_paths` — `deadly-digital-platform-api.yaml` enumerates twenty-seven
files and all six api paths above are among them — and none is on any contract's
`protected_paths`. No row names a directory, a migration, or a file outside
every boundary. No row needs a NEW file, so nothing here depends on the
added-path rule batch 14 had to lean on twice.

**And no row needs a schema change.** That is stated as a property of the batch
rather than discovered per row: everything below is query, route or render work
over columns that exist and are populated. The task spec's instruction about the
protected migration floor — *if the work needs a migration it is not unattended
work however it is scoped* — is honoured by refusing such rows in §5, not by
naming a migration and letting gate 5 find it.

## 3. One row per file pair, and the evidence that this matters

Batch 14 emitted seven rows. Five shipped. **The two that did not are exactly
the two that shared a file pair with each other** — its candidates 3 and 6, both
on `api/analytics/routes/orders.py` and `api/analytics/services/order_query.py`
— and its own §8 predicted they would serialise behind gate 3. Its other five
rows each sat on a distinct page, proxy or module, and every one of those five
is merged.

That is one observation on a sample of seven and it may be ranking rather than
contention; I have not seen the pool and cannot tell the two apart. It is still
the only evidence this document has about which rows survive, so this batch is
built to it: **no two rows below share a file.** Where that forced a choice, the
choice is recorded in §5 rather than left as an absence. It cost this batch two
rows it would otherwise have carried, and I think five rows that can all run
tonight beat seven where three wait on each other.

## 4. The rows

### 4.1 The order export takes one value per filter; the list it copies takes several

**Candidate 1, and the only correctness row this gap list has produced that is
buildable.** `GET /orders` now declares `status`, `payment_method`, `country`
and `coupon` as repeatable query parameters — `Optional[List[str]] = Query`,
four of them, with a `MAX_FILTER_VALUES` cap that refuses rather than trims.
`GET /orders/export` declares the same four as bare `str`. FastAPI binds a
repeated parameter on a `str` field to the last value, so
`?status=completed&status=processing` filters the table on both and the file on
`processing` alone, with a 200, no warning, and a `Content-Disposition` that
says `orders.csv`.

The export's own docstring is what makes this a trust row rather than a missing
feature: *"The file's population is the population the page reported, which is
the whole point."* That sentence is already false for any caller that repeats a
parameter, and the module comment above `PASSTHROUGH` in the export proxy says
the same thing one layer up — *"The file and the table have to describe the same
population."*

**It is latent today and I will not overstate it.** Nothing in the product sends
a repeated parameter: `platform/app/(dashboard)/analytics/orders/page.tsx`
builds its query with `params.set()`, one value per field, and both proxies read
`searchParams.get()` rather than `getAll()`. So no merchant can reach this now.
It becomes reachable the moment the orders page offers a multi-select, which is
§5's held row — which is the second reason this one is worth doing first.

The work is small because the hard half is already built: `export_orders_csv()`
already declares every filter as `FilterValues`, which is
`Optional[Union[str, Sequence[str]]]`, and already goes through the same
`_filter_clause` as the list. The route signature and the cap check are what is
single-valued.

### 4.2 The revenue page throws away two blocks its own payload carries

**Candidate 2, the cheapest row in this batch by a distance, and it needs
reading carefully against the two shipped rows it is adjacent to.**

> **Since the §0 edit this section describes two rows, 2a and 2b**, split along
> the band line. The argument below for treating them as one piece of work is
> left standing because it is the producer's reasoning and it is sound about
> the work; what it did not account for is that a candidate carries one band.
> The paragraph beginning "The two are one row rather than two" is the part
> that no longer describes the block.

`GET /api/analytics/revenue` returns three things the page never looks at:
`net_revenue` on every period row, `net_revenue` on the window summary, and
`payment_methods` as a top-level key with a named bucket for the orders carrying
no method. The revenue page matches `net_revenue` zero times, `payment` zero
times and `[Rr]efund` zero times across 535 lines. The proxy hands the body back
unmodified (`NextResponse.json(data, ...)`), so all of it arrives at the browser
already.

**This is not either of the two rows that shipped.** `ab65311` put net revenue
on the analytics *overview* (`analytics/page.tsx`), not on the revenue trends
page; and `e45036d` built the payment-method *aggregate in the API*, which is
why `payment_method_breakdown()` exists and why nothing renders it. Batch 14
said in as many words that net revenue on the revenue page was real and held it
back because the coupon block already claimed that file — *"the next batch can
carry it once candidate 5 has landed or lapsed"*. Candidate 5 landed at
`04a3a17`. This is that row, plus the block that arrived a day later, on the
same file and in the same kind of work.

The two are one row rather than two for §3's reason: they are the same page, the
same payload and the same render-only change, and splitting them would put two
rows on one file in a batch whose whole shape is about not doing that.

Two properties must come from the payload rather than be invented, and the spec
should carry both. `net_revenue == revenue` is the common case on this data and
has to read as *"no refund is recorded against these orders"* rather than
*"refunds netted to nothing"* — the engine's own docstring insists on the
distinction and it only survives if `refunded_amount` and `orders_with_refund`
ship beside the net figure. And the payment-method block already separates NULL
from the empty string and names the 61,647 orders carrying neither; a page that
renders percentages over the remaining 97.83% without that bucket reports on
part of the store as though it were the store.

### 4.3 There are two CSV endpoints in the whole analytics API, and neither is products

**Candidate 3.** `text/csv` appears exactly twice across every module in
`api/analytics/routes/` — `orders.py` and `segments.py`. The document's Daily
row names orders, customers *and* products; orders shipped yesterday, and
products has `product_report()` returning a complete row shape
(`wc_product_id, name, revenue, quantity, orders, unique_customers`) behind a
`limit` capped at 100 with no way to get the rest.

Products rather than customers, and the choice was close. `product_report()`
already returns every column an export would emit, so the work is a cap, a
header and a streaming response modelled on the order export three modules over.
A customer export has no list query to build on at all — `/customers` returns
metrics over time and `/customers/top` returns a ranking of 100 — so it needs a
new query as well as a new endpoint, and §3 will not let both sit on
`api/analytics/services/analytics_engine.py` in one batch. The customer export
is in §5 and should come back.

The spec must settle the same question the order export settled: above the cap
this is a 400 naming the matched count, never a truncated file, and a filter
matching nothing is a header row rather than an empty download.

### 4.4 The segment export emits a fixed header, and the document is off by one about it

**Candidate 4, and it is the document's own evidence for its third Daily row.**
`export_segment_csv()` writes one literal header and one literal row list —
`email, first_name, last_name, total_spent, order_count, last_order_at,
segment_name, rfm_r, rfm_f, rfm_m, score`. `columns` appears zero times in
`api/analytics/routes/segments.py`, so there is no way to ask for a subset or a
different order.

**The gap list says ten columns. There are eleven.** Counted twice in
`api/analytics/services/segment_engine.py`. It changes nothing about whether the
row is real, and it is the kind of detail that decides whether the next reader
trusts the rest of the paragraph, so it is recorded here rather than quietly
corrected.

This is the same document row batch 14 re-scoped onto the order export. That
version is still open and is still not carried — §5 — so this batch takes the
gap at the file the document actually cites, which has the side effect of
landing on a file pair nothing else here touches. Custom fields are **not** in
this row for the reason batch 14 gave and I re-checked: `sync_engine.py` ingests
no custom meta, so offering them would be offering an empty column.

Unlike most rows in this family, the export it widens is already reachable:
`platform/app/api/analytics/segments/[name]/export/route.ts` streams the file
with its `Content-Disposition` intact and the segment detail page fetches it. So
this improves something a merchant can use today rather than adding a knob to a
capability with no door.

### 4.5 A deployed, proxied endpoint that no page has ever asked for

**Candidate 5, and it is cheaper than any reachability row batch 14 carried,
because even the proxy is written.** `GET /api/analytics/sources/timeline-by-campaign`
is declared in `api/analytics/routes/sources.py` and returns
`{periods, campaigns: {name: [{period, customers, orders, revenue, ad_spend, cpa}]}}`.
`platform/app/api/analytics/sources/timeline-by-campaign/route.ts` exists and
forwards `start` and `end`. And `platform/app/(dashboard)/analytics/sources/page.tsx`
fetches `/api/analytics/sources`, `/sources/insights`, `/sources/timeline` and
`/sources/budget/...` — and never this one. The string `timeline-by-campaign`
appears zero times on the page.

So the work is a request and a render, with no API change and no proxy change.
It is the FEAT-035 family in its purest form: a capability that exists, is
deployed, has a door built for it, and is not on the wall.

The gap list calls UTM attribution *"Has, and ahead"* and names it as one of two
things *"worth protecting rather than closing"*. A per-campaign series with
spend and CPA on it is the part of that claim a person can actually look at, and
it is the part currently unreachable.

## 5. What I turned down, and why

`principles.md`: *"Rejections are the informative half."*

**Multi-value order filters on the orders page and its two proxies.** Real,
buildable — `platform/app/(dashboard)/analytics/orders/page.tsx` and
`platform/app/api/analytics/orders/route.ts` are both writable — and
deliberately held for one batch. Both proxies read `searchParams.get()`, so the
API's repeated-parameter support reaches nobody. The reason not to carry it now
is candidate 1: the moment the page can express "completed or processing", the
download control derives its parameters from the list's, the export route binds
the last value only, and the file silently describes a narrower population than
the table beside it. That is the exact defect this system exists to avoid, and
it would arrive through a contract that auto-merges. **Emit it next batch, after
candidate 1 has landed.** This is a sequencing decision and not a judgement that
the work is wrong.

**Export column selection on the order export** (batch 14 candidate 3, still
open, `columns` still zero in `api/analytics/routes/orders.py`). Held for §3's
reason and nothing else: it shares both files with candidate 1, candidate 1 is
the correctness row, and batch 14's two rows on that pair are the two that did
not ship. It should be re-emitted the moment candidate 1 lands or lapses.

**A CSV export of the customer report.** Real, and the document's Daily export
row names it. Held because it needs a customer list query that does not exist
and would sit on `api/analytics/services/analytics_engine.py`, which candidate 3
claims. The segment export covers one segment at a time and is not a substitute.

**Scheduled digests, recurring exports, and any cross-store roll-up.** Turned
down for the reasons batch 14 gave, re-verified and unmoved. A digest needs
something that runs on a timer and something that delivers; `api/worker.py` is
protected by both platform contracts, `api/services/email_sender.py` is on the
email floor, and every one of the api contract's twenty-seven writable files is
reached from a request. A roll-up needs a cross-tenant surface, therefore a new
module under `api/analytics/routes/`, and that contract enumerates files with no
glob, so no new module there can be written by any task at all. Both may be
right for DD; neither can be unattended work, and saying so in a rationale is
better than naming a path and letting a gate discover it.

**The profit dashboard, product COGS, gateway fees.** No cost column exists
anywhere in the analytics schema. A column is a schema change, and everything
under the analytics migrations tree is on the protected floor for every
contract, so this is not unattended work however it is scoped. The prior
question is anyway not a schema one: cost data is a feed HIB would have to
supply and nobody has been asked for it.

**Refund rate over time, and refunds by country.** `research/refund-coverage.md`
returned an explicit no-go: `refund_total` is `NOT NULL DEFAULT 0` and the
writer coerces an absent field to zero, so no query can separate a store with no
refunds from a store whose refunds were never reported. The repair is a nullable
column, which is the floor again. Candidate 2 is narrower than that thread and
survives it, because it renders the count beside the money instead of computing
a rate.

**Subscriptions, carts, device, variation and custom-meta reporting, and
multi-currency.** No subscription or cart table exists, `order_items` carries no
variation id, `sync_engine.py` ingests no custom meta, there is no device field,
and every order on both tenants is GBP so a currency report renders one line.

**A defect I found and am not proposing, because it is not a candidate's
shape.** `platform/app/api/analytics/segments/[name]/route.ts` fetches
`/api/analytics/segments/{name}/export` — the CSV endpoint — and then calls
`res.json()` on it and returns the result as JSON. There is no
`/segments/{name}` endpoint on the API to fetch, nothing in the frontend calls
this proxy, and if anything ever did it would throw and return a 500 labelled
"Failed to fetch segment detail". It is a copy-paste of the sibling export proxy
with its CSV handling removed. The correct change is almost certainly deleting
the file, and `new_test_bites.sh` requires one added test that fails before the
change — which a deletion does not give you cleanly. It is recorded here for a
person rather than turned into a row an unattended task would struggle with.

## 6. The candidates

```fleet-candidates
source:
  document: specs/metorik-gap.md
  sha: da496f8
  repo: fleet

ordering: unranked

objectives_considered: >
  Weighed dd-trustworthy against dd-feature-parity row by row, because
  principles.md ranks trust above parity and objectives-2026-Q4.yaml warns that
  dd-feature-parity without a baseline "ranks build another report forever" and
  that parity work "must not outrank correctness work by default". This is the
  first batch from this document that is not entirely parity, and the split is
  one row to four rather than a balance. Candidate 1 is labelled dd-trustworthy
  and the argument has to be made rather than asserted, because it is latent
  today - no page sends a repeated parameter, so no merchant can currently reach
  the divergence between the CSV and the table. I label it trust anyway on two
  grounds. The code already states the guarantee it breaks, in the export's own
  docstring and in the export proxy's header comment, so this is a metric
  telling two stories rather than a feature that is missing. And it is the
  precondition for the frontend multi-select the batch deliberately holds back,
  so building it first is what stops that work from shipping the defect. The
  other four are parity and are labelled honestly as such. I considered
  dd-first-revenue for the sources row, since a per-campaign CPA series is the
  thing an agency evaluation would look at, and rejected the label rather than
  the row: the agency partner is unsigned and principles.md forbids inventing a
  counterparty's habits, so the value has to rest on the gap list's own estimate
  rather than on a named prospect. cost-discipline is neither served nor
  threatened - every row is query or render work over data that already exists,
  and none adds a fixed monthly cost.

unasked_question: >
  Nobody has asked HIB's team, or the unsigned agency partner, which of these
  reports they would open. Every coverage figure below describes what HIB's
  store HAS, not what anybody WANTS from it, and the two are different claims -
  payment_method being populated on 97.83% of orders says a breakdown is
  possible, not that anyone would read it twice. The gap document's whole
  Agency-use column is one person's estimate with no agency behind it and says
  so, and DD holds no event, session or page-view table on any schema, so this
  cannot be settled later by observation either. There is a sharper version for
  this batch. Two of these five rows exist only because a shipped, deployed,
  proxied endpoint reaches no page, and one of them - the per-campaign source
  timeline - has had a working proxy written for it and never been requested by
  anything. Somebody built the door and nobody asked for the room. One
  conversation asking which three of these a merchant would open in their first
  week would replace the ordering of this entire batch with something measured.

candidates:

  - title: Let the order CSV export take several values per filter, as the order list already does
    repo: deadly-digital-platform
    objective_ref: dd-trustworthy
    verified_sha: ab65311885b65cb6e6cf2f0085678f18ac7f8220
    rationale: >
      GET /orders declares status, payment_method, country and coupon as
      repeatable query parameters, four of them, with a MAX_FILTER_VALUES cap
      that refuses rather than trims. GET /orders/export declares the same four
      as bare str. FastAPI binds a repeated parameter on a str field to the last
      value, so completed-or-processing filters the table on both and the file
      on processing alone, with a 200, no warning and a filename that claims to
      be the orders. The export's own docstring says the file's population is
      the population the page reported, and the export proxy's header says the
      file and the table have to describe the same population - so the code
      already states the guarantee this breaks. It is LATENT today and the spec
      should say so rather than overstate it, because the page builds its query
      with params.set and both proxies read searchParams.get, so nothing in the
      product can currently send a repeat. It becomes reachable the moment the
      orders page offers a multi-select, which is why this is worth doing before
      that and not after. The work is small because the query builder is already
      done - export_orders_csv declares every filter as FilterValues and goes
      through the same _filter_clause as the list. What must move is the route
      signature and the cap check, which the list route already has in
      _check_filter_caps and the export route does not.
    evidence:
      - document: specs/metorik-gap.md
        sha: da496f8
        repo: fleet
        section: "Daily — Order filtering: status, payment, shipping, location, customer tags, email engagement, products contained"
      - document: specs/metorik-gap.md
        sha: da496f8
        repo: fleet
        section: "Daily — CSV export of orders / customers / products"
    suggested_paths:
      - api/analytics/routes/orders.py
      - api/analytics/services/order_query.py
    hib_signal:
      value: payment_method populated on 2,782,530 of 2,844,177 orders on tenant 2 across nine distinct payment methods, so a gateway filter carrying two values is a request this store's data can actually answer differently from a one-value one
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: payment_method
        populated: 2782530
        total: 2844177
    probes:
      - path_exists: api/analytics/services/order_query.py
      - grep_count:
          glob: api/analytics/routes/orders.py
          pattern: 'payment_method: str = Query'
          expected: 1
      - grep_count:
          glob: api/analytics/routes/orders.py
          pattern: 'status: str = Query'
          expected: 1
    premise:
      - claim: >
          The order list route already declares those same four filters as
          repeatable query parameters, so the export is being brought level with
          a form this API already serves rather than being given a new one.
        probe:
          grep_count:
            glob: api/analytics/routes/orders.py
            pattern: 'Optional\[List\[str\]\] = Query'
            expected: 4
      - claim: >
          The query builder both callers share already accepts several values
          per field, so this widens a route signature rather than teaching the
          where-clause a shape it has never emitted.
        probe:
          grep_count:
            glob: api/analytics/services/order_query.py
            pattern: 'FilterValues'
            expected: 14

  - title: Render the net-revenue figures the revenue endpoint already returns
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: ab65311885b65cb6e6cf2f0085678f18ac7f8220
    rationale: >
      The revenue trends page discards the net-revenue figures its own payload
      carries. revenue_report gives every period row a net_revenue beside its
      gross and revenue_summary gives the window the same, and the page matches
      net_revenue zero times and refund zero times across 535 lines. The proxy
      hands the API's body back unmodified, so the figures reach the browser
      today. This is one file, no proxy change, no query. It is NOT the row that
      shipped on 14 Sep - that put net revenue on the analytics OVERVIEW page,
      and this is the revenue trends page. Batch 14 said net revenue on this
      page was real and held it back only because the coupon block already
      claimed the file; that block has landed. One property must come from the
      payload rather than be invented: net must ship beside refunded_amount and
      orders_with_refund, because net equal to gross is the common case here and
      has to read as no refund being recorded rather than as refunds netting to
      nothing.
    evidence:
      - document: specs/metorik-gap.md
        sha: da496f8
        repo: fleet
        section: "Daily — Net revenue (gross less refunds) on the main figures"
      - document: research/refund-coverage.md
        sha: da496f8
        repo: fleet
        section: "what the refund_total column can and cannot be asked"
    suggested_paths:
      - platform/app/(dashboard)/analytics/revenue/page.tsx
    hib_signal:
      value: refund_total is non-zero on 1 of 2,844,177 orders on tenant 2, which is why the refunded count has to be rendered beside the money rather than instead of it
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: refund_total
        populated: 1
        total: 2844177
    probes:
      - path_exists: platform/app/(dashboard)/analytics/revenue/page.tsx
      - grep_count:
          glob: platform/app/(dashboard)/analytics/revenue/page.tsx
          pattern: 'net_revenue'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/revenue/page.tsx
          pattern: '[Rr]efund'
          expected: 0
    premise:
      - claim: >
          The revenue proxy hands the API's response body back unmodified, so
          the figures reach the page today and no proxy change is part of this
          work.
        probe:
          grep_count:
            glob: platform/app/api/analytics/revenue/route.ts
            pattern: 'NextResponse\.json\(data'
            expected: 1
      - claim: >
          Net revenue is already a float on the rows the engine returns rather
          than something this page would have to derive from gross and refunds
          itself.
        probe:
          grep_count:
            glob: api/analytics/services/analytics_engine.py
            pattern: '"net_revenue": float'
            expected: 4

  - title: Render the payment-method breakdown the revenue endpoint already returns
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: ab65311885b65cb6e6cf2f0085678f18ac7f8220
    rationale: >
      The revenue endpoint returns payment_methods as a top-level key, computed
      server-side over exactly the rows gross revenue is summed from, and the
      revenue trends page matches payment zero times across 535 lines. The proxy
      hands the API's body back unmodified, so the block reaches the browser
      today. This is one file, no proxy change, no query. It is NOT the row that
      shipped on 14 Sep - that shipped the AGGREGATE in the API, which is why
      payment_method_breakdown exists and why nothing renders it. One property
      must come from the payload rather than be invented: the block's named
      bucket for orders carrying no method must be shown, or the percentages
      describe 97.83% of the store while being printed as the store.
    evidence:
      - document: specs/metorik-gap.md
        sha: da496f8
        repo: fleet
        section: "Rarely — Payment method breakdown"
    suggested_paths:
      - platform/app/(dashboard)/analytics/revenue/page.tsx
    hib_signal:
      value: payment_method populated on 2,782,530 of 2,844,177 orders on tenant 2, leaving 61,647 with none, which is the bucket the block has to name rather than drop
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: payment_method
        populated: 2782530
        total: 2844177
    probes:
      - path_exists: platform/app/(dashboard)/analytics/revenue/page.tsx
      - grep_count:
          glob: platform/app/(dashboard)/analytics/revenue/page.tsx
          pattern: 'payment'
          expected: 0
    premise:
      - claim: >
          The revenue endpoint already returns the payment-method breakdown as a
          top-level key of its response, so the page renders a payload it
          receives rather than asking for a report to be computed.
        probe:
          grep_count:
            glob: api/analytics/routes/revenue.py
            pattern: 'payment_methods'
            expected: 4
      - claim: >
          The revenue proxy hands the API's response body back unmodified, so
          the block reaches the page today and no proxy change is part of this
          work.
        probe:
          grep_count:
            glob: platform/app/api/analytics/revenue/route.ts
            pattern: 'NextResponse\.json\(data'
            expected: 1

  - title: Add a CSV export of the product performance report
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: ab65311885b65cb6e6cf2f0085678f18ac7f8220
    rationale: >
      The media type text/csv appears exactly twice across every module in
      api/analytics/routes - orders.py and segments.py - and the document's
      Daily export row names orders, customers and products. Orders shipped on
      14 Sep. Products has product_report returning a complete row shape already
      (wc_product_id, name, revenue, quantity, orders, unique_customers) behind
      a limit capped at 100, so a merchant can see the top hundred products and
      has no way to get the rest of them in any form. The work is the order
      export's shape one module over - a row cap that refuses rather than
      truncates, a header written before anything can return early so a filter
      matching nothing yields a header rather than an empty file, and a
      StreamingResponse with a Content-Disposition. Products rather than
      customers, and the choice was close: product_report already returns every
      column an export would emit, where a customer export has no list query to
      build on at all, since /customers returns metrics over time and
      /customers/top returns a ranking of at most 100. One thing the spec must
      settle rather than let the implementation discover: the export's
      population is the revenue-status population product_report already uses,
      and it must not quietly become all-status on the way out of the same
      module.
    evidence:
      - document: specs/metorik-gap.md
        sha: da496f8
        repo: fleet
        section: "Daily — CSV export of orders / customers / products"
    suggested_paths:
      - api/analytics/routes/products.py
      - api/analytics/services/analytics_engine.py
    hib_signal: null
    probes:
      - grep_count:
          glob: api/analytics/routes/products.py
          pattern: 'csv'
          expected: 0
      - grep_count:
          glob: api/analytics/routes/*.py
          pattern: 'text/csv'
          expected: 2
      - grep_count:
          glob: api/analytics/services/analytics_engine.py
          pattern: 'csv'
          expected: 0
    premise:
      - claim: >
          The product report this would export already exists as a function in
          the writable service module and is already wired into the products
          route, so the export reuses figures the product computes today rather
          than defining a second definition of product revenue.
        probe:
          grep_count:
            glob: api/analytics/routes/products.py
            pattern: 'product_report'
            expected: 2
      - claim: >
          A working CSV download already exists in this package to copy end to
          end, so the file shape, the row cap and the Content-Disposition are
          settled questions rather than new decisions.
        probe:
          grep_count:
            glob: api/analytics/routes/orders.py
            pattern: 'media_type="text/csv"'
            expected: 1

  - title: Let the segment CSV export choose its columns instead of emitting one fixed header
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: ab65311885b65cb6e6cf2f0085678f18ac7f8220
    rationale: >
      This is the document's own evidence for its third Daily row, taken at the
      file the document actually cites. export_segment_csv writes one literal
      header and one literal row list, and the word columns appears zero times
      in the segments route, so there is no way to ask for a subset or a
      different order. The document says ten columns; there are eleven - email,
      first_name, last_name, total_spent, order_count, last_order_at,
      segment_name, rfm_r, rfm_f, rfm_m, score - which changes nothing about
      whether the row is real and is recorded because a reader who spots it will
      wonder what else was quoted rather than read. The work is a repeated query
      parameter validated against the same tuple, so an unknown name is a 400
      rather than a blank column, defaulting to the full list in its current
      order when absent. Two properties must survive: the header the file starts
      with is exactly the columns the rows carry, and the export's population is
      still the segment's population. Custom fields are NOT in this row -
      sync_engine.py ingests no custom meta, so offering them would be offering
      an empty column. Unlike most rows in this family it widens something a
      merchant can already use: the segment export has a proxy and the segment
      detail page fetches it, so this is not a knob on a capability with no door.
    evidence:
      - document: specs/metorik-gap.md
        sha: da496f8
        repo: fleet
        section: "Daily — Export with chosen columns, reordered, incl. custom fields"
    suggested_paths:
      - api/analytics/routes/segments.py
      - api/analytics/services/segment_engine.py
    hib_signal:
      value: all seven RFM buckets are populated on tenant 2, so every segment this export can be asked for returns rows rather than an empty file - which is what makes a column choice something a person would exercise
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage: null
    probes:
      - grep_count:
          glob: api/analytics/routes/segments.py
          pattern: 'columns'
          expected: 0
      - grep_count:
          glob: api/analytics/services/segment_engine.py
          pattern: 'rfm_m", "score",'
          expected: 1
    premise:
      - claim: >
          The segment CSV is already reachable by a merchant, because a proxy
          route exists for it and the segment detail page fetches it, so this
          widens an export people can download today rather than building a
          door for one nobody can open.
        probe:
          path_exists: 'platform/app/api/analytics/segments/[name]/export/route.ts'
      - claim: >
          The route already delegates the whole file to one service function, so
          the column list has a single home to make selectable rather than being
          spread between the route and the query.
        probe:
          grep_count:
            glob: api/analytics/routes/segments.py
            pattern: 'export_segment_csv'
            expected: 2

  - title: Put the per-campaign source timeline in front of somebody on the sources page
    repo: deadly-digital-platform
    objective_ref: dd-feature-parity
    verified_sha: ab65311885b65cb6e6cf2f0085678f18ac7f8220
    rationale: >
      GET /api/analytics/sources/timeline-by-campaign is declared on the API and
      returns a daily per-campaign breakdown carrying customers, orders,
      revenue, ad_spend and cpa. A Next.js proxy for it exists and forwards the
      window. And the sources page fetches /api/analytics/sources,
      /sources/insights, /sources/timeline and /sources/budget, and never this
      one - the string timeline-by-campaign appears zero times in 1,194 lines.
      So this is the FEAT-035 family in its purest form and the cheapest row in
      this batch: a capability that is built, deployed and proxied, with the
      door already cut, and no page that walks through it. No API change and no
      proxy change - the work is a request and a render on the page that already
      shows the aggregate version of the same series. It is worth doing for a
      reason beyond cheapness: the gap list calls UTM attribution Has, and
      ahead, and names it as one of only two things worth protecting rather than
      closing, on the strength of CPA and LTV by source. A per-campaign series
      with spend and CPA on it is the part of that claim a person can look at,
      and it is the part currently unreachable. One property the spec must
      carry: ad_spend is Meta-only, so a campaign with no Meta spend must render
      as no spend recorded rather than as a zero-cost campaign with an infinite
      return.
    evidence:
      - document: specs/metorik-gap.md
        sha: da496f8
        repo: fleet
        section: "Weekly — UTM source attribution"
      - document: specs/metorik-gap.md
        sha: da496f8
        repo: fleet
        section: "Weekly — Ad platform integrations (Meta, Google, TikTok, Pinterest, Snapchat, Reddit, Bing)"
    suggested_paths:
      - platform/app/(dashboard)/analytics/sources/page.tsx
    hib_signal:
      value: utm_source, utm_medium and utm_campaign are populated on 2,010,699 of 2,844,177 orders on tenant 2, so a per-campaign series has roughly 70% of the store's orders behind it and the uncovered 29% has to be visible rather than absorbed
      as_of: '2026-08-28'
      source: specs/metorik-gap.md
      coverage:
        metric: utm_source
        populated: 2010699
        total: 2844177
    probes:
      - path_exists: platform/app/api/analytics/sources/timeline-by-campaign/route.ts
      - grep_count:
          glob: platform/app/(dashboard)/analytics/sources/page.tsx
          pattern: 'timeline-by-campaign'
          expected: 0
      - grep_count:
          glob: platform/app/(dashboard)/analytics/sources/page.tsx
          pattern: '/api/analytics/sources/timeline'
          expected: 1
    premise:
      - claim: >
          The endpoint this row would surface is declared on the API rather than
          only described somewhere, so the page requests a report that answers
          rather than one that has to be written first.
        probe:
          grep_count:
            glob: api/analytics/routes/sources.py
            pattern: '/timeline-by-campaign'
            expected: 2
      - claim: >
          The proxy for it is already written and already points at that
          endpoint, so no route on either side is part of this work and the page
          can call a path that resolves today.
        probe:
          grep_count:
            glob: platform/app/api/analytics/sources/timeline-by-campaign/route.ts
            pattern: 'sources/timeline-by-campaign'
            expected: 1
```

## 7. File contention, and an order to approve these in

There is none between the pieces of work. Every row sits on files no other row
names — **with one exception introduced by the §0 edit**, marked below:

    1   order export, multi-value filters    orders.py, order_query.py
    2a  net revenue                          analytics/revenue/page.tsx  <- same file
    2b  payment-method breakdown             analytics/revenue/page.tsx  <- same file
    3   product report CSV export            products.py, analytics_engine.py
    4   segment export column choice         segments.py, segment_engine.py
    5   per-campaign source timeline         analytics/sources/page.tsx

If an order is wanted: **1 first**, because it is the correctness row and
because the held frontend multi-select row must not precede it; then **5, then
2a and 2b**, which are the cheapest and are pure render work over payloads that
already arrive; then **3 and 4**, which are new endpoints and new service work.

**2a and 2b cannot run the same night and do not need to be stopped by hand.**
They name one file, so whichever is approved first takes it, and gate 3
(`path_overlap`) holds the other while that task is non-terminal. The rest can
run alongside either of them.

## 8. On not deduplicating, and what that means for the six unbuildable rows

`specs/approval-surface.md` §7 forbids deduplicating against previous batches
and the contract enforces it — there is no route from this task to the
`candidates` table and I have not seen one row of it. So everything above was
written from the gap list and the checkout, and any row here that has appeared
before has appeared again because the work is still real, which is the signal
§7 wants preserved.

The task spec says the highest-value thing this run can do is re-emit the six
rows that are held on `unwritable_path` and `protected_path`, because the work
may be real and the row is what is broken. Taking the four examples it names:

* the two rows naming `api/analytics/routes`, a directory — a digest and a
  cross-store roll-up on batch 14's reading — are refused in §5 with the reason
  written into the prose rather than the path, because neither can be unattended
  work under any contract that exists today;
* the row naming `platform/app/(dashboard)/segments/builder/page.tsx` has a
  buildable descendant, and that descendant has now SHIPPED on the API: the
  order list takes several values per filter. What is left of it is candidate 1
  and the frontend row held in §5;
* the row naming a product-categories migration on the protected floor is
  closed on both halves — the endpoint merged as `1f8b7fe` and the page reaches
  it — so there is nothing to re-emit.

I cannot map any of those to a candidate number, and §9.1 says so.

## 9. What I could not establish

1. **Which candidate ids these correspond to, or whether any of them is already
   in the pool.** I have no route to the `candidates` table and have not seen
   it. The task spec names c24, c25, c28 and c35 by number and by path; I could
   reason about the paths and not about the rows, so §8 is a mapping from
   descriptions to work rather than from ids to work. If one of these five is
   already open under another number, that is the reappearance §7 wants and not
   a mistake I could have avoided.

2. **Whether anybody wants any of this.** Said at length in the block's
   `unasked_question` and repeated because it is the largest limit on the page.
   Nothing here is measured demand: the Agency-use band that orders the source
   document is one person's estimate, no agency has been asked, and DD holds no
   telemetry that could answer it later.

3. **That any capability I read actually works.** Everything was established by
   reading the checkout at `ab65311`. `payment_methods` appearing four times in
   `api/analytics/routes/revenue.py` is not a correct breakdown, and a mounted
   `/sources/timeline-by-campaign` is not a report that returns the right rows.
   Nothing was exercised against a running API and no query was run against
   production.

4. **Whether candidate 1's divergence is reachable by any client I did not
   read.** I established that the orders page and both proxies send one value
   per field. I did not audit every caller of `/api/analytics/orders/export` —
   there may be a script, a test fixture or an integration that repeats a
   parameter, in which case the defect is live rather than latent and the row is
   worth more than I have claimed. The rationale states the conservative
   reading.

5. **Every population figure is quoted, not re-run.** Each `coverage` object
   carries `as_of: 2026-08-28`: these are the gap document's figures, seventeen
   days old, tenant 2 only. `deadly_digital` also holds `analytics_1`, which
   behaves differently enough that
   `research/EVIDENCE-refund-coverage-manifests.md` is largely about the
   difference. Anything decided on these numbers is decided on a
   two-and-a-half-week-old observation of one store.

6. **Whether the unreachable endpoints are unreachable by decision.** I
   established that no page requests `/sources/timeline-by-campaign` and that
   the revenue page renders neither net revenue nor the payment-method block. I
   did not establish that nobody intended it that way, or that a frontend half
   is not already queued under a task row I cannot see. Gate 3 catches that at
   approval time against live tasks, which is the check I am relying on rather
   than one I ran.

7. **The §3 claim that contention is what killed batch 14's two unshipped
   rows.** It is one observation on a sample of seven, and ranking is an equally
   good explanation that I cannot distinguish from it without seeing the pool.
   This batch is built on it anyway, and it cost two rows I would otherwise have
   carried — so if it is wrong, the cost is visible in §5 rather than hidden.

8. **Whether `ab65311`'s working tree is its commit.** Probes read the tree and
   `verified_sha` names the ref. I cannot run `git status` under this contract,
   so a dirty checkout would make the two describe slightly different things.
   The same caveat applied to batches 9 through 14 and is stated rather than
   assumed away.

9. **The premise probes are predicates, not proofs of the sentence above them.**
   `FilterValues` appearing fourteen times in
   `api/analytics/services/order_query.py` establishes that the name is used a
   lot; the claim it sits under is that the shared where-clause accepts several
   values per field. I read the type alias and the builder and it does, but the
   check re-executes the predicate and not the reading, and that gap is the one
   `candidate_block_shape.py`'s own docstring says the premise key moves rather
   than closes.

10. **Metorik's side.** No account and no web access in this contract, so
    nothing here checks that Metorik still ships any of these features. The
    parity claim throughout is inherited from
    `research/metorik-gap-2026-08-30.md`'s retrieval dates, read on 30 August
    2026.
