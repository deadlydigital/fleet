# Verification collects its evidence before it refuses

**NOT APPLIED. This is a proposal and a recommendation, not a description of
the runner as it stands.** `runner/verify.run` stops at the first failing check
today, and nothing in this document changes that until somebody decides it
should.

**The recommendation, up front: run every check regardless of the first
failure. Do not reorder them by cost.** What that costs, measured, is in §4.

---

## 1. The finding

`runner/verify.run` runs each command in turn and stops at the first failure.
Its own comment gives the reason:

> Stopping early is deliberate: the second command's output is not evidence
> about a tree the first command already rejected, and the wall clock is better
> spent ending the tick.

On 13 Sep 2026, task 87 was refused at 21:03:17 by
`contracts/checks/spec_requirements_cited.py`, exit 1 in 72ms. That is the
whole of what run 62 recorded: one check. `tsc --noEmit`, `vitest run`,
`new_test_bites.sh` and `proxy_passthrough.py` never ran against that branch,
that night or since.

The citation failure was real and small — `spec:6.` at the head of a test file,
where the checker's `(?<![\w.])spec:6(?![\w.\d])` rejects the sentence-ending
full stop. It was fixed by hand the same evening, one character, and everyone
involved then believed the branch was done.

It was not. Run the contract's checks against that branch and the third one
fails: `test_fleet_net_revenue.test.tsx:218` asserts
`screen.getByText('£0.00')`, which throws when it matches more than one
element, and on that fixture it matches three. Measured 14 Sep against the
branch alone, no merge involved: **1 failed, 6 passed.** The branch had never
passed its own test, and could not have — the commit that would have found out
was never reached.

**Cost of the blind spot, on this instance:** a day of believing a broken
branch was one character from landing, a hand fix written on a false premise,
and a re-queue that will spend up to £6 to learn what 143 seconds of compute
would have said on the night.

## 2. The argument is already in the tree, on both sides

This is not a new idea being introduced. `runner/boundary.Boundary.size_only`
made exactly this decision one layer up, and says why:

> The cost of not drawing the line is measured, on task 69: two runs, £7.97,
> refused at 377 of 300 and then at 606 of 600, and because both died here
> neither test was ever executed. The re-measurement those runs were paying for
> needed to know whether a long test PASSES and BITES, and a size refusal is
> the one outcome that guarantees nobody finds out.

and, decisively:

> This does not make a size-refused branch acceptable. It is refused either
> way — `clean` is still False and the caller still returns FAILED. This only
> decides whether the evidence gets collected first.

So a cheap structural refusal must not pre-empt evidence collection — decided,
argued, and shipped at the boundary layer. One layer down, a cheap structural
refusal still pre-empts evidence collection. The two rules disagree, and task
87 is the bill for the half that was not changed.

**Where `verify.run`'s reasoning breaks.** "The second command's output is not
evidence about a tree the first command already rejected" holds when the first
command judged the tree. It does not hold when the first command judged the
*annotation*. `spec_requirements_cited.py` says so itself, in its own
docstring, under a heading written so nobody would oversell it:

> **That a claim was made, not that it was met.** An agent can write
> `// spec:2.5` and change nothing.
>
> WHAT IT DOES NOT ESTABLISH, so nobody reads more into a green: that the
> requirement was implemented correctly, or at all.

A check that by its own account establishes nothing about whether the code
works is precisely the one whose failure must not stop the checks that do.

## 3. Why all of them, and not "cheap checks last"

**Reordering moves the blind spot; it does not close it.** Whichever check runs
first is the only fact the run records. Put `vitest` first and task 87 fails on
the test, the citation error goes unrecorded, and the next run discovers it a
day later — the same failure with different names in it. Task 87 looks like an
ordering problem only because its first check happened to be the shallow one.

**"Cheap" is not the property that matters.** The property is "establishes
nothing about the tree". `spec_requirements_cited` is cheap *and* shallow at
72ms; `tsc` is expensive and deep at 32s. Cost correlates with the property by
accident, and an ordering built on the accident will be wrong the first time a
slow shallow check or a fast deep one is written.

**An ordering nothing enforces will drift.** Check order lives in each
contract's `verification` array, authored per contract, by hand. This
repository has a long record of exactly that shape going stale while being
believed — `tests/conftest.py` records its own: a hand-maintained migration
list left the suite "building a template two migrations behind and passing
against a schema that no longer existed anywhere else", and it notes the
executed-step tally and `EXPECTED_TABLE_COUNT` drifting the same way. A
cost-ordering convention across all eleven contracts is another such list, and its
failure is silent in the direction nobody checks: the suite goes green.

**Running everything needs no convention.** It is a property of the runner, not
of eleven contract files, and it cannot drift.

## 4. What it costs

**Nothing on the runs that pass.** A green run already executes every check —
fail-fast only ever stops on failure. This changes the cost of failing runs
only, which are the runs whose output was going to be discarded anyway, and
which are exactly the runs where a person is about to spend far longer working
out why.

**Compute, not money.** Verification runs after the agent has finished and been
billed. Run 62's £3.63 was the agent; the checks were free and would have
stayed free.

**The worst case, measured.** Task 89's five checks on the same frontend
contract, 14 Sep 2026:

| check | duration |
|---|---|
| `spec_requirements_cited.py` | 71 ms |
| `tsc --noEmit` | 32,388 ms |
| `vitest run --reporter=dot` | 101,113 ms |
| `new_test_bites.sh` | 9,728 ms |
| `proxy_passthrough.py` | 48 ms |
| **total** | **≈ 143 s** |

So a run that fails its first check at 72ms would spend ~143 seconds instead,
on a tick with a 1800s wall clock. Against task 87's actual cost — a day, a
false premise, and a re-queue — that is not a close comparison.

**The real exposure is timeouts, and it needs bounding.** Per-check deadlines
(`reverify._deadline_for`) mean N checks can now burn N deadlines where the run
used to stop at the first. "Run them all" must not become "wait for all of them
to time out". A ceiling on the verification phase as a whole should be built
with this, not after it.

**Cascading noise is real and acceptable.** A `tsc` failure will usually make
`vitest` fail for the same cause. Two failures, one defect. That is tolerable
because it is attributable — the report keeps the order, so the first failure
is still visibly first — but the report must not read as four independent
defects. `console/automerge.log_failing_checks` (14 Sep) already prints each
failing check with its own `output_tail`, which is the shape this wants.

## 5. What it does not change

**No gate is weakened.** `console/adopt._verification_is_green` requires every
recorded check to be green and at least one to have actually run. Recording
more checks can make a FAIL more informative; it cannot make a FAIL read as a
pass. Green semantics are untouched, because green runs already run everything.

**Could-not-run stays ahead of everything.** `verify.run` already resolves
every checker, and tests every path for writability, *before* running any
command — on the same argument as this document, one step earlier:

> a verification that cannot establish anything should say so instead of
> spending the wall clock proving it one check at a time.

That ordering is correct and this proposal does not touch it. "The contract
names a checker that is not there" and "this check failed" are different
sentences, and only the second is what §3 is about.

**The refusal is still a refusal.** In `size_only`'s words: this only decides
whether the evidence gets collected first.

---

*Written 14 Sep 2026, from task 87. Measurements are from runs 62 (task 87) and
64 (task 89) and from `vitest` executed directly against `fleet/task-87` at
`026eb10` in a worktree of the platform repository.*
