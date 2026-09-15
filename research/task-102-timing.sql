-- task 102, requirement 6: THE MEASUREMENT AFTER THE RESTRICTION
--
-- Run:   psql "$DD_DSN" -v ON_ERROR_STOP=1 -f task-102-timing.sql > timing.txt
--
-- Gives, per statement: execution time, buffer counts, and the index entries
-- the plan walks -- OLD form then NEW form, same box, same window.
--
-- HOW TO READ IT, because EXPLAIN ANALYZE on a cold cache measures the cache.
-- Each statement runs THREE TIMES per form and you take the MEDIAN, which is
-- what research/candidates-dashboard-remaining-2026-09-14.md corrected itself
-- to on 14 Sep after a single-pass table gave top_products as 660 ms against a
-- median of 619 ms. The first run of the file is a warm-up; discard it.
--
-- The number that actually explains the change is not the time. It is
-- `Index Scan using ix_analytics_orders_customer_created` -> `rows` on the
-- `acquired` node: 2,885,651 entries walked to produce 156,981 customers for
-- a join that can use ~21,579 of them. Time follows from that and varies with
-- the box; the entry count does not.
--
-- DO NOT claim an endpoint figure from this. It measures the statement. The
-- non-SQL portion of these endpoints was 6 ms and 2 ms, and task 100's spec
-- already records what claiming end-to-end costs.

\set ON_ERROR_STOP on
\pset pager off
\timing on

\set start '''2026-08-15''::timestamptz'
\set end_plus '''2026-09-15''::timestamptz'

\echo '== window and index size =='
SELECT (SELECT count(*) FROM analytics_2.orders
         WHERE created_at >= :start AND created_at < :end_plus) AS orders_in_window,
       (SELECT count(DISTINCT customer_id) FROM analytics_2.orders
         WHERE created_at >= :start AND created_at < :end_plus
           AND customer_id IS NOT NULL)                          AS window_customers,
       (SELECT count(*) FROM analytics_2.orders
         WHERE status IN ('completed','processing')
           AND customer_id IS NOT NULL)                          AS rows_old_cte_scans,
       pg_size_pretty(pg_relation_size(
         'analytics_2.ix_analytics_orders_customer_created'))    AS index_size;


\echo ''
\echo '-- revenue_report, granularity=day :: OLD :: run 1 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_report, granularity=day :: OLD :: run 2 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_report, granularity=day :: OLD :: run 3 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_report, granularity=day :: NEW :: run 1 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_report, granularity=day :: NEW :: run 2 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_report, granularity=day :: NEW :: run 3 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_report, granularity=month :: OLD :: run 1 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_report, granularity=month :: OLD :: run 2 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_report, granularity=month :: OLD :: run 3 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_report, granularity=month :: NEW :: run 1 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_report, granularity=month :: NEW :: run 2 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_report, granularity=month :: NEW :: run 3 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY period;


\echo ''
\echo '-- revenue_summary :: OLD :: run 1 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo '-- revenue_summary :: OLD :: run 2 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo '-- revenue_summary :: OLD :: run 3 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo '-- revenue_summary :: NEW :: run 1 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo '-- revenue_summary :: NEW :: run 2 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo '-- revenue_summary :: NEW :: run 3 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo '-- customer_report, daily series :: OLD :: run 1 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY d;


\echo ''
\echo '-- customer_report, daily series :: OLD :: run 2 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY d;


\echo ''
\echo '-- customer_report, daily series :: OLD :: run 3 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY d;


\echo ''
\echo '-- customer_report, daily series :: NEW :: run 1 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY d;


\echo ''
\echo '-- customer_report, daily series :: NEW :: run 2 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY d;


\echo ''
\echo '-- customer_report, daily series :: NEW :: run 3 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            GROUP BY d;


\echo ''
\echo '-- customer_report, window totals :: OLD :: run 1 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo '-- customer_report, window totals :: OLD :: run 2 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo '-- customer_report, window totals :: OLD :: run 3 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo '-- customer_report, window totals :: NEW :: run 1 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo '-- customer_report, window totals :: NEW :: run 2 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo '-- customer_report, window totals :: NEW :: run 3 --'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF, TIMING ON)
WITH
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    )
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
            WHERE o.created_at >= :start AND o.created_at < :end_plus;


\echo ''
\echo 'Take the MEDIAN of the three runs per form.'
