# One entry point — the chain as a loop, not four timers

**Decided 12 September 2026.** Built in the order this file states, which is not
the order that saves the most machine time.

## 0. The complaint, stated exactly

A feature costs seven commands: `run_autoapprove`, `run_task`, `run_automerge`,
`run_task`, `run_automerge`, accept in the console, deploy.

Every one of those except the last two is a stage that already knows what
follows it. A draft spec merges and `autoqueue.from_accepted_draft` queues the
code task in the same breath — and then nothing builds it until somebody types
a command or a timer fires at 02:00.

**The win is seven commands becoming one.** It is not machine time, and the
build order below is chosen on that basis.

## 1. What the loop is

`run_chain.py`, calling the same four functions the units already call. Not a
new pipeline — a scheduler around the stages that exist.

    until nothing changed, or a stop fires:
        if a task is QUEUED and affordable   -> build one        cycle.tick
        elif a task is READY_FOR_REVIEW      -> try to merge     automerge.sweep
        elif there is approval room          -> approve one      autoapprove.sweep
        else                                 -> done

### 1.1 A fixpoint, not a sequence

"approve, draft, merge, queue, build, merge" is the common case and not the
shape. A merged draft queues its code task; since `037` a candidate may split
into several links that merge together or not at all. The loop cannot know its
own length in advance, so it runs to a fixpoint and stops when a pass changes
nothing.

### 1.2 Drain before you add, which reverses the current order

Build and merge come before approve, so the loop finishes what is started
rather than widening the front.

The timers do the opposite, and it is the whole of the complaint: approve at
01:30, build every 20 minutes from 02:00 to 04:00, **merge once at 03:30.** A
task that finishes at 03:40 waits a day for a decision that takes seconds.

### 1.3 Where it stops, and what it says

It stops when a pass changes nothing, and then reports what is sitting in
`READY_FOR_REVIEW` with the reason automerge declined each one — which
`automerge.sweep` already returns, per task, as `{task_id, merged: false,
reason}`.

**`accept` and `deploy` stay the operator's.** The loop never merges outside
automerge's existing gates and never calls autodeploy at all.

## 2. What stops a runaway

All three stops exist. All three are currently **approval-time**, which works
only because approval happens once a night.

| stop | today | in the loop |
|---|---|---|
| credit ceiling | read once in `_cut`, at 01:30 | re-read before **every build** |
| queue depth | `max_queued − queued_now`, at approval | same meaning, consulted every pass |
| repeat-failure | `candidate_prior_failures`, at approval | unchanged — plus §3 |

### 2.1 The credit ceiling moves stage, and it is wrong today

`autoapprove` reads `fleet_month_credit()` at 01:30; the runner then spends
until 04:00 against a figure that was stale when it was read.
`reserve_model_budget` bounds one task against its own cap. **Nothing bounds
the night against the pool after approval has happened.**

In the loop the check moves to immediately before each build: if
`autonomous_remaining_gbp` is less than the next task's `max_cost_gbp`, stop —
do not start a run that cannot be afforded. That is a strictly better property
than the sweep has, and it is the main safety argument for a loop rather than
against one.

### 2.2 Queue depth mostly stops binding

A loop that drains does not accumulate. `queued_now` is 0. The ceiling stays as
the bound on how far ahead of itself the loop may get in one pass.

## 3. The same task failing twice

**A loop is more dangerous than a sweep here, and not obviously.**

`cycle.py` re-queues a failed task while `attempts < max_attempts`. Under timers
that is safe by accident — the next fire is twenty minutes away and there are
seven a night. **In a loop, `QUEUED` is claimed on the next iteration**, so
`max_attempts: 3` is three rebuilds in minutes with nobody between them.

And a rebuild is a re-roll. Task 69 ran four times off one spec and one base
commit and produced tests of 377, 606, 439 and 385 lines. The fourth cleared the
gate the third had failed, then failed `ruff` on a single new `I001` — £3.32 to
replace a verified branch with a broken one.

So the loop carries its own stop, distinct from the candidate-level one:

- it keeps a per-invocation set of task ids that have failed;
- a task in that set is **never claimed again in the same invocation**, whatever
  `max_attempts` says;
- **the second failure of the same task halts the loop**, rather than moving on.

Halting rather than skipping is deliberate. One task failing twice in one pass
is the clearest available evidence that the loop is spending money to re-roll
dice, and that is exactly the state nobody is watching at 02:00.

`candidate_prior_failures` is untouched. It answers a different question —
*should this work be attempted again tomorrow* — and withholds only automatic
approval, so the signal stays on the surface.

## 4. The units

**The timers collapse. The services stay.**

`run_automerge.py` argues its own case: *"A SEPARATE unit from fleet-runner, so
it can be stopped on its own — which is what you want at 3am on a bad night, and
not something you want to have to think about."* That argument is about
**stopping a stage**, not about scheduling one, and the loop must not cost it.

- **Removed:** `fleet-autoapprove.timer`, `fleet-runner.timer`,
  `fleet-automerge.timer`.
- **Added:** `fleet-chain.timer`, one fire.
- **Kept, timerless:** all four services. `systemctl start fleet-automerge`
  still runs that stage alone; `run_task.py --task 69` is unchanged.
- **Untouched:** `fleet-autodeploy.timer`. Deploy stays the operator's.
- **Per-stage enable flags in `chain.yaml`**, read at the top of every pass —
  the same reason `runner.yaml` holds thresholds: *"retuning one must not be a
  redeploy."* Turning the merge stage off at 3am must not need an edit and a
  restart. A file rather than a table because a table needs `fleet_owner`, and
  three things are already queued behind that credential.

### 4.1 The loop owns its clock

`fleet-runner.service` carries `TimeoutStartSec=4200`, sized for **one** task. A
chain that builds two or three exceeds it, and being killed by systemd
mid-merge is the hardest failure to read in the morning: the merge either
happened or did not, the decision row either exists or does not, and the journal
stops mid-sentence.

So the loop takes a deadline of its own, checks it before every stage, and stops
cleanly between stages with a stated reason. `TimeoutStartSec` on the unit is
set well above it and is a backstop, never the mechanism. `MemoryMax` becomes
2G, the largest of the four it replaces.

## 5. The three suite runs

A feature runs the analytics suite three times: once in the build, once in
automerge's re-verification, once in accept's. Thirteen minutes each, the same
tree, often seconds apart.

`automerge` runs `reverify.run` **before** the eligibility gates that need its
result, so a task it then declines has already paid; the operator then accepts
by hand and pays again.

### 5.1 It can be skipped, and the condition is already computed

`reverify.py` computes `base_sha == recorded_base` and already states the
consequence in prose:

> *"`main` has NOT moved since the branch was cut … so the merged tree is the
> branch tree. This check passed when the runner ran it against the same tree,
> so look at what differs about where it ran, not at the diff"*

With `merge.preflight` already refusing when `tip != recorded_patch`, the two
tree facts together make the trial merge a fast-forward: the tree being verified
is byte-identical to the one the runner verified.

### 5.2 What skipping gives up

1. **Changes to the checkers, not the trees.** The runner ran
   `contracts/checks/*.py` and the api venv's ruff as they were at build time;
   accept runs them as they are now. A tree comparison cannot see a ruff upgrade
   or an edited check. This is the stale-console class — a property that holds
   by construction until something else stops constructing it — and it is the
   reason the skip is not taken first.
2. **Environment differences.** On 11 Sep `tsc --noEmit` exited 134 under
   `fleet-automerge.service`'s 512M cgroup and was reported as *"the base moved
   under it"* when it had not. That is re-verification catching a difference in
   *where it ran*, which exists only because it runs there. Skipping removes the
   failure rather than failing to notice it.
3. **A second sample of a flaky suite.** Cuts both ways; not weighed.

### 5.3 So: three facts, not two

Only (1) is a real loss and it is closable in this codebase's own idiom. The
runner already records `suite_commit_sha`, a digest over the protected trees.
**Record an analogous digest over the check implementations** — the fleet
checkout's HEAD, a digest of `contracts/checks/`, the pinned ruff version — into
the verification payload. Then the skip rests on three recorded facts instead of
two, and the third is the one that would otherwise be an unrecorded assumption.

The loop makes the skip both safer and more valuable: today a 90-minute gap
separates build from merge and the base may move in it; in the loop the gap is
seconds, and the loop is serial, so the base moves only when the loop moves it.
The skip would apply almost always. **It must still ask git rather than infer
from its own bookkeeping** — the discipline `paired_paths.py`,
`new_test_bites.sh` and `console/adopt.py` all follow.

## 6. Build order

1. **The loop, with all three suite runs intact.** The win is the commands, and
   it is available without touching verification at all.
2. **The checker digest.** Recorded for a few nights before anything reads it,
   so the skip is taken against evidence rather than against a new column.
3. **The skip**, conditional on all three facts.

Deliberately not the order that saves the most machine time. Step 1 changes when
things run; steps 2 and 3 change what is checked before a merge, and those are
worth making against a loop that has already run a few nights.
