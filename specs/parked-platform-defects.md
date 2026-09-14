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
