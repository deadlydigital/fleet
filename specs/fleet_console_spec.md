# Fleet Console — spec

A read-only web page over the `fleet` database. It exists because reviewing a
diff in a terminal at 8am is the thing that stops happening, and a queue whose
output nobody reviews is worse than no queue.

**Read-only in V1.** No merge, no approve, no deploy, no task creation. Those
stay in the shell where they are deliberate. A page that cannot write cannot
break anything, which is what makes it safe to build before you know which
actions you actually reach for.

---

## Where it runs

On `dd-prod`, behind the Caddy instance already serving there, on a subdomain
or path. Basic auth — one user, and nothing here is sensitive beyond your own
operational state.

Connects as `fleet_reader_login`, which exists and holds SELECT and nothing
else. Do not create a new role, and do not use `listmonk`: if the console can
only read, the credential it holds should be one that can only read. That is
the same rule as everywhere else in this system.

Stack: whatever is fastest to stand up and boring to run. FastAPI plus server-
rendered templates is enough — there is no interactivity to justify a frontend
build, and one more Node toolchain on that box is a cost with no return.

---

## Page 1 — Tasks

The review surface, and the reason this exists.

**List:** id, title, status, queue, objective, branch, cost, elapsed, attempt,
created. Default filter to `READY_FOR_REVIEW`, since that is the morning
question. Ordered newest first.

**Detail**, per task:

- the spec as written, rendered
- the contract: writable globs, protected globs, verification commands, caps
- the run and its steps in order, with the identity that wrote each
- **the diff**, syntax-highlighted, the thing you are actually here for
- derived vs claimed changed files, and the divergence between them
- each verification check: command, exit code, duration
- cost against reservation, and whether the reservation was exceeded
- the branch name, with a copyable `git diff main..<branch>` line

The divergence display matters. It is recorded on the `PATCH_PROPOSED` step
precisely so under-reporting is visible after the fact rather than only
refused at the time, and it is invisible unless something surfaces it.

Read the diff from git on disk rather than storing it in the database — the
branch is the artifact, the database records what happened to it.

---

## Page 2 — Detectors

**Health:** per detector, last scheduled run, status, duration, next expected
slot, and whether the heartbeat currently considers it late. Green, amber, red
against the registry's own cadence and grace, not against a hardcoded number.

**Open issues:** fingerprint, type, subject, severity, magnitude, occurrence
count, age, and whether a clear is currently blocked — and if so, which
coverage condition is blocking it. That last column is the one worth building
carefully; "why is this still open" is otherwise a query nobody runs.

**Untriaged observations:** count, and the list. This is the number that
should be zero every morning, so make it prominent when it isn't.

**False-positive rate** by detector, version and observation type, with the
denominator shown. A rate over a small denominator is not a rate, and showing
`2 of 3` rather than `67%` prevents a decision being made on three data points.

---

## Page 3 — Proposals

Whatever the daily cycle produced, with its evidence rows — adapter, query key,
value, fetched-at, and the staleness flag.

Show the cycles that produced **nothing**, and their reasons. The proposer's
"not computed" lines are the most informative thing it emits at this stage, and
a page that only shows proposals would hide them entirely.

Decisions, where made: verdict, reason code, decision time.

---

## Deliberately not in V1

No writes of any kind. No merge or deploy button. No task creation — specs are
written with context loaded, which is not what a text box in a browser
encourages. No charts. No auth beyond basic. No mobile layout beyond whatever
falls out of not fighting the browser.

No polling or live updates. The data changes hourly at most; a refresh is
enough, and a websocket is a service that can break silently.

---

## What to build second, once you know you want it

Actions, and only the ones you actually reach for. The likely two are marking
a task REJECTED or REWORK with a note, and recording an observation verdict —
both currently shell commands you run daily.

If those land, they need the same authority split as everything else: the
console writes as `fleet_console`, not as the reader, and the two are separate
connections rather than one role widened. Do not widen `fleet_reader_login`.

---

## Acceptance

You look at it in the morning instead of opening a terminal. If after a week
you are still running the psql queries by hand, it is showing the wrong things
and the fix is to change what it shows, not to add features.
