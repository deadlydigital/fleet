# Make the Payment, Country and Coupon cells set the order filters

```fleet-spec
work_type: dd_frontend
repo: deadly-digital-platform
title: Clicking a Payment, Country or Coupon value in the order table sets that filter
writable_paths:
  - platform/app/(dashboard)/analytics/orders/page.tsx
```

## What is wrong

Task 53 shipped the four order filters — payment method, country, coupon and
discount — and left §2.5 of its own spec unbuilt. That requirement is in
`drafts/order-filters-frontend.md`, it reads *"the table cells set the
filters"*, and `specs/auto-approval.md` §9.9 records both what happened and how
it was caught: every contract check passed, the diff did not touch row
rendering at all, and `auto_merge: false` — a person reading the spec against
the diff — was the only reader in the path.

This task is that requirement, re-queued on its own merit rather than as a
follow-up fix. The gap it leaves is not cosmetic:

* all four filters are **exact** matches. `api/analytics/routes/orders.py`
  binds `o.payment_method = :payment_method`, `o.billing_country = :country`
  and `o.coupon_code = :coupon`, and `specs/order-list-filters.md` §1 states
  the reason none of them is validated against a list — *"a store that starts
  taking a new gateway must be filterable on it the same day"*.
* **there is no endpoint that lists the distinct values.**
  `platform/app/api/analytics/orders/statuses/route.ts` exists for `status`
  and has no counterpart for these three. `specs/order-list-filters.md` §5
  records nine distinct payment methods on the production tenant, one of which
  covers 85% of rows.

So a user can only filter by typing a string the product never told them. The
values are on screen, in the Payment, Country and Coupon columns of the very
table being filtered, and they are inert. A control an agency can use versus
one it can guess at, for a few lines of the page and no backend work.

## What the user sees

On `/analytics/orders`, the payment method, billing country and coupon code in
each row are clickable. Clicking one puts that exact value into the matching
filter control — the same control the user could have typed into — and the
table, the pager and the summary above it narrow to it, because the API
narrows all three over one `WHERE` clause.

Nothing else about the row changes. The columns, the sort order, the pager and
the summary are what they are today.

## What to build

All of it is in `platform/app/(dashboard)/analytics/orders/page.tsx`. There is
no backend change, no proxy change, no new endpoint and no new dependency.

### 1. The three values become filter setters

**1.1 One click sets one filter.** Clicking the payment method in a row sets
the payment-method filter to that row's value; country sets country; coupon
sets coupon. The other filters, the date range and the status keep whatever
they hold. Discount is not clickable — it is a three-state select, not a value
in a cell.

**1.2 Send the row's value, not the rendered text.** If the Payment column
renders a label, an icon or any prettified form of `payment_method`, the
filter must carry the underlying field from the order row, because `=` in
Postgres is exact and case-sensitive. The same applies to the country cell: if
it renders a flag or a country name, the filter carries the ISO-3166 alpha-2
code the column holds. A click that sends the display string returns an empty
table and looks like the feature is broken with no way to tell why. This is
the one rule in this spec that produces a wrong page rather than a missing
affordance.

**1.3 Set, do not toggle.** Clicking a value that is already the active filter
does nothing. A click that means "apply" on one row and "clear" on the next is
a control whose effect the user cannot predict from what is on screen; the
clear affordance task 53 shipped is how a filter comes off.

**1.4 An empty value is not clickable.** Most orders carry no coupon.
`coupon=` is an exact match against the empty string, so it returns nothing
and reads to a user as "there are no orders" rather than "that row had no
coupon". A null or empty cell renders exactly as it does today: plain text, no
affordance, no request. The same holds for a missing payment method or
country.

**1.5 It resets the pager to page 1.** Filtering from page 7 of an unfiltered
list into a two-page result renders an empty table over a summary saying there
are hundreds of matches. This is the rule the typed controls already follow;
the click goes through the same state and inherits it. Do not add a second
path to the request that bypasses it.

### 2. It has to be a control, not an onClick on a cell

**2.1 A real button.** The clickable value is a `<button>` (or an element with
an equivalent role, name and keyboard behaviour). Keyboard and screen-reader
users get the filter; a bare `onClick` on a `<td>` or a `<span>` gives it to a
mouse and nobody else, and this is a table an agency operator lives in.

**2.2 It must not steal the row's own click.** If the row is a link to the
order at `platform/app/(dashboard)/analytics/orders/[id]/page.tsx`, or is
itself clickable, the filter button must stop the event reaching it —
otherwise clicking a payment method navigates to an order and the user never
sees a filter. If the row is not clickable today, nothing here makes it one.

**2.3 It looks clickable.** Hover and focus states that say the value is a
control, and a title or accessible name that says what the click does. The
minimum bar is that a user who has never read a changelog can tell the
difference between the Payment cell and the Total cell.

### 3. The filter control shows what was set

The value that was clicked appears in the filter control for that field, in
the filter row where search, status and the date range already live. A table
that narrows without the reason being visible and editable is the same
unexplained empty page §1.4 is about — the user has to be able to see it,
change it, and clear it with the affordance that is already there.

Do not introduce a second mechanism for filter state, a chip or token UI, or a
separate "active filters" bar. The controls exist; this writes into them.

## What must not change

* **The unfiltered page.** With nothing clicked, the request the page sends
  and the table it renders are byte-for-byte what they are today.
  `platform/__tests__/unit/analytics/orders.render.test.tsx` is the regression
  guard and it must keep passing untouched.
* **The proxy.** `platform/app/api/analytics/orders/route.ts` already forwards
  all four parameters; task 53 landed that half. There is nothing to change in
  it and this spec does not declare it writable. See *Before this is queued*.
* **The API.** `api/analytics/routes/orders.py` and
  `api/analytics/services/order_query.py` are named here as the thing being
  reached, not as files to edit. `api/**` is protected under this contract.
* **The columns, the sort order and the pager.** `_SORTABLE` on the backend
  did not gain these columns, so no new sort option appears.
* **The summary.** It arrives from the API already narrowed. Do not recompute
  a count or a total in the client from the rows on the current page.
* **The status dropdown.** Its counts come from `/orders/statuses`, which
  takes `start` and `end` only. That is a real question about what the counts
  mean, it is backend work, and it is not this task.

## Where the change is not, and what to do if it is there

The cells are expected to be rendered in
`platform/app/(dashboard)/analytics/orders/page.tsx`, which is the file this
spec declares. If the Payment, Country and Coupon cell contents turn out to be
produced inside a shared primitive under `platform/components/ui/`, that
directory is deliberately outside this contract —
`contracts/dd-analytics-frontend.yaml` says why: the same primitive renders on
the campaigns, subscribers and billing pages, and ten analytics render tests
would not show what a change there did to them. **Stop and report that** rather
than widening the boundary. A spec that guessed wrong about a path is worth a
branch that says so.

## What the added test must assert

The contract permits **creating** exactly one file matching
`platform/__tests__/unit/analytics/test_fleet_*.test.tsx`. Two such files
already exist, so this one needs a name of its own — call it
`platform/__tests__/unit/analytics/test_fleet_order_cell_filters.test.tsx`.

`contracts/checks/new_test_bites.sh` runs it against the tree as it was before
this change and refuses the branch if it passes there. It refuses **two** added
test files, and it refuses any other change under `platform/__tests__/**` —
including the fixtures. So: one new file, nothing else in the suite touched,
and in particular `platform/__tests__/unit/analytics/test_fleet_order_filters.test.tsx`
(task 53's) is not modified.

Follow the pattern of the existing orders render test: render the page, serve
`*/api/analytics/orders` with MSW from
`platform/__tests__/fixtures/analytics/orders-list.json` and
`platform/__tests__/fixtures/analytics/orders-statuses.json`.

Assert **on the URL the MSW handler received**, not on what rendered:

1. **A click reaches the request.** Clicking the payment method of a fixture
   row produces a request whose query string carries `payment_method=` with
   **that row's exact value, read from the fixture**. Hard-coding the string is
   fine; taking it from the fixture is better. Repeat for country and coupon —
   three assertions, because §1.2 can be got right for one field and wrong for
   another.
2. **The pager resets.** With the pager moved off page 1, clicking a value
   produces a request carrying `page=1`.
3. **An empty value offers nothing.** Written against whatever
   `orders-list.json` actually contains: if it has a row with no coupon, assert
   that cell renders no button; if every row has one, assert instead that no
   request the handler received carries a bare `coupon=` with an empty value.
   The fixture is protected and may not be edited to make this convenient.

A test that only asserts the buttons render would bite — the buttons are new —
and would pass against a page that sends the rendered label instead of the
row's value, which is §1.2, the failure that produces a wrong page. **Assert on
the request.**

That matters more here than it did on task 53. `auto_merge` is `true` on this
contract since 10 Sep 2026, so unless the person queueing this changes it, this
merges with no one reading the spec against the diff — the exact silence
`specs/auto-approval.md` §9.9 describes, on the task that exists because that
silence swallowed a requirement once already. The added test is the only thing
in the path that can establish this requirement was met.

## Before this is queued: `paired_paths` will refuse this diff

`contracts/dd-analytics-frontend.yaml` declares a paired group over
`platform/app/api/analytics/orders/route.ts` and the orders page: both or
neither. `contracts/checks/paired_paths.py` fails when some but not all of a
group's paths appear in the diff. **This change touches the page and not the
proxy, so it lands half a group and the check exits 1** — after `tsc` and
`vitest` have already run, since it is last in the verification list.

That is a true refusal of a false problem. The group was added on 10 Sep 2026
because the proxy dropped four parameters the page was about to send: *"four
controls that appear to work and silently return unfiltered rows"*. Task 53
landed both halves, so the proxy forwards all four today and a page-only change
that introduces **no new parameter** cannot produce that failure. The group
still has work to do — a fifth filter would need both files again — but as
written it also refuses ordinary page-only work, and this is the first task to
meet that.

**The implementing task must not resolve this itself.** A cosmetic edit to
`platform/app/api/analytics/orders/route.ts` to make a check go green is
mutation to satisfy a gate, and it would land a diff whose second file has no
reason to be in it. If the group is still in the contract when this runs, the
right outcome is a branch that fails `paired_paths.py` and says why.

It is a human decision at queue time, and it is one line either way in a file
only a person can edit — `contracts/**` is protected for every fleet task. The
options, in the order I would take them:

1. **Narrow the group's `why` and keep it**, if a formulation can be found that
   distinguishes "the page sends a parameter the proxy does not forward" from
   "the page changed at all". `024_paired_paths.sql` requires two or more paths,
   a non-empty `why`, and every path inside `writable_paths`; it has no
   conditional or directional form, so this may not be expressible today.
2. **Remove the group and record why**, accepting that the hole it closed
   reopens for the next task that adds a filter parameter.
3. **Queue this together with a real proxy change**, if one is wanted anyway.
   None is needed for this feature.

## How it is checked

`console/autoqueue.py` resolves the contract by which one covers every declared
path: the single path above is writable under
`contracts/dd-analytics-frontend.yaml` and not under
`contracts/dd-acquiring-page.yaml`, so the resolution is unambiguous — which is
the discriminator `specs/auto-approval.md` §9.13 describes.

What that contract runs, in order:

    cd platform && tsc --noEmit
    cd platform && vitest run                21 files, 319 tests before this
    new_test_bites.sh                        the added test fails without the
                                             change and passes with it
    paired_paths.py                          see the section above

Budget is not the constraint: `max_diff_lines` is 600 and this is tens of
lines in one file plus a test.

## How a human checks it

Against the running app, signed in, on `/analytics/orders`:

1. Nothing clicked. The table, the pager and the summary read exactly as they
   did before the branch.
2. Click a payment method in the table. The filter control shows that value,
   the row count drops, and **the summary total drops with it**. If the summary
   does not move, the parameter is not reaching the API.
3. Every row now shown carries the value that was clicked. If any row does
   not, the click sent a different string from the one it displayed — §1.2.
4. Tab to a payment method with the keyboard and press Enter. Same result as
   the click — §2.1.
5. Find a row with no coupon. Nothing there is clickable, and clicking near it
   does not empty the table — §1.4.
6. Page to 3, then click a country. The page returns to 1 with rows on it.
7. Clear the filter with the affordance that already exists. The full
   population comes back, equal to step 1.

## Out of scope

* **A facets endpoint.** Distinct payment methods and countries with counts
  would turn the three text boxes into selects. It is the obvious follow-up, it
  is backend work, and this task is the cheap substitute that needs none.
* **Making other columns clickable.** Status has a dropdown fed by an endpoint
  that lists its values; total, date and customer are not exact-match filters
  the API accepts.
* **The order detail page** at
  `platform/app/(dashboard)/analytics/orders/[id]/page.tsx`, and the other
  analytics pages.
* **Editing `specs/metorik-gap.md`.** It is in the fleet repository, which this
  contract cannot reach.

## What was read for this spec, and what was not

`platform/app/(dashboard)/analytics/orders/page.tsx` **was not read.** The
read-only checkout this contract links at `reference/deadly-digital-platform`
is created after the agent exits, so no file in the platform repository was
open while this was written. Every path here is from the runner's own listing
of the tree, and the behavioural rules are from
`drafts/order-filters-frontend.md`, `specs/order-list-filters.md`,
`specs/auto-approval.md` §9.9 and `contracts/dd-analytics-frontend.yaml`, all
of which are in this repository and were read.

What follows from that, and it is the reason §"Where the change is not" is
written the way it is: this spec states **what the page must do** and does not
name a single identifier, hook or line inside it. Where it says "the filter
control", "the existing clear affordance" or "the same state the typed controls
use", it is describing something task 53 built and this author has not seen.
Those are the places to read the file rather than this document.
