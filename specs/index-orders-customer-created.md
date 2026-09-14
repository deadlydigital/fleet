# Index: the first revenue-status order per customer

Add one index migration under `api/analytics/migrations/versions/`. Nothing
else. `contracts/dd-index-migration.yaml` is the contract and
`contracts/checks/index_migration_only.py` is what it is judged by — read both
before writing, because they refuse more than they permit.

## What this is for, and what it is NOT expected to achieve on its own

`_query_period_stats` in `api/analytics/services/analytics_engine.py` builds an
`acquired` CTE — the earliest revenue-status order of every customer active in
the window. Measured 14 Sep 2026 on `analytics_2` (2,887,010 orders):

    Seq Scan on orders          2,887,010 rows, to remove 2,063 (0.07%)
    Hash Join                   -> 1,724,169 rows
    Sort (external merge 50MB)  -> to produce 21,280 rows

**Read `specs/neither-half-works-alone.md` before you start.** This index does
**not**, by itself, change that plan — measured, with `hypopg`, twice. It
becomes useful only once the query is also rewritten to ask per customer, which
is a separate task under a different contract and is deliberately not in scope
here. Do not rewrite the query. Do not touch `analytics_engine.py`; the
contract protects it.

So the success condition for this task is not "the dashboard is faster". It is
"the index exists, is correct, and is built in a way that does not take the
site down".

## Requirements

**1. One new migration file**, named for the next free version number under
`api/analytics/migrations/versions/`. Do not edit an existing migration:
applied migrations are history, and the check refuses it.

**2. One `CreateIndexStep`**, on `orders`, over `customer_id, created_at, id`
in that order. The column order is the `DISTINCT ON (customer_id) ... ORDER BY
customer_id, created_at, id` it exists to serve; any other order does not serve
it. Name the index `ix_analytics_orders_customer_created`.

**3. `transactional=False`.** `CREATE INDEX CONCURRENTLY` cannot run inside a
transaction block, and `migration.py` is explicit that a migration is
transactional or it is not, never mixed. `v0003_orders_utm_campaign_index.py`
is the shipped precedent — read it.

**4. No other step type.** `SQLStep` and `DataStep` are refused by the check,
by type. If you find yourself wanting one, the answer is that this task is the
wrong shape for what you are trying to do — say so in your reply rather than
working around it.

**5. `unique` stays false.** A unique index is a constraint: it can fail on
existing data and reject future inserts. That is a change to what the system
accepts, not to how fast it answers.

**6. A note on the `Migration` recording what it will cost to build.** Two
tenant schemas hold this table — `analytics_1` with 679,917 orders and
`analytics_2` with 2,887,844 — and the planner estimates 112 MB per schema. The
build time was **unmeasured** when this was written and is now known: **1s on
`analytics_1`, 5s on `analytics_2`** (applied 14 Sep 2026). The size estimate
was exact — **112 MB on `analytics_2`, 26 MB on `analytics_1`**. `v0003` gives
`analytics_12` its own window for an 802,396-row build; at five seconds this
one did not need one, which is worth knowing rather than inheriting the
caution.

## What the migration system gives you, so do not rebuild it

`CreateIndexStep` already renders `CONCURRENTLY` on a live schema, emits
`IF NOT EXISTS`, drops an invalid leftover from a failed concurrent build, and
carries a predicate requiring `indisvalid`. You do not write any of that. The
predicate is what lets one migration meet tenant schemas at different states —
`migration.py`'s own header records `analytics_12` sitting half through a
change, which is why per-step predicates exist at all.

## The index is NOT partial, and that is three things at once

**It carries no `WHERE status IN ('completed','processing')`.** An earlier
recommendation did, with a stated reason: the predicate would satisfy the
status filter inside the index and remove the sequential scan. That reason
belonged to the query as it stands, and the query is being rewritten.

**Why it would be marginal rather than structural under the rewrite.** In the
original shape the predicate was the point — it was what stopped Postgres
reading all 2,887,010 rows to discard 2,063. Under `LATERAL ... LIMIT 1` the
scan is already bounded to one customer's entries, so the predicate would only
save reading `status` from the heap to check it. **2,884,947 of 2,887,010 rows
are revenue-status**, so the first entry passes almost always: roughly 21,500
heap fetches across the window, against a structural change to the plan before.

**And `CreateIndexStep` cannot express one regardless.** Its fields are
`table`, `index`, `columns`, `unique`, `requires_autocommit`, and
`_create_sql` renders `CREATE [UNIQUE] INDEX [CONCURRENTLY] IF NOT EXISTS ...
ON schema.table (columns)` — there is no `WHERE` in it anywhere. (The
`predicate` set in `__post_init__` is `IndexValid`, the step's applicability
test, not a SQL predicate; it is easy to misread as support.) A partial index
would need `SQLStep`, which `index_migration_only.py` refuses by type — so it
would need `migration.py` opened first, which this contract protects
deliberately.

**So do not add one, and if a later measurement says it is wanted, that is a
decision needing `migration.py` changed before any task can write it.** The
honest order is: build this, land the rewrite, then measure whether those heap
fetches show up at all.

## What no check verifies, and a reviewer must

**The column order.** `index_migration_only.py` proves the step is a
`CreateIndexStep` and nothing else; it does not read the columns. The order
`(customer_id, created_at, id)` is the entire reason this index exists — it is
what lets the `DISTINCT ON (customer_id) ... ORDER BY customer_id, created_at,
id` be read from the index rather than sorted — and an index on the same three
columns in any other order is a 112 MB no-op.

This contract does not carry `spec_requirements_cited.py`; see the argument in
`contracts/dd-index-migration.yaml`. It does not auto-merge, and this is the
thing the person accepting it is accepting.

## What you cannot check from here, and must not claim

Whether Postgres will use the index. It will not, for the query as it stands —
that is the point of the spec named above. Do not write a rationale claiming a
speed-up; the honest claim is that the index is a precondition for one.

## Objectives

`dd-trustworthy`. This is correctness-of-service work: a page that takes 21.3s
is one a merchant stops opening.
