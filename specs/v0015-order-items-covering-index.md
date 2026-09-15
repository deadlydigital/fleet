# v0015 — the covering index on `order_items`, in the composite form

```fleet-spec
work_type: dd_index_migration
repo: deadly-digital-platform
contract: dd-index-migration.yaml
title: v0015 — ix_analytics_order_items_order_covering, as a plain composite index
writable_paths:
  - api/analytics/migrations/versions/v0015_order_items_order_covering_index.py
```

## Everything below is GIVEN. Do not attempt to measure anything

You have `Read, Grep, Glob, Write, Edit` and no shell, no database and no
network. Every figure here was measured on 15 Sep 2026 against `analytics_2`
with `hypopg` and is recorded in
`fleet:research/top-products-gate-a2-2026-09-15.md` beside the document that
designed the procedure, `fleet:research/top-products-index-pricing.md`. Cite
them as stated facts. Do not re-derive them and do not claim to have taken them.

**This task writes one migration file. That is all of it.**

## What was established, and what was not

`top_products` reads `order_items` joined to `orders` and is the largest single
statement on the dashboard at **619 ms** of a **1,666 ms** SQL budget. The
pricing document fixed three gates before any number was seen. Running its
procedure:

| gate | question | result |
|---|---|---|
| A | does `hypopg` model this planner? | **pass** — the bare `(order_id)` index that already exists and is already declined does not flip the plan hypothetically either |
| placebo | does it flip on an index that cannot serve the query? | **pass** — `(product_name)` does not flip it |
| A2 | did `hypopg` honour `INCLUDE` rather than parsing it away? | **pass** — 101 MB bare against 361 MB covering, 3.56× |
| B | does the covering hypothetical flip the plan? | **pass** — to `Index Only Scan` |
| C | is the real win ≥2× and ≥250 ms? | **NOT MEASURED** |

**Gate C is outstanding and this task does not close it.** It needs a real
execution time against a real index, which needs the index to exist. That is
why this migration is being written, and it is also why
`dd-index-migration.yaml` sets `auto_merge: false`: the branch stops for a
person, and the number that decides whether it ships is taken after it is
built and before it is deployed. **Do not write anything claiming the index is
worth it.** What is established is that the plan flips; what it is worth is not.

## The one decision the pricing document refused to make, now made

§9 of the document declines to choose between two forms and says exactly what
would decide it: *"add the composite as a second hypothetical and compare size
and plan. If they price the same, take the composite; it is the one a reviewer
can read."*

Both were priced on `analytics_2`:

| form | estimated size | plan |
|---|---|---|
| `(order_id) INCLUDE (wc_product_id, product_name, total, quantity)` | 378,363,904 bytes (361 MB) | `Index Only Scan` |
| `(order_id, wc_product_id, product_name, total, quantity)` | 378,363,904 bytes (361 MB) | `Index Only Scan` |

Identical, to the byte. So the rule resolves: **write the composite.**

The reason it matters is not size. `CreateIndexStep` renders `columns` straight
into `CREATE INDEX ... ON {schema}.{table} ({columns})`
(`api/analytics/migrations/migration.py:142`), so the `INCLUDE` form can only be
expressed by closing the parenthesis inside the string — a bracket-balancing
trick in the one field `contracts/checks/index_migration_only.py` does not
verify. `dd-index-migration.yaml` says in its own header that the column order
is verified by no check at all. Given two forms that price the same, the one a
reviewer can read is the one to write.

Note for honesty, and it does not change the decision: identical estimates mean
`hypopg` does not distinguish the two, not that the built indexes will be
byte-identical. The document expects the composite to have slightly larger
internal nodes. The tiebreak is readability and the rule was fixed in advance.

## Requirements

### 1. One new file, at the next free version

`api/analytics/migrations/versions/v0015_order_items_order_covering_index.py`.
`v0014_orders_customer_created_index.py` is the highest present, so 15 is next
and `version=15` in the `Migration`. This contract's `writable_paths` admits
that one path and nothing else.

### 2. The composite column list, and the index name

```python
CreateIndexStep(
    table="order_items",
    index="ix_analytics_order_items_order_covering",
    columns="order_id, wc_product_id, product_name, total, quantity",
)
```

The order is `order_id` first because that is what the join seeks on; the other
four follow so the scan is index-only. **No `INCLUDE`, and no closing
parenthesis inside the string.** The name follows
`ix_analytics_orders_customer_created` and `ix_analytics_order_items_order`:
`ix_analytics_` + table + what it is on.

### 3. `transactional=False`, because the build is concurrent

`CreateIndexStep` renders `CONCURRENTLY`, which cannot run inside a transaction
block, and `migration.py` refuses a migration that is half of each.
`v0014_orders_customer_created_index.py` and
`v0003_orders_utm_campaign_index.py` are the shipped precedents; follow them.

### 4. Not unique

`unique` stays false. A unique index is a constraint: it can fail mid-build
against existing data and reject inserts afterwards, which changes what the
system ACCEPTS — not something a migration whose whole purpose is a query plan
should do. Nothing about these five columns is known to be unique.

### 5. The docstring states what is established and what is not

Follow v0014's shape, which is the model: what it serves, why concurrently,
what it costs, and — the part that matters most here — **what is unknown**.
It must say, in its own words:

* that the plan flip is established by `hypopg` and the real win is not;
* that the build time is **unknown**, because a size estimate is not a
  duration and guessing one is worse than the gap — v0014 makes this argument
  and it applies unchanged;
* that this is a size estimate from the planner, not a measured index.

Cite `fleet:research/top-products-index-pricing.md` for the procedure and
`fleet:research/top-products-gate-a2-2026-09-15.md` for the readings.

### 6. The `note` carries the per-schema figures and a window for the larger one

Given, measured 15 Sep 2026:

| schema | `order_items` rows | estimated index size |
|---|---|---|
| `analytics_1` | 1,073,809 | 85 MB |
| `analytics_2` | 4,549,159 | 361 MB |

**Only these two schemas exist.** `discover_tenant_ids`
(`api/analytics/migrations/runner.py:144`) walks every schema matching
`^analytics_[0-9]+$` and exactly two match. The pricing document names
`analytics_12` as a third — it appears in the tree's history and is **not** a
schema in this database. Do not write it into the note.

`analytics_2` is 4.2× `analytics_1` and deserves its own window, the way v0014
gives one to it:

    python -m analytics.migrations apply --execute --only 2 --to 15

## What this task does NOT include

* **Gate C.** No execution time exists for this index and none is obtainable
  from here. §7 of the pricing document proposes two ways to get one and
  performs neither. Do not cite a speed-up.
* **Any change to `analytics_engine.py`.** The statement is already written to
  benefit from this index if the planner takes it. This is one file.
* **Registering the migration anywhere else.** If a chain file or tally needs
  the new version, say so in your reply rather than editing it — this
  contract's `writable_paths` is the one version file.

## How this will be checked

`dd-index-migration.yaml` runs `compileall`, `index_migration_only.py` — which
proves every step is a `CreateIndexStep` and nothing more — and `tests/unit`
per file. `auto_merge` is false: this stops for a person.

**It does NOT run `spec_requirements_cited.py`**, and that is a recorded
argument rather than an oversight — task 98 failed on it with exit 2 because
its requirements used a form the parser deliberately does not read. So nothing
enforces the `spec:` citations here. Write them for the reviewer; understand
that the requirements above are held to by the review and not by a gate.

## Objectives

`dd-trustworthy`.
