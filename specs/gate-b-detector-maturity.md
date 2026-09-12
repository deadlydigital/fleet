# Gate B — detector maturity

**Decided 9 September 2026. Written into the repository 12 September 2026,
three days late and only because a session went looking for it and could not
find it.**

## 0. Why this file exists at all

Gate B was decided on 9 September and recorded in a handover document. Nothing
in this repository mentioned it: not `specs/`, not `objectives-2026-Q4.yaml`,
not `principles.md`, not `detector_registry`, not `decision_log`. A session
asked to build toward it searched all five and reported that the gate did not
exist.

That is the failure this file closes, and it is worth naming as a class rather
than as an incident. **A decision that lives only where a session cannot read
it is a decision the fleet cannot act on, and it will be re-derived — wrongly
and confidently — by whoever needs it next.** The same shape has already cost
this project three times in one week: a ceiling whose derivation lived in one
person's head, a frozen contract whose value lived in a row nobody read back,
and a console enforcing rules that lived in a process image rather than in the
tree. Each was found by the work rather than by review.

So: handover documents are for handover. **If a decision constrains what gets
built, it belongs in `specs/` on the day it is made.**

## 1. What Gate B admits — AND THIS IS THE ONE THING NOT RECORDED HERE

The criterion below is exact, because it was dictated. What eligibility
*unlocks* was not, and it is not reconstructed here: that sentence is still in
the handover document, and a plausible guess written into `specs/` would be
worse than the gap, because the next reader could not tell the guess from the
decision.

**TO WHOEVER HAS THE HANDOVER: replace this section with the consequent, in
your words.** Everything below stands on its own and does not depend on it.

## 2. The criterion

Gate B is met when **both** hold:

1. **20 human-verdicted observations**, in total; and
2. those verdicts span **at least 3 substantive detector families**.

`fleet_heartbeat` is **excluded**. It watches the fleet, not the product: a
heartbeat verdict says the detector track is alive, which is exactly the thing
Gate B is trying to find evidence *beyond*. Counting it would let the gate be
satisfied by the fleet observing itself.

### 2.1 Two readings, and the one taken

"20 across at least three families" can mean 20 in total spread over three, or
20 in each of three. **The plain reading is taken: 20 in total, spread across
three or more.** Stated here rather than settled silently, so that if the
handover meant the other one, the disagreement is visible in a sentence rather
than buried in a query.

### 2.2 What counts as a verdict

Any row in `observation_verdicts` — `VALID`, `FALSE_POSITIVE` or
`INCONCLUSIVE`. All three are a person having looked. The gate measures human
attention paid across the detector surface, not whether the detectors turned
out to be right; a detector proven to lie is as much evidence of a working
review loop as one proven correct, and `false_positive_rate_rising` is already
where being wrong is measured.

`enforce_verdict_authority` already restricts writes to `fleet_console` and
`fleet_evaluator`, so "human" is enforced by the database rather than asserted
here.

## 3. `family` on `detector_registry`, so the count is derived

The second clause is a count of families. Today there is nowhere to count them
from, so satisfying Gate B would mean somebody deciding by eye which detectors
are "different enough" — which is a judgement, made once, unrecorded, and
different the next time it is made.

    ALTER TABLE detector_registry
        ADD COLUMN family      text    NOT NULL DEFAULT 'unclassified',
        ADD COLUMN substantive boolean NOT NULL DEFAULT true;

and the gate becomes one query with no judgement in it:

```sql
SELECT count(*)                       AS verdicts,
       count(DISTINCT r.family)       AS families
  FROM observation_verdicts v
  JOIN detector_registry r
    ON r.detector_key = v.detector_key
   AND r.issue_key_version = v.issue_key_version
 WHERE r.substantive
   AND r.retired_at IS NULL;
```

Gate B is met when `verdicts >= 20 AND families >= 3`.

**`substantive` is a column rather than a rule about names** because the
exclusion is itself a judgement, and a judgement in a `WHERE family <>
'fleet_self'` somewhere in Python is the thing this column exists to stop. One
`false` on one row, visible in the table, beats a string comparison in code
nobody re-reads.

### 3.1 The four detectors, classified

| detector_key | family | substantive | why |
|---|---|---|---|
| `dd_analytics_reconciliation` | `analytics_integrity` | yes | the analytics copy against its source, and against itself |
| `dd_api_errors` | `application_errors` | yes | Sentry: the product failing in front of a user |
| `dd_aws_cost` | `infrastructure_cost` | yes | spend, which no other detector can see |
| `fleet_heartbeat` | `fleet_self` | **no** | the fleet watching itself — see §2 |

Three substantive families exist. That is the clause that has been binding.

### 3.2 Where Gate B actually stands, 12 September 2026

Measured, not estimated:

| | |
|---|---|
| verdicts recorded | **45** |
| substantive families they span | **1** (`dd_analytics_reconciliation`, all of them) |
| verdicts by | `eamonn`, 28–30 August |
| verdict breakdown | 45 `VALID`, 0 `FALSE_POSITIVE`, 0 `INCONCLUSIVE` |

**The count clause passed a fortnight ago and the family clause is nowhere near
met.** Gate B is not one verdict away; it is two families away, and no amount
of reviewing reconciliation observations will move it. That is the gate working
as designed — it was written to require breadth, and breadth is what is missing.

What would move it, and the shape of the work is not the same for the two:

| detector | observations | verdicted |
|---|---|---|
| `dd_analytics_reconciliation` | 356 | 45 |
| `dd_api_errors` | **346** | **0** |
| `dd_aws_cost` | **0** | 0 |
| `fleet_heartbeat` | 6 | 0 (excluded anyway) |

`dd_api_errors` is the near one and it is very near: **346 observations already
sitting there, none of them ever looked at.** A second family is a review
session, not a build.

`dd_aws_cost` is the far one, and for a different reason — it has never
produced an observation at all. Its cadence is daily and its registry row is
live, so either nothing has crossed its threshold or it is not finding what it
was built to find. A third family therefore needs that answered first, and
"why has the cost detector never fired" is a real question with two very
different answers.

## 4. The deferral, and why it expired

**The column was deferred on 9 September**, on the stated grounds that it
changed nothing until a second substantive detector existed. That was correct
at the time: with one substantive family, `count(DISTINCT family)` is 1 whether
the column exists or not, and a column that cannot change an answer is a
migration for nobody.

**The grounds have expired.** There are four detectors and three substantive
families. The count is now a real number that a person would otherwise have to
derive by eye, which is the condition the deferral was waiting on.

Recording the deferral rather than quietly building the thing matters for the
same reason as the rest of this file: a reader finding `family` in the schema
with no history would reasonably assume it had been there from the start and
that nobody had thought about the cost. Somebody did, and was right, and the
reason it changed is the thing worth keeping.

## 5. What this file does not do

It does not add the column. That is a migration, it needs `fleet_owner`, and
two other migrations are already queued behind that credential — `038` and
`analytics_2` to `0013`. Writing the decision down does not depend on holding
the credential, and waiting for the credential is how it stayed unwritten for
three days.

It does not decide whether `STUCK_ORDER_TRANSITION` constitutes a fourth
family. It does not: it is an invariant on `dd_analytics_reconciliation` and
inherits that detector's `analytics_integrity`. A check added to an existing
detector adds evidence, not breadth, and the gate counts breadth on purpose.
