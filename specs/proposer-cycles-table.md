# A cycles table for the proposal layer

**Status:** proposed, not built. Logged 2026-08-30 while building the console.
Needs a migration (`005_cycles.sql`), so it is a schema change and not a
read-only console's business.

## What is missing

`002_proposals.sql` creates `proposals`, `proposal_evidence` and `decisions`,
and nothing else. `cycle_id` exists only as a column on `proposals`.

So **a cycle that proposed nothing leaves no row anywhere.** The console
cannot distinguish:

* the cycle ran and had nothing to say — the healthy case, and the expected
  one on most mornings
* the cycle ran and every finding was starved of a usable reading
* the cycle did not run at all

Those are three different situations with one appearance, and the third is a
failure that currently looks exactly like the first.

## Why this matters more than it sounds

The proposer's *"not computed"* lines are, at this stage, the most informative
thing it emits. `proposer/cycle.py` assembles them — every finding type that
could not be computed and why, every suppressed item, everything cut by the
five-item cap — and `run_cycle.py` prints them. They reach stdout, then
journald, and nowhere else.

`002`'s own README argues that what is cut must be printed, because "a layer
that quietly showed five things out of twenty would read as *here is
everything*". The same argument applies one level up: a layer that produced
nothing, and cannot say so anywhere durable, reads as a layer that is fine.

Production today has **0 proposals and 0 cycles recorded**, and the timer is
active and ran at 07:30. Whether that is health or silence is not answerable
from the database.

## What it would need

A `cycles` table written by `fleet_proposer` at the end of every run, carrying:

* `cycle_id`, `started_at`, `completed_at`
* `proposals_written` (0 is the interesting value)
* `findings_computed` and `findings_not_computed`, with the reason per finding
  key — the printed report's content, stored
* `suppressed` and `cut_by_cap` counts
* whether the objectives file validated, since the cycle refuses to start when
  the weights stop summing to 1.0 and that refusal is currently invisible

The console would then show cycles with no output and why, which is what
`specs/fleet_console_spec.md` page 3 asks for and what it cannot have today.

## What not to do

Do not have the console read journald. A page that parses log lines is a UI
inventing a data source: it breaks silently when the format changes, and it
cannot be queried. The console states the gap instead, which is why this file
exists.
