# Draft spec — orders and revenue grouped by currency, with no number summed across two of them

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Group the revenue window's orders and money by orders.currency, keeping the per-currency count the engine computes today and discards, and carrying no total across currencies
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/revenue.py
```

## Everything below is GIVEN. The build agent measures nothing

The agent that builds this has no shell, no database and no network. Every figure
here was taken from documents in the fleet repository and is cited where it is
used. **No numbered requirement asks anybody to re-derive any of it.**

| Figure | Value | Source |
|---|---|---|
| `orders.currency` populated | 2,889,850 of 2,889,850 | `research/metorik-report-classification-2026-09-15.md:24` |
| Distinct currency codes | **never counted** | `research/candidates-metorik-gap-2026-09-21.md:850` |
| Status vocabulary | completed 2,887,414; cancelled 1,971; processing 241; on-hold 203; pending 20; refunded 1 | same classification, `:32` |
| `refund_total` non-zero | 4 of 2,889,850 | same, `:31` |
| `revenue_summary()` | `api/analytics/services/analytics_engine.py:928`, returned as `summary` | `drafts/coupon-performance-on-the-revenue-summary.md:64` |
| `ltv_distribution()`'s `GROUP BY o.currency` | `api/analytics/services/analytics_engine.py:3635`, keeps the codes, drops the count | `research/candidates-metorik-gap-2026-09-21.md:126` |
| `payment_method_breakdown()` returned as a top-level key beside `data` and `summary`, taking no new parameter | shipped 14 Sep 2026 | `drafts/render-the-payment-method-breakdown-on-the-revenue-page.md:37` |
| Budget for a grouped scan of this window | the comparable unbounded summary aggregate is a 601ms parallel seq scan | `specs/order-list-filters.md:97` |

The candidate is `research/candidates-metorik-gap-2026-09-21.md:770`, at
`verified_sha` `fd5a404`, citing section *Rarely — Order groups (2 of 6)* of
`research/metorik-report-classification-2026-09-15.md` at sha `80677a2`, where
the row is classified **A** with the note that the report "may well return one
row".

## Two documents in this repository disagree about whether the answer is known

`specs/metorik-gap.md:149` states, under *Never*, that **all 2,844,177 production
orders are GBP**. `research/candidates-metorik-gap-2026-09-21.md:850` states that
the distinct codes have **never been counted** — not by the evidence pack, not by
the 16 September readings. Both are in the tree today.

The second is the one that holds up. `research/EVIDENCE-metorik.md` contains no
currency reading at all, and neither does `research/metorik-gap-2026-08-30.md`;
the 15 September readings list `currency` among the **populated** columns and
stop there. So "all GBP" is an assertion with no reading behind it that three
later candidate batches have repeated from each other
(`research/candidates-metorik-gap-2026-09-11.md:197`,
`research/candidates-metorik-gap-2026-09-13.md:225`,
`research/candidates-metorik-gap-2026-09-14.md:349`), each citing the one before.

**This spec does not settle it and does not need to.** It is the reason the
design below refuses a single-currency assumption anywhere: every shape is
correct with one row and correct with five, and the deployed endpoint is what
answers the question. If the answer is one row, the store has its evidence and
the response says so in a boolean two other blocks already carry.

## What the approver should weigh, because the candidate says it first

The candidate calls this **the weakest of its batch's nine** and says the honest
alternative out loud: an approver who wants the finding without the feature
should reject this and read `currencies_present` off the LTV endpoint instead
(`research/candidates-metorik-gap-2026-09-21.md:786`). That remains the right
read. What this spec adds to the choice is the part that read does not give:
`currencies_present` is a list of codes over the **lifetime** population of
`ltv_distribution()`, unscoped to any window, with no count and no money beside
it — so it can tell you that a second code exists and cannot tell you when, how
often, or for how much.

## Why this is a code change and not an investigation

Nothing has to be found out first. The column is populated on every row, the
grouping expression is already written once in this very module, and the two
blocks that would have to agree with the new one are deployed and tested. There
is no new column, no new table and no migration:
`api/analytics/migrations/**` is protected under
`contracts/deadly-digital-platform-api.yaml` and nothing here wants it.

## Why the revenue endpoint, and not the two paths the candidate suggested

The candidate's `suggested_paths` are advisory and none of the three is taken.

**Not `api/analytics/routes/orders.py`.** The title says *orders and revenue*,
and the money half is what decides the location. Three statements about currency
would then exist on two endpoints over two populations:
`revenue_summary()` and `payment_method_breakdown()` each carry a `currency` and
a `mixed_currency` computed over the revenue window
(`research/candidates-metorik-gap-2026-09-21.md:125`), and a third computed over
the order-list population in `api/analytics/services/order_query.py` would be
free to disagree with both, in a response neither of them appears in. Currency
is exactly the dimension where two disagreeing answers are indistinguishable
from one correct one: both are short code lists that look right.

**Not `platform/app/(dashboard)/analytics/orders/page.tsx`.** `platform/**` is
protected under this contract. See *Not in scope*.

**So: `api/analytics/services/analytics_engine.py` and
`api/analytics/routes/revenue.py`.** The engine module owns the window
aggregates, the revenue route already assembles them into one response, and the
new block lands beside the two it has to agree with — where a test can assert
that it does.

## Why this contract

`contracts/deadly-digital-platform-api.yaml`, work_type `dd_api`. Both declared
paths are in its enumerated writable set and neither is protected by it.

The contract that would have been tempting is
`contracts/dd-order-filters.yaml` — same work_type, same repo, and it covers
`api/analytics/routes/orders.py` exactly. Putting this report on the order list
would have brought it into range, and it is refused on its own terms as well as
on the placement argument above: it declares **no `creatable_paths`**, so no
test could be added at all; its checks are `compileall`, `ruff_no_new_findings.py`
and an acceptance check written for the order-filters task, which knows nothing
about this report and would pass whatever the diff did; and `max_diff_lines` is
150 across production and test together.

The defect this change is most likely to ship is a wrong answer, not an
exception. A `GROUP BY` that silently drops a row, a total summed across two
currencies, and a `mixed_currency` that contradicts the one on the same response
all compile, lint, and pass every test in the tree today. The chosen contract
runs `tests/unit` and `tests/analytics` per file and requires one added test
proven by `contracts/checks/new_test_bites.sh` to fail against the tree without
this change. That is the whole of the difference and it is the reason for the
choice.

## Citing the requirements

`contracts/checks/spec_requirements_cited.py` runs first under this contract and
reads only lines the diff adds. Put `# spec:N` on a line this change adds — the
grouped expression, a docstring line naming a key, a test name — for each of 1
through 6. Six requirements, against a `max_requirements` of 10.

---

### 1. One grouped statement in `api/analytics/services/analytics_engine.py`

Add `currency_breakdown(db, tenant_id, start_date, end_date)` beside
`payment_method_breakdown()`, taking the same arguments in the same order and
built the same way.

* **One statement.** A single `GROUP BY` over `orders` for the window. Not a
  query per currency, and not rows fetched and bucketed in Python: the unbounded
  window is the whole table.
* **No join.** Nothing here reads `order_items`, `customers` or
  `product_categories`. A join added for any reason fans the order rows out and
  every count below becomes a count of lines.
* **The window and the revenue-status set come from `payment_method_breakdown()`,
  read in the file and reused rather than re-spelled.** This report's numbers are
  compared against that block's on the same response; two definitions of "revenue
  status" would make the comparison meaningless while both blocks looked right.
* **The two absent-shapes are the ones already there.** Return a bare `{}` when
  the tenant has no analytics schema, and `{}` again when the aggregate comes
  back empty — the two cases
  `drafts/render-the-payment-method-breakdown-on-the-revenue-page.md:85` records
  `payment_method_breakdown()` returning today. A consumer that already handles
  one block's absence then handles both.

**`ltv_distribution()` is not touched, and this is the requirement that says so.**
The candidate's framing is that the engine "already runs a real `GROUP BY` over
`orders.currency` and throws the count away", and that is true of
`api/analytics/services/analytics_engine.py:3635` — but that grouping runs over
the **lifetime** customer population with no window bound, so keeping its count
would put a second per-currency number in the product that legitimately
disagrees with this one for every window shorter than all time. The expression
there is a template, not a call site to widen. `currencies_present` keeps its
current shape and the LTV response does not change.

### 2. The rows, and the invariant that proves none was dropped

`currency_breakdown()` returns `currencies`: a list, one entry per code the
window contains, each carrying

* `currency` — the code as stored, uppercased for grouping so `gbp` and `GBP`
  are one row rather than two;
* `orders_all_statuses` and `orders_revenue_statuses` — both, never one. On this
  tenant they will differ by about 0.08% (`:32` of the classification: 2,436
  non-completed orders out of 2,889,850), and that near-equality is a fact about
  today's data, not a reason to report a single count that later silently means
  either;
* `revenue` and `refunded_amount` — over the revenue-status orders of **that
  currency only**. `refund_total` is non-zero on 4 rows in the whole table, so
  this will be zero nearly everywhere; it is carried because the block beside it
  carries it and a reader comparing the two should not have to wonder;
* `aov` — `revenue / orders_revenue_statuses` **within the row**, `None` when
  that count is zero.

**Rows whose currency is NULL or empty are reported, not dropped.** They appear
as a single entry with `currency: null`, flagged as such. The reading says the
column is populated on every row of `analytics_2`, so this entry is expected to
be absent — and a `GROUP BY` that drops them is indistinguishable from data that
has none, which is precisely the defect
`drafts/revenue-by-payment-method.md` spent a requirement on for a column that
was 97.83% populated.

**The invariant.** The sum of `orders_all_statuses` across every entry equals the
window's all-status order count, and the sum of `orders_revenue_statuses` equals
the revenue-status count the same window reports elsewhere on this response.
That is one assertion a consumer can make, it is requirement 6's first test, and
it is what makes the NULL entry above checkable rather than decorative.

**Ordered by `orders_all_statuses` descending, then `currency` ascending.** Not
by revenue: see requirement 3. The tiebreak is there because a one-row report and
a five-row report should both be stable across calls.

### 3. No arithmetic across two currencies, anywhere in the response

This is the requirement the report exists to get right, and the one a reader
should check against the diff.

* **No grand total.** No `total_revenue`, no `total_refunded`, no overall `aov`,
  no share-of-revenue percentage. Adding 100 GBP to 100 USD produces 200 of
  nothing, and a percentage is that addition in the denominator.
* **No conversion, and no rate.** There is no FX source in this repository and
  this change does not introduce one. `specs/metorik-gap.md:149` files
  multi-currency conversion under *Never* for this quarter's tenants and that
  stands.
* **Counts may be totalled, money may not.** An order is an order whatever it was
  paid in, which is why requirement 2's invariant is over counts and why the
  ordering is too.
* **The docstring says all of this in the function**, because the next person to
  add a field here will be adding it to a response that has no total and will
  wonder why.

### 4. `mixed_currency` and `distinct_currencies`, agreeing with what already ships

The block carries `distinct_currencies` — the number of entries, excluding the
NULL entry of requirement 2 — and `mixed_currency`, true when the window holds
more than one code.

**`mixed_currency` is not defined a second time.** `revenue_summary()` and
`payment_method_breakdown()` each already compute one
(`research/candidates-metorik-gap-2026-09-21.md:125`). Read how, in
`api/analytics/services/analytics_engine.py`, and derive this one the same way
from this grouping — or call whatever already produces it. Two booleans on one
JSON response that can disagree is worse than one of them being absent, and this
report is the first thing in the product with the row-level detail to show which
of them was wrong.

### 5. `api/analytics/routes/revenue.py` returns it, with no new parameter

* **A top-level key `currencies`, beside `data`, `summary` and
  `payment_methods`**, computed from the same `start_date` and `end_date` the
  route already resolved. Additive: no existing key changes shape, and
  `summary.currency` keeps the meaning it has today.
* **No new query parameter and no ceiling.** `payment_method_breakdown()` takes a
  `method_limit`; this takes nothing equivalent. A currency code is a
  three-letter value bounded by the gateways a store has enabled, and a truncated
  currency table could omit the one code whose existence is the entire finding.
* **One more grouped scan on this endpoint, and that is the cost.** It is the
  same shape as the grouping already on this route — the unbounded summary
  aggregate is a 601ms parallel seq scan (`specs/order-list-filters.md:97`) and a
  hash aggregate over a three-character column is that scan with a low-cardinality
  grouping on top. Requirement 1's "one statement, no join" is what keeps it
  there.
* **The docstring states what the JSON means**: that money is per currency and
  unconverted, that no key totals across currencies and why, that
  `orders_all_statuses` covers every status while `revenue` covers the
  revenue-status set, and that a `currency: null` entry means orders with no code
  rather than an error. The frontend is protected under this contract and whoever
  drafts the page will read this docstring and nothing else.
* **No reformatting.** `api/analytics/routes/revenue.py` carries a pre-existing
  ruff I001 that the ratchet tolerates
  (`drafts/coupon-performance-on-the-revenue-summary.md:266`); tidying it is diff
  with no gate asking for it.

### 6. One added test, and what it has to pin

Create `api/tests/analytics/test_fleet_currency_breakdown.py` — the only shape
this contract's `creatable_paths` permits. No existing test may be edited. It
must fail against the tree without this change;
`contracts/checks/new_test_bites.sh` runs it against both trees.

Over a fixture seeded with **two** currencies — which production may well not
have, and which is the only way to test the thing this report is for — assert:

* the reconciliation of requirement 2: summed `orders_all_statuses` equals the
  window's all-status count, and summed `orders_revenue_statuses` equals the
  revenue-status count. **This is the assertion a dropped row fails**, and it is
  why the fixture includes a cancelled order in one of the two currencies.
* `revenue` and `aov` for each row use only that row's orders. Seed the two
  currencies with amounts whose cross-sum is a recognisable wrong number, so a
  total that leaked across them is visible rather than plausible.
* **no key anywhere in the block totals money across currencies.** Assert on the
  block's keys, not only on its values: a later addition of a `total_revenue`
  should fail this test rather than pass it silently.
* `mixed_currency` is true for the two-currency window, false for a window
  narrowed to one of them, and **equal to the `mixed_currency` the same response
  already carries** for the same window. That is requirement 4 as an assertion
  rather than a promise, and it is the one that bites if the build agent writes a
  second definition.
* an order whose currency is NULL or empty appears as the `currency: null` entry
  and is inside the reconciliation, rather than vanishing from it.
* a window with no orders returns `{}`, and a tenant with no analytics schema
  returns `{}` — requirement 1's two absent-shapes.
* `GET /api/analytics/revenue` carries `currencies` beside `payment_methods`,
  and every pre-existing top-level key is still present and unchanged in shape.

`test_diff_target` under this contract is guidance, not a gate.

## Not in scope, stated so nobody reads it as included

**The page.** `platform/app/(dashboard)/analytics/revenue/page.tsx` is where this
becomes visible, and nothing in this diff can reach it: `platform/**` is
protected under `contracts/deadly-digital-platform-api.yaml`. This ships
computed, tested and invisible, exactly as the payment-method breakdown did —
and for the same concrete reason, quoted from
`drafts/render-the-payment-method-breakdown-on-the-revenue-page.md:53`, the page's
fetch handler rebuilds its state from two named keys and discards every other
top-level key on the response. The follow-up is a `dd_frontend` draft against
`contracts/dd-analytics-frontend.yaml` once this has merged; it is deliberately
not a second `fleet-spec` block here, because `console/autoqueue.py` writes the
whole document into every link's `tasks.spec_md` and
`contracts/checks/spec_requirements_cited.py` then obliges each link's diff to
cite every numbered requirement in it, so a two-block chain fails both links
after paying for both.

**A currency filter on the order list.** `api/analytics/routes/orders.py` and
`api/analytics/services/order_query.py` are untouched. A one-row report needs no
filter, and if the report comes back with more than one row, the filter is a
better-motivated follow-up than it is today.

**`ltv_distribution()`'s codes.** Requirement 1 states the refusal and the
reason; `api/analytics/routes/customers.py` is not in the writable set and does
not change.

**Multi-currency conversion, an FX rate source, and a base-currency total.** All
three are the *Never* row at `specs/metorik-gap.md:149`, and requirement 3 is the
statement that this change does not quietly start any of them.

## Before this is queued

`auto_merge` is `true` on this contract, so nobody reads a spec against a diff on
this path. The requirement most likely to ship **wrongly** is **3**: a grand
total is the most natural thing in the world to add to a table of money and it
will look like the block's headline figure. The requirement most likely to ship
**unbuilt** is **2**'s NULL entry, because on this tenant it is an entry that
never appears and a response without it looks complete. If one thing is read
against the diff, read the response keys against requirement 3.
