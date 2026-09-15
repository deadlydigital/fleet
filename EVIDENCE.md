# Evidence pack for task 114: Classify Metorik's 100 published reports into data DD holds, a table that does not exist, or the segmentation engine

Produced by the fleet runner before the agent started, as read-only
roles. **The agent did not run these and cannot run others.** If the
question you need answered is not below, say so in the document under
what you could not verify -- do not guess at the number.

Generated 2026-09-15 19:52 UTC.

## cat_01_orders_column_population

Reader: `deadly_digital`. Ran at 2026-09-15T19:52:53.185302+00:00.

```sql
SELECT count(*) AS orders,
       count(*) FILTER (WHERE refund_total  IS NOT NULL AND refund_total  <> 0) AS refund_total_nonzero,
       count(*) FILTER (WHERE discount_total IS NOT NULL AND discount_total <> 0) AS discount_total_nonzero,
       count(*) FILTER (WHERE shipping_total IS NOT NULL AND shipping_total <> 0) AS shipping_total_nonzero,
       count(*) FILTER (WHERE tax_total     IS NOT NULL AND tax_total     <> 0) AS tax_total_nonzero,
       count(*) FILTER (WHERE coupon_code   IS NOT NULL AND coupon_code   <> '') AS coupon_code_set,
       count(*) FILTER (WHERE payment_method IS NOT NULL AND payment_method <> '') AS payment_method_set,
       count(*) FILTER (WHERE currency      IS NOT NULL AND currency      <> '') AS currency_set
  FROM analytics_2.orders
```

| orders | refund_total_nonzero | discount_total_nonzero | shipping_total_nonzero | tax_total_nonzero | coupon_code_set | payment_method_set | currency_set |
|---|---|---|---|---|---|---|---|
| 2889850 | 4 | 152685 | 0 | 0 | 152698 | 2826259 | 2889850 |

1 row.

## cat_02_orders_source_and_location

Reader: `deadly_digital`. Ran at 2026-09-15T19:52:54.494991+00:00.

```sql
SELECT count(*) FILTER (WHERE utm_source   IS NOT NULL AND utm_source   <> '') AS utm_source_set,
       count(*) FILTER (WHERE utm_medium   IS NOT NULL AND utm_medium   <> '') AS utm_medium_set,
       count(*) FILTER (WHERE utm_campaign IS NOT NULL AND utm_campaign <> '') AS utm_campaign_set,
       count(*) FILTER (WHERE billing_country  IS NOT NULL AND billing_country  <> '') AS billing_country_set,
       count(*) FILTER (WHERE billing_city     IS NOT NULL AND billing_city     <> '') AS billing_city_set,
       count(*) FILTER (WHERE billing_postcode IS NOT NULL AND billing_postcode <> '') AS billing_postcode_set,
       count(*) FILTER (WHERE shipping_country IS NOT NULL AND shipping_country <> '') AS shipping_country_set
  FROM analytics_2.orders
```

| utm_source_set | utm_medium_set | utm_campaign_set | billing_country_set | billing_city_set | billing_postcode_set | shipping_country_set |
|---|---|---|---|---|---|---|
| 2054935 | 1460764 | 211957 | 2884311 | 2884311 | 2884111 | 0 |

1 row.

## cat_03_order_items_population

Reader: `deadly_digital`. Ran at 2026-09-15T19:52:55.351877+00:00.

```sql
SELECT count(*) AS item_rows,
       count(DISTINCT wc_product_id) AS distinct_products,
       count(*) FILTER (WHERE product_name IS NOT NULL AND product_name <> '') AS product_name_set,
       count(*) FILTER (WHERE sku IS NOT NULL AND sku <> '') AS sku_set,
       count(*) FILTER (WHERE price IS NOT NULL) AS price_set
  FROM analytics_2.order_items
```

| item_rows | distinct_products | product_name_set | sku_set | price_set |
|---|---|---|---|---|
| 4549662 | 3743 | 4549662 | 0 | 0 |

1 row.

## cat_04_status_vocabulary

Reader: `deadly_digital`. Ran at 2026-09-15T19:52:57.667343+00:00.

```sql
SELECT status, count(*) AS n
  FROM analytics_2.orders GROUP BY status ORDER BY n DESC LIMIT 20
```

| status | n |
|---|---|
| completed | 2887414 |
| cancelled | 1971 |
| processing | 241 |
| on-hold | 203 |
| pending | 20 |
| refunded | 1 |

6 rows.

## cat_05_date_span

Reader: `deadly_digital`. Ran at 2026-09-15T19:52:57.910918+00:00.

```sql
SELECT min(created_at)::date AS earliest, max(created_at)::date AS latest,
       count(DISTINCT customer_id) AS customers_with_orders
  FROM analytics_2.orders
```

| earliest | latest | customers_with_orders |
|---|---|---|
| 2023-03-12 | 2026-09-15 | 157311 |

1 row.
