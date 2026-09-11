# Segmentation: seven fixed RFM buckets, or attribute-based?

**Decision document. Written 2026-09-11**, from the `deadly-digital-platform`
checkout as it stood on that date, and from the fleet evidence packs
`research/EVIDENCE-metorik.md` (generated 2026-08-30 14:20 UTC) and
`research/metorik-gap-2026-08-30.md`. It answers the candidate raised in
`research/candidates-metorik-gap-2026-09-09.md` under *"Segment orders and
products, not only customers into seven fixed RFM buckets"*, which is the
Daily-band row of `specs/metorik-gap.md` with the widest gap on the document.

No code was changed. No database was read — the contract that queued this task
carried no `evidence_queries`, and the consequences of that are in the last
section.

## 1. Can the email side's rule builder express analytics filters?

**No.** The read that the gap list left open has a negative answer, and the
decision does not get cheaper as a result. There is no reusable grammar on the
email side to point analytics at.

The draft spec for this task recorded five findings from a partial read and
asked that each be confirmed at line level or overturned. Two are confirmed as
written, one is confirmed with a **different mechanism** than the draft named,
and two are **overturned in the direction of worse**. Taking them in order.

### 1.1 Finding one is overturned: there are three evaluators, not two

The builder at `platform/app/(dashboard)/segments/builder/page.tsx` writes a
JSON `conditions` blob (`{combinator, rules[]}`, declared at lines 32–35) and
posts it to `/api/segments` at line 173. Three separate pieces of code read
that blob back and compile it:

1. `platform/app/api/segments/preview/route.ts`, `buildListmonkSQL` at lines
   5–68, which compiles it to a Listmonk SQL string over `subscribers.attribs`.
2. `platform/app/api/segments/refresh/route.ts`, a near-duplicate
   `buildListmonkSQL` at lines 4–43 — the draft did not find this one. It
   differs from the preview copy by dropping the `contains` operator (compare
   `preview/route.ts:59` with the switch at `refresh/route.ts:29–39`).
3. `query_segment_customers` at `api/app.py:7942`, which compiles it to
   SQLAlchemy filters over the `Customer` model in the **public** schema.

None of the three reads an `analytics_<tenant_id>` schema, which is the part of
the draft's finding that stands. But the third implementation matters for
costing: `refresh/route.ts` is the code that writes `segments.customer_count`
and `segments.last_synced_at` back (line 68), so the number a user sees beside
a saved segment on `platform/app/(dashboard)/segments/page.tsx:200` comes from a
different evaluator, over a different data store, than the list that
`sync_segment` actually mails. Two writers, one column, two populations.

### 1.2 Finding two is confirmed: the vocabulary is seven customer attributes

`PROPERTY_FIELDS` at `platform/app/(dashboard)/segments/builder/page.tsx:71–79`
offers `total_spent`, `order_count`, `avg_order_value`,
`days_since_last_order`, `rfm_segment`, `is_vip` and `is_repeat_customer`.
`EVENTS` at lines 37–45 adds seven tracked events with per-event property
filters at lines 47–69. There is no order attribute, no product, no coupon, no
cart, no subscription. The email side is customer-only. **It does not narrow
the resource half of the gap at all**, and that is the half Metorik's claim
turns on.

### 1.3 Finding three is confirmed: the AND/OR is flat

`Conditions` carries one `combinator` over one flat `rules` array (lines
32–35). All three evaluators join with a single separator and cannot nest:
`preview/route.ts:67`, `refresh/route.ts:42`, and `api/app.py:7999–8005`, which
wraps the whole filter list in one `and_()` or one `or_()`. Metorik's claim is
AND/OR *groups*. Nothing here nests, and nothing is one edit away from nesting.

### 1.4 Finding four is confirmed, but not for the reason the draft gave

The draft said six of the seven `PROPERTY_FIELDS` resolve to nothing. For
`query_segment_customers` that is exactly right. `Customer` at `api/app.py:744`
carries `total_spent` (758), `total_orders` (757), `average_order_value` (759)
and `last_order_date` (761). Of the builder's seven names only `total_spent`
matches a column; `order_count` and `avg_order_value` are near-misses for
columns that exist under other names, and `days_since_last_order`,
`rfm_segment`, `is_vip` and `is_repeat_customer` exist nowhere on the model.
`getattr(Customer, field, None)` at `api/app.py:7977` returns `None` and line
7979 silently `continue`s.

The operator vocabularies differ too, though less starkly than the draft said.
The builder emits nine operators (`OPERATORS`, lines 81–86); the sync path
handles eight (`api/app.py:7982–7997`), and the overlap is five. `=` is not
handled — the sync path spells equality `==` — and neither are `contains`,
`is_true` or `is_false`. So `total_spent = 500`, a rule whose *field* resolves,
is still dropped for its operator. The key differs as well: the builder writes
`combinator: and|or`, `query_segment_customers` reads `match: all|any` and
defaults to `"all"` at `api/app.py:7960`. **Every OR segment syncs as an AND.**

Where the draft was incomplete: the two SQL evaluators map all seven names onto
`subscribers.attribs` keys (`preview/route.ts:37–48`,
`refresh/route.ts:19–27`), and those keys **do** have a writer.
`platform/app/api/sync/subscriber-attribs/route.ts` computes and PUTs exactly
that attribute set to Listmonk at lines 190–210, including `rfm_segment`,
`is_vip`, `is_repeat_customer`, `order_count`, `avg_order_value` and
`days_since_last_order`. On that reading the preview path is coherent and only
the Python path is broken.

It does not survive the next step. That writer's two queries select
`o.email_optin` and `o.sms_optin` (lines 130–131, and lines 40–41 in the GET),
and migration
`api/alembic/versions/20260129_1400_81f250d288c2_add_deliverability_monitoring_tables.py`
drops both columns from `orders` in `upgrade()` at lines 138–139 — they are
re-added only in `downgrade()` at 303–304. `platform/lib/db.ts` points the
Next.js pool at the same `DB_HOST`/`DB_NAME` the API uses, so this is the same
`orders` table. Post-migration both handlers raise `UndefinedColumn`, are
caught by their own `try`/`catch`, and return a 500 with zeroed stats. **The
only writer of six of the seven attributes is dead code.** The draft's
conclusion holds; the repair it implies is different, because the fields are
not merely unmapped, they are unpopulated.

### 1.5 Finding five is confirmed and is worse than stated

There are three RFM implementations with three name vocabularies:

| Implementation | Method | Names it can emit |
|---|---|---|
| `compute_rfm_segments`, `api/analytics/services/segment_engine.py:40` | `NTILE(5)` quintiles, 180-day lookback | Champions, Loyal, Potential Loyalists, At Risk, Hibernating, Lost, New |
| `subscriber-attribs/route.ts` POST, lines 156–188 | absolute thresholds, 3-digit score → lookup table | Champions, Loyal Customers, Lost, Other |
| `subscriber-attribs/route.ts` GET, lines 65–72 | a third `CASE` ladder over the same metrics | Champions, Loyal Customers, New Customers, At Risk, Lost, Other |

The builder's `rfm_segment` select (line 76) offers seven options. The POST
writer's `RFM_SEGMENTS` map (lines 157–161) has eleven entries covering four
distinct names out of 125 possible score combinations; everything else falls to
`'Other'`. So *Potential Loyalists*, *New Customers* and *At Risk* are options
the UI offers that **no writer on the platform can ever produce**, even if the
writer were alive. And the GET ladder that paints the "RFM Segments" cards on
`platform/app/(dashboard)/segments/page.tsx:221` uses different rules again, so
the distribution a user reads and the attribute a user filters on have never
agreed.

### 1.6 A dropped rule returns every customer, and sync mails them (severity)

Requirement 1.2 of the draft asked whether this is real. It is.
`query_segment_customers` starts the query with only the tenant predicate
(`api/app.py:7956`), accumulates `filters` (7962), and applies them **only if
the list is non-empty** (7999). A segment whose every rule was dropped — which
is any segment built from the six unresolvable fields, or any using `=`,
`contains`, `is_true` or `is_false` — reaches `return query.all()` at 8007 with
no `WHERE` and returns the tenant's entire customer table.

`sync_segment` at `api/app.py:7893` takes that list at 7909, writes
`len(customers)` to `customer_count` at 7912, and at 7919–7932 loops it calling
`create_subscriber(..., lists=[segment.listmonk_list_id])`. There is no cap and
no sanity check. A segment reading *"Is Repeat Customer is true"* — the
builder's own **Repeat Buyers** preset, at line 99 — enrols the whole customer
base on the segment's Listmonk list. The same function is reached from
`api/worker.py:1586` and `api/worker.py:2830`.

Two related one-liners, recorded and not pursued: `refresh/route.ts` has no
`getServerSession` check at all (compare `preview/route.ts:72–73`) and its
`SELECT id, conditions FROM segments WHERE is_active = true` at line 52 has no
tenant predicate; and both SQL evaluators interpolate rule values straight into
the query string (`preview/route.ts:53–62`). **These need their own task.**
They are not design inputs and nothing below depends on them.

I have not proposed a fix to any of it. That is section 4's job.

## 2. What analytics segmentation can express today

### 2.1 The taxonomy is closed at three layers

Changing one and not the others is the obvious wrong build, so all three:

1. `VALID_SEGMENTS`, a seven-element literal at
   `api/analytics/services/segment_engine.py:29–37`.
2. `_validate_segment_name` at `api/analytics/routes/segments.py:29–36`, which
   returns 400 for any name outside that list, guarding all three routes
   (lines 60, 77).
3. The `CASE` ladder inside `compute_rfm_segments`
   (`api/analytics/services/segment_engine.py:118–135`), the only writer of
   `customer_segments.segment_name`.

Nothing derives any of the three from the others. Beyond them, the name is read
by `analytics_engine.py`, `api/analytics/services/gdpr.py` (it goes into the
subject-access export), `api/analytics/routes/setup.py`, `api/worker.py`, the
backfill script, and two frontend pages under
`platform/app/(dashboard)/analytics/segments/`. A taxonomy change is a
nine-file change before anyone writes a filter.

### 2.2 The scores are quintiles of a population, not thresholds

`compute_rfm_segments` computes `NTILE(:ntile_n)` over recency, frequency and
monetary within a 180-day lookback
(`api/analytics/services/segment_engine.py:106–108`), restricted to orders with
status `completed` or `processing` (line 26, applied at 95), with `New`
overriding on a 30-day first-order window (line 120) and a default fallback of
`Hibernating` (line 134).

**For a user this means the buckets are relative.** A store's Champions are its
own top quintile by construction; the boundary moves whenever the population
moves, and the bucket is never empty and never large. Two stores' Champions are
not comparable, and the same customer can leave Champions without doing
anything differently. An attribute-based model replaces that with absolute
thresholds the user chooses — *"spent over £500 and has not ordered in 90
days"* — where the boundary is stable, the set can be empty, and the definition
means the same thing next month.

**These answer different questions and neither subsumes the other.** Quintiles
answer *how is my customer base distributed*. Absolute filters answer *give me
this list so I can act on it*. This is the substance of the decision, and it is
why a naive migration of the seven names into seeded filter definitions loses
information rather than preserving it — there is no absolute threshold that
means "top quintile".

### 2.3 What is segmentable at all, and where a real filter grammar could seed

Only customers, and only via the precomputed
`analytics_<tenant_id>.customer_segments` table (`api/analytics/models.py:193`),
read through `get_segment_summary`, `get_segment_customers` and
`export_segment_csv`. Everything else in the analytics schema — orders, order
items, products, product categories — is reportable but not segmentable, and
**coupons, carts and subscriptions have no table at all**: the model list in
`api/analytics/models.py` declares thirteen tables and none of them is one of
the three.

The draft asked whether `api/analytics/services/order_query.py` is the real seed
of a filter grammar. Read at line level, the answer is **in discipline yes, in
shape no.**

`list_orders` (lines 78–94) takes seven filters: a date range, `status`,
`search`, `payment_method`, `country`, `coupon` and `has_discount`. Each is a
named keyword argument with a hand-written `where.append` and a bound parameter
at lines 125–151, and the clauses are joined with `" AND "` at line 155. So:

* **It is a fixed list, not composable.** One value per filter, no repetition,
  no negation, no per-filter operator. Adding a filter means editing the
  signature, the body, and the route signature in
  `api/analytics/routes/orders.py:54–73`.
* **It has no OR.** The join at line 155 is the only combinator, and it is
  literal.
* **But every value is bound, the sort column comes from the `_SORTABLE`
  allow-list (lines 56–61), and every sort closes on the primary key** for a
  total order under `LIMIT/OFFSET`. The summary reports both the all-status and
  revenue-status populations, named, rather than one ambiguous count
  (`_summary`, lines 211–223).

That is exactly the engineering a filter grammar needs and exactly the opposite
of what the email evaluators do. If anything on this platform is the seed, it
is this file — but what it seeds is a *method*, not a data structure. The step
from here to a grammar is replacing seven keyword arguments with a field
registry and a predicate list. That is a bounded change. The step from
`conditions` JSON to a grammar is a rewrite with three call sites to migrate.

## 3. Three options, on the same axes

Costs are engineering-day **bands**, not estimates. They are meant to be
argued with.

### 3.1 Keep the seven buckets

**User gains:** nothing. **Build cost:** zero. **Breaks:** nothing.
**Forecloses:** nothing technically, but the Daily row stays Red and it is the
row an evaluation tests first.

What an agency evaluating DD cannot do, in their words:

> "Show me everyone who bought the Rolex competition twice and hasn't been back
> in 90 days." — *Not expressible; product is not a customer attribute.*
> "Save that as a list I can send to every month." — *No user-defined segment
> exists; the seven are computed, not saved.*
> "Export it." — *One CSV route exists on the whole analytics API and it emits
> one of seven fixed buckets with a fixed ten-column header
> (`api/analytics/routes/segments.py:70`).*
> "Your 'Champions' isn't my definition of a champion." — *Correct, and not
> changeable; it is a quintile, per 2.2.*
> "Show me orders paid by Klarna that used a discount, in one saved view." —
> *The filters exist as URL parameters and cannot be saved or combined with OR.*

### 3.2 Attribute-based segmentation, customers only

A filter grammar over customer attributes, persisted definitions, evaluated
against `analytics_<tenant_id>.customers`.

**User gains:** the second, third and fourth lines above. This is the
difference between a dashboard and a tool an agency uses on Monday morning.

**Build cost — medium band.** Field registry over the customer columns plus
derived recency; a predicate compiler with bound parameters and nesting; a
persisted definition (new table, therefore a migration); count, paginated list
and CSV export — but those three re-use the shape
`api/analytics/routes/segments.py` already has, which is real savings; a
builder UI; and the definition has to be evaluated somewhere on a schedule if
counts are to be cached the way `customer_segments` is.

**What breaks:** nothing, if the seven names are left alone. **What happens to
the seven** is the question this option must answer, and per 2.2 the honest
answer is that they should *not* become seeded definitions, because a quintile
is not a threshold and the seeded version would silently mean something else.
They should survive as what they are — a distribution view — alongside saved
definitions as a worklist feature.

**Migration this option owns:** the `rfm_segment` field on the email side.
Today it points at a string that three implementations disagree about (1.5). If
analytics gains user-defined segment names, that field points at a fourth
namespace. This option owns deciding whether the email builder's `rfm_segment`
resolves against analytics names or is retired.

**Forecloses:** nothing, *provided* the grammar is written resource-generic —
field registry keyed by resource — even though only one resource is wired up.
Writing it customer-shaped is the way this option forecloses 3.3, and it is a
design discipline, not extra cost.

### 3.3 Attribute-based segmentation across resources

The full Metorik claim. Broken down, because a single number is not a costing:

| Component | Band | Note |
|---|---|---|
| Filter grammar (shared) | small–medium | Same work as 3.2; done once |
| Persistence + migration (shared) | small | Same as 3.2 |
| Evaluator: customers | small | Table exists, columns populated |
| Evaluator: orders | small | `api/analytics/services/order_query.py` already does two-thirds of it |
| Evaluator: products | medium | Table exists; see the attribute problem below |
| **Resource: coupons** | **large** | *No table.* Ingest, backfill, reconcile, then segment |
| **Resource: carts** | **large** | *No table, no ingest.* Abandoned carts are a data-collection project before they are a filter |
| **Resource: subscriptions** | **large** | *No table.* Same |
| UI (builder, per resource) | medium | AND/OR groups is the hard part and it is one component, not five |
| Count + export + saved-view paths per resource | medium | Every existing segment surface has all three; five resources means five of each |

Two of Metorik's six resources are a data project before they are a
segmentation project, and a third — coupons — is one on a store where
`research/EVIDENCE-metorik.md` records **65,444 distinct coupon codes across
2,846,280 orders** on tenant 2. That is a per-entry code generator, not a
promotions programme; a coupon-as-resource filter would return a list of
65,444 things nobody wants to segment.

**Forecloses:** budget. This is the most expensive item on the gap document and
it would consume the cycles that close three or four Red rows elsewhere.

### 3.4 The convergence cost, as its own line

Whatever is chosen, the two segment surfaces disagree today. Merging them is:
collapsing three `conditions` evaluators to one; reconciling three RFM name
vocabularies to one; either reviving or deleting the dead attribute writer in
`subscriber-attribs/route.ts`; and re-pointing the builder's seven fields at
whatever the surviving vocabulary is. **Medium band on its own.**

This belongs to 3.2 and 3.3 and **not** to 3.1 — under 3.1 the two surfaces
simply stay separate, which is the state they are in. It should never be folded
into either total. The severity finding in 1.6 is unconditional and belongs to
none of them: it must be fixed whichever option wins.

## 4. Recommendation

**Take 3.2 — attribute-based segmentation for customers only, built on the
analytics schema with a resource-generic grammar, and keep the seven RFM
buckets as a distribution view rather than migrating them into seeded
definitions.**

Three reasons, in order of weight.

**The store data says so (4.2).** `research/EVIDENCE-metorik.md` gives tenant 2
2,846,280 orders with **two** distinct billing countries, nine payment methods,
`tax_total > 0` on **zero** rows, `shipping_total > 0` on **zero** rows, and
four refunded orders; `dd_order_status_breakdown` puts 2,845,479 of those
orders in `completed`. Tenant 1 has 679,912 orders and four refunds. An
order-attribute grammar over these two stores would offer filters that are
almost all constant — and the handful that discriminate (date, total, coupon,
payment method, `utm_source`, which is populated on 100% of rows on both
tenants) are **already exposed** as query parameters at
`api/analytics/routes/orders.py:58–68`. Meanwhile the customer side has
something to segment: `specs/metorik-gap.md` records all seven RFM buckets
populated on tenant 2 as of 2026-08-28. Products are worse than orders — no
COGS, no stock, no variation parent (`research/metorik-gap-2026-08-30.md`, rows
25 and 26). **A segmentation model whose most-used attributes are constant on
both live tenants is a worse recommendation than a narrower one whose
attributes vary**, and that is the whole of the case against 3.3 here.

**3.1 is not stable.** Zero cost is only zero if nothing moves, and 1.6 means
something must move anyway. Once the segment surfaces are being touched, the
marginal cost of 3.2 is the grammar and the UI, not the whole of 3.4.

**3.2 is the only option that converts the existing investment.**
`api/analytics/routes/segments.py` already has count, paginated list and CSV
export over a named customer set. 3.2 changes what defines the set and reuses
all three. 3.3 needs five copies of them.

### 4.1 The email builder is a warning, not a foundation

This is the crux and it should not be left implicit. **Do not adopt the
`conditions` JSON shape as the grammar.**

Adopting it means adopting: a flat combinator that three evaluators join
literally and none can nest (1.3); a rule union of `property` and `event` where
the event half has no evaluator in the Python path at all; a field vocabulary
that was written against no schema, six of whose seven names resolve to nothing
in one evaluator and to a dead writer in the other two (1.4); a `combinator`
key that one reader spells `match` with inverted values (1.4); and a
value-interpolation habit that puts unescaped user strings into a SQL string
(1.6). The parts that are worth keeping are the `segments` table and its
`conditions` JSONB column as a *place to persist a definition* — that is a
column type, not a grammar.

What *should* be adopted is the method in
`api/analytics/services/order_query.py` (2.3): an allow-list of fields, bound
parameters for every value, a total order on every paginated read, and
populations named rather than implied. A grammar is a field registry plus an
operator registry plus a predicate tree, and the registry half of that already
exists there in longhand. Extending it is the cheap direction. Reusing
`conditions` inherits a vocabulary nobody ever checked against a schema and
three call sites that would all have to be migrated first — that is 3.4's cost
paid up front for a worse starting shape.

### 4.2 What would change my mind

**The named condition: a census of `public.segments`.** If that table holds a
material number of active segments whose `conditions` use the six unresolvable
fields, and whose linked Listmonk lists have been mailed, then 1.6 stops being
a severity finding and becomes an incident, and the right first move is
repairing the email side — not building a new capability beside it. In that
world 3.1-plus-repair is correct for at least one more cycle and this
recommendation is wrong. **I could not run that query** (see below), so I am
recommending 3.2 under the assumption that the number is small. That assumption
is falsifiable in one `SELECT` and should be tested before anything is queued.

A second, weaker condition: if a tenant arrives whose store has real product
data — variations, COGS, stock — the product evaluator in 3.3 stops being
worthless and the balance shifts toward the fuller build. Neither current
tenant is that store.

## 5. The first buildable task, and its contract

**The first step of the recommendation does not fit any contract in
`contracts/`, and that is a finding.** 3.2 needs a persisted definition, which
needs a table, which needs a migration. Every platform contract on the floor
protects `api/analytics/migrations/**` explicitly —
`contracts/deadly-digital-platform-api.yaml:145`,
`contracts/dd-order-filters.yaml:27`, `dd-analytics-frontend.yaml:159`,
`dd-acquiring-page.yaml:30`, `dd-utm-source-alias.yaml:39`,
`dd-docstring-proving.yaml:48`. Queueing the real first step therefore requires
a *new* contract that unprotects the analytics migration tree for one task,
which is a fleet-side decision about blast radius and not something a code task
can take on its own. **That is the honest answer to requirement 5**, and it is
the thing that tells a reader this candidate is not one task away from being
built.

The largest thing that does fit, is worth queueing alone, and is not wasted
under any of the three options:

> **Let `list_orders` accept multiple values per filter.** `status`, `country`,
> `payment_method` and `coupon` today take one exact value each
> (`api/analytics/services/order_query.py:128–147`). Accepting a repeated query
> parameter and emitting `IN (...)` with bound parameters is the smallest real
> step toward a predicate list, and it is a user gain on its own — *"completed
> or processing"* is the first thing anyone asks the order list for.

**Contract: `contracts/deadly-digital-platform-api.yaml`.** Both files it
touches — `api/analytics/services/order_query.py` and
`api/analytics/routes/orders.py` — are in its `writable_paths` (lines 134 and
117). It needs no migration, no frontend, and no new table. It is *not*
`contracts/dd-order-filters.yaml`: that contract's acceptance check
`order_filters_shape.py` is pinned to the shape the previous task delivered, so
a task changing that shape belongs under the wider api contract with a check of
its own.

Under 3.1 this improves the order list, which Metorik has either way. Under 3.2
it is unrelated but harmless. Under 3.3 it is the first brick of the order
evaluator. It is also the only first step here that survives the decision being
reversed.

## What I could not verify

* **How many segments exist, and what they use.** The contract that queued this
  task carried no `evidence_queries` and the research agent has no shell and no
  credential, so `public.segments` was never read. The document can say the
  sync path drops rules; it cannot say how many live segments are affected.
  That number is the difference between a severity finding and an incident, and
  it is also the named condition in 4.2 under which this recommendation is
  wrong. **Whoever queues the follow-up should add it**: `public.segments`
  grouped by tenant, with the `conditions` column.
* **Whether migration `20260129_1400_81f250d288c2` has actually run in
  production.** The whole of 1.4's conclusion about the dead attribute writer
  depends on `orders.email_optin` being absent. I read the migration; I could
  not read the database to confirm it was applied, or that no later migration
  restored the column.
* **Whether an event rule crashes `sync_segment` outright.** Event rules carry
  no `field` key, so `rule.get("field")` at `api/app.py:7964` is `None`, and on
  my reading `getattr` type-checks its name argument before consulting the
  default — making `getattr(Customer, None, None)` a `TypeError` rather than a
  silent skip. If so the builder's own **Cart Abandoners** and **Active
  Browsers** presets produce segments that 500 on sync rather than mailing
  everybody. I could not execute anything under this contract to confirm which
  of the two failure modes it is. Both are bugs; they need different fixes, so
  the task in 1.6 should establish it first.
* **Whether `platform/app/api/segments/refresh/route.ts` is ever called.** It
  has no caller in the checkout outside `docs/TEST-AUDIT.md:262`. An external
  cron could be hitting it; I have no way to see one from here. That matters,
  because unauthenticated and untenanted it would be worse live than dormant.
* **The cost bands in section 3.** They are argued from component counts and
  from what exists in the tree, not from any measured velocity. Treat the
  *relative* ordering as the claim and the absolute bands as a prompt to
  disagree.
* **Nothing in this document was checked against Metorik's own product.** The
  feature claims attributed to Metorik come from
  `research/metorik-gap-2026-08-30.md`, which recorded them with its own
  retrieval dates. No page was fetched on 2026-09-11.
