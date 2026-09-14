# Verification collects its evidence before it refuses

**APPLIED 14 Sep 2026** in `runner/verify.run`, with the two callers that
branched on `undecided` corrected alongside it (§6). Written first as a
proposal; this paragraph and §4's ceiling note are the only parts rewritten
after building it, and what changed is recorded rather than tidied away.

**The recommendation, which is what was built: run every check regardless of
the first failure. Do not reorder them by cost.** What that costs, measured,
is in §4.

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

**The ceiling already existed, and this paragraph used to say otherwise.** As
proposed, this section claimed that per-check deadlines meant N checks could
burn N deadlines, and that a phase ceiling had to be built alongside. **That
was wrong, and reading `verify.run` before changing it is what corrected it.**
`deadline_seconds` is already one budget for the whole phase: the loop computes

    remaining = deadline_seconds - sum(c.duration_ms for c in result.checks) / 1000

and passes `remaining` as each check's timeout, so the checks share one
allowance and continuing past a failure spends what is left of it rather than
starting a fresh clock. N checks cannot burn N deadlines and never could. The
worst case is one `deadline_seconds`, which is the contract's own verification
budget — `reverify._deadline_for` derives it from the task's `timeout_seconds`,
and `cycle` passes the task's wall clock less whatever the agent spent.

**What did need building was smaller.** When the budget runs out the loop used
to record the one check it was about to start and stop. That was defensible
while everything after a stopping point was unknown by convention; now that the
ordinary case is "everything ran", a silent tail reads as checks that passed.
Every remaining command is recorded as `undecided`, on the argument the
unresolved branch already makes one screen up: *recorded, rather than dropped,
so the report shows the whole contract.*

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

## 6. What building it turned up: one run can now hold both classes

Not foreseen when this was written as a proposal, and the reason it is a change
to three files rather than one.

Until now `verify.run` stopped at the first failure, so a verification held at
most one terminal check: **either** a failing verdict **or** a check that was
killed, never both. Two callers rely on that without saying so —
`console/reverify.run` and `runner/cycle._execute` both branch on
`Verification.undecided` first and report *"this says nothing about the
branch"*, which is right when the killed check is all there is.

Running everything breaks the assumption. A genuine `exit 1` followed by a
`tsc` the cgroup kills — which is not hypothetical; it is the measured task 53
case `Check.undecided_reason` exists for — would have been reported as *"could
not be verified"*, throwing away the one finding the run did establish and
sending the reader to look at the unit's memory limits instead of at their
diff. That is the same false-confidence failure `undecided` exists to prevent,
pointing the other way.

So `Verification.failed_outright` asks the question directly — did any check
look at the tree and return a verdict of failure — and both callers ask it
before they claim nothing is known. A verdict that was reached is kept.

`tests/test_verify_evidence.py` asserts both orderings, because order must not
decide which class a run reports.

---

*Written 14 Sep 2026, from task 87. Measurements are from runs 62 (task 87) and
64 (task 89) and from `vitest` executed directly against `fleet/task-87` at
`026eb10` in a worktree of the platform repository.*
