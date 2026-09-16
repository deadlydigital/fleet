# Draft spec — split orders and revenue by new versus returning customer

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Split orders and revenue by new versus returning customer everywhere the customer counts already appear
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/customers.py
  - api/analytics/routes/dashboard.py
  - api/analytics/routes/revenue.py
```

## Read this before the requirements: you have no shell

The agent that builds this gets `Read`, `Edit`, `Write`, `Grep` and `Glob`, and
nothing else — `contracts/deadly-digital-platform-api.yaml` declares no
`agent_tools`, so `runner.yaml`'s default applies. **No database, no
interpreter, no network.**

So nothing below asks you to measure anything. Every figure quoted in this
document is a **given**, taken from
`research/metorik-report-classification-2026-09-15.md` and from
`research/candidates-metorik-gap-2026-09-16.md`, and it is to be cited as a
stated fact rather than re-derived. Requirement 4 is designed the way it is
specifically because the one number that would settle it has never been taken
and you cannot take it.

`specs/lateral-acquiring-order-in-three-call-sites.md` is the worked example of
this shape, and it exists because task 102 numbered two requirements that needed
production measurements, the agent correctly refused to claim figures it could
not take, and the gate refused the branch with every code check green.

## What I read, and what I did not

This draft was written from the fleet tree and from the path listing the runner
generated for the run. **I did not read the Deadly Digital source**, so there
are no line numbers below and no quoted code. Where this spec describes the
shape of the acquiring-order lookup it is quoting
`specs/acquired-order-lookup-per-customer.md` and
`specs/lateral-acquiring-order-in-three-call-sites.md`, which describe that
lookup clause by clause. Requirement 1 exists because those documents describe
the lookup and not the classification, and the build must establish the rest by
reading the file.

## What is missing

`research/metorik-report-classification-2026-09-15.md` §"Daily — Orders (3 of
10)" classifies **New vs returning customer orders** as bucket **A** —
buildable from what is already synced — on the grounds that `orders.customer_id`
is populated across 157,311 distinct customers and the first-order date is
derivable from `orders` alone.

DD answers the customer question and never the order question.
`customer_report()` returns `new_customers` and `returning_customers` as counts
of **distinct customers**, and `dashboard_overview()` and `revenue_report()`
carry the same two figures per period. Nobody can ask how many *orders* and how
much *revenue* came from each group, and that is the figure that separates
growth by acquisition from growth by repeat buying. A month where new customers
hold flat and returning-customer orders double looks identical, in what DD
prints today, to a flat month.

`research/candidates-metorik-gap-2026-09-16.md` filed this against
`dd-feature-parity` rather than `dd-trustworthy`, and argued the distinction:
the customer counts DD prints today are correct, so this adds a cut that does
not exist rather than repairing one that is wrong. That framing holds and this
spec keeps it — **no figure DD prints today may move.**

## Why this is a code change and not an investigation

The classification already exists per order and only the aggregate over it is
missing. `specs/acquired-order-lookup-per-customer.md` §2 states what the
acquiring-order lookup returns: for each customer active in the window, the
`created_at` of their earliest revenue-status order over all time, history
unbounded, `status IN ('completed','processing')`, tiebreak `created_at, id`.
That lookup is already joined to the window's order rows in the statement that
computes `orders_rev`, `revenue` and `aov`. Every order row in that join already
carries, beside it, the date its customer was acquired.

There is no new column, no migration, and nothing to find out. There is an
aggregate to add over rows a query is already scanning.

## Why this contract

`contracts/deadly-digital-platform-api.yaml` makes the analytics services and
routes writable, caps the diff at 400 production lines, admits one new test
under `api/tests/analytics/test_fleet_*.py` that must fail against the tree
before the change, and runs `tests/unit` and `tests/analytics` per file.

`contracts/dd-order-filters.yaml` is the other `dd_api` contract and it is not
eligible: its writable set is `api/analytics/routes/orders.py` and
`api/analytics/services/order_query.py`, neither of which is where the period
aggregates live. It also permits no new test file, and the classification rule
in requirement 3 is exactly the kind of boundary that needs one.

`contracts/dd-analytics-frontend.yaml` covers the stat cards the candidate also
asked for. Those are a separate task — see "What this task does NOT include".

## Requirements

### 1. Find every site that produces the two customer figures, and list them in a comment

Before changing anything, `Grep` `api/analytics/services/analytics_engine.py`
for `new_customers` and `returning_customers` and find every function that
produces them. Record the list — function name per site — in a comment above the
first aggregate you add, so the next reader can tell whether a site was
considered and rejected or simply missed.

`research/candidates-metorik-gap-2026-09-16.md` names three: `_query_period_stats`
(reached by `dashboard_overview()`), `revenue_report()` and `customer_report()`.
`specs/lateral-acquiring-order-in-three-call-sites.md` independently counts
acquiring-order lookups in `revenue_report()`, `revenue_summary()` and
`customer_report()` beside the one in `_query_period_stats`. Those two counts are
close and not identical. **The file is the authority over both of them.**

**Every site that emits the customer counts gets the order and revenue split.**
A response carrying `new_customers` without `new_orders` beside it is the
inconsistency this task exists to remove, and shipping the split on one endpoint
and not its neighbour makes the product harder to read rather than easier.

If a site emits the customer counts but has no order-level rows in the same
statement to aggregate over, say so in that comment and leave it — do not add a
second scan of `orders` to reach it.

### 2. Four aggregates, computed, not derived

At each site from requirement 1, add to the existing outer aggregate:

- `new_orders` — count of window orders that are their customer's acquiring order
- `returning_orders` — count of window orders that are not
- `new_revenue` — sum of `total` over the `new_orders` population
- `returning_revenue` — sum of `total` over the `returning_orders` population

All four are `FILTER` aggregates over rows the statement already scans, in the
same `SELECT` that produces `orders_rev` and `revenue`. **Compute all four.** Do
not compute two and derive the others by subtracting from `orders_rev` and
`revenue`: subtraction silently absorbs whatever requirement 4 covers into
whichever bucket is derived, and hides it there.

The measure is `orders.total`, the same column `revenue` sums, over the same
`status IN ('completed','processing')` population. `new_revenue` and
`returning_revenue` are gross, matching `revenue`.

### 3. An order is classified by identity, not by timestamp

An order is a new-customer order **iff it is the acquiring order itself** —
matched by primary key, `orders.id` against the acquiring order's id.

This is the requirement most likely to be got wrong, and the wrong version looks
right. `specs/acquired-order-lookup-per-customer.md` §2 gives the lookup's
tiebreak as `created_at, id` precisely because two orders can share an instant.
A branch that classifies by comparing the order's `created_at` to the acquiring
order's `created_at` marks **both** of those orders as new, so `new_orders`
exceeds the number of customers acquired and the two buckets stop partitioning
the rows.

The lookup as specified returns `created_at`. Extending it to carry the acquiring
order's `id` as well is part of this task, in whichever form you find it —
`DISTINCT ON` or the `LATERAL … LIMIT 1` of
`specs/lateral-acquiring-order-in-three-call-sites.md`. It is one more column out
of a subquery that is already selecting that row, and it must not change which
row the lookup picks: same `ORDER BY`, same `LIMIT`, same filter.

### 4. The buckets partition the rows exhaustively, by construction

An order with no `customer_id` has no acquiring order and is neither new nor
returning. **Nothing in the evidence says whether such rows exist.**
`research/metorik-report-classification-2026-09-15.md` records 157,311 distinct
`customer_id` values, which is a count of distinct values and not a claim that
the column is never null, and no measurement of its nullability has ever been
taken. You cannot take one.

So do not write a query whose correctness depends on the answer. Add, beside the
four:

- `unattributed_orders` — count of window revenue-status orders for which the
  acquiring-order lookup produced no row
- `unattributed_revenue` — sum of `total` over those same rows

Then the three buckets sum to `orders_rev` and to `revenue` **by construction**,
whatever the nullability turns out to be, and a reader can see the residual
instead of assuming two numbers add up to a third. If the column is in fact
never null, both keys read zero on every response and cost nothing.

Do **not** fold unattributed rows into `returning_orders`. A customer-less order
is not a repeat purchase, and that is the version of this that would be wrong
and invisible.

### 5. Free entries are in, both halves, and no AOV is emitted from these figures

`research/metorik-report-classification-2026-09-15.md` §"Correction (16
September 2026), third entry" establishes as fact, stated by Eamonn, that the
66,764 zero-total orders are HIB's legally required free-entry route into a prize
competition. 66,676 of them carry status `completed`, so they are already inside
the revenue-status population these aggregates run over, and 15,616 distinct
customers have placed one. The correction is explicit that free entries are real
orders placed by real customers and belong in every order count; what they do
not belong in, unlabelled, is an average or a distribution of `orders.total`.

Applied here:

- **Free entries stay in `new_orders` and `returning_orders`.** They are orders.
- **Free entries stay in `new_revenue` and `returning_revenue`.** They add £0 to
  a sum, which is the truth about them, and excluding them would stop the two
  revenue figures reconciling with `revenue`.
- **Emit no AOV derived from these figures, on any endpoint, under any key.** A
  free entry can be a customer's *acquiring* order, which books an acquisition at
  £0, so `new_revenue / new_orders` is diluted in a way specific to the new
  bucket and different from the dilution the existing `aov` already carries. A
  per-bucket AOV is a real report and it needs the free-entry question decided
  first; it is not this task.

Say in a comment beside the aggregates that this ruling was read and applied. A
branch that ships a `new_aov` key has not read it.

### 6. Nothing else in these statements moves

`orders_all`, `orders_rev`, `revenue`, `customers_all`, `customers_rev`,
`new_customers`, `returning_customers`, `aov`, `refunded_amount`,
`orders_with_refund`, `net_revenue`, the granularity bucketing, the coupon block
and the payment-method breakdown are all computed in the same statements and
none of them changes — not its expression, not its filter, not its name.

This task adds columns to an aggregate and one column to a lookup's projection.
It is not a rewrite of any function it touches.

### 7. The new figures reach the HTTP body

Whatever `api/analytics/routes/customers.py`, `api/analytics/routes/dashboard.py`
and `api/analytics/routes/revenue.py` do with the engine's dicts, the six keys
must arrive in the response beside the customer counts they belong with, under
the same names at every endpoint. If a route declares a response model, it gains
the six fields; if it passes the dict through untouched, it does not change and
a comment in the engine says which routes were checked and found to need nothing.

These three routes are declared writable for that reason and no other. Nothing
else about them moves.

### 8. Do not restrict, rewrite or de-duplicate the acquiring-order lookup

`specs/lateral-acquiring-order-in-three-call-sites.md` is separate, queued work
over the same lookups: it bounds them to the window's customers and converts
them to `LATERAL … LIMIT 1`, and it carries its own measurements and its own
production identity proof.

**This task changes which columns come out of those lookups and nothing else.**
Do not bound them, do not convert them, do not factor the copies into a shared
helper, and do not add an index —
`api/analytics/migrations/versions/v0014_orders_customer_created_index.py` is
already the index this read wants, and everything under the migrations tree is
protected by this contract in any case.

Whichever of the two branches lands second rebases onto the first. Keeping them
separate is what lets either be reverted on its own.

### 9. One new test, and it fails against the tree before the change

Create **one** file,
`api/tests/analytics/test_fleet_new_vs_returning_orders.py`. This contract's
`creatable_paths` admits `api/tests/analytics/test_fleet_*.py` and nothing else;
every existing file under the `api/tests` tree is protected and none may be
edited.

The test must **bite** — `new_test_bites.sh` runs it against the tree before the
change and requires it to fail there, so it must turn on the new keys' values
and not merely on their presence.

Build one tenant fixture that discriminates the ways this can go wrong:

- a customer whose first-ever order predates the window and who orders again
  inside it — their in-window order is **returning**, and a classification that
  dates acquisition from the first order *in the window* calls it new;
- a customer acquired inside the window who orders twice more inside it — one
  new order, two returning, one new customer;
- **two orders for the same customer at the same `created_at`** — requirement
  3's case: exactly one of them is new;
- a zero-total order that is a customer's acquiring order — requirement 5's
  case: it counts in `new_orders` and adds £0 to `new_revenue`;
- an order with no `customer_id` — requirement 4's case: it lands in
  `unattributed_orders` and in neither of the other two buckets;
- and on every window the fixture exercises, `new_orders + returning_orders +
  unattributed_orders == orders_rev`, with the same identity for the three
  revenue figures against `revenue`.

`api/tests/analytics/test_fleet_acquired_per_customer.py` is how task 100 made
an equivalent property of this lookup observable; reuse that approach rather than
reinventing one.

## What this task does NOT include, and that is the point of this section

**The production identity proof is not yours and must not be attempted.** You
have no database. Requirement 6 is discharged for review by a person running
each touched endpoint against the tree before and after, on a real tenant schema,
for at least one 30-day window and one spanning a period boundary, and comparing
row for row. That is a step in the review of this branch, it is deliberately not
a numbered requirement, and a branch claiming to have done it has claimed
something it could not do.

Also out:

- **The stat cards.** The candidate asked for two, and they are a `dd_frontend`
  task under `contracts/dd-analytics-frontend.yaml` against
  `platform/app/(dashboard)/analytics/customers/page.tsx` — a different contract,
  a different writable set and a different suite.
  `drafts/net-revenue-on-the-analytics-overview.md` is the precedent for the
  split: the API half shipped first, and the page ignored the new keys until a
  second task read them. Queue the frontend task after this one merges, and
  expect it to find that `platform/app/api/analytics/customers/route.ts` and
  `platform/app/api/analytics/dashboard/route.ts` already forward the body
  untouched.
- **Per-bucket AOV, and the free-entry split generally.** See requirement 5.
  `research/metorik-report-classification-2026-09-15.md` marks the average and
  distribution rows **MUST SPLIT FREE ENTRIES**, and that decision belongs to
  whichever task builds them.
- **Net revenue per bucket.** `net_revenue` and `refunded_amount` sit in the same
  aggregate and could be filtered the same way. HIB has 4 non-zero refunds in
  2,890,319 orders, so a per-bucket net figure would differ from the gross one on
  almost no row, and it is not worth the width.
- **New vs returning customer KPIs**, the Monthly — Retention row.
  `research/candidates-metorik-gap-2026-09-16.md` dropped it from the batch for
  the ceiling. It is a related and larger report and this task does not start it.
- **Performance.** Six `FILTER` aggregates over rows already being scanned should
  not change the plan, and nothing here is to be tuned against that expectation.
  See requirement 8.

## How this will be checked

`contracts/deadly-digital-platform-api.yaml` runs, in order: the
requirement-citation check, `compileall` on the changed Python, ruff with no new
findings, `tests/unit` per file, `new_test_bites.sh`, then `tests/analytics` per
file. **Cite the numbered requirements above in the diff** — the first check
reads this spec and reports requirements cited nowhere, and it is the only check
that reads it at all.

`api/CLAUDE.md` forbids suite and directory pytest runs on this host; the
per-file runner exists for that reason and is what the contract calls.

## Objectives

`dd-feature-parity`. One bucket-**A** Metorik row, classified and unbuilt, whose
data is already sitting in the join.
