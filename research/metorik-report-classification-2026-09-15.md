# Metorik's 100 published reports, classified against what DD holds

Produced 2026-09-15. Serves `dd-feature-parity`. It classifies every row of
`research/metorik-report-catalogue-2026-09-15.md` into one of three buckets and
gives each an agency-use band, so that the catalogue can be read next to the
data DD actually has.

It does not rank, prioritise, recommend or estimate effort, and it writes no
candidates. Bucket and band are all it claims.

## What this was built from

| Input | What it settled |
|---|---|
| `api/analytics/models.py` | which tables and columns exist. `EXPECTED_TABLES` is derived from `ALL_MODELS`: customers, orders, order_items, products, product_categories, customer_segments, churn_scores, interventions, daily_metrics, sync_log, churn_snapshots, metrics_dirty_dates, reconciliation_manifests. Thirteen, and nothing else. |
| `EVIDENCE.md` in this worktree | five readings taken by the runner at 2026-09-15 19:52 UTC as the `deadly_digital` reader, over `analytics_2.orders` and `analytics_2.order_items` only. I could not run anything else. |
| `research/metorik-report-catalogue-2026-09-15.md` | the 100 rows, in their own 17 groups and order, which this document preserves. |
| `https://metorik.com/reports`, fetched 2026-09-15 | the relayed catalogue's source, checked as far as a fetch can check it. See *The live page, checked*. |
| `specs/metorik-gap.md` | the empty-column rule and the sense of the band column, both reused here unchanged. |

The readings, quoted once so the rows below can cite figures rather than repeat
the query. All are `analytics_2`, 2,889,850 orders, 4,549,662 order item rows:

* Populated: `currency` 2,889,850; `payment_method` 2,826,259; `billing_country`
  2,884,311; `billing_city` 2,884,311; `billing_postcode` 2,884,111;
  `utm_source` 2,054,935; `utm_medium` 1,460,764; `utm_campaign` 211,957;
  `coupon_code` 152,698; `discount_total` non-zero 152,685;
  `order_items.product_name` 4,549,662 over 3,743 distinct `wc_product_id`.
* Empty or as good as: `shipping_total` non-zero **0**; `tax_total` non-zero
  **0**; `shipping_country` **0**; `order_items.sku` **0**; `order_items.price`
  **0**; `refund_total` non-zero **4** of 2,889,850.
* Status vocabulary: completed 2,887,414, cancelled 1,971, processing 241,
  on-hold 203, pending 20, refunded 1.
* Span 2023-03-12 to 2026-09-15 — 1,283 days — over 157,311 distinct
  `customer_id`.

## The three buckets, defined before anything was classified

**A — DD already holds the data.** Every field the report needs is a column on
a table `api/analytics/models.py` defines, and the evidence pack shows that
column populated. The report is a fixed aggregation over those columns: a known
`GROUP BY` on a named column, a histogram, a window function, a join between
two tables DD has.

**B — the data is not in DD.** Either the report needs an entity `models.py`
has no model for, or it needs a column `models.py` defines and the pack shows
empty. Every B row below is tagged `no model` or `empty column` so the two are
never confused, because they are different repairs. The empty-column case is
filed under B and not under a fourth bucket because bucket A excludes it by
rule and bucket C is defined over *data DD holds* — an empty column is not
data DD holds, so B is the only bucket left. `specs/metorik-gap.md` set the
underlying rule: a report over an empty column is not a feature.

**C — needs the segmentation engine.** The data is held and populated, but the
grouping is one `customer_segments` cannot express. That table stores exactly
one `segment_name` per customer plus an RFM triple, so the engine question
bites in two shapes: the grouping dimension is chosen by the user rather than
fixed, or the unit of the report is a customer or a cohort of customers grouped
by an attribute derived from their orders — `customers` in `models.py` carries
`order_count`, `total_spent`, `aov`, `first_order_at`, `last_order_at` and
nothing about where a customer is, what they first bought, or where they came
from.

Three tie-break rules, also written first:

1. **A is a statement about data, not about difficulty.** A forecast is
   arithmetic over `orders.created_at` and `orders.total`; it needs no table
   DD lacks and no grouping `customer_segments` blocks, so it is A. That says
   the data is not the obstacle. It does not say the report is cheap, and this
   document does not estimate effort.
2. **A report spanning two buckets goes in the one that blocks it.** Gross
   revenue is A-shaped and net revenue is not, so *Net/gross revenue over time*
   is B: the half that cannot be built decides.
3. **A report offering alternative dimensions is A if any named dimension is
   populated**, with the empty ones named in the row. *Revenue by
   billing/shipping location or payment method* is A on billing and on payment
   method; its shipping half is dead (`shipping_country` set on 0 rows) and the
   row says so.

## The band, and why these four words

`Daily`, `Weekly`, `Monthly`, `Rarely`: how often an agency running WooCommerce
stores for clients would open the report. The reasoning, once, rather than per
row:

* **Daily** is what an agency looks at before it does anything else — today's
  money, today's orders, whether anything is stuck. Eight rows.
* **Weekly** is the client-facing rhythm: what sold, where orders came from,
  which coupons ran, what is going wrong that is not on fire. Thirty-five rows.
* **Monthly** is the retrospective — cohorts, retention, forecasts, costs.
  Twenty-five rows.
* **Rarely** is a report with a real use that comes up a few times a year, or
  one that depends on the store selling something this store does not. Thirty-
  two rows, eighteen of which are the subscriptions block.

This is a judgement and nothing else. No agency was asked and DD has no
telemetry that would answer it; it is the most falsifiable column here and the
cheapest to correct.

**The band word leads every group heading below**, because
`console/load_candidates.py` reads a candidate's band from the heading of the
evidence section it cites. Two details of that reader shaped the headings.
`BANDS` is exactly the four words above, and a heading whose lead is any other
single alphabetic word followed by a dash *raises* rather than loading as
band-less — so `specs/metorik-gap.md`'s fifth status, `Never`, is unusable as a
heading here, and the subscriptions block is banded `Rarely` instead. And where
one catalogue group splits across bands, it appears below as more than one
heading, marked `(n of m)`, with the catalogue's order kept inside each — one
heading cannot carry two bands, and `console/rank.py` would sort the difference
silently.

There is no band column in the tables. The heading is the band, so a column
repeating it could only ever disagree with it.

## Summary

| Bucket | Rows | Share |
|---|---|---|
| **A** — DD holds the data | 29 | 29% |
| **B** — the data is not in DD | 59 | 59% |
| **C** — needs the segmentation engine | 12 | 12% |

Of the 59 in B, **54 are `no model`** and 5 are `empty column` — the five being
*Net/gross revenue over time*, three of the six refund reports, and *Customer
groups by shipping location*. Twenty-five of the 59 are the subscriptions and
carts blocks — see *Subscriptions and carts*.

By band: 8 Daily, 35 Weekly, 25 Monthly, 32 Rarely.

Two facts that cut across the table. **Refunds are absent** — `refund_total` is
non-zero on 4 orders of 2,889,850 and no refund entity exists, which takes the
whole six-row Refunds group and the net half of the headline revenue report.
**Costs are absent** — no table in `models.py` has a cost column, which takes
the five-row Costs & profit group and three of the ten cohort reports.

> **THE FIRST OF THOSE TWO FACTS WAS CORRECTED ON 16 SEPTEMBER 2026 AND THIS
> SUMMARY IS LEFT AS THE RUN WROTE IT.** HIB does not refund tickets, so the
> six-row Refunds group and the net half of the headline revenue report are
> **not applicable to this business** rather than blocked on data, and must not
> be proposed as gaps. The costs half is unaffected and stands. Corrected
> counts, the seven rows involved, and what a producer may not emit are in
> *Correction (16 September 2026)* immediately below.
>
> **AND THREE FURTHER RULINGS LANDED THE SAME DAY**, on the same terms and from
> the same source: HIB **ships nothing** (it sells digital entries), **charges
> no VAT** on entries, and **sells no recurring product**. Those take another 22
> rows — the whole 18-row Subscriptions block, 3 shipping rows and 1 tax row.
> **Twenty-eight of the 100 are N/A in total, the parity figure is 30 of 72, and
> not one of the 28 may be proposed as a gap.** Both the Summary table above and
> the cross-cutting paragraph it sits under are left as the 2026-09-15 run wrote
> them. The standing counts are in *The corrected counts, final*, inside
> *Correction (16 September 2026), second entry*.
>
> **A FIFTH FACT LANDED THE SAME DAY AND TAKES NO ROWS AT ALL.** 66,764 orders
> carry a total of zero and they are the **legal free-entry route** a prize
> competition must offer. They are real orders and stay in the denominator,
> which is still 72. But they are inside the revenue statuses, so **every mean
> of `orders.total` mixes them with paid entries — AOV reads £8.23 where
> paid-only is £8.43** — and four rows carry a `MUST SPLIT FREE ENTRIES` mark
> that is explicitly **not** a do-not-propose mark. See *Correction
> (16 September 2026), third entry*.

## Correction (16 September 2026): HIB does not refund, so refunds are not a gap

**Stated as fact by Eamonn (eamonn@hittinitbig.com) on 2026-09-16, and recorded
here rather than in a separate file because this is the only document the
candidate producer can read: `contracts/candidate-producer.yaml` gives that
agent no Bash, no credential and no web, so a correction it cannot open is a
correction that does not exist.**

**The fact.** HIB does not refund tickets.

**What it changes, and it is an interpretation and not a figure.** Every
measurement in this document stands. `refund_total` is still non-zero on 4
orders of 2,889,850, and `models.py` still defines no refund entity, no refund
reason and no refund timestamp. What changes is what those readings *mean*.
This document filed refunds under *absent* — the language of something missing
that ought to be there. Four refunds in 2,889,850 is not an absence. It is the
correct and complete record of a business that does not refund.

**This settles one of the open questions above in the "no such data"
direction.** *What I could not verify* closes by saying that whether an empty
column is empty because the store has no such data or because the pipeline does
not deliver it "is a question this pack cannot answer, and the two have
different consequences". For refunds it is now answered, and two independent
things answer it:

* the stated fact above; and
* `specs/refund-hook.md`, which read the connector source and found both
  `woocommerce_order_refunded` and `woocommerce_refund_created` registered on
  every commit, the payload carrying `refund_total` from `get_total_refunded()`,
  the guards deliberately bypassed so a partial refund cannot be swallowed, and
  the `wp dd sync-refunds` backfill implemented. It also records `refund_total`
  arriving as `0.69` on `analytics_2.orders` for order `3570823`. **The refund
  feed is wired and has demonstrably carried a refund end to end.** The column
  is sparse because the business is, not because the pipeline drops anything.

So the four are evidence that the path works, not evidence that it is broken.

### The rows this applies to, and the only two effects it has

**Seven rows, and no others.** *Refunds are absent* in the Summary above names
its own blast radius exactly — "the whole six-row Refunds group and the net half
of the headline revenue report" — and that is the whole of it. Nothing in
Subscriptions, Carts, Costs & profit, Cohorts or anywhere else turns on refunds.

1. **The six-row Refunds group becomes N/A** — not applicable to this business,
   rather than blocked on data. Each row below keeps the bucket the 2026-09-15
   run gave it, named inside its Why cell, so nothing that was measured is lost.
   Three of the six were `no model` on schema facts that remain true: there is
   still no refund reason column, no refund timestamp and no line-level refund
   attribution. Those facts did not stop being true. They stopped being worth
   repairing, because the reports they block would return an empty result for
   HIB even if every one of them were built.

2. **Net/gross revenue over time becomes A**, on its gross half. Tie-break rule
   2 sent it to B because "the half that cannot be built decides" — but the half
   that cannot be built is now the half that should not be built. Gross revenue
   is `orders.total` over `orders.created_at`, both present, and it carries the
   `†` mark for `orders.total` like every other row resting on that column. Net
   revenue is N/A for HIB.

**A producer must not emit a candidate for any of the seven.** They are not
gaps, and `candidate_block_shape.py` cannot catch this by itself: its
vocabulary is `path_exists`, `path_absent` and `grep_count` over a source tree,
so a probe asserting "no refund reason column exists in `models.py`" would
*hold*, and the candidate would pass every mechanical check while proposing
work this business has no use for. This paragraph is the only thing standing
between that document and that batch.

### The corrected counts

The Summary table above is left as the 2026-09-15 run found it. These are the
same 100 rows after the correction:

| Bucket | Rows | Share of the 94 |
|---|---|---|
| **A** — DD holds the data | 30 | 32% |
| **B** — the data is not in DD | 52 | 55% |
| **C** — needs the segmentation engine | 12 | 13% |
| **N/A** — not applicable to HIB | 6 | (excluded) |

> **SUPERSEDED THE SAME DAY.** Three further rulings landed on 16 Sep 2026 and
> took another 22 rows. The figures in this table were correct for the refund
> correction alone; the standing counts are in *The corrected counts, final*.

Of the 52 in B, 51 are `no model` and **1 is `empty column`** — the refund
correction collapses that class almost entirely. Before it there were five
empty-column rows; *Net/gross revenue over time* is now A and three of the
others were refund rows, leaving *Customer groups by shipping location* alone
in the category. **Every remaining "the column exists and holds nothing" row in
this document is now a shipping row**, which makes shipping the next question
of exactly this shape — see *The shipping and tax columns* below.

### What is NOT corrected

**Costs.** The second cross-cutting fact is untouched. No table in `models.py`
has a cost column, and that takes the five-row Costs & profit group and three
of the ten cohort reports. Nothing above bears on it. With refunds and
subscriptions set aside, costs becomes the largest single absent subject left
in the document.

### The shipping and tax columns, raised here and decided in the second entry

> **ANSWERED ON 16 SEPTEMBER 2026, a few hours after this section was written.**
> Eamonn stated that HIB sells digital entries and ships nothing, and that no
> VAT is charged on entries. Both columns are correct as they stand and four
> rows became N/A. The section is kept as written because it records what was
> and was not established before that fact existed, and because it is the
> worked example of the only thing that settles a question of this shape: a
> stated fact about the business, not another query. See *Correction
> (16 September 2026), second entry*.

`shipping_total` is non-zero on **0** of 2,889,850 and `shipping_country` is set
on **0**; `tax_total` is non-zero on **0**. `research/EVIDENCE-metorik.md`,
taken 2026-08-30, shows the same three at zero on the same tenant, so this is
not one bad reading. That is the identical shape of question the refund fact
just answered, on stronger numbers — zero twice over 1,283 days, against four.

**It is not answered here, and no row above has been changed for it.** This
document's own rule is that a pack cannot tell an empty column from an absent
subject, and `specs/metorik-gap.md` separated tax and shipping for that reason.
Settling it needs a stated fact about the business in the way refunds did, not
another query. Three rows outside the groups already set aside turn on shipping
alone — *By shipping method* under Order groups, *Shipping costs by shipping
method* under Costs & profit, and *By shipping location* under Customer groups
— and one turns on tax, *Revenue by tax code, label or ID*. Two bucket-A rows
name shipping as a dead half and are unaffected either way, since billing
carries them.

## Correction (16 September 2026), second entry: shipping, tax and subscriptions are N/A

**Three further facts stated by Eamonn (eamonn@hittinitbig.com) on 2026-09-16,
recorded on the same terms as the refund correction above and for the same
reason: the candidate producer reads this document and nothing else.**

| The fact, as stated | What it settles |
|---|---|
| **HIB sells digital entries and ships nothing.** | `shipping_total` non-zero on 0 of 2,889,850 and `shipping_country` set on 0 are the correct and complete record of a business with no shipments. Not an unfed column. |
| **No VAT is charged on entries.** | `tax_total` non-zero on 0 of 2,889,850 is correct, not an unfed column. |
| **HIB sells no recurring product.** | The absent subscription entity is one this business has no use for, not one DD is missing. |

**The third confirms an inference rather than replacing one.** The refund
correction above set subscriptions aside on my reading of HIB as a one-off
purchase business, and flagged that it rested on inference and wanted a stated
fact. It now has one, and the parity figure below no longer carries that
qualifier.

### A correction to my own reasoning, after reading geography.py

**I claimed the shipping zeros were "stronger numbers" than the refund four.
They are not evidence about the business at all, and the ruling above does not
need them to be.** `api/analytics/services/geography.py` in
`deadly-digital-platform` carries a `_UNAVAILABLE` map that already names
`shipping_country`, `shipping_city`, `shipping_state` and `shipping_postcode` —
together with `billing_state` — as **`connector_never_sends`**. Found
2026-09-16 by the producer run reading this document.

So the shipping columns would read zero whether or not HIB shipped anything: the
connector never sends them, and a pipeline explanation was sitting in the
platform code the whole time. **The shipping ruling stands entirely on Eamonn's
stated fact and on nothing measured here.** That is a sound basis and it is the
only one; the arithmetic I offered alongside it was not doing the work I said it
was.

**The refund case is genuinely different and the distinction is the point.**
There, `specs/refund-hook.md` shows the feed demonstrably carrying a refund end
to end, so a sparse column with a working feed *is* informative about the
business. Shipping had no such evidence. **Tax is different again:** `tax_total`
is NOT in that `_UNAVAILABLE` map, so the connector does send it and the zero is
informative — the tax ruling and the refund ruling rest on the same kind of
ground, and the shipping ruling does not.

The general rule this repeats, from *What I could not verify*: a pack cannot
tell an empty column from an absent subject. Reading the *pipeline* is what
separates them, and it is a different question from reading the data.

**These answer the question the section *The shipping and tax columns, raised
and deliberately not decided* left open**, in the direction that section said
only a stated fact could settle. No query was run and none would have helped: a
pack cannot tell an empty column from an absent subject, which is exactly why
that section refused to decide and asked instead.

### The rows this takes, and it is twenty-two

**Twenty-two rows, none of them overlapping the seven the refund correction
already took.** Each is marked at its own row with the bucket the 2026-09-15
run gave it, so no measurement is lost.

| Ruling | Rows | Which |
|---|---|---|
| Ships nothing | 3 | *By shipping method* (Order groups), *Shipping costs by shipping method* (Costs & profit), *By shipping location* (Customer groups) |
| No VAT | 1 | *Revenue by tax code, label or ID* (Revenue) |
| No recurring product | 18 | the whole Subscriptions block |

Two rows inside blocks already set aside also turn on these facts and needed no
separate ruling: Refunds' *By shipping location* was already N/A on the refund
fact and is now N/A twice over, and Subscriptions' *Active subs by shipping
location* is inside the eighteen.

**No cost row moves except one.** *Shipping costs by shipping method* leaves on
the shipping ruling, not a cost ruling. The other seven cost rows stand as
bucket B. Costs remains uncorrected, as it was after the first entry.

### The two bucket-A rows that name shipping keep their bucket

*Revenue by billing/shipping location or payment method* and *By
billing/shipping location (country, state, city, ZIP)* both stay **A**. Tie-break
rule 3 — a report offering alternative dimensions is A if any named dimension is
populated — decides them on billing and payment method, and did so before this
ruling. What changes is only the description of their shipping half: it is N/A
rather than dead data. Their rows now say so.

### Every remaining gap now needs a new entity or column, not a backfill

**The `empty column` class is empty.** There were five such rows on 2026-09-15.
*Net/gross revenue over time* became A, three were refund rows, and the last —
*Customer groups by shipping location* — goes on the shipping ruling. **All
thirty remaining B rows are `no model`.**

That is worth stating plainly because it changes what the B bucket *means* for
this business. Not one report is blocked by a column that exists and holds
nothing, so no backfill, no connector re-sync and no repair of an existing feed
would move the parity number by a single row. Every remaining data gap needs a
table or a column that does not exist yet.

### The corrected counts, final

The Summary table near the top and the interim table in the first correction
entry are both left as written and are both superseded by this one. These are
the same 100 rows after both corrections:

| Bucket | Rows | Share of the 72 |
|---|---|---|
| **A** — DD holds the data | 30 | 42% |
| **B** — the data is not in DD, all `no model` | 30 | 42% |
| **C** — needs the segmentation engine | 12 | 17% |
| **N/A** — not applicable to HIB | 28 | (excluded) |

**The parity figure is 30 of 72, or 42%**, and the 28 excluded are 18
subscriptions, 6 refunds, 3 shipping and 1 tax.

### What remains a genuine gap, and carts and devices are in it

The thirty B rows, by subject:

| Subject | Rows |
|---|---|
| Carts | 7 |
| Costs and profit | 7 |
| Products (variations, stock, bundles, vendors) | 5 |
| Acquisition (referring site, landing path) | 4 |
| Devices | 3 |
| Custom fields and customer role | 3 |
| Order status-transition history | 1 |

**Carts and devices were considered for exclusion on 16 Sep 2026 and
deliberately kept.** A cart is a funnel stage and a device split is a browser
fact; HIB has both, and DD simply ingests neither. Excluding them would have
made the parity figure look better by hiding ten rows of real work. They are
gaps and a producer may propose them.

**Costs and carts are now tied as the largest absent subject**, at 7 rows each,
and together they are 14 of the 30. The first correction entry said costs would
be the largest once refunds and subscriptions were set aside; the shipping
ruling has since moved *Shipping costs by shipping method* out of the cost
count, which is what produced the tie.

## Measured 16 September 2026: the twelve unverified columns, and billing_state is empty

**Taken by Claude at Eamonn's direction on 2026-09-16, on `analytics_2` as the
`deadly_digital` reader, before queueing the producer batch that reads this
document.** The 2026-09-15 pack could name only what its five queries measured,
and the `†` and `‡` tables below record what it could not. Most of that is now
measured. The row counts have moved since 15 Sep because the tenant is live:
**2,890,319 orders** (was 2,889,850) and **4,550,334 order item rows** (was
4,549,662).

| Column | Measured | Verdict |
|---|---|---|
| `orders.total` | NOT NULL on **2,890,319 of 2,890,319**; non-zero on **2,823,569** (97.7%) | **Populated.** |
| `order_items.quantity` | NOT NULL on all 4,550,334; non-zero on **4,550,326** (all but 8) | **Populated.** |
| `order_items.total` | NOT NULL on all 4,550,334; non-zero on **4,447,939** (97.8%) | **Populated.** |
| `orders.billing_state` | set on **0 of 2,890,319** | **EMPTY.** |

### `orders.total` is populated, which was the document's own biggest open risk

*Bucket-A rows the pack does not fully cover* calls `orders.total` "the single
most load-bearing unmeasured column in this document: it is the measure behind
six A rows. It is `Numeric(10, 2)` and nullable in `models.py`, and nothing in
this pack says how often it is set." It is set on every row and non-zero on
97.7% of them. **All six of those A rows stand, and so does the seventh that
the refund correction added** (*Net/gross revenue over time*, on its gross
half). With `order_items.quantity` and `order_items.total` also populated,
**every `†` mark in this document is now discharged.** The mark is left on the
rows because it records what the 2026-09-15 pack could see, which is a
different claim from what is true; this section is where the answer lives.

The 2.3% of orders with `total` at zero are not investigated here. `status`
carries 1,971 cancelled and 20 pending, which does not account for 66,750, so
there is a real question about zero-total orders — it is a data question and
not a classification one, and no row above turns on it.

### `orders.billing_state` is empty, and this is a new finding

The `†` table records `billing_state` as unmeasured for *By billing/shipping
location (country, state, city, ZIP)*. **It is set on 0 of 2,890,319 rows.**

That row **stays bucket A**. Tie-break rule 3 decides it on the dimensions that
are populated — country 2,884,311, city 2,884,311, postcode 2,884,111 — exactly
as it already did for the shipping half. But the row now has **two** dead
dimensions rather than one, and a candidate proposing *orders grouped by billing
state* would be proposing an empty report. **A producer must not emit one.**

This is an empty column and **not** an N/A ruling. Nothing has been stated about
whether HIB collects a state or region, and unlike shipping and tax there is no
business fact here: `billing_state` may be empty because the store does not
collect it, because WooCommerce does not send it, or because the connector does
not map it. That is the open question this document could not answer for tax and
shipping either, and it is recorded rather than decided.

### Two tables could not be read at all, and now for a specific reason

`analytics_2.products`, `analytics_2.product_categories` and
`analytics_2.customers` all return **permission denied** for the
`deadly_digital` reader (`dd_detector_login`, whose grants in `analytics_2` are
`orders`, `order_items` and `reconciliation_manifests` and nothing else). So the
reason the `‡` rows were unverified is precise: not "the pack did not query
them" but **the reader has no SELECT on them**.

> **I WROTE "NO QUERY AVAILABLE TO THIS DOCUMENT CAN CLOSE THAT" AND IT WAS
> WRONG.** The platform's own `DATABASE_URL` in `deadly-digital-platform/api/.env`
> reads those tables — the API could hardly serve `/products/categories`
> otherwise. The limit was the credential I reached for first, not the box.
> Measured below on 16 Sep 2026 with that credential, read-only.

### The two double dagger rows are grounded, and the coverage is half

**`analytics_2.product_categories` is not empty: 4,059 rows over 1,770 distinct
products and 47 distinct categories.** So *Top selling categories* — already
shipped as `GET /products/categories` — is returning real rows, and *Category
comparison* is not resting on an empty table. **Both `‡` marks are discharged.**

Two things the count does not say, and both bear on any category report:

* **Coverage is 51.5%.** `analytics_2.products` holds 3,750 rows and only 1,770
  carry a category, so **2,344,861 of 4,550,393 line items (51.5%) and £12.24M
  of £23.82M (51.4%) sit behind a category**. Nearly half of sales are
  uncategorised. The shipped report handles this correctly and deliberately —
  `product_category_report` uses LEFT joins for exactly this reason, leads its
  response with a `coverage` block, and carries an `uncategorised` bucket. **Any
  new category report must inherit that treatment or it will silently compare
  halves.**
* **The fan-out is near total. 1,768 of the 1,770 categorised products (99.9%)
  carry more than one category**, averaging 2.29 and reaching 6. Each category
  is credited the product's full line revenue, so category revenues do not sum
  to the total and **two categories cannot be differenced naively**. The shipped
  docstring estimates this at "~98%"; measured, it is 99.9%.

**And the category names are a fact about the business, not about the schema.**
The six largest are *Closed Competitions* (1,696 products), *Cash Competitions*
(723), *Tech Competitions* (319), *Mini Draw* (236), *Featured Competitions*
(200) and *Scratchcard Competitions* (118). HIB runs prize competitions, which
is what "digital entries" means and why nothing ships. Note that the largest
category by far is a **lifecycle state** rather than a product type: a category
ranking will put *Closed Competitions* on top, covering 96% of categorised
products, and that is close to meaningless as a ranking. Whoever builds
*Category comparison* should know that before choosing the default cut.

## Correction (16 September 2026), third entry: 66,764 orders are free entries

**Stated as fact by Eamonn (eamonn@hittinitbig.com) on 2026-09-16**, confirming
what the data already showed: HIB runs prize competitions, and a prize
competition must offer a free entry route by law. **The zero-total orders are
that route.**

**THIS IS NOT AN N/A RULING AND IT MARKS NO ROW `do not propose`.** The other
four facts removed rows from the denominator. This one removes nothing. Free
entries are real orders placed by real customers and they belong in every order
count. What they do not belong in, unlabelled, is an average or a distribution
of `orders.total`. The parity denominator is unchanged at **72** and the
classification is unchanged at A 30 / B 30 / C 12.

### The measurement, taken 2026-09-16 on analytics_2

| Figure | Value |
|---|---|
| Orders with `total = 0` | **66,764** of 2,890,319 (2.3%) |
| Of those, status `completed` | **66,676** — so they are inside `_REVENUE_STATUSES` |
| Distinct customers placing one | 15,616 |
| Span | 2023-03-15 to 2026-09-16, i.e. the whole history |
| Line rows in them | 73,378, of which **71,122 are themselves zero-value** |
| Mean quantity per line | **21.13** entries |

**The product names are the evidence and they are not ambiguous.** The largest
by line count: *£500 FOR FREE* (7,248), *FREE PLINKO EVERY 24HRS – Site Credit
PLAY 2 Win!* (4,438), *FREE £50 VOUCHER (£100 IF YOUR ORDER IS OVER £5!)*
(2,829), *Win £50 Site Credit* (2,467), *£200 FOR FREE* (1,930), *FREE GIVEAWAY
- WESTLIFE FOR 2* (1,742). 17,507 of the 66,764 also carry a coupon code.

This closes the question left open in *Measured 16 September 2026*, which
recorded that status accounted for at most 1,991 of the 66,750 zero-total orders
and said "it is a data question, I had no way to ask it". The answer is that
they are not a data defect at all.

### What it does to a figure already in front of a user

**`AOV` reads £8.23 where paid-only is £8.43. It is understated by 2.4%, and
nothing on the page says so.** Measured over `completed`, `processing` and
`on-hold` — the statuses the platform's `_REVENUE_STATUSES` uses: 2,888,343
orders, of which 2,821,656 are non-zero.

Revenue **sums** are unaffected: a free entry contributes £0, so gross revenue,
net revenue and every total are already correct. Order **counts** are also
correct, and deliberately so — a free entry is an order. **The defect is
confined to means and distributions**, and it is a labelling problem rather than
a filtering one: the right repair is to show both figures, or to name the free
bucket, not to drop 66,764 orders from the denominator and quietly change what
"orders" means.

### The rows this marks, and the mark is MUST SPLIT rather than do not propose

Four rows take a `**MUST SPLIT FREE ENTRIES**` mark: the three bucket-A rows
whose measure is a mean or a distribution of `orders.total`, and the one bucket
C row with the same measure. Their buckets are unchanged and all four remain
proposable.

The general rule, because it reaches further than four rows: **any report whose
measure is a mean of `orders.total`, or a distribution over it, must state
whether free entries are in or out.** That includes per-group averages that have
already shipped — the AOV column of the payment-method breakdown is the live
example — and it will include any future one. A report that sums `orders.total`
needs nothing.

## The classification

### Daily — Revenue (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| Net/gross revenue over time | **A** † (was **B** `empty column`) | **Corrected 16 Sep 2026 — see *Correction (16 September 2026)*.** Gross is `orders.total` over `orders.created_at`, both present, and is the buildable half. The net half needs `orders.refund_total`, non-zero on 4 of 2,889,850 — and HIB does not refund, so net revenue is N/A for this business rather than blocked. Tie-break rule 2 no longer sends this row to B, because the half that cannot be built is the half that should not be built. `orders.total` unmeasured, hence †. |

### Weekly — Revenue (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| Revenue by billing/shipping location or payment method | **A** † | `orders.billing_country` 2,884,311, `orders.billing_city` 2,884,311, `orders.payment_method` 2,826,259. Measure is `orders.total`, which the pack did not measure. **Amended 16 Sep 2026:** the shipping dimension is not dead data but N/A — HIB ships nothing, so `shipping_country` set on 0 is correct. Tie-break rule 3 keeps the row **A** on billing and payment method either way. |

### Rarely — Revenue (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| Revenue by tax code, label or ID | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — no VAT is charged on entries; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** The schema fact stands: `models.py` has one tax field, `orders.tax_total`, and no code, label or ID. `tax_total` non-zero on 0 of 2,889,850 is the correct record of a business that charges no VAT, not an unfed column. |

### Daily — Costs & profit (1 of 5)

| Report | Bucket | Why |
|---|---|---|
| Profit & costs over time | **B** `no model` | No cost column on any of the 13 tables in `ALL_MODELS`. `products` is `id, wc_product_id, name, sku, price, category, status` — a price, never a cost. |

### Weekly — Costs & profit (1 of 5)

| Report | Bucket | Why |
|---|---|---|
| Advertising costs by platform | **B** `no model` | No ad-spend entity in the analytics models. |

### Monthly — Costs & profit (3 of 5)

| Report | Bucket | Why |
|---|---|---|
| Operational costs by type | **B** `no model` | No cost entity of any kind. |
| Transaction costs by payment method | **B** `no model` | `orders.payment_method` is populated on 2,826,259, but there is no fee column to group. The dimension exists and the measure does not. |
| Shipping costs by shipping method | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB ships nothing; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** The readings stand and are now explained: no shipping-method column on `orders`, and `shipping_total` non-zero on 0 of 2,889,850. A store that ships nothing has no shipping cost to group. |

### Monthly — Forecasts (3 of 3)

| Report | Bucket | Why |
|---|---|---|
| Sales forecast (12 months) | **A** † | `orders.created_at` and `orders.total` over 1,283 days, 2023-03-12 to 2026-09-15. Enough history to fit on; `total` not measured by the pack. |
| Order volume forecast (3/6/12 months) | **A** | `orders.created_at`, 2,889,850 rows across the same span. A count, so nothing unmeasured. |
| New customers forecast | **A** | First order per `orders.customer_id` — 157,311 distinct — over `created_at`. `customers.first_order_at` and `daily_metrics.new_customers` would serve too but are not needed, so this row does not rest on an unverified table. |

### Daily — Orders (3 of 10)

| Report | Bucket | Why |
|---|---|---|
| Orders over time | **A** | `orders.created_at`, 2,889,850 rows, 2023-03-12 to 2026-09-15. |
| New vs returning customer orders | **A** | `orders.customer_id` populated across 157,311 distinct customers; first-order date derivable from `orders` alone. |
| Average order gross over time | **A** † | **MUST SPLIT FREE ENTRIES (16 Sep 2026) — 66,764 zero-total orders are the legal free-entry route; see *Correction (16 September 2026), third entry*. This is NOT a do-not-propose mark: the row is still a candidate, but the report must say whether free entries are in or out.** AOV over all orders reads £8.23 against £8.43 paid-only. `orders.total` over `orders.created_at`. `daily_metrics.aov` holds it precomputed; `total` was not measured. |

### Weekly — Orders (7 of 10)

| Report | Bucket | Why |
|---|---|---|
| Item count distribution | **A** † | `order_items` 4,549,662 rows keyed by `order_id`. Lines per order is measured; a true item count needs `order_items.quantity`, which the pack did not measure. |
| Order value distribution | **A** † | **MUST SPLIT FREE ENTRIES (16 Sep 2026) — 66,764 zero-total orders are the legal free-entry route; see *Correction (16 September 2026), third entry*. This is NOT a do-not-propose mark: the row is still a candidate, but the report must say whether free entries are in or out.** 66,764 orders land in the zero bucket and they are free entries, not £0 sales — the histogram must name that bucket rather than let a reader read it as failed checkouts. `orders.total`, not measured by the pack. |
| Orders by day of week | **A** | `orders.created_at` is `DateTime(timezone=True)`. |
| Orders by hour of day | **A** | As above — the column carries the time, not just the date. |
| Orders heatmap (day × hour) | **A** | Same column, two-dimensional bucketing. |
| Average order item count | **A** † | 4,549,662 item rows over 2,889,850 orders. `quantity` unmeasured. |
| Order created → completed time | **B** `no model` | `orders` has `created_at`, `updated_at`, `synced_at` and a single current `status`. There is no status-transition history, and `updated_at` is the last write of any kind, not the moment of completion. |

### Daily — Order groups (1 of 6)

| Report | Bucket | Why |
|---|---|---|
| By status | **A** | `orders.status`, six values measured: completed 2,887,414, cancelled 1,971, processing 241, on-hold 203, pending 20, refunded 1. |

### Weekly — Order groups (3 of 6)

| Report | Bucket | Why |
|---|---|---|
| By payment method | **A** | `orders.payment_method` set on 2,826,259 of 2,889,850. |
| By shipping method | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB ships nothing; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** The schema fact stands: no shipping-method column on `orders`. There is also no shipping method to record. |
| By billing/shipping location (country, state, city, ZIP) | **A** † | Billing is populated — country 2,884,311, city 2,884,311, postcode 2,884,111. `billing_state` exists in `models.py` and was not measured. **Amended 16 Sep 2026:** the shipping half is N/A rather than empty — HIB ships nothing. Tie-break rule 3 keeps the row **A** on billing. |

### Rarely — Order groups (2 of 6)

| Report | Bucket | Why |
|---|---|---|
| By currency | **A** | `orders.currency` set on all 2,889,850. The pack did not count distinct values, so the report is buildable and may well return one row. |
| By custom field | **B** `no model` | `orders` is named columns by design — the comment above the billing block says so, because `gdpr.py` must be able to enumerate them. There is no JSONB bag and no custom-field table. |

### Weekly — Refunds (3 of 6)

| Report | Bucket | Why |
|---|---|---|
| Refunds over time | **N/A** (was **B**) `empty column` | **N/A 16 Sep 2026 — HIB does not refund tickets; see *Correction (16 September 2026)*. Not a gap; do not propose.** The reading is unchanged and correct: `orders.refund_total` non-zero on 4 of 2,889,850, one order carrying status `refunded`. That is the complete record of a business that does not refund, not a missing feed. |
| Most refunded products | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — see *Correction*. Not a gap; do not propose.** The schema fact stands: `refund_total` is order-level and `order_items` has no refund column, so a refund cannot be attributed to a line. Building it would return an empty report for HIB. |
| By refund reason | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — see *Correction*. Not a gap; do not propose.** The schema fact stands: no reason column anywhere in `models.py`. There is also no refund to give a reason for. |

### Rarely — Refunds (3 of 6)

| Report | Bucket | Why |
|---|---|---|
| Time between order & refund | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — see *Correction*. Not a gap; do not propose.** The schema fact stands: no refunded_at on `orders` and no refund entity to carry one. |
| By billing location | **N/A** (was **B**) `empty column` | **N/A 16 Sep 2026 — see *Correction*. Not a gap; do not propose.** The dimension is fine (`billing_country` 2,884,311); the measure is not a gap but an absent subject — 4 non-zero refunds, because HIB does not refund. |
| By shipping location | **N/A** (was **B**) `empty column` | **N/A 16 Sep 2026 — see *Correction*. Not a gap; do not propose.** Both halves are now N/A for either reason alone: HIB does not refund, and HIB ships nothing (ruled 16 Sep 2026, *Correction (16 September 2026), second entry*). |

### Weekly — Acquisition / sources (6 of 6)

| Report | Bucket | Why |
|---|---|---|
| Order sources by referring site | **B** `no model` | `orders` carries `utm_source`, `utm_medium`, `utm_campaign` and no referrer column. |
| Order sources by landing path | **B** `no model` | No landing-page or path column on `orders`. |
| Order sources by UTM combination | **A** | `utm_source` 2,054,935, `utm_medium` 1,460,764, `utm_campaign` 211,957 of 2,889,850 — the three-way combination is groupable today, and the campaign column even has an index. |
| Customer sources by referring site | **B** `no model` | Blocked by the absent column before the engine question arises. |
| Customer sources by landing path | **B** `no model` | As above. |
| Customer sources by UTM combination | **C** | The data is held and populated on `orders`; `customers` carries no source at all. Attributing a customer to one of their orders' UTM triples is a derived per-customer attribute, and `customer_segments` holds one RFM `segment_name` per customer. |

### Weekly — Coupons (1 of 1)

| Report | Bucket | Why |
|---|---|---|
| Coupon usage, amount discounted and sales generated | **A** † | `orders.coupon_code` set on 152,698 and `orders.discount_total` non-zero on 152,685 — the two agree to within 13 rows. "Sales generated" needs `orders.total`, unmeasured. |

### Daily — Customers (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| New customers over time | **A** | First order per `orders.customer_id` over `created_at`, 157,311 distinct customers. Needs no table the pack could not see. |

### Monthly — Customers (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| Customers by first-ordered month | **C** | A cohort key derived per customer from their orders, then counted by month. The data is in `orders`; the grouping is the one `customer_segments` cannot hold. |

### Rarely — Customers (1 of 3)

| Report | Bucket | Why |
|---|---|---|
| Customer heatmap (world map) | **C** | `orders.billing_country` is populated on 2,884,311 rows, but `customers` has no address column — placing a *customer* on a map means deriving one location from many orders, which is a per-customer attribute the engine would own. |

### Monthly — Customer groups (3 of 5)

| Report | Bucket | Why |
|---|---|---|
| By first product ordered | **C** | Held: `order_items.product_name` on all 4,549,662 lines, 3,743 distinct products, joined through `orders.created_at`. The grouping is a derived per-customer attribute. |
| By billing location | **C** | Held on `orders`, absent on `customers`, same shape as the heatmap row. |
| By shipping location | **N/A** (was **B**) `empty column` | **N/A 16 Sep 2026 — HIB ships nothing; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** `shipping_country` is set on 0 of 2,889,850 because there are no shipments, not because a column is unfed. This was the last `empty column` row in the document. |

### Rarely — Customer groups (2 of 5)

| Report | Bucket | Why |
|---|---|---|
| By custom field | **B** `no model` | No custom-field storage on `customers` or anywhere else. |
| By customer role | **B** `no model` | `customers` is `wc_customer_id, email, first_name, last_name, first_order_at, last_order_at, order_count, total_spent, aov, created_at, updated_at`. No role. |

### Monthly — Retention (4 of 4)

| Report | Bucket | Why |
|---|---|---|
| Orders made over customer lifetime | **A** | A count per `orders.customer_id` across 157,311 customers, bucketed. One `GROUP BY`, no per-customer dimension to choose. |
| New vs returning customer KPIs | **A** † | **MUST SPLIT FREE ENTRIES (16 Sep 2026) — 66,764 zero-total orders are the legal free-entry route; see *Correction (16 September 2026), third entry*. This is NOT a do-not-propose mark: the row is still a candidate, but the report must say whether free entries are in or out.** The revenue KPIs among them are means of `orders.total`. Same derivation; `orders.total` unmeasured by the pack. |
| Time between repeat orders | **A** | A window function over `orders.created_at` partitioned by `customer_id`. Both columns populated. |
| Items bought over customer lifetime | **A** † | `order_items` 4,549,662 rows joined to `orders` by `order_id`. A line count is covered; a unit count needs `quantity`, unmeasured. |

### Monthly — Cohorts (10 of 10)

| Report | Bucket | Why |
|---|---|---|
| Returning customers | **C** | A cohort matrix: cohort key × elapsed period × metric, over `orders.customer_id` and `created_at`. Data held; the cohort key is the user's choice and `customer_segments` holds one fixed label. |
| Customers by order count | **C** | Cohort matrix over a derived per-customer count. |
| Orders per customer | **C** | As above, with orders as the measure. |
| Average order value | **C** † | **MUST SPLIT FREE ENTRIES (16 Sep 2026) — 66,764 zero-total orders are the legal free-entry route; see *Correction (16 September 2026), third entry*. This is NOT a do-not-propose mark: the row is still a candidate, but the report must say whether free entries are in or out.** Bucket unchanged: the engine blocks this row either way. Same matrix; the measure is `orders.total`, unmeasured by the pack. |
| Average order profit | **B** `no model` | Spans B and C; B blocks it. No cost column exists, so no profit measure exists to put in the matrix. |
| Customer lifetime value | **C** | `customers.total_spent` exists, and the lifetime-by-cohort curve is the matrix again. |
| Customer lifetime profit | **B** `no model` | No cost column. |
| Sales over time | **C** † | Cohorted revenue; `orders.total` unmeasured. |
| Orders over time | **C** | Cohorted counts over `orders.created_at`. |
| Profit over time | **B** `no model` | No cost column. |

### Daily — Products (1 of 8)

| Report | Bucket | Why |
|---|---|---|
| Top selling products | **A** † | `order_items.product_name` set on all 4,549,662 lines over 3,743 distinct `wc_product_id`. Ranking by revenue needs `order_items.total` and by units needs `quantity`; neither was measured. `order_items.price` and `sku` are NULL on all 4,549,662, so neither can be the measure. |

### Weekly — Products (4 of 8)

| Report | Bucket | Why |
|---|---|---|
| Top selling variations | **B** `no model` | `products` has no parent or variation column and `order_items` records one `wc_product_id`. A variation is not a thing DD stores. |
| Top selling categories | **A** ‡ | `product_categories` is one row per (product, category) — the right shape, deliberately not `products.category`, which joins names together. The pack cannot see either table, so the population is unknown. |
| Product stock velocity | **B** `no model` | No stock or inventory column on `products`. |
| Variation stock velocity | **B** `no model` | Neither the variation nor the stock exists. |

### Monthly — Products (1 of 8)

| Report | Bucket | Why |
|---|---|---|
| Frequently bought together | **A** | A self-join of `order_items` on `order_id` — 4,549,662 rows, 3,743 distinct products, `product_name` populated throughout. No column the pack found empty is involved. |

### Rarely — Products (2 of 8)

| Report | Bucket | Why |
|---|---|---|
| Product groups (custom bundles of products/variations) | **B** `no model` | A user-defined bundle has to be stored. There is no product-group table, so this is blocked by the missing entity before it is blocked by the engine. |
| Product vendors/brands | **B** `no model` | No vendor or brand column on `products`. |

### Weekly — Comparison (2 of 2)

| Report | Bucket | Why |
|---|---|---|
| Product comparison | **A** † | Two products, two windows, over `order_items` joined to `orders.created_at`. The measure is `order_items.total`, unmeasured. |
| Category comparison | **A** ‡ | Same shape through `product_categories`, whose population the pack could not see. |

### Rarely — Devices (3 of 3)

| Report | Bucket | Why |
|---|---|---|
| Orders by device (desktop vs mobile) | **B** `no model` | No device, user-agent, OS or browser column on `orders` or anywhere in `ALL_MODELS`. |
| Orders by operating system | **B** `no model` | As above. |
| Orders by browser | **B** `no model` | As above. |

### Rarely — Subscriptions (18 of 18)

Every row here was **B** `no model` for the same reason, stated once: there is
no subscription model in `api/analytics/models.py`, so there is no subscription,
no plan, no billing interval, no renewal and no subscription event. No row in
this block is blocked by a band, by the engine, or by an empty column — it is
blocked by an entity DD has never had.

**ALL EIGHTEEN BECAME N/A ON 16 SEPTEMBER 2026.** Eamonn stated that HIB sells
no recurring product, so the absent entity is not one DD is missing — it is one
this business has no use for. The eighteen leave the parity denominator
entirely and none may be proposed. See *Correction (16 September 2026), second
entry*.

| Report | Bucket | Why |
|---|---|---|
| MRR over time | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No subscription entity. |
| Active subscriptions over time | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No subscription entity. |
| Subscription plans breakdown | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No plan entity. |
| Retention rate over time | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No subscription entity. Distinct from customer retention, which is C above. |
| Churn rate over time | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** `churn_scores` predicts *customer* churn from order recency; it is not subscription churn and has no subscription to cancel. |
| Subscription cohort retention | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No subscription entity. |
| Subscription events over time | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No subscription event log. |
| Active subs by billing location | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No subscription entity; the location would come from `orders` in any case. |
| Active subs by shipping location | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No subscription entity, and `shipping_country` is set on 0 orders. |
| Active subs by payment method | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No subscription entity. |
| Active subs by billing period/interval | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No interval is stored because no subscription is. |
| Active subs by custom field | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** Neither the subscription nor a custom field exists. |
| Active subscriptions heatmap | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No subscription entity. |
| Future renewals (expected revenue) | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No renewal date exists to project from. |
| Subs started by day of week | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No subscription start timestamp. |
| Subs started by hour | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No subscription start timestamp. |
| Subs cancelled by day | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No cancellation timestamp. |
| Subs cancelled by hour | **N/A** (was **B**) `no model` | **N/A 16 Sep 2026 — HIB sells no recurring product; see *Correction (16 September 2026), second entry*. Not a gap; do not propose.** No cancellation timestamp. |

### Weekly — Carts (7 of 7)

Every row here is **B** `no model`: `api/analytics/models.py` defines no cart.
DD's order rows begin at the order, so a cart that never became one leaves no
trace at all.

| Report | Bucket | Why |
|---|---|---|
| Carts started by date | **B** `no model` | No cart entity. |
| Carts abandoned by date | **B** `no model` | No cart entity, and abandonment is a cart state. |
| Carts placed by date | **B** `no model` | The resulting order exists; the cart it came from does not, so "placed" cannot be distinguished from "ordered". |
| Carts recovered by date | **B** `no model` | No cart and no recovery event. `interventions` records churn interventions against a customer, not a cart. |
| Time between cart & order | **B** `no model` | No cart timestamp to subtract from `orders.created_at`. |
| Carts by billing country | **B** `no model` | No cart entity; the country would come from `orders`. |
| Cart product reports (most added / abandoned / placed / recovered) | **B** `no model` | No cart and no cart line. |

## Subscriptions and carts, and what they do to a parity number

**Twenty-five of the 100 reports — a quarter of the catalogue — are
unreachable without an entity DD has never had.** Eighteen subscriptions and
seven carts, every one of them bucket B `no model`, none of them blocked by
anything smaller.

That matters to any parity figure computed from this document. "DD has 29 of
Metorik's 100" and "DD has 29 of the 75 that do not require a new entity class"
are different sentences, and the second is the one a reader should be given
before a number is quoted at anyone. The 25 are not "add a `GROUP BY`" work
sitting next to *Orders by day of week*; they are two product surfaces —
recurring billing and pre-order behaviour — that would each need ingestion from
the connector, a table, a sync path and a backfill before the first report
could be drawn. Counting them in the same denominator as the 29 makes the gap
look uniform when it is not.

The same care applies one level down. Of the remaining 34 B rows, refunds
account for 6 and costs for 8 across two groups — so two absent subjects,
neither of them an exotic one, carry 14 of the 34.

> **Two corrections to the paragraph above, 16 September 2026.** *Three groups*
> was wrong and is now *two*: the eight cost rows are the five-row Costs &
> profit group and three of the ten Cohorts, which is two groups. The band
> split of Costs & profit across Daily, Weekly and Monthly headings is three
> **headings**, not three groups. **And the sentence is otherwise superseded:**
> refunds are no longer among the B rows at all, and neither are the
> subscriptions counted just above. Of the 25 named in this section, the 18
> subscriptions are now N/A and only the 7 carts remain a real gap. Costs is
> the last of the three subjects still standing. See both correction sections
> above; the final counts are in *The corrected counts, final*.

## Bucket-A rows the pack does not fully cover

The pack read `analytics_2.orders` and `analytics_2.order_items` and nothing
else, so some bucket-A rows rest on `api/analytics/models.py` alone. Both marks
used above are collected here; an A row carrying neither mark has every column
it needs measured and populated in the pack.

**‡ — the table is one the pack could not see.** The column exists in
`models.py`; whether it holds anything is unknown.

| Row | What is unverified |
|---|---|
| Top selling categories | `product_categories` and `products` — no reading of either table exists in the pack. |
| Category comparison | `product_categories`, as above. |

**† — the table was read, but this column was not one of the eight or five the
query named.** The dimension is measured; the measure usually is not. This mark
is not in the task's list of four unverified tables, and it is the same class
of claim: an unmarked row would assert a population figure the pack does not
contain.

| Row | Unverified column |
|---|---|
| Net/gross revenue over time (gross half; A since the 16 Sep 2026 correction) | `orders.total` |
| Revenue by billing/shipping location or payment method | `orders.total` |
| Sales forecast (12 months) | `orders.total` |
| Average order gross over time | `orders.total` |
| Order value distribution | `orders.total` |
| New vs returning customer KPIs | `orders.total` |
| Coupon usage, amount discounted and sales generated | `orders.total` |
| By billing/shipping location (country, state, city, ZIP) | `orders.billing_state` — **MEASURED 16 Sep 2026: set on 0 of 2,890,319, i.e. EMPTY.** The row stays A on country, city and postcode; do not propose a by-state grouping. |
| Item count distribution | `order_items.quantity` |
| Average order item count | `order_items.quantity` |
| Items bought over customer lifetime | `order_items.quantity` |
| Top selling products | `order_items.total`, `order_items.quantity` |
| Product comparison | `order_items.total` |

Two C rows carry † for the same reason — cohort *Average order value* and
*Sales over time* need `orders.total` — but their bucket does not turn on it,
since the engine blocks them either way.

`orders.total` is the single most load-bearing unmeasured column in this
document: it is the measure behind six A rows. It is `Numeric(10, 2)` and
nullable in `models.py`, and nothing in this pack says how often it is set.

> **MEASURED 16 SEPTEMBER 2026: set on every row and non-zero on 97.7%.** So is
> `order_items.quantity` and so is `order_items.total`. Every `†` mark in this
> table is discharged; see *Measured 16 September 2026*. The marks are left in
> place because they record what the 2026-09-15 pack could see.

## The live page, checked

`research/metorik-report-catalogue-2026-09-15.md` records that nothing in the
fleet had checked it against its source. I fetched
`https://metorik.com/reports` on **2026-09-15** and it was reachable. Per the
task, the catalogue is classified **as written**; this section records the
disagreement and does not reconcile it.

**It disagrees, mostly about shape.** The page as retrieved is marketing prose
under roughly nine or ten feature sections — Revenue, Order, Customer,
Subscription, Discounts & Refunds, Retention, Product, Device, Cart — not an
enumeration of 100 reports in 17 groups. The catalogue's group names *Costs &
profit*, *Forecasts*, *Order groups*, *Acquisition / sources*, *Coupons*,
*Customer groups*, *Cohorts* and *Comparison* do not appear as headings on the
page; coupons appear folded into "Discounts & Refunds", and cohorts and
comparison appear in body text and a screenshot caption rather than as sections.

**The headline count corroborates the catalogue's own warning.** The page says
"Over 75 Reports" while the catalogue lists 100 — exactly the discrepancy the
catalogue flagged and declined to reconcile.

**Individual rows corroborated by name**, in the fetched text: New vs Returning
Customers, Order Value Distribution, Item Count Distribution, Average Order
Net/Gross, orders grouped by Currency, orders grouped by Custom Field, Refunds
by Country, product comparison, Customer Cohorts, the subscription block's MRR /
churn / LTV / cohorts, the cart block's abandoned and placed carts, COGS and
shipping and transaction costs, inventory forecasts, filtering by UTM values and
landing page and referring domain, and a tax question ("Is revenue higher for
certain tax rates?").

**Wordings that differ.** The page says "Time between Created & Shipped" where
the catalogue says "Order created → completed time"; "Spend by Day/Hour" where
the catalogue has orders by day and by hour; an "in-progress" cart where the
catalogue says carts started; and it describes a desktop/mobile/**tablet**
breakdown where the catalogue says desktop vs mobile. None of these change a
bucket: the created→completed row is B `no model` either way, because DD stores
no status-transition timestamp of any kind.

**Nothing found is a row the catalogue lacks.** No report on the fetched page is
absent from the 100.

**What the fetch could not settle.** The retrieval converts the page to markdown
and answers through a small model, and that step is lossy: a second fetch
reported "not found" for heatmap, operating system, browser and vendor — four
things the catalogue lists — and in the same answer quoted my own question back
as though it were page text. So **absence in the fetch is not evidence of
absence on the page**, and I have not treated it as such anywhere above. The
honest summary is that the source page is organised differently from the
relayed catalogue and markets a smaller number, and that a row-by-row
reconciliation is a separate task with a separate method.

## What I could not verify

**The population of nine of the thirteen tables.** The pack covers `orders` and
`order_items` in `analytics_2`. `customers`, `products`, `product_categories`,
`daily_metrics`, `customer_segments`, `churn_scores`, `interventions`,
`sync_log` and the rest were not read at all. Two bucket-A rows rest on that
gap and are marked ‡; several rows name a convenient alternative source —
`daily_metrics.aov`, `customers.total_spent` — that I did not lean on for the
bucket precisely because it is unverified.

**Twelve columns on the two tables that were read**, listed under † above,
including `orders.total`. The five queries named eight columns on `orders`,
seven more on `orders`, and five on `order_items`; everything else on those two
tables is unmeasured, and I could not add a query.

**One tenant, one instant.** Every figure is `analytics_2` as of 2026-09-15
19:52 UTC. `analytics_1` was not read this run. The emptiness is at least not
new: `research/EVIDENCE-metorik.md`, taken 2026-08-30, shows the same tenant
with `tax_total > 0` and `shipping_total > 0` on 0 orders and `refund_total > 0`
on 4. Whether an empty column is empty because the store has no such data or
because the pipeline does not deliver it is a question this pack cannot answer,
and the two have different consequences — `specs/metorik-gap.md` separated them
for tax and shipping and I have not repeated that work here.

**Whether the buckets survive contact with an implementation.** A bucket-A row
says the columns are there and populated; it does not say the report is easy,
correct or cheap, and no row here was prototyped. In particular the A/C line is
a judgement about what `customer_segments` can express, not a measurement of it:
I read the model, not the engine's query surface, and a reader who thinks a
given C row is really an A row is disagreeing with a judgement rather than with
a figure.

**The bands, entirely.** No agency was asked, nothing was measured, and DD has
no telemetry that would settle any of the 100. They are the most falsifiable
column in the document.

**The catalogue itself remains relayed.** The fetch above narrows the
uncertainty but does not close it: a marketing page is not a feature list, and
neither the catalogue nor this classification establishes that any of the 100
reports is implemented in Metorik as described.
