# Classify Metorik's 100 published reports against what DD can actually build

```fleet-spec
work_type: research
repo: fleet
contract: research.yaml
title: Classify Metorik's 100 published reports into data DD holds, a table that does not exist, or the segmentation engine
writable_paths:
  - research/metorik-report-classification-2026-09-15.md
evidence_queries:
    - key: cat_01_orders_column_population
      reader: deadly_digital
      sql: |
        SELECT count(*) AS orders,
               count(*) FILTER (WHERE refund_total  IS NOT NULL AND refund_total  <> 0) AS refund_total_nonzero,
               count(*) FILTER (WHERE discount_total IS NOT NULL AND discount_total <> 0) AS discount_total_nonzero,
               count(*) FILTER (WHERE shipping_total IS NOT NULL AND shipping_total <> 0) AS shipping_total_nonzero,
               count(*) FILTER (WHERE tax_total     IS NOT NULL AND tax_total     <> 0) AS tax_total_nonzero,
               count(*) FILTER (WHERE coupon_code   IS NOT NULL AND coupon_code   <> '') AS coupon_code_set,
               count(*) FILTER (WHERE payment_method IS NOT NULL AND payment_method <> '') AS payment_method_set,
               count(*) FILTER (WHERE currency      IS NOT NULL AND currency      <> '') AS currency_set
          FROM analytics_2.orders
    - key: cat_02_orders_source_and_location
      reader: deadly_digital
      sql: |
        SELECT count(*) FILTER (WHERE utm_source   IS NOT NULL AND utm_source   <> '') AS utm_source_set,
               count(*) FILTER (WHERE utm_medium   IS NOT NULL AND utm_medium   <> '') AS utm_medium_set,
               count(*) FILTER (WHERE utm_campaign IS NOT NULL AND utm_campaign <> '') AS utm_campaign_set,
               count(*) FILTER (WHERE billing_country  IS NOT NULL AND billing_country  <> '') AS billing_country_set,
               count(*) FILTER (WHERE billing_city     IS NOT NULL AND billing_city     <> '') AS billing_city_set,
               count(*) FILTER (WHERE billing_postcode IS NOT NULL AND billing_postcode <> '') AS billing_postcode_set,
               count(*) FILTER (WHERE shipping_country IS NOT NULL AND shipping_country <> '') AS shipping_country_set
          FROM analytics_2.orders
    - key: cat_03_order_items_population
      reader: deadly_digital
      sql: |
        SELECT count(*) AS item_rows,
               count(DISTINCT wc_product_id) AS distinct_products,
               count(*) FILTER (WHERE product_name IS NOT NULL AND product_name <> '') AS product_name_set,
               count(*) FILTER (WHERE sku IS NOT NULL AND sku <> '') AS sku_set,
               count(*) FILTER (WHERE price IS NOT NULL) AS price_set
          FROM analytics_2.order_items
    - key: cat_04_status_vocabulary
      reader: deadly_digital
      sql: |
        SELECT status, count(*) AS n
          FROM analytics_2.orders GROUP BY status ORDER BY n DESC LIMIT 20
    - key: cat_05_date_span
      reader: deadly_digital
      sql: |
        SELECT min(created_at)::date AS earliest, max(created_at)::date AS latest,
               count(DISTINCT customer_id) AS customers_with_orders
          FROM analytics_2.orders
```

## What this is for

`research/metorik-report-catalogue-2026-09-15.md` lists 100 reports from
Metorik's published catalogue. It has no DD status and no agency-use band, and
until something supplies both it cannot feed the candidate producer:
`console/load_candidates.band_of` reads a band from the evidence section
heading, and `console/rank.py` sorts a NULL band LAST, so band-less candidates
would rank below everything already in the pool, permanently and silently.

`specs/metorik-gap.md` did that work for 48 features on 2026-08-28. This does
it for 100, and the three-way split is the part nobody has had.

## What you have, and what you do not

`Read, Grep, Glob, Write, Edit, WebSearch, WebFetch` — and **no shell, no
database and no credential**. You cannot query production. The runner has
already run the queries in the block above and written the answers into your
worktree as a markdown file before you started; that pack is your only view of
the data and you cannot add to it.

You have a read-only checkout of `deadly-digital-platform`.
`api/analytics/models.py` is the authoritative list of what tables exist —
`EXPECTED_TABLES` at the foot of it — and it is a file, so read it rather than
guessing.

## Requirements

### 1. The three rules, written before any report is classified

State the test for each bucket before applying it, so a row cannot be argued
into a bucket after the fact:

* **A — DD already holds the data.** Every field the report needs is a column
  on a table `models.py` defines AND the evidence pack shows it populated. A
  column that exists and is empty is **not** bucket A; `specs/metorik-gap.md`
  set that rule and its reason is that a report over an empty column is not a
  feature.
* **B — needs a table that does not exist.** The report needs an entity
  `models.py` has no model for.
* **C — needs the segmentation engine.** The report is a grouping, filter or
  cohort over data DD holds, whose difficulty is the engine rather than the
  data — `customer_segments` exists and what it can express is the question.

Where a report spans two buckets, say which and put it in the one that blocks
it. Every one of the 100 lands in exactly one.

### 2. All 100 rows, each with its bucket and its evidence

One row per report, in the catalogue's own groups and order so the two
documents can be read side by side. Each row cites what put it in its bucket:
a table and column from `models.py`, a figure from the evidence pack, or the
absence of a model.

### 3. An agency-use band per report

`Daily`, `Weekly`, `Monthly` or `Rarely`, in the sense `specs/metorik-gap.md`
uses: how often an agency running a WooCommerce store would open it. This is
the column that lets the producer draw from this document — put the band word
at the start of each group heading, the way the gap list does, because that is
where `band_of` reads it from.

A band is a judgement and cannot be measured. State the reasoning once, at the
top, rather than defending each row.

### 4. What the evidence pack could not answer

The pack covers `analytics_2.orders` and `analytics_2.order_items` only,
because those are the tables the read-only role can see. Any bucket-A claim
about `customers`, `products`, `product_categories` or `daily_metrics` rests on
`models.py` alone — the column exists, and whether it is POPULATED is unknown.
Mark every such row and collect them in one section. An unmarked bucket-A row
asserts a population figure the pack does not contain.

### 5. The catalogue is relayed, and you can check it

The catalogue document records that nothing in the fleet verified it against
`https://metorik.com/reports`. You have `WebFetch`. Fetch that page, compare it
to the 100 rows, and record what you find: rows that are gone, rows that are
new, groups renamed, or the page unreachable. **If it disagrees, say so and
classify the catalogue as written** — reconciling two sources is a second task
and mixing them would leave neither checkable.

If the fetch fails, record the failure and continue. The classification does
not depend on it.

### 6. The subscriptions and carts blocks, called out

18 of the 100 are subscriptions and 7 are carts. `models.py` defines no model
for either. Say plainly what proportion of the catalogue is unreachable without
entities DD has never had, because a parity number that counts them alongside
"add a GROUP BY" is a number that misleads.

## What this task does NOT do

* **It does not rank, prioritise or recommend.** Bucket and band are facts and
  judgements about each report; what to build is a decision downstream.
* **It does not estimate effort.** No hours, no t-shirt sizes.
* **It does not write candidates.** The producer runs against this document
  afterwards, under its own contract.
* **It does not query the database.** The pack is what there is.

## How this will be checked

`research.yaml` runs `research_document_shape.py`. `auto_merge` does not apply:
research is read by a person and never merges unattended — the chain says so
itself.

## Objectives

`dd-feature-parity`.
