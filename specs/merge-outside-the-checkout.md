# Merge outside the checkout

**Status: SPEC. Nothing built.** Reads: `console/merge.py`,
`console/reverify.py`, `runner/worktree.py`, `systemd/fleet-console.service`.

---

## 0. The rule this removes

`console/merge.py` refuses to merge unless the console's checkout is on the
task's `base_branch` (`if head != base`), and unless the working tree is clean
(`if dirty`). Both are correct given what merging currently is: `git merge`
executed **in the live checkout**, which is also production
([deploy-from-a-ref](deploy-from-a-ref.md) §1). Guarding a real checkout
against a merge landing on the wrong branch is the least that could be done.

The guards are not the problem. Merging there at all is.

Because the merge happens in the checkout, accepting a task requires the
checkout to be on that task's base branch. `tasks.base_branch` is immutable by
database trigger, so the branch a task names must be kept alive and correct
until the task is terminal. On 2026-09-09 that requirement is what caused a
branch switch that took out three timers.

## 1. What already exists

Accept re-verifies in a **throwaway clone** built by
`runner.worktree.create_trial_clone`: clone into `PrivateTmp`, merge, verify,
delete. It reads the source repository and writes nothing to it — that property
is asserted by
`tests/test_console_decide.py::test_a_trial_writes_nothing_into_the_repository_it_came_from`.

So the console can already produce the exact merge commit that Accept would
make, in a place that is not the checkout, under its own sandbox. The trial
proves the merge is clean and passes the contract. What happens next is that
the whole thing is thrown away and the merge is done *again*, in the checkout,
by a different code path with different failure modes.

**Doing it twice is the defect.** The second merge is not verified by the
first: it is a separate operation on a different tree that is merely expected
to produce the same result.

## 2. What to build

**2.1 Promote the trial rather than repeat it.** The clone that verified is the
clone that ships. On a passing re-verification, push the merge commit from the
trial clone to the remote; do not re-merge anywhere. The commit that was tested
is then the commit that lands, by identity rather than by expectation.

**2.2 The checkout becomes a follower.** After the push, the checkout is
fast-forwarded, or — better, once
[deploy-from-a-ref](deploy-from-a-ref.md) exists — it is not touched at all and
the deployment moves separately. Accept stops writing to the checkout, which
means `ReadWritePaths=/home/ubuntu/deadly-digital-platform` can be dropped from
`fleet-console.service` and the console becomes a process that writes to one
database and one remote and to nothing on the filesystem outside its own
`PrivateTmp`.

**2.3 Which guards survive, and which stop meaning anything.** Worth deciding
explicitly rather than deleting whatever fails:

| Guard | After 2.1 |
|---|---|
| `head != base` (checkout on the base branch) | **gone** — there is no checkout involved |
| `dirty` (working tree clean) | **gone** — same reason |
| tip is the commit that was verified | **stays**, and gets stronger: it is now the commit being pushed |
| merge base equals the recorded branch point | **stays** |
| base agrees with its remote before merging | **stays**, and becomes the primary guard: the trial must be built from the remote's tip, or the push will be rejected anyway |
| push verified against the remote, not trusted | **stays** |

Two guards disappearing is the point — they exist to make a dangerous location
safe, and the location is being removed. Each is covered by a reversion guard
in `tests/revert_guards.py`; those entries must be deleted deliberately, with
the reason recorded, and not left pointing at code that no longer exists.

**2.4 The failure mode this introduces.** Today a merge that half-succeeds
leaves a real checkout in a known-bad state that a person can see. After 2.1 a
push can fail after the merge commit exists only in a deleted clone. That is
strictly better — nothing was published — but the code must not report it as
"merged"; `merge_and_push` already distinguishes `merged` from `pushed` and
that distinction becomes load-bearing rather than informational.

## 3. Ordering

After [deploy-from-a-ref](deploy-from-a-ref.md) §3.1–3.3. If the checkout is
still production when this lands, 2.2 has nowhere to put the deployment and the
fast-forward has to stay, which keeps most of the coupling this is for.

## 4. What this deliberately does not do

**It does not touch what is verified.** Re-verification against the merged tree
stays exactly as it is; this changes only which copy of the merge is kept.

**It does not make the console able to write to more places.** It should end
with the console writing to strictly fewer: one database, one remote, and its
own private temporary directory.
