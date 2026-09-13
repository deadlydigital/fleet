# A candidate must name paths some contract can actually write

**Status: specified, not built. A person's change — see "Why no `fleet-spec`
block" below.** Raised by specs/auto-approval.md §9.20, measured 13 Sep 2026.

## The defect, in one sentence

`contracts/checks/candidate_block_shape.py` asks whether a `suggested_paths`
entry **resolves in the tree**, when the question that matters is whether **any
contract could write it** — so a producer may emit, and the loader may accept,
a candidate no task can ever be queued for.

## What it costs today

Six of the 33 candidates ever loaded for `deadly-digital-platform` name at
least one path no contract can write. Every one of them is still `PENDING`;
not one has ever been approved, because the approval sweep re-derives the
contract and refuses. They were written on 9 and 10 September and have sat in
the pool through batches 9, 10, 11 and 13.

    c24  api/analytics/routes
    c25  platform/app/(dashboard)/segments/builder/page.tsx
    c26  api/analytics/schema_context.py, api/analytics/routes,
         platform/app/(dashboard)/analytics
    c27  api/analytics/migrations/versions
    c28  api/analytics/routes, platform/app/(dashboard)/analytics
    c35  api/analytics/migrations/versions/v0008_product_categories.py

Three shapes, and they want different repairs from the producer:

1. **A directory where a file belongs** — `api/analytics/routes`,
   `platform/app/(dashboard)/analytics`. A contract makes *files* writable; a
   directory matches no glob and never will.
2. **A file outside every boundary** — c25's segment builder, c26's
   `schema_context.py`. Plausible paths that nothing may write.
3. **A path on the protected floor** — c27 and c35, both under
   `api/analytics/migrations/**`. Refused however the work is scoped.

Until 13 Sep the brief reported all six as `older_batch`, because gate 2 fired
first and the gates short-circuit. Removing gate 2 made them report
`unwritable_path` and `protected_path` instead. That is the noticing; this is
the fixing.

## What the check asks now

`check_candidate`, in the `suggested_paths` branch:

```python
missing = [p for p in paths
           if not (repo / str(p)).exists()
           and not (repo / str(p)).parent.exists()]
```

`api/analytics/routes` **exists** — it is a real directory — so the block
verifies, the batch loads, and the row is unbuildable from the moment it is
written. The check is not wrong about what it asks; it asks the wrong thing.

## What it should ask instead

> A suggested path is buildable when **at least one contract for that repo
> makes it writable and does not protect it.**

One predicate, and it covers both failures the approval sweep finds separately
(`unwritable_path` at gate 6, `protected_path` at gate 5). Keep the existing
resolves-in-the-tree test as well — it catches a different error, an invented
filename — and report the two separately, because "this path does not exist"
and "nothing may write this path" send the producer to different repairs.

**Verified before proposing.** Run over the live pool against the yaml alone,
this predicate flags exactly `{24, 25, 26, 27, 28, 35}` and exactly the paths
listed above — the same rows and the same paths the database-backed gates
refuse. It neither over- nor under-reports on the only evidence available.

## What it needs to read, and why it can

Two lists, both already on disk, **neither of them in the database**:

* `writable_paths` from every `contracts/*.yaml` whose `repo:` matches.
* `protected_paths` from the same file. This matters: the floor lives in
  `protected_path_floor` in the database, which a check may not reach and
  should not start reaching (specs/auto-approval.md §9.12), **but it is
  generated into every contract file rather than typed** — all seven platform
  contracts carry it. Reading it from the yaml is reading the floor, not a
  copy of it.

Per-contract rather than a single merged floor, deliberately: contracts
protect *more* than the floor where they choose to — `dd-infra.yaml` also
protects `api/analytics/routes/interventions.py` — and the per-contract form
answers the real question without needing to know which contract a task would
eventually run under.

The check already reaches into the fleet checkout for exactly this kind of
fact: `objective_ids()` does `sys.path.insert(0, str(FLEET))` and imports
`proposer.objectives`. This would be the same move.

## How to get the predicate, and the trade

`console/rank.contract_writables(repo)` already reads the `writable_paths`
half, and `rank._inside(path, globs)` is the prefix matcher. `console/rank.py`
imports only stdlib and `yaml` — no `psycopg`, no `console.db` — and
`console/__init__.py` imports nothing, so importing it does not drag a
database dependency into a check.

**Recommended: import them, inside the function body, the way `objective_ids`
does.** `contract_writables` returns `(name, writable_globs)` and would need a
third element for `protected_paths`, or a sibling function beside it.

One wrinkle, stated because it will look like a bug later: `rank._shape_check()`
loads this file **by path** via `importlib`, so once this file imports
`console.rank` there will be two module objects for the shape check in a
process that uses both. Harmless — the check is pure functions over paths —
but it is the kind of thing that reads as a mistake at 2am.

**If you would rather copy the eight lines than import them**, that is
defensible and there is precedent — `rank._inside` is itself a deliberate copy
of `autoqueue`'s matcher. But read `rank._inside`'s docstring first: the copy
is acceptable *only* because a test asserts the two agree on the paths that
matter. A third copy without that test is how these three drift into three
different answers about the same path.

## Where the refusal should land

On the **producer's own verification**, before the row is loaded — the same
place a failing probe lands today. The repair there is "name the file you
mean", and the producer is the only thing that can name it. A producer run
that fails is cheaper than a candidate that cannot be built, because the
candidate costs a person's attention every morning until somebody looks.

## What is NOT proposed

**Teaching the producer to widen a contract.** A path outside every boundary
is sometimes a real answer — c25's segment builder is plausible work — and the
response is a contract a person wrote, not one the producer negotiated for
itself.

**Retiring the six existing rows.** They are evidence of this defect until it
is fixed, and the next producer run will re-emit the work that is still real.

## Why no `fleet-spec` block

No task this system can queue may make this change. `contracts/**` is on
`protected_path_floor` for `fleet`, and the only two fleet contracts that write
anything write `research/**` and `drafts/**`. The check that judges the work is
exactly what the floor exists to keep out of the agent's hands —
`contracts/draft-spec.yaml` says so in as many words. This is a person's
change, by hand, and a `fleet-spec` block here would only produce a refusal at
accept time.

## Done when

* A candidate block naming `api/analytics/routes` fails
  `candidate_block_shape.py` with a message naming the path and saying no
  contract makes it writable.
* A candidate block naming `api/analytics/migrations/versions/...` fails with a
  message naming the protected floor — a different message, not the same one.
* A candidate naming a path some contract writes and does not protect still
  passes.
* The existing resolves-in-the-tree test still fires on an invented filename,
  under its own message.
* If the matcher was copied rather than imported, a test asserts the copy and
  `rank._inside` agree on at least the six paths above.
