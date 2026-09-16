# Parked: platform defects no unattended contract can fix

**Started 14 September 2026.** A sibling to `specs/parked-connector-defects.md`,
which parks defects that need the connector plugin source. This one parks
defects in `deadly-digital-platform` itself whose *correct fix cannot be
expressed as unattended work* — so they will sit here, visible, rather than
being turned into candidate rows that no task can satisfy.

## What puts a defect here rather than in a candidate batch

Every code contract on the platform requires `new_test_bites.sh`: one added
test that fails before the change and passes after. That is the right rule and
it is not the thing to loosen. But it cannot be met by a change whose correct
form is a **deletion** — there is nothing to assert about code that is gone,
and a test written to pass once the file is absent is a test written for the
gate rather than for the reader.

So: if the honest fix is "delete this", or is otherwise outside what a contract
can be written to accept, it belongs here and a person does it by hand.

**THE GENERAL FORM, NAMED 16 September 2026 because a second instance arrived
that is not a deletion.** The class is: *work whose correct form requires
editing a file its own contract PROTECTS.* A deletion is one shape of it — the
gate demands an added test and the change removes the thing to test. Entry 2 is
another: the change is a deliberate correction to a number, and a protected
test asserts the old number on purpose.

It is worth separating from the three blockers that get confused with it,
because none of the usual remedies touches it:

| Blocker | What moves it |
|---|---|
| The migration floor | A migration contract wider than `CreateIndexStep` |
| A data-collection project | Somebody collects the data |
| A contract's diff ceiling | A bigger number, or splitting the task |
| **A protected file the fix must edit** | **Nothing here. Not budget, not attempts, not a bigger cap.** |

That last row is why these are parked rather than queued. A candidate for one
of them is a row a human will approve, a spec task will describe and a work
task will fail — the first three cost money and produce something; this one
cannot produce anything, ever, under the contract that would run it.

This file is not a backlog of everything unfixed. It is specifically the set
where **the machine is structurally the wrong tool**, which is a much smaller
set and worth keeping separate for that reason.

---

## 1. The segment-detail proxy is dead code that would 500 if anything called it

**Found 13–14 September 2026** by the batch 15 producer run (task 90), which
recorded it in §5 of `research/candidates-metorik-gap-2026-09-14.md` and
deliberately did **not** emit it as a candidate, on the grounds above. Every
claim below was re-verified by hand against `deadly-digital-platform` at
`ab65311`.

**The file:** `platform/app/api/analytics/segments/[name]/route.ts`

It fetches the CSV export endpoint and parses the response as JSON:

```ts
const res = await fetch(`${BACKEND_URL}/api/analytics/segments/${encodeURIComponent(name)}/export`, ...)
const data = await res.json()
return NextResponse.json(data, { status: res.status })
```

**Three things are true about it, each checked:**

1. **It parses CSV as JSON.** `/api/analytics/segments/{name}/export` returns
   `text/csv` — it is one of only two `text/csv` endpoints in the whole
   analytics API. `res.json()` on that body throws, the `catch` swallows it,
   and the caller gets `500 {"error": "Failed to fetch segment detail"}`.

2. **There is no endpoint it could have meant.**
   `api/analytics/routes/segments.py` declares exactly three routes: `""`,
   `/{segment_name}/customers` and `/{segment_name}/export`. There is no
   segment-detail route on the API at all, so this proxy has never had a
   correct target.

3. **Nothing calls it.** The segment detail page
   (`platform/app/(dashboard)/analytics/segments/[name]/page.tsx`) fetches
   `/api/analytics/segments/{name}/customers` and
   `/api/analytics/segments/{name}/export`, never the bare path. The two other
   references to that URL shape in the app are `router.push` page navigations,
   not fetches. So no merchant can currently reach the 500.

It reads as a copy of the sibling export proxy with its CSV handling removed.

**The fix is to delete the file**, and that is why it is here: `new_test_bites`
cannot be satisfied by a deletion. Deleting it removes a route that can only
ever fail, and removes the trap that the next person to build a segment-detail
page would otherwise inherit — a proxy that looks like it exists and works.

**If instead a segment-detail endpoint is wanted**, that is ordinary candidate
work and does not belong in this file: it needs a route on the API first, and
then this proxy rewritten to call it. The defect and the feature are separate
decisions and only the first one is parked here.

---

## 2. The sources page and the LTV distribution can disagree, and the guard that would catch it is the thing the fix must edit

**Found 16 September 2026**, landing task 62's work by hand. Recorded at the
helper in `api/analytics/services/analytics_engine.py`, where a reader meets it.

`analytics/routes/sources.py` computes its per-source `average_ltv` from
`customers.total_spent`. `GET /customers/ltv`, shipped in the same session,
computes lifetime value from the orders themselves via `lifetime_spend_sql()`.
**They are two numbers for one quantity and they can disagree** — by exactly the
drift the stored column carries, which is what task 62's own 4.1 block exists
to measure.

Task 62's spec asked for this in requirements 5.1 and 5.2: sources uses the
shared helper, and its 365-day lookback does not change. The branch did it in
seventeen lines. **That hunk was not taken, and the requirements are recorded
as DEFERRED rather than met.**

### Why it cannot be landed by a task

`16e1d8a` — *"perf(sources): the LTV panel ranked every order to keep 24% of
them"* — added `api/tests/analytics/test_sources_ltv_window.py`. It reproduces
the pre-optimisation sources query in full and requires the shipped query to
return identical rows:

> *If the two ever disagree, the bounded form has changed the answer and not
> merely the cost — which is the only claim the rewrite makes.*

That guard is correct and it is doing its job. 5.1 is a **deliberate** change of
the answer, so the guard fires. Measured against one running database, minutes
apart: base `7 passed`; the same file with the sources hunk applied,
`1 failed, 6 passed`, an `AssertionError` on row sets. Not an environment
artefact, and not the `public.utm_source_alias` warning that appears beside it
in the output — that is logged on the base too.

Making both true means editing the guard's reference query so it computes what
5.1 computes. `api/tests/**` is protected by
`contracts/deadly-digital-platform-api.yaml`, whose `creatable_paths` admits
`api/tests/analytics/test_fleet_*.py` and nothing else. **So no task under that
contract can make this change correct — not at a higher cap, not on a third
attempt, not with a longer timeout.**

### What would unpark it

A contract that can write both `api/analytics/routes/sources.py` and
`api/tests/analytics/test_sources_ltv_window.py`, and whose acceptance can
express *"this changes an existing figure on purpose, and here is the guard
updated to the new definition with the old one recorded"*. That is a different
shape of task from anything in `contracts/` today: every existing one either
forbids touching an existing test or has no business near a guard.

**It is deliberately NOT a candidate.** A candidate here is a row somebody
approves, a spec task describes, and a work task fails — which is what already
happened once. When such a contract exists, queue it then; the work is
seventeen lines of query plus a reference query in the guard, and both are
written down: the query is on `fleet/task-62.2` at `d564126` and the guard is
on `main`.

### What is true today, so nobody reads this as fixed

The sources page still reads `customers.total_spent`. `/customers/ltv` reads
the orders. A merchant comparing the two can see different numbers for the same
customer, and neither surface says so.
