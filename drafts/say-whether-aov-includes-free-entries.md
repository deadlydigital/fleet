# Draft spec — say whether AOV includes free entries, wherever the API prints it

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Say whether AOV includes free entries — a paid-only AOV and a free-entry count beside every aov the analytics API serves, with aov itself unchanged
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/revenue.py
  - api/analytics/routes/dashboard.py
```

## The measurement, stated rather than asked for

The agent that builds this has no shell, no database and no network. Every
figure it needs is here, taken from
`research/candidates-aov-free-entries-2026-09-16.md` at sha `b0b20da`, read
against production `analytics_2` on 2026-09-16. **No numbered requirement below
asks anybody to re-derive any of it.**

| Figure | Value |
|---|---|
| Orders inside `_REVENUE_STATUSES` | 2,888,343 |
| Of those, non-zero `total` | 2,821,656 |
| Of those, `total = 0` | 66,676 |
| AOV as shipped, over all of them | £8.23 |
| AOV over the non-zero ones | £8.43 |
| Understatement | 2.4% |

`_REVENUE_STATUSES` is `('completed', 'processing', 'on-hold')`. The 66,676
zero-total orders are the free-entry route a prize competition must offer by
law. They are recorded correctly and they are real orders.

## Why this is a code change and not an investigation

The figure exists, is computed, and is already on a page. It is not a parity
gap and there is nothing to find out first.

`research/candidates-metorik-gap-2026-09-16.md` records that *Average order
gross over time* is already shipped inside the revenue series —
`revenue_report()` returns `orders` and `aov` per period. `revenue_report()`
and `revenue_summary()` in `api/analytics/services/analytics_engine.py` are
mapped in `research/refund-coverage.md` as the two window aggregates
`GET /api/analytics/revenue` exposes, as `data` and `summary`.
`dashboard_overview()` in the same module returns `period` and `previous`
objects whose keys `specs/dashboard-comparison-windows.md` enumerates as
`orders_revenue_statuses`, `customers_revenue_statuses`, `revenue` and **`aov`**,
served by `api/analytics/routes/dashboard.py`.

So `aov` is served from two routes over three engine call sites, and no
consumer of any of them is told which population it was averaged over. That is
the defect, and it is a defect of silence rather than of arithmetic.

## Why `dd-trustworthy`, and why the repair is a label

`objectives-2026-Q4.yaml` states the objective as *no metric telling two
stories*. The same `orders.total` column means "a sale" on one row and "a free
entry" on the next, and a mean over both distinguishes neither.

**Nothing may be filtered out.** `research/metorik-report-classification-2026-09-15.md`
carries the `MUST SPLIT FREE ENTRIES` mark on this row and is explicit that it
is not a do-not-propose mark: the report must *say* whether free entries are in
or out. Dropping 66,676 orders from a denominator on a page that prints an
order count beside it produces two figures over two populations with one label,
which is the same failure one layer down. Every sum is already correct — a free
entry contributes £0 — and this change must leave every sum alone.

The precedent for the shape is in this repository. `product_category_report()`
in `api/analytics/services/analytics_engine.py` leads its response with a
`coverage` block rather than quietly dropping uncategorised lines;
`api/analytics/routes/products.py` states in its own docstring that the
per-category rows deliberately do not sum to `revenue_total` and why. The same
move here is a second AOV and a count, named, beside the one that already
ships.

## Why this contract

`contracts/deadly-digital-platform-api.yaml`, work_type `dd_api`. All three
declared paths are in its enumerated writable set, and none of them is in
`contracts/dd-order-filters.yaml`, whose whole writable set is
`api/analytics/routes/orders.py` and `api/analytics/services/order_query.py`.
So it is the only contract for this work_type and repo that covers the paths —
and it is also the one that can judge the change: it runs `tests/unit` and
`tests/analytics` per file and requires one added test proven to fail against
the tree without the change. `contracts/dd-order-filters.yaml` permits no new
test at all, which for a change whose entire content is *what a number means*
would be a gate that cannot fail.

## Why the page is a separate draft, and not a second link in this one

The candidate says *every surface that prints it*, and the revenue page is one:
`research/candidates-aov-free-entries-2026-09-16.md` counts 17 mentions of AOV
in platform/app/(dashboard)/analytics/revenue/page.tsx. **It is deliberately
not in this spec, and the reason is mechanical rather than editorial.**

No contract covers both trees, by design — the api contract protects
`platform/**` because it can verify nothing there, and
`contracts/dd-analytics-frontend.yaml` protects `api/**` for the mirror reason.
A draft may split into an ordered chain of `fleet-spec` blocks to cross that
line, and a chain is the wrong instrument here: `console/autoqueue.py` writes
**the whole markdown** into `tasks.spec_md` for every link, and
`contracts/checks/spec_requirements_cited.py` parses that whole document and
obliges each link's diff to cite every numbered requirement in it. A two-block
chain would require the API diff to cite the page's requirements and the page
diff to cite the engine's. Both links would fail, having been built and paid
for. A single-block draft narrowing the work is an ordinary editorial decision
and `console/autoqueue.py` treats it as one; only a split is held to the
candidate's full path list.

**So the page is a known follow-up, not a discovery.** It should be drafted
against `contracts/dd-analytics-frontend.yaml` once this has merged, and it has
something to render only after this has: the keys in requirement 2 are what a
page would print. Queue it separately.

## Citing the requirements

`contracts/checks/spec_requirements_cited.py` runs first under this contract and
reads only lines the diff adds. Put `# spec:N` on a line this change adds — the
line computing the paid aggregate, the docstring line naming the key, the test
name — for each of 1 through 6. Six requirements, against a `max_requirements`
of 10.

---

### 1. Every key that exists today keeps its name, its population and its value

`aov` stays the mean of `total` over **all** orders in `_REVENUE_STATUSES`,
zero-total ones included, everywhere it is returned. It is not renamed, not
recomputed, and not deprecated.

No `total != 0`, `total > 0` or `total <> 0` predicate is added to any existing
aggregate, CTE or `WHERE` clause. Gross revenue, net revenue, refunded amount,
`orders`, `orders_revenue_statuses`, `customers_revenue_statuses` and every
other count and sum are byte-identical to what they return now. `_REVENUE_STATUSES`
itself does not change.

This is the requirement most likely to be violated by an agent that reads the
title and reaches for a filter. The new predicate belongs **only** inside the
new aggregates in requirements 2 and 3, computed beside the existing ones over
the same rows. The discipline is the one `specs/net-revenue-after-refunds.md`
established for net beside gross: additive keys, nothing recomputed, because
the frontend is protected under this contract and a silently different number
has no way to announce itself.

### 2. Each period row of `revenue_report()` carries the paid figure and the free count

`revenue_report()` in `api/analytics/services/analytics_engine.py` gains two
keys on every row it already returns:

* `aov_paid` — the mean of `total` over the row's revenue-status orders whose
  `total` is greater than zero;
* `orders_free` — the count of the row's revenue-status orders whose `total`
  is zero.

Both come out of the **same outer aggregate over the same rows** as `orders`
and `aov` — a `SUM`/`COUNT` with a `FILTER` clause or the equivalent
conditional, not a second query, not a second pass over `orders`, and not a
post-hoc subtraction in Python. `orders` minus `orders_free` is the paid count
and no third key is added for it.

`orders_free` is `0`, never `None`, for a period with no free entries.

**`aov_paid` is `None` when the paid count for that period is zero, never `0`
and never `aov`.** A period in which every order was a free entry has no paid
average, and £0.00 there is a figure a reader would take for a collapse in
order value. This is the same no-baseline rule
`specs/dashboard-comparison-windows.md` states for a comparison window with no
prior: absent is reported as absent.

### 3. The overview does the same, for both of its windows

`dashboard_overview()` in `api/analytics/services/analytics_engine.py` returns
`period` and `previous` objects that each carry `aov` today. Each gains
`aov_paid` and `orders_free` under requirement 2's definitions and null rule.

Nothing else about the comparison moves. The number of period-stats queries
stays at two, one per window. The percentage rules are untouched: a comparison
window with `prior <= 0` still yields `None`, never `0` and never `100`, and
**no percentage change is computed for `aov_paid` or `orders_free`** unless the
existing code path derives one for every numeric key generically — this
requirement adds data, not a new comparison.

`previous.aov_paid` may be `None` while `period.aov_paid` is a number. A
consumer must not read that as zero, which is requirement 5's job to say.

### 4. One block states the convention, once, in words

Following `product_category_report()`'s `coverage` precedent, the response of
`GET /api/analytics/revenue` leads with a small block — built in
`api/analytics/routes/revenue.py` from what the engine returned, alongside the
existing `data` and `summary` keys — that states in a machine-readable way:

* that `aov` is computed over all orders in the revenue statuses, zero-total
  free entries included;
* that `aov_paid` excludes orders whose `total` is zero;
* the number of zero-total revenue-status orders in the requested window, and
  the revenue-status order count it is a share of. Both are already available
  as sums of requirement 2's per-period keys; do not issue another query for
  them.

`api/analytics/routes/dashboard.py` carries the same block over its own window,
built from requirement 3's keys.

The block is **additive and top-level**. It does not nest, rename or reorder
`data`, `summary`, `period` or `previous`, and no existing consumer has to
change to keep working.

Free entries are not a data-quality problem and the block must not read like
one. The wording belongs nearer *"66,676 of these orders were free entries"*
than *"66,676 orders had missing totals"*, because a competition's free-entry
route is a legal obligation being met correctly.

### 5. The route docstrings say which population each figure used

`api/analytics/routes/revenue.py` and `api/analytics/routes/dashboard.py` each
document, in the docstring of the endpoint that returns these keys, that `aov`
includes zero-total free entries and `aov_paid` does not, that `aov_paid` is
`None` rather than `0` when a window holds no paid order, and what
`orders_free` counts.

This is not decoration. The JSON is the only contract a consumer of these
routes has, the frontend is protected under this contract and cannot be
updated in this diff, and the person who writes the page draft will read these
docstrings and nothing else. The precedent is
`api/analytics/routes/products.py`, whose docstring explains why the category
rows do not sum — the same class of statement, about the same class of trap.

### 6. One added test, and what it has to pin

Create `api/tests/analytics/test_fleet_aov_free_entries.py` — the only shape
this contract's `creatable_paths` permits. No existing test may be edited;
`api/tests/analytics/test_analytics_engine.py` in particular stays untouched,
and if it asserts an exact `aov` those assertions must still pass, which
requirement 1 guarantees.

The test must fail against the tree without this change — `new_test_bites.sh`
runs it against both trees — and over a fixture holding a mix of zero-total and
paid orders in the revenue statuses it must assert:

* `aov` is unchanged and equals the mean over **all** the fixture's
  revenue-status orders, and the window's revenue and order totals are what
  they were. A test that only checks the new keys would pass against a build
  that filtered the free entries out of the old one;
* `aov_paid` is strictly greater than `aov` on that fixture, and equals the
  mean over the non-zero rows only. Seed the fixture so the two differ —
  equal values would pass against code that returned the same number twice;
* `orders_free` equals the fixture's zero-total revenue-status count, and
  `orders` still counts every order including those;
* a period in which **every** order is a free entry returns `aov_paid is None`
  and `orders_free` equal to that period's order count. This is the case
  requirement 2's null rule exists for and the one a naive division writes
  `0.0` or raises on;
* an order in a status outside `_REVENUE_STATUSES` with `total = 0` does not
  appear in `orders_free`. The free-entry count is over the revenue statuses,
  matching the population `aov` already uses — 66,676 of the 66,764 zero-total
  orders, not all of them.

`test_diff_target` under this contract is 300 lines and is guidance, not a
gate; a case that earns its place is worth going over it for.

## Not in scope, stated so nobody reads it as included

**`daily_metrics.aov`.** A precomputed per-day value that may carry the same
mixing and that `research/candidates-aov-free-entries-2026-09-16.md` names
explicitly as a second question and possibly a second candidate row. Nothing in
this change reads or writes it, and no requirement above touches the metrics
tables or `api/analytics/models.py`. If the page later prefers the precomputed
value to the engine's, it would silently reintroduce the defect this closes —
worth a row of its own, not a widened diff.

**`customers.aov`.** A stored per-customer lifetime average, a different figure
over a different population, and nothing here touches it.

**Whether the default should be paid-only.** It should not be decided by this
task. `research/candidates-aov-free-entries-2026-09-16.md` is explicit that the
right default is a product decision for Eamonn, and requirement 1 keeps today's
default precisely so that the decision stays open and reversible. Changing
which figure leads is one line once somebody has decided, on a surface that by
then says which is which.

**Whether the 2.4% is stable or seasonal.** One lifetime measurement, and the
per-period figures this change adds are what would answer it. Nothing above
asks the build agent to establish it, because the build agent cannot.

**`analytics_1`.** Not read for the candidate. The keys added here are computed
per tenant from the same query, so a tenant with no free entries gets
`orders_free: 0` and `aov_paid == aov`, which is the correct and quiet outcome.

## Before this is queued

`auto_merge` is `true` on this contract and nobody reads a spec against a diff
on that path. The requirement most likely to ship unbuilt is **5** — a
docstring is invisible to `compileall`, to `ruff` and to every pytest run in
the verification list, and the change passes every gate without it while the
next reader of these routes learns nothing. The requirement most likely to be
shipped *wrongly* is **1**, and wrongly here means the free entries quietly
leave the denominator, `aov` becomes 8.43, the revenue page keeps its label,
and the page disagrees with its own order count. If one thing is read against
the diff, read requirement 1 first.
