# Render the coupon and discount block the revenue endpoint already returns

```fleet-spec
work_type: dd_frontend
repo: deadly-digital-platform
contract: dd-analytics-frontend.yaml
title: Render the coupon and discount block on the revenue page, and forward coupon_limit through the revenue proxy
writable_paths:
  - platform/app/(dashboard)/analytics/revenue/page.tsx
  - platform/app/api/analytics/revenue/route.ts
```

## What is wrong

`specs/metorik-gap.md` carries this in the Weekly band: *"Coupon and discount
performance: usage, discount total, orders, AOV with/without"*, recorded as
**Missing**.

The backend half of that row is no longer missing.
`drafts/coupon-performance-on-the-revenue-summary.md` specified a coupon block
on `revenue_summary()` in `api/analytics/services/analytics_engine.py`, exposed
through `api/analytics/routes/revenue.py` under `summary`, and the test that
spec's requirement 7 mandated is in the tree at
`api/tests/analytics/test_fleet_coupons.py`. What that block carries:

* the with-coupon and without-coupon split — orders, gross total and an AOV on
  each side, plus the discount total, the distinct-code count and the coupon
  share of orders;
* per-code rows ranked by **discount total** descending, bounded by a
  server-clamped `coupon_limit`;
* a **not-returned tail** that accounts for every code left out of those rows;
* eight named counts of the ways `coupon_code` and `discount_total` disagree.

And the string `coupon` occurs **zero times** in both
`platform/app/(dashboard)/analytics/revenue/page.tsx` and
`platform/app/api/analytics/revenue/route.ts`. The figure is computed, tested,
deployed, and invisible. This is the same shape of gap
`specs/comparison-windows-frontend.md` and `drafts/order-filters-frontend.md`
describe: the API gained the capability and the Next.js layer did not carry it
to a person.

## Why this is cheap, and where the one piece of work is

The block arrives in the payload the page already fetches, at the endpoint's
**default** `coupon_limit`, with no parameter sent and no API change. So the
rendering half of this task needs nothing from the backend at all.

The proxy work is one parameter. `coupon_limit` is the only name this feature
adds to the request, and it is what lets a reader ask for more than the default
handful of codes instead of being stuck at whatever the endpoint chose.

## Why there is no coupons page in this spec, and it is not an oversight

`contracts/dd-analytics-frontend.yaml` enumerates the page directories an
unattended task may write. There is no `coupons` directory among them, and the
nav component that reserves a `/analytics/coupons` slot is writable under
`contracts/dd-acquiring-page.yaml`, whose other paths are the products page and
the products proxy. **That reserved slot cannot be filled by an unattended task
however this row is cut** — not by this contract and not by the other one. It
needs a person to widen a contract by hand first.

The revenue page is where the figure already is. Rendering it there is not a
compromise: the coupon block is computed over the revenue endpoint's own window
and revenue-status predicate, so it inherits the date picker and the population
rule that the gross and net figures beside it already use. A separate page
would have to restate both.

## The number that decides the shape of the table

`research/EVIDENCE-metorik.md`, read against production `analytics_2` on
2026-08-30 and quoted in `drafts/coupon-performance-on-the-revenue-summary.md`:
2,846,280 orders, 146,509 with a coupon code, across **65,444 distinct codes**.
That is 2.24 orders per code. This store issues codes per customer; it is not
running a dozen campaigns.

So a twenty-row table covers **0.03%** of the codes. A table that does not say
so reads as the whole store, and every figure a reader takes from it is wrong by
three and a half orders of magnitude. That is why requirement 2.3 below is not
a nicety.

## What the user sees

On `/analytics/revenue`, below the existing revenue figures and inside the same
date window:

* **A coupon headline.** Orders with a coupon and orders without, each with its
  own total and its own AOV, plus the total discount given, the number of
  distinct codes in the window, and the coupon share of orders.
* **A table of codes**, ranked by discount given, with the code, orders,
  discount total, gross total and AOV per code.
* **A line under the table saying what is not in it** — how many codes, how many
  orders and how much discount the table leaves out.
* **A control to ask for more codes**, which is the only thing on the page that
  sends a parameter.
* In a window with no coupon orders: one sentence saying so.

---

### 1. The proxy forwards `coupon_limit`

In `platform/app/api/analytics/revenue/route.ts`, `coupon_limit` joins the
parameters the file forwards to the API. **Read the file before writing this
line.** `platform/app/api/analytics/orders/route.ts` forwards a literal
`PASSTHROUGH` allowlist and drops every key outside it; the revenue proxy may or
may not use that shape, and the change is to whatever mechanism is there, not to
a mechanism imported from another file.

**Forward, do not interpret.** Do not clamp `coupon_limit`, do not default it,
do not reject a value above the ceiling. The endpoint clamps server-side and
returns the clamped result — that is what
`drafts/coupon-performance-on-the-revenue-summary.md` requirement 4 specified,
and a proxy holding a second opinion about the ceiling is a file that cannot
test one. An absent `coupon_limit` must stay absent: forwarding `coupon_limit=`
or a defaulted value changes the response on an ordinary page load, which is
what requirement 4 below refuses.

`coupon_limit` is the **only** name added. A name the FastAPI signature does not
declare is discarded without an error and without a log line, which is FEAT-035.

Nothing else in the file changes.

### 2. The page renders the block

All of this is in `platform/app/(dashboard)/analytics/revenue/page.tsx`, reading
the coupon block off the object the page already fetches. **Read the key names
out of `revenue_summary()` in `api/analytics/services/analytics_engine.py` and
out of `api/tests/analytics/test_fleet_coupons.py`, which asserts on them.** The
names in this spec's prose are descriptions of the figures, not a claim about
the payload's spelling; `api/**` is protected under this contract and is being
read, never edited.

**2.1 The headline, with every denominator printed.** Orders with a coupon and
orders without, each carrying its own order count, its own gross total and its
own AOV, so a reader can divide the two numbers printed beside it and get the
third. Beside them the discount total, the distinct-code count and the coupon
share of orders. An AOV whose denominator is absent is a number nobody can
check, and `specs/metorik-gap.md` already records a documented conflict over
which population an AOV covers — do not add a third unstated one. Amounts are
GBP, named rather than implied: `specs/metorik-gap.md` records every production
order as GBP and multi-currency as out of scope.

**2.2 The table is the API's order, not the client's.** Rows render in the order
the payload returns them — discount total descending — and the page does **not**
re-sort, re-rank or truncate them. A client-side sort over a server-side top-N
is a table ordered by one rule and selected by another, which reads as a ranking
and is not one. No new sort control: the endpoint takes no sort parameter for
this block, so a header that appeared to sort would sort the sample.

**2.3 The tail is rendered, and it is not optional.** Under the table, in
prose a merchant reads rather than a footnote: the number of distinct codes in
the window, and the orders and discount total belonging to the codes **not** in
the table. Take these from the payload's not-returned tail. **Do not compute
them in the client** by subtracting the visible rows from the headline — that is
a second lineage for a figure that already has one, and the endpoint computes it
against the full window rather than against the page. On this tenant the
sentence under a twenty-row table says roughly 65,424 codes are missing from it,
and that is the honest reading of the table above it.

**2.4 Empty and absent are different, and neither is nothing.** A window whose
coupon block is present with zero coupon orders renders the section with a
sentence in place of the table — *"no coupon orders in this window"* or wording
the page's other empty states already use — because an empty region and a
missing feature look identical to a user and mean different things. A payload
carrying **no** coupon block at all is an older API, not an empty window: omit
the section entirely and do not throw. That second case is not hypothetical —
`platform/__tests__/fixtures/analytics/revenue-summary.json` is protected under
this contract and cannot be updated, so whatever it contains today is what
`platform/__tests__/unit/analytics/revenue.render.test.tsx` will render this
page against, and that test must keep passing untouched. Read the fixture first;
it decides which of the two paths the existing test exercises.

**2.5 Where coupon and discount disagree, say so once or not at all.** The block
carries eight named counts of the ways `coupon_code` and `discount_total`
disagree — on the reading of
`drafts/coupon-performance-on-the-revenue-summary.md` requirements 2 and 6, four
kinds of disagreement over two populations; **confirm that against the payload
rather than against this sentence**. When every one of them is zero, render
nothing: eight zeroes is noise, and the page has said all it has to say. When
any is non-zero, render one line naming the directions that are non-zero with
their counts — coupon codes that discounted nothing, discounts with no coupon,
empty-string codes. Do not net them off against each other. They pull in
opposite directions and a single difference is not a measurement of either,
which is the whole reason those fields exist separately.

### 3. Asking for more codes is the only request this page changes

One control — a "show more codes" affordance, or a small select of sizes — that
re-requests the same window with a larger `coupon_limit`. It joins whatever
state the date range already lives in and is sent the same way; do not introduce
a second mechanism for request state beside the one that is there.

**Render what came back, not what you asked for.** The endpoint clamps
`coupon_limit` to a ceiling and returns the clamped result rather than an error.
So the row count, the tail sentence and any "showing N of M" wording are all
read from the response. A page that asks for 500, receives the ceiling, and
prints 500 is lying about a table the reader can count.

**The control stops when it stops doing anything.** When the returned rows
already account for every distinct code in the window — the tail is zero — or
when asking for more returns no more rows than the previous request did, the
control is disabled or absent. A button that changes nothing when pressed is
worse than no button, and on a 65,444-code tenant the ceiling is reached long
before the codes run out.

### 4. The default load is unchanged

With the control untouched, the request this page sends and the figures it
renders above the coupon section are byte-for-byte what they are today. No
`coupon_limit` on the URL, no extra fetch, no second call to the endpoint to
populate the table — the block is already in the response the page has.

`platform/__tests__/unit/analytics/revenue.render.test.tsx` is the regression
guard for this and it is worth more than any wording improvement above.

### 5. A test that fails without this change

One new file, `platform/__tests__/unit/analytics/test_fleet_revenue_coupons.test.tsx`.
This contract's `creatable_paths` admits
`platform/__tests__/unit/analytics/test_fleet_*.test.tsx` and nothing else, the
extension must be `.test.tsx` or vitest never collects it, and
`contracts/checks/new_test_bites.sh` runs it against the tree as it was before
the change and refuses the branch if it passes there.

**No existing test file, fixture or handler may be edited.**
`platform/__tests__/**` is protected, which includes
`platform/__tests__/fixtures/analytics/revenue-summary.json` and
`platform/__tests__/mocks/handlers.ts`. The new test therefore supplies its own
coupon-bearing payload by overriding the handler from inside itself, through
`platform/__tests__/mocks/server.ts`, following the pattern
`platform/__tests__/unit/analytics/revenue.render.test.tsx` already uses for
this endpoint.

Assert four things, because a test that only checks the section renders passes
against a page that renders the wrong twenty rows:

1. **The tail is on screen.** Given a payload whose table holds fewer codes than
   the window's distinct-code count, the rendered output states the number of
   codes not in the table and their discount total — requirement 2.3. This is
   the assertion that makes a silent top-N impossible to ship.
2. **An empty block says so.** A payload whose coupon block is present with zero
   coupon orders renders the sentence, not an absent section and not a table
   header with no rows — requirement 2.4.
3. **`coupon_limit` reaches the request.** Operating the control produces a
   request to `/api/analytics/revenue` whose query string carries
   `coupon_limit=`, asserted **on the URL the MSW handler received** — and the
   first render carries no `coupon_limit` key at all, which is requirement 4.
   The negative half is what makes this bite: a test that only checks the
   parameter appears passes against a page that sends it on every load.
4. **The clamp is respected.** Given a response returning fewer rows than the
   control asked for, the page renders the returned count — requirement 3.

**Cite every requirement in the diff.**
`contracts/checks/spec_requirements_cited.py` runs first in this contract's
verification list and fails the task if a numbered requirement appears nowhere
in the lines the diff adds: `// spec:2.3` on the line rendering the tail, and so
on. The leaves are 1, 2.1, 2.2, 2.3, 2.4, 2.5, 3, 4 and 5 — nine, and the parsed
list including the parent `2` is ten, against a `max_requirements` of 12.

---

## What must not change

* **Every figure already on the revenue page.** Gross, net, refunds and the
  series keep their names, their values and their positions. The coupon block is
  additive and sits below them.
* **The date window mechanism.** The coupon block is computed over the window
  the page already asks for. Do not give it its own dates, and do not touch
  `platform/components/analytics/DateRangePicker.tsx`.
* **No figure recomputed in the client.** Not the AOVs, not the coupon share,
  not the tail. All of them are in the payload and all of them are computed over
  the full window rather than over the rows on screen.

## Out of scope

* **Any backend change.** `api/**` is protected under this contract, and every
  figure this task renders is already deployed. The API files named above are
  being read.
* **A `/analytics/coupons` page and the nav slot that reserves it.** Neither is
  writable under any contract — see the third section above. This is the reason
  that section exists, and it is a decision for a person widening a contract,
  not something to route around.
* **A coupon filter on the revenue page.** The order-list filter `coupon` on
  `platform/app/(dashboard)/analytics/orders/page.tsx` already exists and works.
  Making a code in this table link through to it is the obvious follow-up and it
  is a second page's concern; leave both alone.
* **Normalising or casing codes.** `drafts/coupon-performance-on-the-revenue-summary.md`
  requirement 5 groups on `coupon_code` exactly as stored, because
  `specs/order-list-filters.md` §2 defines the order-list filter as an exact
  match. A code prettified in this table is a code that returns nothing when
  somebody pastes it into that filter.
* **A chart.** 65,444 codes with 2.24 uses each is not a shape a bar chart says
  anything about.
* **Editing `specs/metorik-gap.md`.** It is in the fleet repository, which this
  contract cannot reach. The Weekly row closes when this merges; that is a note
  for whoever merges.

## How it is checked

Two contracts declare `work_type: dd_frontend`. This runs under
`contracts/dd-analytics-frontend.yaml`; the other,
`contracts/dd-acquiring-page.yaml`, makes only the products route, the products
page and the nav component writable, so neither declared path is writable under
it.

In the order the contract runs them:

    spec_requirements_cited.py    every numbered leaf cited in the diff
    cd platform && tsc --noEmit
    cd platform && vitest run     21 files, 319 tests
    new_test_bites.sh             the added test fails without the change
    proxy_passthrough.py          two pairs, and neither of them is this one

## Before this is queued

* **`proxy_passthrough.py` does not cover the revenue pair, and this task is the
  first to send a parameter from that page.** `PAIRS` in
  `contracts/checks/proxy_passthrough.py` names the orders page and the
  analytics overview and nothing else; its own docstring lists revenue among
  thirteen unchecked pairs of the same shape. So the one gate that exists for
  *"the page sends a name the proxy drops"* will go green without looking at
  either file this task touches. That file is in the fleet repository and this
  contract cannot reach it — whoever queues this either adds the revenue pair
  there first or reads the two-line diff for it. It is the cheaper half of the
  change and the half that fails silently.
* **Read `platform/__tests__/fixtures/analytics/revenue-summary.json` before
  deciding requirement 2.4 is satisfied.** Whether the existing fixture carries
  a coupon block decides whether `revenue.render.test.tsx` exercises the empty
  path, the absent path, or the populated one — and that test cannot be edited
  to suit the answer.
* **The key names in requirement 2 are descriptions, not quotations.** This spec
  was written from the payload's specification in
  `drafts/coupon-performance-on-the-revenue-summary.md` and from the candidate,
  not from the shipped source. The count of eight disagreement fields comes from
  the candidate; the 4×2 reading of it is an inference. Every name is to be read
  out of the engine and the API test.
* **This merges with nobody reading it.** `auto_merge` is `true` on
  `contracts/dd-analytics-frontend.yaml` since 10 Sep 2026, and that file's own
  header sets out the cost: eight of nine requirements can ship with every check
  green and no revert triggered, because there is nothing to revert. The
  `spec:N` tokens in the diff are the only trace. The requirement most likely to
  go missing that way is 2.3, because the page looks finished without it and
  wrong only to somebody who knows there are 65,444 codes.
* **The coverage figures are a reading of production on 2026-08-30**, quoted
  rather than re-measured. Nothing above depends on their exact values, only on
  the shape they establish: many codes, few uses each.
