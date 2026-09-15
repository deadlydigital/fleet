\set ON_ERROR_STOP on
\pset pager off
-- task 104 (MERGED as d7a34b3) vs the pre-104 base fd20133.
-- Requirement 7: requirement 5's proof RE-RUN against the LATERAL form,
-- not reused from the restriction. The LATERAL CTEs below are the ones
-- _acquiring_order_ctes() actually ships; they were read out of the merged
-- file, not retyped.


\echo ''
\echo 'BLOCK 1  revenue_report, granularity=day -- expect 0 rows'
WITH
    acquired AS (
            SELECT DISTINCT ON (a.customer_id)
                   a.customer_id, a.created_at AS acquired_at
            FROM analytics_2.orders a
            WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
            ORDER BY a.customer_id, a.created_at, a.id
        ),
old_result AS (
    SELECT
                    o.created_at::date AS period,
                    COUNT(*)                                                      AS orders_all_statuses,
                    COUNT(*) FILTER (WHERE o.status IN ('completed', 'processing'))        AS orders_revenue_statuses,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS revenue,
                    COUNT(DISTINCT o.customer_id)                                 AS customers_all_statuses,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.status IN ('completed', 'processing'))                    AS customers_revenue_statuses,
                    -- 2.1: both sides revenue-status.
                    COALESCE(
                        SUM(o.total) FILTER (WHERE o.status IN ('completed', 'processing'))
                        / NULLIF(COUNT(*) FILTER (WHERE o.status IN ('completed', 'processing')), 0),
                    0)                                                            AS aov,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.created_at::date = q.acquired_at::date)                  AS new_customers,
                    -- Refunds, over EXACTLY the rows `revenue` above is summed from:
                    -- same bucket, same revenue-status filter, one query.
                    COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS refunded_amount,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)
                    - COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS net_revenue,
                    COUNT(*) FILTER (
                        WHERE o.status IN ('completed', 'processing')
                          AND o.refund_total > 0)                                 AS orders_with_refund
                FROM analytics_2.orders o
                LEFT JOIN acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
                GROUP BY period
),
    window_customers AS (
            -- Only customers active in the window can be acquired in it, so only
            -- their acquiring orders need finding. Derived from the window rows
            -- the outer aggregate already reads — not a second predicate.
            SELECT DISTINCT customer_id
            FROM analytics_2.orders
            WHERE created_at >= :start AND created_at < :end_plus AND customer_id IS NOT NULL
        ),
        lat_acquired AS (
            -- ASK PER CUSTOMER, NOT PER ROW. Their HISTORY is deliberately not
            -- bounded: "first" still means first ever, which is why the inner
            -- query carries no date predicate.
            SELECT wc.customer_id, first_order.created_at AS acquired_at
            FROM window_customers wc
            CROSS JOIN LATERAL (
                SELECT o.created_at
                FROM analytics_2.orders o
                WHERE o.customer_id = wc.customer_id
                  AND o.status IN ('completed', 'processing')
                ORDER BY o.created_at, o.id
                LIMIT 1
            ) first_order
        ),
new_result AS (
    SELECT
                    o.created_at::date AS period,
                    COUNT(*)                                                      AS orders_all_statuses,
                    COUNT(*) FILTER (WHERE o.status IN ('completed', 'processing'))        AS orders_revenue_statuses,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS revenue,
                    COUNT(DISTINCT o.customer_id)                                 AS customers_all_statuses,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.status IN ('completed', 'processing'))                    AS customers_revenue_statuses,
                    -- 2.1: both sides revenue-status.
                    COALESCE(
                        SUM(o.total) FILTER (WHERE o.status IN ('completed', 'processing'))
                        / NULLIF(COUNT(*) FILTER (WHERE o.status IN ('completed', 'processing')), 0),
                    0)                                                            AS aov,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.created_at::date = q.acquired_at::date)                  AS new_customers,
                    -- Refunds, over EXACTLY the rows `revenue` above is summed from:
                    -- same bucket, same revenue-status filter, one query.
                    COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS refunded_amount,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)
                    - COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS net_revenue,
                    COUNT(*) FILTER (
                        WHERE o.status IN ('completed', 'processing')
                          AND o.refund_total > 0)                                 AS orders_with_refund
                FROM analytics_2.orders o
                LEFT JOIN lat_acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
                GROUP BY period
)
SELECT 'in OLD, not in MERGED' AS side, * FROM (
  SELECT * FROM old_result EXCEPT ALL SELECT * FROM new_result) a
UNION ALL
SELECT 'in MERGED, not in OLD', * FROM (
  SELECT * FROM new_result EXCEPT ALL SELECT * FROM old_result) b;


\echo ''
\echo 'BLOCK 2  revenue_report, granularity=month -- expect 0 rows'
WITH
    acquired AS (
            SELECT DISTINCT ON (a.customer_id)
                   a.customer_id, a.created_at AS acquired_at
            FROM analytics_2.orders a
            WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
            ORDER BY a.customer_id, a.created_at, a.id
        ),
old_result AS (
    SELECT
                    DATE_TRUNC('month', o.created_at)::date AS period,
                    COUNT(*)                                                      AS orders_all_statuses,
                    COUNT(*) FILTER (WHERE o.status IN ('completed', 'processing'))        AS orders_revenue_statuses,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS revenue,
                    COUNT(DISTINCT o.customer_id)                                 AS customers_all_statuses,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.status IN ('completed', 'processing'))                    AS customers_revenue_statuses,
                    -- 2.1: both sides revenue-status.
                    COALESCE(
                        SUM(o.total) FILTER (WHERE o.status IN ('completed', 'processing'))
                        / NULLIF(COUNT(*) FILTER (WHERE o.status IN ('completed', 'processing')), 0),
                    0)                                                            AS aov,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE DATE_TRUNC('month', o.created_at)::date = DATE_TRUNC('month', q.acquired_at)::date)                  AS new_customers,
                    -- Refunds, over EXACTLY the rows `revenue` above is summed from:
                    -- same bucket, same revenue-status filter, one query.
                    COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS refunded_amount,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)
                    - COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS net_revenue,
                    COUNT(*) FILTER (
                        WHERE o.status IN ('completed', 'processing')
                          AND o.refund_total > 0)                                 AS orders_with_refund
                FROM analytics_2.orders o
                LEFT JOIN acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
                GROUP BY period
),
    window_customers AS (
            -- Only customers active in the window can be acquired in it, so only
            -- their acquiring orders need finding. Derived from the window rows
            -- the outer aggregate already reads — not a second predicate.
            SELECT DISTINCT customer_id
            FROM analytics_2.orders
            WHERE created_at >= :start AND created_at < :end_plus AND customer_id IS NOT NULL
        ),
        lat_acquired AS (
            -- ASK PER CUSTOMER, NOT PER ROW. Their HISTORY is deliberately not
            -- bounded: "first" still means first ever, which is why the inner
            -- query carries no date predicate.
            SELECT wc.customer_id, first_order.created_at AS acquired_at
            FROM window_customers wc
            CROSS JOIN LATERAL (
                SELECT o.created_at
                FROM analytics_2.orders o
                WHERE o.customer_id = wc.customer_id
                  AND o.status IN ('completed', 'processing')
                ORDER BY o.created_at, o.id
                LIMIT 1
            ) first_order
        ),
new_result AS (
    SELECT
                    DATE_TRUNC('month', o.created_at)::date AS period,
                    COUNT(*)                                                      AS orders_all_statuses,
                    COUNT(*) FILTER (WHERE o.status IN ('completed', 'processing'))        AS orders_revenue_statuses,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS revenue,
                    COUNT(DISTINCT o.customer_id)                                 AS customers_all_statuses,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.status IN ('completed', 'processing'))                    AS customers_revenue_statuses,
                    -- 2.1: both sides revenue-status.
                    COALESCE(
                        SUM(o.total) FILTER (WHERE o.status IN ('completed', 'processing'))
                        / NULLIF(COUNT(*) FILTER (WHERE o.status IN ('completed', 'processing')), 0),
                    0)                                                            AS aov,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE DATE_TRUNC('month', o.created_at)::date = DATE_TRUNC('month', q.acquired_at)::date)                  AS new_customers,
                    -- Refunds, over EXACTLY the rows `revenue` above is summed from:
                    -- same bucket, same revenue-status filter, one query.
                    COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS refunded_amount,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)
                    - COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                AS net_revenue,
                    COUNT(*) FILTER (
                        WHERE o.status IN ('completed', 'processing')
                          AND o.refund_total > 0)                                 AS orders_with_refund
                FROM analytics_2.orders o
                LEFT JOIN lat_acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
                GROUP BY period
)
SELECT 'in OLD, not in MERGED' AS side, * FROM (
  SELECT * FROM old_result EXCEPT ALL SELECT * FROM new_result) a
UNION ALL
SELECT 'in MERGED, not in OLD', * FROM (
  SELECT * FROM new_result EXCEPT ALL SELECT * FROM old_result) b;


\echo ''
\echo 'BLOCK 3  revenue_summary -- expect 0 rows'
WITH
    acquired AS (
            SELECT DISTINCT ON (a.customer_id)
                   a.customer_id, a.created_at AS acquired_at
            FROM analytics_2.orders a
            WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
            ORDER BY a.customer_id, a.created_at, a.id
        ),
old_result AS (
    SELECT
                    COUNT(*)                                                   AS orders_all_statuses,
                    COUNT(*) FILTER (WHERE o.status IN ('completed', 'processing'))     AS orders_revenue_statuses,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)             AS revenue,
                    COUNT(DISTINCT o.customer_id)                              AS customers_all_statuses,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.status IN ('completed', 'processing'))                 AS customers_revenue_statuses,
                    COALESCE(
                        SUM(o.total) FILTER (WHERE o.status IN ('completed', 'processing'))
                        / NULLIF(COUNT(*) FILTER (
                            WHERE o.status IN ('completed', 'processing')), 0),
                    0)                                                         AS aov,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE q.acquired_at >= :start AND q.acquired_at < :end_plus)              AS new_customers,
                    -- Refunds, over EXACTLY the rows `revenue` above is summed from:
                    -- same window, same revenue-status filter, same join, one query.
                    COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)             AS refunded_amount,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)
                    - COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)             AS net_revenue,
                    COUNT(*) FILTER (
                        WHERE o.status IN ('completed', 'processing')
                          AND o.refund_total > 0)                              AS orders_with_refund
                FROM analytics_2.orders o
                LEFT JOIN acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
),
    window_customers AS (
            -- Only customers active in the window can be acquired in it, so only
            -- their acquiring orders need finding. Derived from the window rows
            -- the outer aggregate already reads — not a second predicate.
            SELECT DISTINCT customer_id
            FROM analytics_2.orders
            WHERE created_at >= :start AND created_at < :end_plus AND customer_id IS NOT NULL
        ),
        lat_acquired AS (
            -- ASK PER CUSTOMER, NOT PER ROW. Their HISTORY is deliberately not
            -- bounded: "first" still means first ever, which is why the inner
            -- query carries no date predicate.
            SELECT wc.customer_id, first_order.created_at AS acquired_at
            FROM window_customers wc
            CROSS JOIN LATERAL (
                SELECT o.created_at
                FROM analytics_2.orders o
                WHERE o.customer_id = wc.customer_id
                  AND o.status IN ('completed', 'processing')
                ORDER BY o.created_at, o.id
                LIMIT 1
            ) first_order
        ),
new_result AS (
    SELECT
                    COUNT(*)                                                   AS orders_all_statuses,
                    COUNT(*) FILTER (WHERE o.status IN ('completed', 'processing'))     AS orders_revenue_statuses,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)             AS revenue,
                    COUNT(DISTINCT o.customer_id)                              AS customers_all_statuses,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.status IN ('completed', 'processing'))                 AS customers_revenue_statuses,
                    COALESCE(
                        SUM(o.total) FILTER (WHERE o.status IN ('completed', 'processing'))
                        / NULLIF(COUNT(*) FILTER (
                            WHERE o.status IN ('completed', 'processing')), 0),
                    0)                                                         AS aov,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE q.acquired_at >= :start AND q.acquired_at < :end_plus)              AS new_customers,
                    -- Refunds, over EXACTLY the rows `revenue` above is summed from:
                    -- same window, same revenue-status filter, same join, one query.
                    COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)             AS refunded_amount,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)
                    - COALESCE(SUM(o.refund_total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)             AS net_revenue,
                    COUNT(*) FILTER (
                        WHERE o.status IN ('completed', 'processing')
                          AND o.refund_total > 0)                              AS orders_with_refund
                FROM analytics_2.orders o
                LEFT JOIN lat_acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
)
SELECT 'in OLD, not in MERGED' AS side, * FROM (
  SELECT * FROM old_result EXCEPT ALL SELECT * FROM new_result) a
UNION ALL
SELECT 'in MERGED, not in OLD', * FROM (
  SELECT * FROM new_result EXCEPT ALL SELECT * FROM old_result) b;


\echo ''
\echo 'BLOCK 4  customer_report, daily series -- expect 0 rows'
WITH
    acquired AS (
            SELECT DISTINCT ON (a.customer_id)
                   a.customer_id, a.created_at AS acquired_at
            FROM analytics_2.orders a
            WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
            ORDER BY a.customer_id, a.created_at, a.id
        ),
old_result AS (
    SELECT
                    o.created_at::date AS d,
                    COUNT(DISTINCT o.customer_id)                                  AS cust_all,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.status IN ('completed', 'processing'))                     AS cust_rev,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE q.acquired_at::date = o.created_at::date)            AS new_cust
                FROM analytics_2.orders o
                LEFT JOIN acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
                GROUP BY d
),
    window_customers AS (
            -- Only customers active in the window can be acquired in it, so only
            -- their acquiring orders need finding. Derived from the window rows
            -- the outer aggregate already reads — not a second predicate.
            SELECT DISTINCT customer_id
            FROM analytics_2.orders
            WHERE created_at >= :start AND created_at < :end_plus AND customer_id IS NOT NULL
        ),
        lat_acquired AS (
            -- ASK PER CUSTOMER, NOT PER ROW. Their HISTORY is deliberately not
            -- bounded: "first" still means first ever, which is why the inner
            -- query carries no date predicate.
            SELECT wc.customer_id, first_order.created_at AS acquired_at
            FROM window_customers wc
            CROSS JOIN LATERAL (
                SELECT o.created_at
                FROM analytics_2.orders o
                WHERE o.customer_id = wc.customer_id
                  AND o.status IN ('completed', 'processing')
                ORDER BY o.created_at, o.id
                LIMIT 1
            ) first_order
        ),
new_result AS (
    SELECT
                    o.created_at::date AS d,
                    COUNT(DISTINCT o.customer_id)                                  AS cust_all,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.status IN ('completed', 'processing'))                     AS cust_rev,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE q.acquired_at::date = o.created_at::date)            AS new_cust
                FROM analytics_2.orders o
                LEFT JOIN lat_acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
                GROUP BY d
)
SELECT 'in OLD, not in MERGED' AS side, * FROM (
  SELECT * FROM old_result EXCEPT ALL SELECT * FROM new_result) a
UNION ALL
SELECT 'in MERGED, not in OLD', * FROM (
  SELECT * FROM new_result EXCEPT ALL SELECT * FROM old_result) b;


\echo ''
\echo 'BLOCK 5  customer_report, window totals -- expect 0 rows'
WITH
    acquired AS (
            SELECT DISTINCT ON (a.customer_id)
                   a.customer_id, a.created_at AS acquired_at
            FROM analytics_2.orders a
            WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
            ORDER BY a.customer_id, a.created_at, a.id
        ),
old_result AS (
    SELECT
                    COUNT(DISTINCT o.customer_id)                                  AS cust_all,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.status IN ('completed', 'processing'))                     AS cust_rev,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE q.acquired_at >= :start AND q.acquired_at < :end_plus)                  AS new_cust,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                 AS revenue
                FROM analytics_2.orders o
                LEFT JOIN acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
),
    window_customers AS (
            -- Only customers active in the window can be acquired in it, so only
            -- their acquiring orders need finding. Derived from the window rows
            -- the outer aggregate already reads — not a second predicate.
            SELECT DISTINCT customer_id
            FROM analytics_2.orders
            WHERE created_at >= :start AND created_at < :end_plus AND customer_id IS NOT NULL
        ),
        lat_acquired AS (
            -- ASK PER CUSTOMER, NOT PER ROW. Their HISTORY is deliberately not
            -- bounded: "first" still means first ever, which is why the inner
            -- query carries no date predicate.
            SELECT wc.customer_id, first_order.created_at AS acquired_at
            FROM window_customers wc
            CROSS JOIN LATERAL (
                SELECT o.created_at
                FROM analytics_2.orders o
                WHERE o.customer_id = wc.customer_id
                  AND o.status IN ('completed', 'processing')
                ORDER BY o.created_at, o.id
                LIMIT 1
            ) first_order
        ),
new_result AS (
    SELECT
                    COUNT(DISTINCT o.customer_id)                                  AS cust_all,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE o.status IN ('completed', 'processing'))                     AS cust_rev,
                    COUNT(DISTINCT o.customer_id) FILTER (
                        WHERE q.acquired_at >= :start AND q.acquired_at < :end_plus)                  AS new_cust,
                    COALESCE(SUM(o.total) FILTER (
                        WHERE o.status IN ('completed', 'processing')), 0)                 AS revenue
                FROM analytics_2.orders o
                LEFT JOIN lat_acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
)
SELECT 'in OLD, not in MERGED' AS side, * FROM (
  SELECT * FROM old_result EXCEPT ALL SELECT * FROM new_result) a
UNION ALL
SELECT 'in MERGED, not in OLD', * FROM (
  SELECT * FROM new_result EXCEPT ALL SELECT * FROM old_result) b;


\echo ''
\echo 'history still unbounded -- acquiring orders BEFORE the window'
WITH
    window_customers AS (
            -- Only customers active in the window can be acquired in it, so only
            -- their acquiring orders need finding. Derived from the window rows
            -- the outer aggregate already reads — not a second predicate.
            SELECT DISTINCT customer_id
            FROM analytics_2.orders
            WHERE created_at >= :start AND created_at < :end_plus AND customer_id IS NOT NULL
        ),
        acquired AS (
            -- ASK PER CUSTOMER, NOT PER ROW. Their HISTORY is deliberately not
            -- bounded: "first" still means first ever, which is why the inner
            -- query carries no date predicate.
            SELECT wc.customer_id, first_order.created_at AS acquired_at
            FROM window_customers wc
            CROSS JOIN LATERAL (
                SELECT o.created_at
                FROM analytics_2.orders o
                WHERE o.customer_id = wc.customer_id
                  AND o.status IN ('completed', 'processing')
                ORDER BY o.created_at, o.id
                LIMIT 1
            ) first_order
        )
SELECT count(*) AS acquired_before_window, min(acquired_at) AS earliest
FROM acquired WHERE acquired_at < :start;
