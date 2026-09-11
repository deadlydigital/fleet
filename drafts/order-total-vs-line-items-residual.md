# Draft spec — reconcile each order's header total against its own line items

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Reconcile each order's header total against the sum of its line items, and report the residual
writable_paths:
  - api/analytics/services/reconciliation.py
  - api/analytics/routes/manifest.py
```

## Why this is a code change and not an investigation

The arithmetic has already been done once, by hand, in `specs/empty-columns.md`.
It is not the measurement that is missing — it is that the product cannot take
the measurement again. `specs/metorik-gap.md:121-122` retires two rows on it:
tax and shipping are both marked *Not applicable to this tenant* because
`total = SUM(order_items.total)` holds to the penny on 99.58% of orders, which
leaves no room for either term. Two status verdicts now rest on a number that
nothing in the API computes, nothing re-runs, and nothing would contradict if it
drifted.

So the deliverable is not a document. It is a query that lives in the service
that already does this comparison's external half, and a field on the endpoint
that already reports that half's result.

## Why `reconciliation.py`, and why this is not the comparison it already makes

`api/analytics/services/reconciliation.py` compares the store's own asserted
period totals against the platform's stored copy, from the connector's manifest,
and `api/analytics/routes/manifest.py` surfaces the verdict at `/manifest/status`.
That instrument answers *"did the sync lose anything the store sent?"* — and
`research/EVIDENCE-refund-coverage-manifests.md:71-84` is explicit that it cannot
answer more, because both sides of it are written by the same connector build:
*"A build that cannot see refunds at all would report zero in both places, and
the agreement above would look exactly as it does now."*

This check has no such dependency. `orders.total` and `order_items.total` are both
already in the platform's own database. Comparing them needs no manifest, no
connector, and no WordPress host — it is the one reading here the product can take
about itself. That is the whole reason it belongs beside the existing comparison
rather than inside it: same service, same endpoint, **separate verdict**, because
an internal disagreement and an external one mean different things and a single
merged status would hide which had happened.

The string `order_items` does not appear in `reconciliation.py` today.

## What the residual actually is, so the implementer does not re-derive it

From `specs/empty-columns.md:78-102`, measured once, on 30 August:

* `total == SUM(order_items.total)` held to the penny on **2,831,826 of
  2,843,780** revenue-status orders **that have line items** — 99.58%.
* The misses are **negative pennies**. Largest buckets: −0.09 (743 orders),
  −0.24 (711), −0.49 (685), −0.04 (643), −0.14 (455). Line items slightly exceed
  the header. That shape is rounding on per-line discount apportionment.
* A shipping term would be a **positive** residual clustered on a few round
  values. There is no positive cluster anywhere. That is the argument the two
  Rarely rows stand on, and it is an argument about the *shape* of the residual,
  not its size — which is why §3 below reports buckets and not just a count.

Two things about that measurement the implementer must not paper over.

**The denominators disagree.** `specs/metorik-gap.md:121` restates the same
99.58% against **2,844,177** orders; `specs/empty-columns.md` measured it against
**2,843,780** — "revenue-status orders that have line items". The ~397-order
difference is orders with **no line items at all**, for which the sum is not
zero but undefined. Counting those as reconciling would inflate the pass rate;
counting them as failures would invent a discrepancy. They are a third outcome
and §2 reports them as one.

**Both figures are older than a week** by the standard `principles.md` sets, and
neither has been recomputed since. Nothing below quotes them as current. They
are here so the implementer can recognise a wrong answer, not so the code can
assert them.

## What to build

Four requirements. Put `spec:<id>` on a line this change adds — a comment, a
docstring, or a test name — for each of `1`, `2`, `3` and `4`; see
`contracts/checks/spec_requirements_cited.py`, which runs first under
`contracts/deadly-digital-platform-api.yaml` and reads only added lines.

### 1. A line-item reconciliation query in `api/analytics/services/reconciliation.py`

Add one function to the service that, for a single tenant schema and a bounded
date range, compares each order's header total against the sum of its own line
items and returns the aggregate. It takes the range as parameters; it does not
choose one.

Requirements on the query itself:

* **Compare in `numeric`, not float.** These are money columns and the whole
  measurement is *to the penny*. A float round-trip manufactures residuals of
  1e-14 on orders that reconcile exactly, and the pass rate collapses for a
  reason that has nothing to do with the data. Round the comparison to 2 decimal
  places explicitly rather than relying on the column types to do it.
* **Aggregate in SQL.** One grouped query over the range, not a row loop in
  Python. `research/gap-list-open-questions.md:129-138` measured 4,488,746
  `order_items` rows on tenant 2 alone; pulling them into the process to sum
  them is not an option at that width.
* **Apply the same order-status scope the service already applies** to the
  period comparison it performs today. Do not introduce a second, differently
  scoped notion of which orders count — reuse the existing one, importing it if
  it lives elsewhere rather than re-spelling the literal statuses. If the
  existing comparison applies no status filter, apply none here either, and say
  so in the docstring.
* **Left-join, do not inner-join.** An inner join silently drops the orders that
  have no line items, which is exactly the population §2 has to be able to
  report. They must reach the aggregate as a distinct case.

### 2. Three outcomes, not two

The return value carries, for the range:

* `orders_compared` — orders in scope that have at least one line item.
* `orders_matching` — of those, the ones where header equals line-item sum to the
  penny.
* `orders_differing` — `orders_compared - orders_matching`.
* `orders_without_items` — orders in scope with **no** line items at all. Not a
  match and not a mismatch; the sum is undefined, not zero. This is the ~397 the
  two published denominators disagree by, and it is reported rather than assigned
  to whichever side makes the number look better.
* `residual_total` — the signed sum of `header − items` over `orders_differing`,
  as a 2-place decimal. **Signed**, because the sign is the finding: negative is
  the known discount-apportionment rounding, positive would be a missing term.
  An absolute-value sum would erase the distinction the tax and shipping verdicts
  depend on.

A ratio may be included, but the counts are what is authoritative and the ratio
is derived from them. Do not return the ratio alone.

### 3. The residual's shape, bucketed and bounded

Alongside the counts, return the distribution of the signed per-order residual:
a list of `{residual, orders}` pairs, ordered by `orders` descending, **capped at
the twenty largest buckets** with a count of how many distinct residual values
were omitted by the cap.

This is the part that carries the argument. A count of twelve thousand
disagreeing orders is not evidence about tax or shipping either way; twelve
thousand disagreements all at −0.09, −0.24, −0.49 is evidence of rounding, and
the same twelve thousand clustered at +3.95 and +4.95 would retire the two
Rarely verdicts in `specs/metorik-gap.md`. The cap is there because the bucket
count is unbounded in principle and this response is served over HTTP; the
omitted-count is there because a silently truncated tail reads as an absent one.

### 4. Surface it at `/manifest/status`, per period, as its own verdict

Extend the handler in `api/analytics/routes/manifest.py` that serves
`/manifest/status` so each period it already reports also carries the §2/§3 block
for that period's own date range, under a distinct key — `line_item_reconciliation`
or similar. It sits **beside** the existing source-versus-platform comparison and
does not merge into it, does not overwrite its verdict, and does not change its
shape. A consumer reading the existing fields must see exactly what it saw before.

Two constraints on this:

* **Bound the work by the period, and only the period.** The range comes from the
  manifest period the route is already iterating. Do not add an unbounded
  whole-table variant of this endpoint; a full-table sweep of 2.84M orders and
  4.49M line items is not something to hang off a status route, and the periods
  are the natural bound the route already has.
* **A failure here must not take the endpoint down.** If the line-item query
  errors, the period's existing manifest verdict must still be returned, with the
  new block reporting the failure rather than propagating it. The external
  comparison has been live and on the dashboard since before this existed and it
  does not become unavailable because an addition to the same response broke.

## The test

`contracts/deadly-digital-platform-api.yaml` requires exactly one new test file
and proves it bites: `new_test_bites.sh` runs it against the tree before the
change and the tree after, and a test that passes on both is refused. Create

    api/tests/analytics/test_fleet_line_item_residual.py

which is the only creatable shape the contract allows — `test_fleet_*.py` under
`api/tests/analytics`. Budget is 300 lines for it, separate from the 400 production
lines; `api/tests/analytics/test_reconciliation_manifest.py` is the neighbouring
suite to read for fixture conventions, and it must not be edited.

The test has to discriminate on the property §1–§3 asked for, not merely on the
function existing. Build a small fixture of orders whose arithmetic is known and
assert on all of it:

* an order whose line items sum exactly to its header → counted in
  `orders_matching`, contributes nothing to `residual_total`;
* an order whose line items exceed its header by 0.09 → counted in
  `orders_differing`, contributes **−0.09**, and appears in the buckets at −0.09.
  Assert the sign. A test that asserts `abs(residual) == 0.09` passes against a
  wrong implementation and is the specific failure §2 exists to prevent;
* an order whose header exceeds its line items → contributes a **positive**
  residual, so the two signs cannot cancel unnoticed;
* an order with **no line items** → `orders_without_items == 1`, and it is absent
  from both `orders_matching` and `orders_differing`. This is the assertion an
  inner join fails;
* a header/items pair differing only in the third decimal place → counted as
  matching, proving the penny rounding in §1 rather than a float compare.

## What this does not do, stated so nobody reads it as doing it

**It does not explain the residual.** It reports it. Whether the negative pennies
are discount apportionment in the connector's payload builder, in WooCommerce
itself, or in DD's writer is a question this cannot answer, because all it sees
is the two numbers after they arrived. `docs/CONNECTOR-V3-SPEC.md:185` states the
identity the payload is supposed to satisfy — `total == subtotal + tax + shipping
- discount` — and `specs/empty-columns.md` already established that this store's
line items arrive *already net of discount*, so the shipped identity is
`total = items_total`. Finding out which layer drops the penny needs the
connector, and this task deliberately does not reach for it.

**It does not change any verdict in `specs/metorik-gap.md`.** It makes the
evidence under two of them re-measurable. Whether the tax and shipping rows stay
where they are is a judgement someone makes after reading the first real output,
and if the bucket distribution comes back the shape `specs/empty-columns.md`
found, the right outcome is that nothing changes and the rows are now standing on
something checkable.

**It does not touch `orders` or `order_items` themselves**, adds no column, and
needs no migration. `api/analytics/migrations/**` is protected under this
contract and nothing here wants it. If the query turns out to need an index on
`order_items.order_id` to run inside the route's budget, that is a separate,
measured proposal with a timing in it — not something to slip into this diff.

**It does not correct `api/analytics/services/order_query.py`.** That file
computes `implied_unit_price` as `total / quantity` because `order_items.price`
is null on all 4,488,746 rows (`research/gap-list-open-questions.md:129-145`).
It is a real and adjacent problem. It is not this one, and widening into it would
put the diff past what a reader can check.
