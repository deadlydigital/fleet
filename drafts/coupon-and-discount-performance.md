# Draft spec — coupon and discount performance, over 65,444 distinct codes

```fleet-spec
work_type: dd_api
repo: deadly-digital-platform
title: Aggregate coupon and discount performance — usage, discount total, orders and AOV with and without a coupon — as an endpoint on the orders router
writable_paths:
  - api/analytics/routes/orders.py
  - api/analytics/services/order_query.py
```

## What is missing

`specs/metorik-gap.md` carries this in the Weekly band as **Missing**: *"No coupon report or
endpoint. The data is partly there — `coupon_code` and `discount_total` are populated on
146,136 and 146,043 orders respectively — and surfaces only as fields on an order row.
`Sidebar.tsx` reserves a `/analytics/coupons` nav slot for a page that does not exist."*

`research/candidates-metorik-gap-2026-09-10.md` re-verified that at platform sha `6fd8ddd`
and it still holds. The string `coupon` occurs three times in the whole of
api/analytics/routes/, all of them in `api/analytics/routes/orders.py`, and all of them the
order-list **filter** that task 53 shipped: `specs/order-list-filters.md` §2 defines it as
`o.coupon_code = :coupon`, exact. A filter answers "show me the orders on WELCOME10". It
does not answer "which coupons are costing us what", and nothing in the tree does.

So this is an absent computation on a populated column — the cheapest shape of parity gap
there is, and the reason it is worth doing now rather than after the harder rows.

## The number that should decide the design, and it is not 5.14%

The candidate leads with coverage: 146,136 of 2,844,177 orders, *"not thin data, it is the
share of orders that used a coupon"*. That is right and it is not the interesting number.
`research/EVIDENCE-metorik.md`, run by the fleet runner against production `analytics_2` on
2026-08-30, reports in one row:

| orders | coupon_code non-null | distinct coupon codes | discount_total > 0 |
|---|---|---|---|
| 2,846,280 | 146,509 | **65,444** | 146,429 |

**146,509 coupon orders across 65,444 distinct codes is 2.24 orders per code.** This store is
not running a dozen campaign codes; it is issuing codes per customer, or close to it. Every
obvious build of this report — a table of coupons ranked by usage — is, on this tenant, a
table of 65,444 rows in which the top row was used a handful of times. A report that returns
all of them is a 65,444-element JSON body nobody can read, and a report that returns the top
50 without saying so describes 0.08% of the codes while looking like the whole story.

That is why the requirements below make the **aggregate** the headline and the per-coupon
table a bounded, self-describing tail rather than the other way round. The Metorik row this
serves — *"usage, discount total, orders, AOV with/without"* — asks for the aggregate first
too; the per-coupon breakdown is the part that has to be made safe.

## The 93 orders, which are two questions rather than one

The candidate notes that *"the 93-order difference between the two columns is worth a look
while somebody is in there"*. Reading the evidence pack's SQL, the two figures are not
measuring one thing with a discrepancy — they are different predicates:
`count(coupon_code)` counts orders whose code is **not null**, and the other counts orders
whose `discount_total` is **greater than zero**. Neither is a subset of the other by
construction, and a single difference of 93 can be any combination of:

* a coupon that discounts nothing on the order it is attached to — free shipping, a gift, a
  code that failed its minimum-spend rule but was still recorded;
* a discount with no coupon at all — a store-wide sale, a manual adjustment, a plugin;
* an **empty-string** code, which `count(coupon_code)` counts as present and which the
  existing `coupon=` filter cannot usefully match.

Those pull in opposite directions and cancel, so the one subtraction hides its own inputs. A
report that states each side separately answers the question permanently, at no extra query
cost, and replaces the look somebody was going to take by hand. Requirement 6 is that.

## Why `dd_api`, and why the page is not in this task

`contracts/deadly-digital-platform-api.yaml` makes `api/analytics/routes/orders.py` and
`api/analytics/services/order_query.py` writable, and its verification — compileall, the
ruff ratchet, both pytest suites, and one added test proven to fail without the change — is
what can actually judge an aggregate query.

**The sidebar slot and the page cannot be queued today, and that is a fact about the
contract rather than a scheduling choice.** `contracts/dd-analytics-frontend.yaml`
enumerates its writable paths rather than globbing them, and neither an
`app/api/analytics/coupons` proxy directory, nor a `coupons` page directory under
platform/app/(dashboard)/analytics/, nor `platform/components/layout/Sidebar.tsx` appears in
that list — the only components it makes writable are the four named files under
platform/components/analytics/. Its own header calls this **"THE PRICE"** and says what pays
it: *"A new report page in a directory not named below needs a line added here, by the person
queueing the task. That is not friction to be engineered away — it is the review this
contract's narrowness is made of."*

So the follow-up is a second draft, written the way `drafts/order-filters-frontend.md` was
written — after this endpoint exists and its response can be quoted rather than predicted —
and it cannot be queued until somebody adds those paths to the frontend contract and the
pair to `contracts/checks/proxy_passthrough.py`. Splitting this draft into a two-link chain
instead would not help: `console/autoqueue.py` copies the whole draft into every link's
`spec_md`, so the frontend link would be handed API requirements it cannot cite and
`contracts/checks/spec_requirements_cited.py` would fail both. Named here rather than left to
be discovered, because until that draft lands this feature reaches nobody.

**Citing the requirements.** Each numbered requirement below must be cited by a line this
change adds — `# spec:3` on the line that computes the with/without split, and so on.
`contracts/checks/spec_requirements_cited.py` runs first in this contract's verification
list and fails the task otherwise. Eight requirements, against a `max_requirements` of 10.

---

### 1. One endpoint, on the orders router, and it must actually be reachable

`GET /api/analytics/orders/coupons`, added to `api/analytics/routes/orders.py` beside the
existing list endpoint, taking `start` and `end` on the same terms as the routes already
there and a `limit` as described in requirement 4. Each `Query(...)` gets a `description`,
as `specs/order-list-filters.md` §4 asked of the filters.

**It is declared before `GET /orders/{id}`.** Route matching is in declaration order, and a
detail route whose path parameter accepts a string will swallow `/orders/coupons` and hand
the detail handler the id `"coupons"`. The result is not an error a suite notices — it is a
404 or a 500 from the wrong handler. If the existing parameter is typed as an integer this
is already safe; declaring the static path first makes it safe either way, and requirement 8
is what proves it rather than assuming it. No new route module: `api/analytics/routes/coupons.py`
is not in this contract's enumerated `writable_paths` and `creatable_paths` admits only the
one test file, so a task that creates it is refused for the path rather than for the work.

### 2. One definition of which orders count, reused and not restated

The aggregate lives in `api/analytics/services/order_query.py`, which already owns the
revenue-status rule and the `WHERE` clause the order list and its summary share. This
endpoint uses **that** definition of a revenue-status order; it does not write a second list
of statuses. Two lists that can drift is how a coupon report and the revenue page come to
disagree about the same window.

Both populations are reported, never collapsed: the all-status counts and the revenue-status
counts, as separately named fields, which is the convention `specs/order-list-filters.md` §3
and the existing summary already hold to. On this tenant the gap is small — 2,845,479 of
2,846,280 orders are `completed`, against 332 cancelled, 241 processing, 203 on-hold, 24
pending and 1 refunded — and reporting both is what makes that small rather than unknown.

### 3. With and without a coupon is the headline, and both sides carry their own AOV

The top-level block covers the whole window and answers the Metorik row directly. For each
of the two populations — orders **with** a coupon code and orders **without** — the response
carries the order count, the gross order total, and the AOV computed as that total over that
count. Beside them: the total discount given, the number of distinct coupon codes seen, and
the coupon-usage share of orders.

AOV is computed per side from the fields above, so a reader can divide the two numbers and
get the third. An AOV whose denominator is not in the response is a number nobody can check,
and `specs/metorik-gap.md` already records a documented conflict about which population an
AOV is over — this endpoint does not add a third unstated one.

### 4. The per-coupon table is bounded, ordered, and states its own tail

Rows carry the coupon code, the order count, the discount total, the gross order total, and
the AOV for that code. They are ordered by discount total descending — the money question,
not the count question — and bounded by `limit`, defaulting to 50 with a hard ceiling in the
low hundreds. A request for more returns the ceiling rather than an error.

**The tail is reported, not implied.** Beside the rows: the total number of distinct codes in
the window, and the order count and discount total of the codes *not* in the returned rows.
With 65,444 codes on tenant 2 a top-50 covers a rounding error of them, and a table that does
not say so reads as the whole store. A window with no coupon orders at all returns an empty
row list with the totals present and zeroed — an absent block and an empty one read
identically to a frontend and mean different things.

### 5. The code the report returns is the code the filter matches

The `GROUP BY` key is `coupon_code` exactly as stored: no `LOWER()`, no `TRIM()`, no
collapsing of variants. `specs/order-list-filters.md` §2 defines the order-list filter as
`o.coupon_code = :coupon`, exact and case-sensitive, so a normalised code in this report is a
code that returns an empty order list when a reader clicks through to it — a control that
appears to work and shows nothing, which is the failure class
`contracts/checks/proxy_passthrough.py` exists for one layer up.

If normalisation turns out to be wanted, it is a second field beside the exact code and a
decision somebody takes with this report in hand; it is not this task's, and it is not done
silently.

### 6. Where coupon and discount disagree, both directions are counted

Four figures in the window, as named fields: orders with a non-null coupon code and
`discount_total = 0`; orders with a discount above zero and a null coupon code; orders whose
coupon code is the empty string; and orders with both. Read together these decompose the 93
— 80 in the 2026-08-30 evidence, and the number moves with the window — into the
populations that produce it, rather than reporting a subtraction whose inputs cancel.

A zero is stated, not omitted. If every coupon order carries a discount and every discount
carries a coupon, the fields are present and zero, because "checked and agreed" and "not
checked" are the difference this requirement exists to make.

### 7. One pass over the table, no index, no migration

Everything above comes from one grouped scan of `orders` in the window plus, at most, one
aggregate for the without-coupon side — not a query per coupon, and not a second round trip
per row of the table. `specs/order-list-filters.md` §5 measured the existing unbounded
summary at **601ms as a parallel seq scan**, and a grouped aggregate over the same rows is
the same scan with a hash aggregate on top; that is the budget this stays inside.

No index and no migration. `api/analytics/migrations/**` and `api/alembic/**` are protected
under this contract and nothing here needs them. No change to any existing endpoint's
response shape, no change to `GET /orders/statuses`, no reformatting and no unrelated lint
fixes — the ruff gate is a ratchet that tolerates existing findings, so a tidy-up is pure
diff with no gate asking for it.

### 8. A test that fails without this change

One new file, `api/tests/analytics/test_fleet_coupons.py`. The contract's `creatable_paths`
admits `api/tests/analytics/test_fleet_*.py` and nothing else; no existing test may be
edited, and `new_test_bites.sh` proves the new one fails against the tree before the change.

It asserts four things, and a test that only asserts a 200 satisfies the bite check while
establishing nothing:

* the endpoint returns the aggregate body rather than an order detail — requirement 1's
  shadowing, caught by shape rather than by reading the router;
* over a fixture whose with-coupon and without-coupon AOVs differ, both are returned and
  each equals its own total over its own count — requirement 3;
* a fixture carrying more distinct codes than `limit` returns exactly `limit` rows and a
  tail whose counts account for the rest — requirement 4;
* a fixture containing one coupon order with a zero discount and one discounted order with
  no coupon reports **one in each direction**, not a net of zero — requirement 6.

---

## What this task must not do

* **No page, no proxy, no sidebar entry.** `platform/**` is protected under this contract,
  and the paths that would be needed are not writable under the frontend one either. See
  above: it needs a line in `contracts/dd-analytics-frontend.yaml` from whoever queues it.
* **No migration, no index, no schema change.** Everything is computable from `orders` as it
  stands.
* **No new route module and no new service module.** The two files in the block are the
  whole of it.
* **No change to the order-list filter.** `coupon` and `has_discount` work and are deployed;
  this endpoint reads the same column and leaves them alone.
* **No currency conversion.** `specs/metorik-gap.md` records every production order as GBP
  and multi-currency as out of scope. The response names the currency rather than implying
  it.

## Before this is queued

* **The `limit` ceiling is a judgement and is labelled as one.** 50 by default is chosen
  against a tenant with 65,444 codes, where any table is a sample; a store running twelve
  campaign codes wants all twelve and gets them. Requirement 4's tail is what keeps a wrong
  ceiling from becoming a wrong report.
* **Requirement 6 may return large numbers, and that is a result rather than a failure.** If
  it turns out that most of this tenant's coupon orders carry no discount, the coupon
  programme is not what the 5.14% suggests, and this endpoint is how anyone would find out.
  Whoever reads this branch should read those four fields before reading the diff.
* **This merges with nobody reading it.** `auto_merge` is `true` on this contract, and the
  contract's own header sets out what that costs: four of eight requirements can ship with
  every check green and no revert triggered, because there is nothing to revert. The
  `spec:N` tokens are the only trace, and `brief/pass_.py`'s list of what merged unattended
  is the only surface a person is known to look at afterwards.
* **The coverage figures are from 2026-08-30 and the window moves.** 146,509 / 65,444 /
  146,429 are a reading of production on one day, quoted from `research/EVIDENCE-metorik.md`
  rather than re-measured here. Nothing in the requirements depends on their exact values —
  only on the shape they establish, which is many codes and few uses each.
