# Draft spec — coupon and discount performance on the revenue summary

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
contract: deadly-digital-platform-api.yaml
title: Report coupon and discount performance from the revenue endpoint — usage, discount total, orders and AOV with and without a coupon
writable_paths:
  - api/analytics/services/analytics_engine.py
  - api/analytics/routes/revenue.py
```

## What is missing, and it is still missing

`specs/metorik-gap.md` carries this in the Weekly band as **Missing**: *"No coupon
report or endpoint. The data is partly there — `coupon_code` and `discount_total` are
populated on 146,136 and 146,043 orders respectively — and surfaces only as fields on
an order row."*

`research/candidates-metorik-gap-2026-09-11.md` re-verified that at platform sha
`2ce6f50`. The string `coupon` occurs in the whole of the analytics route tree only in
`api/analytics/routes/orders.py`, and every occurrence is the order-list **filter** that
task 53 shipped: `specs/order-list-filters.md` §2 defines it as `o.coupon_code = :coupon`,
exact. A filter answers *"show me the orders on WELCOME10"*. It does not answer *"what is
the coupon programme costing"*, and nothing does — `coupon` appears nowhere in
`api/analytics/services/analytics_engine.py`, so no aggregate groups by it.

So this is an absent computation over a populated column: the cheapest shape of parity
gap there is.

## Why this is the third attempt, and what is different about it

Two earlier attempts on this row died on WHERE the code was to go, not on whether the
work was worth doing.

* Task 23 proposed `api/analytics/routes/coupons.py`. The api contract enumerates
  twenty-seven existing files and contains no glob, deliberately — see the header of
  `contracts/deadly-digital-platform-api.yaml` and `specs/auto-approval.md` §15 — so a
  new route module is a path no contract can make writable. Refused for the path, not
  for the work.
* Candidate 34 was approved and its draft refused because its declared paths were
  covered by two contracts. `api/analytics/routes/orders.py` and
  `api/analytics/services/order_query.py` are the whole writable set of
  `contracts/dd-order-filters.yaml` *and* a subset of the api contract's, and the
  derivation that used to pick a contract had nothing to pick on. That draft merged and
  queued nothing.

This one names `api/analytics/services/analytics_engine.py` and
`api/analytics/routes/revenue.py`, and names its contract in the block above rather than
leaving it to be derived. Neither path is in `contracts/dd-order-filters.yaml`, so
`deadly-digital-platform-api.yaml` is the only contract for `dd_api` on this repo that
covers both — and it is also the one that can actually judge an aggregate query: it runs
`tests/unit` and `tests/analytics` per file and requires one added test proven to fail
against the tree before the change.

## Why the revenue endpoint is the right surface and not a compromise

`research/refund-coverage.md` maps the engine's window aggregates, read after the net
revenue change merged:

| Function | Line | Exposed by |
|---|---|---|
| `revenue_report` | 787 | `GET /api/analytics/revenue` (`data`) |
| `revenue_summary` | 928 | `GET /api/analytics/revenue` (`summary`) |

`revenue_summary()` already computes window totals — gross, net, refunded amount, orders
with a refund — over a start/end window and a revenue-status predicate. *Usage, discount
total, orders, and AOV with versus without a coupon* is the same shape of figure over the
same rows in the same window. It belongs in that object, and putting it there means the
report inherits a window selector, a status rule and a page that already exist rather
than restating any of them.

`revenue.py` and `dashboard.py` are the only routes that expose those keys and neither
names them — `research/refund-coverage.md` records that both pass the engine's dict
through. That is what makes an additive key cheap here.

**The page.** The revenue page already exists under platform/app/(dashboard)/analytics/,
and it reads this endpoint. A coupons page does not exist and **cannot be built by an
unattended task at all**: `contracts/dd-analytics-frontend.yaml` enumerates the page
directories it may write and a `coupons` directory is in none of them, and
`Sidebar.tsx` — which reserves a `/analytics/coupons` nav slot — is writable only under
`contracts/dd-acquiring-page.yaml`, whose other globs are the products page and its
proxy. **That reserved slot cannot be filled however this row is cut.** Rendering the
new block on the revenue page is a separate, later draft against a frontend contract
somebody has widened by hand; it is named here so it is a known follow-up rather than a
discovery.

## The number that should decide the shape of the per-coupon table

The candidate leads with coverage — 146,136 of 2,844,177 orders, the 5.14% being the
share of orders that used a coupon rather than missing data. That is right and it is not
the number that constrains the design. `research/EVIDENCE-metorik.md`, run against
production `analytics_2` on 2026-08-30, reports in one row:

| orders | coupon_code non-null | distinct coupon codes | discount_total > 0 |
|---|---|---|---|
| 2,846,280 | 146,509 | **65,444** | 146,429 |

**146,509 coupon orders across 65,444 distinct codes is 2.24 orders per code.** This
store is not running a dozen campaign codes; it is issuing codes per customer, or close
to it. Any obvious build of this report — a table of coupons ranked by usage — is, on
this tenant, 65,444 rows whose top row was used a handful of times. Returned whole it is
a response nobody can read; truncated silently at fifty it describes 0.08% of the codes
while looking like the whole story.

That is why the aggregate is the headline below and the per-code table is a bounded,
self-describing tail. The Metorik row asks for the aggregate first too.

## The 93 orders are two questions, not one discrepancy

The candidate notes the 93-order gap between the two columns is *"worth a look while
somebody is in there"*. Reading the SQL in `research/EVIDENCE-metorik.md`, the two
figures are not one measurement with an error — they are different predicates:
`count(coupon_code)` counts orders whose code is **not null**, and the other counts
orders whose `discount_total` is **greater than zero**. Neither contains the other, and
a single subtraction can be any mix of a coupon that discounted nothing (free shipping,
a failed minimum-spend rule), a discount with no coupon (a store-wide sale, a manual
adjustment), and an **empty-string** code, which `count(coupon_code)` counts as present
and which the existing `coupon=` filter cannot usefully match. Those pull in opposite
directions and cancel. Requirement 6 reports each side separately, at no extra query
cost, and answers the question permanently instead of inviting the look.

**Citing the requirements.** Each numbered requirement must be cited by a line the diff
adds — `# spec:3` on the line computing the with/without split, and so on.
`contracts/checks/spec_requirements_cited.py` runs first in this contract's verification
list and fails the task otherwise. Seven requirements, against a `max_requirements` of 10.

---

### 1. An additive block on the revenue summary, and the route names it

The engine change is in `revenue_summary()` in
`api/analytics/services/analytics_engine.py`. It gains one new top-level key on the dict
it already returns — a coupon block holding everything in requirements 3, 4 and 6.

**No existing key changes name, meaning or value.** The revenue page and the dashboard
both read this object today and the frontend is protected under this contract, so a
renamed or recomputed key ships a silently different number with no way to tell. That is
the discipline `specs/net-revenue-after-refunds.md` §1 established for net beside gross,
and it is the same argument here.

`api/analytics/routes/revenue.py` gains one query parameter, `coupon_limit`, with a
`description` on its `Query(...)` as `specs/order-list-filters.md` §4 asked of the
filters, passed through to the engine. No new route and no new module:
`api/analytics/routes/coupons.py` is not in this contract's enumerated `writable_paths`,
and `creatable_paths` admits only the one test file, so a task that creates it is refused
for the path rather than judged on the work.

### 2. The same window and the same population as the figures beside it

The coupon aggregate uses the window bounds and the revenue-status predicate that
`revenue_summary()` already applies to gross and net — read them in the function and
reuse them; do not write a second list of statuses and do not re-derive the bounds. Two
definitions that can drift is how a coupon block and the gross figure printed beside it
come to disagree about the same window.

Where the surrounding code reports both populations — all-status and revenue-status — as
separately named figures, the coupon block follows that convention rather than collapsing
them. On this tenant the gap is small, and reporting both is what makes it small rather
than unknown.

### 3. With and without a coupon, and each side carries its own AOV

The headline, and the Metorik row answered directly. For each of the two populations —
orders **with** a coupon code and orders **without** — the block carries the order count,
the gross order total, and the AOV computed as that total over that count. Beside them:
the total discount given, the number of distinct coupon codes seen in the window, and the
coupon-usage share of orders.

Each AOV is computed from the two fields printed next to it, so a reader can divide the
numbers and get the third. An AOV whose denominator is absent is a number nobody can
check, and `specs/metorik-gap.md` already records a documented conflict about which
population an AOV covers — this does not add a third unstated one.

### 4. The per-code table is bounded, ordered by money, and states its own tail

Rows carry the coupon code, the order count, the discount total, the gross order total
and the AOV for that code. They are ordered by discount total descending — the money
question rather than the count question — and bounded by `coupon_limit`, defaulting to a
small number with a hard ceiling in the low hundreds. A request above the ceiling returns
the ceiling rather than an error; `coupon_limit=0` returns no rows and leaves the
aggregate of requirement 3 intact, which is what the revenue page wants on an ordinary
load.

**The tail is reported, not implied.** Beside the rows: the total number of distinct
codes in the window, and the order count and discount total of the codes *not* returned,
obtained by subtracting the returned rows from the window totals of requirement 3 rather
than by a third query. With 65,444 codes on this tenant a top-twenty covers a rounding
error of them, and a table that does not say so reads as the whole store. A window with
no coupon orders returns an empty row list with the totals present and zeroed — an absent
block and an empty one read identically to a frontend and mean different things.

### 5. The code this returns is the code the order-list filter matches

The `GROUP BY` key is `coupon_code` exactly as stored: no `LOWER()`, no `TRIM()`, no
collapsing of variants. `specs/order-list-filters.md` §2 defines the order-list filter as
`o.coupon_code = :coupon`, exact and case-sensitive, so a normalised code here is a code
that returns an empty order list when a reader clicks through to it — a control that
appears to work and shows nothing, which is the failure class
`contracts/checks/proxy_passthrough.py` exists for one layer up.

If normalisation turns out to be wanted it is a second field beside the exact code, and a
decision somebody takes with this report in hand. It is not this task's, and it is not
done silently.

### 6. Where coupon and discount disagree, both directions are counted

Four figures over the window, as named fields: orders with a non-null coupon code and
`discount_total = 0`; orders with a discount above zero and a null coupon code; orders
whose coupon code is the empty string; and orders with both. Read together they
decompose the 93 — 80 in the 2026-08-30 evidence, and the number moves with the window —
into the populations that produce it.

A zero is stated, not omitted. If every coupon order carries a discount and every
discount carries a coupon, the fields are present and zero, because *checked and agreed*
and *not checked* are the difference this requirement exists to make.

### 7. A test that fails without this change

One new file, `api/tests/analytics/test_fleet_coupons.py`. This contract's
`creatable_paths` admits `api/tests/analytics/test_fleet_*.py` and nothing else, no
existing test may be edited, and `contracts/checks/new_test_bites.sh` proves the new one
fails against the tree before the change. Its budget is `max_test_diff_lines`, separate
from the production 400.

It asserts four things, because a test that only asserts a 200 satisfies the bite check
while establishing nothing:

* the coupon block appears on the revenue summary and every pre-existing summary key
  keeps its name and its value — requirement 1;
* over a fixture whose with-coupon and without-coupon AOVs differ, both are returned and
  each equals its own total over its own count — requirement 3;
* a fixture carrying more distinct codes than `coupon_limit` returns exactly
  `coupon_limit` rows and a tail whose counts account for the rest — requirement 4;
* a fixture with one zero-discount coupon order and one discounted order with no coupon
  reports **one in each direction**, not a net of zero — requirement 6.

---

## What this task must not do

* **No page, no proxy, no sidebar entry.** `platform/**` is protected under this
  contract, and the paths a coupons page would need are writable under no contract
  either. Rendering this belongs to a later frontend draft, against a contract somebody
  has widened by hand first.
* **No new route module and no new service module.** The two files in the block are the
  whole of the production diff.
* **No migration and no index.** `api/analytics/migrations/**` and `api/alembic/**` are
  protected here and nothing below needs them; `coupon_code` and `discount_total` are
  stored columns on `api/analytics/models.py` that the sync already writes.
* **At most two extra grouped scans per request, and the second only when
  `coupon_limit > 0`.** One aggregate keyed on whether a coupon is present yields
  requirements 3 and 6 together; one `GROUP BY coupon_code ... ORDER BY ... LIMIT` yields
  requirement 4. Not a query per coupon, and not a round trip per row.
  `specs/order-list-filters.md` §5 measured the comparable unbounded summary at 601ms as
  a parallel seq scan, and a hash aggregate over the same rows is that scan with a
  grouping on top — that is the budget, and it is why `coupon_limit=0` must be the cheap
  path.
* **No change to the order-list filter.** `coupon` and `has_discount` on
  `api/analytics/routes/orders.py` work and are deployed; this reads the same column and
  leaves them alone.
* **No currency conversion.** `specs/metorik-gap.md` records every production order as
  GBP and multi-currency as out of scope. The block names the currency rather than
  implying it.
* **No reformatting and no unrelated lint fixes.** The ruff gate is a ratchet that
  tolerates existing findings — `api/analytics/routes/revenue.py` carries a pre-existing
  I001 — so a tidy-up is pure diff with no gate asking for it.

## Before this is queued

* **Where the block goes is the one judgement to check against the tree.** This spec
  names `revenue_summary()` because `research/refund-coverage.md` places the window
  totals there and `api/analytics/routes/revenue.py` returns them under `summary`.
  Locate the function **by name, not by the line numbers quoted above** — that file has
  moved under its recorded line numbers before, which is why
  `specs/net-revenue-after-refunds.md` says the same thing.
* **The `coupon_limit` default and ceiling are judgements and are labelled as such.**
  They are chosen against a tenant with 65,444 codes, where any table is a sample; a
  store running twelve campaign codes wants all twelve and gets them. Requirement 4's
  tail is what keeps a wrong ceiling from becoming a wrong report.
* **Requirement 6 may return large numbers, and that is a result rather than a failure.**
  If most of this tenant's coupon orders carry no discount, the coupon programme is not
  what 5.14% suggests, and this is how anyone would find out. Read those four fields
  before reading the diff.
* **This merges with nobody reading it.** `auto_merge` is `true` on
  `contracts/deadly-digital-platform-api.yaml`, and that file's own header sets out the
  cost: six of seven requirements can ship with every check green and no revert
  triggered, because there is nothing to revert. The `spec:N` tokens in the diff are the
  only trace. `specs/unattended-operation.md` §3.2 is the distinction being relied on
  here — the suites prove nothing broke, `contracts/checks/new_test_bites.sh` proves the
  added test discriminates, and neither proves the other six requirements were built.
* **The coverage figures are a reading of production on 2026-08-30**, quoted from
  `research/EVIDENCE-metorik.md` rather than re-measured here. Nothing above depends on
  their exact values — only on the shape they establish, which is many codes and few uses
  each.
