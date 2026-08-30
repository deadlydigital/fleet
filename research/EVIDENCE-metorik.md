# Evidence pack for task 5: Metorik feature gap list for DD analytics (research)

Produced by the fleet runner before the agent started, as read-only
roles. **The agent did not run these and cannot run others.** If the
question you need answered is not below, say so in the document under
what you could not verify -- do not guess at the number.

Generated 2026-08-30 14:20 UTC.

## dd_order_column_population_tenant_2

Reader: `deadly_digital`. Ran at 2026-08-30T14:20:24.876110+00:00.

```sql
SELECT count(*)                                       AS orders,
       count(payment_method)                          AS payment_method,
       count(DISTINCT payment_method)                 AS payment_methods_distinct,
       count(billing_country)                         AS billing_country,
       count(DISTINCT billing_country)                AS countries_distinct,
       count(coupon_code)                             AS coupon_code,
       count(DISTINCT coupon_code)                    AS coupons_distinct,
       count(*) FILTER (WHERE discount_total > 0)     AS discounted,
       count(*) FILTER (WHERE refund_total > 0)       AS refunded,
       count(*) FILTER (WHERE tax_total > 0)          AS taxed,
       count(*) FILTER (WHERE shipping_total > 0)     AS shipped,
       count(utm_source)                              AS utm_source,
       min(created_at)                                AS earliest,
       max(created_at)                                AS latest
  FROM analytics_2.orders
```

| orders | payment_method | payment_methods_distinct | billing_country | countries_distinct | coupon_code | coupons_distinct | discounted | refunded | taxed | shipped | utm_source | earliest | latest |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2846280 | 2784598 | 9 | 2842138 | 2 | 146509 | 65444 | 146429 | 4 | 0 | 0 | 2846280 | 2023-03-12 10:31:40+00:00 | 2026-08-30 14:19:59+00:00 |

1 row.

## dd_order_column_population_tenant_1

Reader: `deadly_digital`. Ran at 2026-08-30T14:20:29.890085+00:00.

```sql
SELECT count(*) AS orders, count(coupon_code) AS coupon_code,
       count(*) FILTER (WHERE refund_total > 0) AS refunded,
       count(utm_source) AS utm_source
  FROM analytics_1.orders
```

| orders | coupon_code | refunded | utm_source |
|---|---|---|---|
| 679912 | 19095 | 4 | 679912 |

1 row.

## dd_order_status_breakdown

Reader: `deadly_digital`. Ran at 2026-08-30T14:20:30.046185+00:00.

```sql
SELECT status, count(*) AS orders
  FROM analytics_2.orders GROUP BY 1 ORDER BY 2 DESC
```

| status | orders |
|---|---|
| completed | 2845479 |
| cancelled | 332 |
| processing | 241 |
| on-hold | 203 |
| pending | 24 |
| refunded | 1 |

6 rows.

## dd_tenants

Reader: `deadly_digital`. Ran at 2026-08-30T14:20:30.360576+00:00.

```sql
SELECT id, name, created_at FROM public.tenants ORDER BY id
```

| id | name | created_at |
|---|---|---|
| 1 | HITTIN IT BIG STAGING | 2026-08-18 14:41:28.962221 |
| 2 | HITTIN IT BIG COMPEITTIONS | 2026-08-25 13:49:39.116738 |

2 rows.

## fleet_open_issues

Reader: `fleet`. Ran at 2026-08-30T14:20:30.383674+00:00.

```sql
SELECT detector_key, issue_type, severity, status, occurrence_count,
       current_magnitude, first_seen, last_seen
  FROM issues ORDER BY last_seen DESC
```

| detector_key | issue_type | severity | status | occurrence_count | current_magnitude | first_seen | last_seen |
|---|---|---|---|---|---|---|---|
| dd_analytics_reconciliation | MISSING_ANALYTICS_ORDER | CRITICAL | OPEN | 47 | 29603 | 2026-08-28 17:00:00+00:00 | 2026-08-30 14:00:00+00:00 |

1 row.
