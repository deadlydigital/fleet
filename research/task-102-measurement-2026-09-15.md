# Task 102 — requirements 5 and 6, measured

`analytics_2` (tenant 2): 2,888,640 orders, 157,258 customers,
2023-03-12 .. 2026-09-15. Platform at `fd20133` (base) and `dcd0f9d` (branch
`fleet/task-102`). Run 15 Sep 2026 from this host over loopback.

Scripts, both runnable and both rendered FROM the two engine versions rather
than transcribed: `research/task-102-identity-proof.sql`,
`research/task-102-timing.sql`.

## Requirement 5 — the identity holds

Every block, every window, **zero rows** in both directions of `EXCEPT ALL`.

| window | | result |
|---|---|---|
| `2026-08-15 .. 2026-09-15` | the 30-day window the 619 ms was measured on | 0 rows |
| `2026-07-20 .. 2026-08-11` | spans the July/August boundary | 0 rows |
| `2000-01-01 .. 2100-01-01` | all history | 0 rows |
| `2019-01-01 .. 2019-02-01` | no orders at all | 0 rows |

Compared per window: the `acquired` CTE itself for every usable customer, then
the full result rows of `revenue_report` (day **and** month granularity),
`revenue_summary`, and both of `customer_report`'s statements — row for row,
every column, not summary-for-summary.

**History is still unbounded**, which is the way this could have broken
quietly. On the 30-day window 17,352 acquiring orders predate the window, the
earliest being 2023-03-15; on the boundary window, 16,669. A restriction that
had silently become a date filter would show 0 there.

Structural check, done mechanically rather than by eye: after swapping the CTE,
the outer projections of all four statements are **token-identical** between
`fd20133` and `dcd0f9d`. Nothing outside `acquired` moved.

## Requirement 6 — the measurement, and the decision it forces

`revenue_report`, granularity=day, 30-day window. `EXPLAIN (ANALYZE, BUFFERS)`,
median of three, first run discarded.

| form | execution | vs base |
|---|---|---|
| base — unrestricted `DISTINCT ON` | **5,787 ms** | — |
| branch — restricted `DISTINCT ON` | **3,595 ms** | 1.6× |
| `LATERAL … LIMIT 1` + restriction | **454 ms** | **12.7×** |

The other four statements behave the same way and gain less: `revenue_summary`
4,227 → 3,477 ms, `customer_report` daily 4,232 → 3,294 ms, totals 3,951 →
3,256 ms, `revenue_report` monthly 4,307 → 3,408 ms. All 1.2×–1.3×.

### THE RESTRICTION IS NOT THE WHOLE OF THE 7.3×, AND THE SPEC SAID IT WAS

The spec's ordering argument states the restriction "is the whole of the 7.3×"
and that LATERAL's "effect here is unknown until the restriction has shrunk the
input". The first half is wrong and the plan says why.

The branch's plan does **not** use `ix_analytics_orders_customer_created` at
all. It sorts:

    Unique            (actual time=3087.140..3475.402 rows=21379)
      ->  Sort        (actual time=3087.137..3316.140 rows=1728430)
            Sort Key: a.customer_id, a.created_at, a.id
            Sort Method: external merge  Disk: 50784kB

3,087 ms of the 3,635 ms, and 50 MB spilled to disk. The restriction bounds
**which customers** are computed — correctly, that is the whole of requirement
4 — but not **how much of their history** is read. Those 21,379 customers have
1,728,430 revenue-status orders between them, and `DISTINCT ON` must sort all
of them to take the first per customer.

`LATERAL … LIMIT 1` is what stops that, exactly as requirement 7 says:

    Limit                (actual time=0.008..0.008 rows=1 loops=21619)
      ->  Index Scan using ix_analytics_orders_customer_created
                           (actual time=0.007..0.007 rows=1 loops=21619)

One index entry per customer instead of 1.73M rows sorted. The CTE alone is
**260 ms**.

### The decision requirement 6 asks for

**Requirement 7 is justified and should be built.** Not marginally: the
restriction alone leaves 3.1 s of sorting per statement on the table, and the
endpoint stays over 3 s — nowhere near the 1.73 s the dashboard sits at, which
is the bar the spec set for declaring the restriction sufficient.

The LATERAL form was checked for requirement 4's identity on the 30-day window
against the ORIGINAL unrestricted form, row for row: **0 rows** both
directions. That is a pre-check and not requirement 5's proof — requirement 7
states its proof must be re-run across the windows, not reused, and that has
not been done for the other three statements or the other three windows.

## Caveats, stated rather than left to be discovered

* `EXPLAIN ANALYZE` adds per-node timing overhead; these are statement figures,
  not endpoint figures. The non-SQL portion of these endpoints was 6 ms and
  2 ms, and task 100's spec already records what claiming end-to-end costs.
* One box, one tenant, warm cache, medians of three. The **shape** — an
  external merge sort of 1.73M rows versus 21,619 single-entry index lookups —
  is what generalises; the millisecond counts are this box on this afternoon.
