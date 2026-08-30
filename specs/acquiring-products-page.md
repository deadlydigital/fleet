# Make the acquiring-products report reachable

## What is wrong

`GET /api/analytics/products/acquiring` is built, mounted and reasoned
through — and no user can get to it. Read at `63130ad`:

* the endpoint is served by `api/analytics/routes/products.py:56`, whose
  router is included at `api/analytics/__init__.py:74`
* `api/analytics/services/acquisition.py` carries the report, with three
  named rulings about what "the acquiring product" means
* **`platform/` contains no reference to it.** `grep -ri acquiring platform`
  over `.ts`/`.tsx` returns nothing: no proxy route under
  `platform/app/api/analytics/products/`, no page, no nav entry

It is the only analytics endpoint in the API with no frontend proxy. Every
other one — including `/geography`, `/geography/cities`,
`/geography/areas/{area}`, `/sources/timeline-by-campaign` and
`/segments/{name}/export` — has one.

`specs/metorik-gap.md` records this row as **"Has — no Metorik equivalent
found"**. That is wrong against the document's own definition of Has: *"an
endpoint that is mounted **and** a page that reaches it"*. It is the same
"built but unreachable" state that document correctly identified for
geography, which has since been built. **Correct the row while you are here.**

## Which Metorik behaviour this matches

None — and that is why it is worth reaching. `specs/metorik-gap.md`, Weekly
band: *"Which product acquired each customer — **Has — no Metorik equivalent
found**"*, one of two capabilities the gap list flags as running the other
way and *"worth protecting rather than closing"*.

Everything else in the Weekly band that is missing needs a backend. This
needs a page. It is the cheapest remaining item on the list by a wide margin
and it is a differentiator rather than a catch-up.

## What the user sees

A new page at `/analytics/products/acquiring`, reached from **Products →
Acquiring** in the sidebar, showing which product brought each customer in
over a chosen window.

The endpoint returns three things and **the page must show all three**:

1. **`products`** — the ranking. Per product: `wc_product_id`,
   `product_name`, `customers_acquired`, `customers_present_on_first_order`,
   and whatever else the service returns.
2. **`coverage`** — the reconciliation. `customers_acquired` summed across a
   *complete* ranking equals `coverage.customers_acquired_total`.
3. **`truncation`** — `products_total`, `products_returned`, `is_truncated`,
   `customers_acquired_in_returned_products`, `customers_acquired_total`.

### The two customer counts are not the same number and the page must say so

`acquisition.py` ships both deliberately:

    customers_acquired               one per customer. SUMS to the total.
    customers_present_on_first_order any line of the first order. DOES NOT
                                     SUM — a customer whose first order had
                                     three lines appears under three products.

Measured in that module: attributing to every line inflates the customer
count by 55% (90,917 rows for 58,608 customers, 1.551x). A page showing the
two side by side without labelling which one adds up invites exactly the
subtraction that produces a wrong answer. Label them.

### Truncation must be visible

`routes/products.py` says it in a comment: *"No silent caps. There are more
acquiring products on this tenant (785) than MAX_PAGE_SIZE (200), so
`customers_acquired` summed over `products` does NOT equal
`coverage.customers_acquired_total` unless the ranking is complete."*

When `truncation.is_truncated` is true the page must say so, showing
`products_returned` of `products_total` and the two customer totals. A
ranking that quietly shows the top 200 of 785 reads as "here is everything",
which is the failure the endpoint went to trouble to make impossible.

## What done means

1. **Proxy route** at
   `platform/app/api/analytics/products/acquiring/route.ts`. Model it on
   `platform/app/api/analytics/geography/route.ts`, which is the most
   recently written example of the same job: session guard returning 401
   without `tenantId`, forward `start`, `end` and `limit` only, call
   `${BACKEND_URL}/api/analytics/products/acquiring`, pass
   `X-DD-API-Key` from the session, return the backend's body and status.
2. **Page** at
   `platform/app/(dashboard)/analytics/products/acquiring/page.tsx`,
   rendering the ranking, the coverage reconciliation and the truncation
   notice, with a date-range control that maps to `start`/`end`.
3. **Both customer counts rendered and labelled**, with the "sums" /
   "does not sum" distinction visible to a reader who has not read
   `acquisition.py`.
4. **Sidebar**: add `{ name: 'Acquiring', href: '/analytics/products/acquiring', icon: Package }`
   to the Products section of `navSections` in
   `platform/components/layout/Sidebar.tsx`.
5. **`specs/metorik-gap.md` is not in this repo and must not be edited.**
   Correcting that row is a note for the reviewer, not a file change.

### The date filter bounds the acquisition, not the orders

`routes/products.py` is explicit: *"`start`/`end` bound the ACQUISITION, not
orders — a customer acquired before the window is not re-acquired by ordering
inside it."* If the page labels the control, label it as the acquisition
window. Do not call it "orders between".

`start` and `end` must be sent together or not at all — the endpoint returns
400 if only one is present.

## What is not in this task

- **Any change under `api/`.** The endpoint is finished. This contract
  protects `api/**` and the task will be rejected for touching it.
- **A test.** `platform/__tests__/**` is a protected path, so this task
  cannot add one, and the existing 298 do not cover a page that does not
  exist yet. A render test modelled on
  `platform/__tests__/unit/analytics/geography.render.test.tsx` should follow
  from a person. This is a known hole and it is stated rather than hidden.
- **Reformatting, dependency changes, or edits to `package.json`.**
- **The `/analytics/categories`, `/analytics/coupons` and
  `/analytics/payment-methods` pages** the sidebar comment still reserves.
  All three need a backend endpoint that does not exist.

## How it is checked

    tsc --noEmit is clean across the platform
    the existing 298 unit tests still pass
    the proxy route and the page exist, the proxy guards the session and
    forwards the right parameters, and the page surfaces coverage,
    truncation and both customer counts

The third check reads the files and lives outside this repository. It fails
on `main` today and passes only when the page actually surfaces the
reconciliation — a page that renders the ranking alone does not pass.
