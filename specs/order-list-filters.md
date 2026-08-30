# Filter the order list by payment method, country, coupon and discount

**This is backend work.** `GET /api/analytics/orders` does not accept these
filters today, so there is nothing the frontend could send. Read at `63130ad`:
`api/analytics/routes/orders.py` declares `start`, `end`, `status`, `search`,
`page`, `limit`, `sort_by`, `sort_dir` and nothing else, and
`list_orders()` in `api/analytics/services/order_query.py` builds its `where`
list from exactly those.

The frontend half — proxy allow-list and UI controls — is a separate task
under the platform contract, and is deliberately not in this one. See *What
is not in this task*.

## What it does

Adds four filters to the order list endpoint. Every one of them is a column
the query already selects and the order rows already carry:
`payment_method`, `billing_country`, `coupon_code`, `discount_total` are all
in the `SELECT` at `order_query.py:157-163` and all four reach the page today
as columns. They cannot be filtered on.

## Which Metorik behaviour this matches

`specs/metorik-gap.md`, Daily band: *"Order filtering: status, payment,
shipping, location, customer tags, email engagement, products contained"* —
recorded as **Partial**, with the note *"The order rows carry payment method,
country, coupon and discount; they cannot be filtered on."*

This closes the payment / location / coupon / discount part of that row. It
does not close customer tags, email engagement or products-contained, which
need joins this endpoint does not make.

## What the user sees

Nothing yet — this task ships an API. A caller can do:

    GET /api/analytics/orders?payment_method=superpayments
    GET /api/analytics/orders?country=IE&start=2026-01-01&end=2026-03-31
    GET /api/analytics/orders?coupon=WELCOME10
    GET /api/analytics/orders?has_discount=true

and get the filtered page, the filtered pager, **and a `summary` that
describes the same filtered rows**.

## What done means

### 1. Four new query parameters on `GET /api/analytics/orders`

| parameter | type | matches |
|---|---|---|
| `payment_method` | string | `o.payment_method = :payment_method`, exact |
| `country` | string | `o.billing_country = :country`, exact |
| `coupon` | string | `o.coupon_code = :coupon`, exact |
| `has_discount` | bool | `true` → `o.discount_total > 0`; `false` → `o.discount_total = 0` |

All four are optional and combine with each other and with the existing
`start`/`end`/`status`/`search` as `AND`.

**None of them is validated against a list of known values.** An unrecognised
payment method returns an empty page, not a 400. This is the rule
`routes/orders.py` already states for `status`: *"Not validated against a
list — the whole point of this page is to show statuses we did not expect."*
A store that starts taking a new gateway must be filterable on it the same
day, not after a deploy.

`has_discount=false` means "no discount", not "ignore this filter". Absent
means ignore. `discount_total` is `NOT NULL` in the schema, so `= 0` is total
with `> 0` and no third case exists.

### 2. Every predicate is a bound parameter

Append to the `where` list and populate `params`, exactly as `status` and
`search` already do. **No caller value may be interpolated into the SQL
string.** `_SORTABLE` exists in this module because sort columns cannot be
bound and therefore need an allow-list; these four are values, so they bind,
and an allow-list would be the wrong tool as well as an unnecessary one.

### 3. The summary reflects the filters

`list_orders` builds one `where_clause` and uses it for both the summary
aggregate and the row query. Keep it that way. A summary computed over
unfiltered rows beside a filtered list is conflict 2.2 in a new place — a
count and a total whose population the reader has to guess — and this module
exists partly to not do that.

### 4. The route forwards them

`get_orders()` passes each through to `list_orders()`. Give each `Query(...)`
a `description`, as the existing parameters have.

### 5. Nothing gets slower, and no index is added

Measured against production `analytics_2` (2,845,628 orders) on 2026-08-30:

| query | today | with a filter |
|---|---|---|
| summary aggregate, no date bound | 601ms parallel seq scan | 236–829ms |
| list page 1, `ORDER BY created_at DESC LIMIT 50` | 1ms | 1ms – 370ms |

**The summary already seq-scans the whole table with no filter at all**, so
adding a predicate to that scan costs nothing — several filters are *faster*
than the baseline because the aggregate has less to add up. The list page
walks the existing `ix_analytics_orders_created` backwards and stops at 50;
the slowest case measured was 370ms for a coupon code held by one order in
2.8M, and a rare payment method (3,125 orders) was 315ms.

**Do not add an index and do not write a migration.** `api/analytics/migrations/**`
is a protected path and the task will be rejected for touching it. It is also
not needed: the numbers above are the whole argument, and two of the four
columns would not benefit anyway — `billing_country` has 2 distinct values on
this tenant (GB 2,795,433, IE 46,053) and `payment_method` has 9, of which
one covers 85% of rows.

## What is not in this task

- **The frontend.** `platform/app/api/analytics/orders/route.ts` forwards
  only the keys in its `PASSTHROUGH` list, so the four new parameters would
  be dropped even if a control sent them; and the page has no controls for
  them. Both are `platform/**`, which this contract protects. That is a
  separate task and it cannot start until this one merges.
- **`GET /orders/statuses`.** It takes `start`/`end` only. Making the status
  counts respect the other filters is a real question — it changes what the
  status dropdown means — and it is not this task's.
- **A discount range.** `has_discount` is a boolean. A min/max needs a UI
  control that does not exist and a decision about whether the bound is the
  discount or the discounted total.
- **Sorting by the new columns.** `_SORTABLE` stays as it is.
- **Cleaning up anything else in these files.** Do not reformat, do not
  reorder imports, do not fix unrelated lint. The lint gate tolerates
  findings that were already there and rejects only new ones, so an
  unrelated cleanup is pure diff nobody scoped.

## How it is checked

    the changed files still compile
    they introduce no ruff finding that was not already there
    the four parameters exist on the route, are accepted by list_orders,
    are forwarded, and every new predicate binds rather than interpolates

The third check reads the two files with `ast` and lives outside this
repository. **There is no test gate for backend work** — the api suite has
roughly 81 pre-existing failures on a clean database and cannot be run on
this host at all (`TEST-004` in `docs/TODO.md`). A passing run here means the
change parses, lints clean and has the right shape. Someone has to read it.
