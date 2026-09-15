-- task 102, requirement 5: THE IDENTITY IS PROVED ON PRODUCTION DATA
--
-- Run:   psql "$DD_DSN" -v ON_ERROR_STOP=1 -f task-102-identity-proof.sql
--
-- Read:  every block must print ZERO ROWS. A row means the restriction
--        changed an answer, and the branch is wrong.
--
-- WHAT THIS COMPARES, AND WHY IT IS THE WHOLE CHANGE
--
-- The four statements task 102 touches all have the shape
--
--     FROM analytics_2.orders o
--     LEFT JOIN acquired q ON q.customer_id = o.customer_id
--     WHERE o.created_at >= :start AND o.created_at < :end_plus
--
-- and the branch changes ONLY the `acquired` CTE. Checked mechanically against
-- fd20133 and dcd0f9d: after swapping the CTE the outer projections of all
-- four statements are token-identical, so nothing else can move. The SQL below
-- was rendered FROM those two files rather than transcribed, because
-- retyping a projection is how an identity proof ends up proving something
-- adjacent.
--
-- The argument the numbers have to confirm: `window_customers` is exactly the
-- set of non-null `o.customer_id` the outer WHERE admits, so the LEFT JOIN can
-- only ever consume rows for those customers. Restricting `acquired` to them
-- therefore removes only rows the join would have discarded. If that is right,
-- every column agrees for every window. If it is subtly wrong, `new_customers`
-- is where it shows: a customer missing from `acquired` gets a NULL
-- `acquired_at` and is silently counted as returning rather than new.
--
-- HISTORY STAYS UNBOUNDED on both sides -- neither `acquired` has a date
-- predicate on `a.created_at`. Narrowing WHICH CUSTOMERS are computed is not
-- narrowing THEIR HISTORY, and confusing the two is the one way this can break
-- quietly. Block 0 tests exactly that and nothing else.
--
-- Tenant 2 (analytics_2): 2,888,640 orders, 157,258 customers,
-- 2023-03-12 .. 2026-09-15. This is the schema the 619 ms was measured on.

\set ON_ERROR_STOP on
\timing off
\pset pager off

-- ===========================================================================
-- CHOOSE THE WINDOW. Run the whole file once per window.
-- `end_plus` is EXCLUSIVE, which is what range_params() computes from an
-- inclusive `end` -- end + 1 day. Get that wrong and the two sides still
-- agree, which is the sort of passing test that proves nothing.
-- ===========================================================================

-- (a) the 30-day window the 619 ms was measured on
\set start '''2026-08-15''::timestamptz'
\set end_plus '''2026-09-15''::timestamptz'

-- (b) a window spanning a month boundary  -- uncomment for the second run
-- \set start '''2026-07-20''::timestamptz'
-- \set end_plus '''2026-08-11''::timestamptz'

-- (c) ALL HISTORY -- the degenerate case, where window_customers is every
--     customer and the restriction buys nothing. It must still agree.
-- \set start '''2000-01-01''::timestamptz'
-- \set end_plus '''2100-01-01''::timestamptz'

-- (d) a window with NO orders in it at all. `window_customers` is empty,
--     `acquired` is empty, and every LEFT JOIN yields NULL on both sides.
-- \set start '''2019-01-01''::timestamptz'
-- \set end_plus '''2019-02-01''::timestamptz'

\echo '=============================================================='
\echo 'window:'
SELECT :start AS window_start, :end_plus AS window_end_exclusive,
       (SELECT count(*) FROM analytics_2.orders
         WHERE created_at >= :start AND created_at < :end_plus) AS orders_in_window,
       (SELECT count(DISTINCT customer_id) FROM analytics_2.orders
         WHERE created_at >= :start AND created_at < :end_plus
           AND customer_id IS NOT NULL) AS window_customers;


-- ===========================================================================
-- BLOCK 0 -- the CTEs themselves, which is where a break would actually live.
-- For every customer the outer query can use, the two forms must agree on the
-- acquiring order EXACTLY. Zero rows.
-- ===========================================================================
\echo ''
\echo 'BLOCK 0  acquiring order per usable customer -- expect 0 rows'
WITH
    old_acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing') AND a.customer_id IS NOT NULL
        ORDER BY a.customer_id, a.created_at, a.id
    ),
    window_customers AS (
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    new_acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
    ),
usable AS (SELECT customer_id FROM window_customers),
old_side AS (
    SELECT o.customer_id, o.acquired_at FROM old_acquired o
    JOIN usable u ON u.customer_id = o.customer_id
),
new_side AS (SELECT customer_id, acquired_at FROM new_acquired)
SELECT 'in OLD, not in NEW' AS side, * FROM (
    SELECT * FROM old_side EXCEPT ALL SELECT * FROM new_side) a
UNION ALL
SELECT 'in NEW, not in OLD', * FROM (
    SELECT * FROM new_side EXCEPT ALL SELECT * FROM old_side) b;

\echo ''
\echo 'BLOCK 0b  history is still unbounded: acquiring orders BEFORE the window'
\echo '          must survive. A non-zero count here is the proof that the'
\echo '          restriction did not silently become a date filter.'
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
SELECT count(*) AS acquired_before_window,
       min(acquired_at) AS earliest_acquiring_order
FROM acquired WHERE acquired_at < :start;


-- ===========================================================================
-- BLOCK 1 -- revenue_report, granularity=day
-- ===========================================================================
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
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    new_acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
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
                LEFT JOIN new_acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
                GROUP BY period
)
SELECT 'in OLD, not in NEW' AS side, * FROM (
    SELECT * FROM old_result EXCEPT ALL SELECT * FROM new_result) a
UNION ALL
SELECT 'in NEW, not in OLD', * FROM (
    SELECT * FROM new_result EXCEPT ALL SELECT * FROM old_result) b;


-- ===========================================================================
-- BLOCK 2 -- revenue_report, granularity=month
-- ===========================================================================
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
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    new_acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
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
                LEFT JOIN new_acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
                GROUP BY period
)
SELECT 'in OLD, not in NEW' AS side, * FROM (
    SELECT * FROM old_result EXCEPT ALL SELECT * FROM new_result) a
UNION ALL
SELECT 'in NEW, not in OLD', * FROM (
    SELECT * FROM new_result EXCEPT ALL SELECT * FROM old_result) b;


-- ===========================================================================
-- BLOCK 3 -- revenue_summary
-- ===========================================================================
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
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    new_acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
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
                LEFT JOIN new_acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
)
SELECT 'in OLD, not in NEW' AS side, * FROM (
    SELECT * FROM old_result EXCEPT ALL SELECT * FROM new_result) a
UNION ALL
SELECT 'in NEW, not in OLD', * FROM (
    SELECT * FROM new_result EXCEPT ALL SELECT * FROM old_result) b;


-- ===========================================================================
-- BLOCK 4 -- customer_report, daily series
-- ===========================================================================
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
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    new_acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
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
                LEFT JOIN new_acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
                GROUP BY d
)
SELECT 'in OLD, not in NEW' AS side, * FROM (
    SELECT * FROM old_result EXCEPT ALL SELECT * FROM new_result) a
UNION ALL
SELECT 'in NEW, not in OLD', * FROM (
    SELECT * FROM new_result EXCEPT ALL SELECT * FROM old_result) b;


-- ===========================================================================
-- BLOCK 5 -- customer_report, window totals
-- ===========================================================================
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
        SELECT DISTINCT customer_id
        FROM analytics_2.orders
        WHERE created_at >= :start AND created_at < :end_plus
          AND customer_id IS NOT NULL
    ),
    new_acquired AS (
        SELECT DISTINCT ON (a.customer_id)
               a.customer_id, a.created_at AS acquired_at
        FROM analytics_2.orders a
        WHERE a.status IN ('completed', 'processing')
          AND a.customer_id IN (SELECT customer_id FROM window_customers)
        ORDER BY a.customer_id, a.created_at, a.id
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
                LEFT JOIN new_acquired q ON q.customer_id = o.customer_id
                WHERE o.created_at >= :start AND o.created_at < :end_plus
)
SELECT 'in OLD, not in NEW' AS side, * FROM (
    SELECT * FROM old_result EXCEPT ALL SELECT * FROM new_result) a
UNION ALL
SELECT 'in NEW, not in OLD', * FROM (
    SELECT * FROM new_result EXCEPT ALL SELECT * FROM old_result) b;


\echo ''
\echo '=============================================================='
\echo 'Every block above printed zero rows  ->  requirement 5 holds for'
\echo 'this window. Re-run for windows (b), (c) and (d).'
