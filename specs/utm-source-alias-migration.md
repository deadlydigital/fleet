# Create and seed `public.utm_source_alias`

**Recommendation: this should not be a fleet task.** It is an operator commit.
The reasoning is in *Split, or widen the contract?* below and it is the part of
this document worth reading first — the DDL underneath it is already written and
is not the interesting question.

Pairs with `specs/utm-source-alias-route.md`, which is a normal `dd_api` task
and needs no contract change.

## Split, or widen the contract?

The framing offered was: either split into two tasks, or give the contract a
writable migrations path. **Splitting does not avoid the second choice.** A
migration has to be written by someone either way, so a split that leaves task 1
inside the fleet still needs `api/alembic/versions/**` made writable. The two
options are not alternatives; one is a subset of the other.

The real question is whether an *agent* writes this file. It should not, for
three reasons that are specific to this file rather than to migrations
generally:

1. **There is nothing to design.** The seed exists, settled, at
   `specs/data/utm_source_alias_seed.sql` — 20 rows, each carrying a written
   note, six of them recording operator judgement calls (keep `meta_paid` paid;
   `ig` paid→social; `undefined` → `(broken)`; `loquax.co.uk` stays referral;
   `bing.com`/`google.com` left asymmetric; `sms` gets `allow_override=false`).
   Handing that to an agent is asking it to transcribe 245 lines of prose-bearing
   SQL. The upside is zero and the failure mode is a silently altered note or a
   dropped row.

2. **Nothing would catch that.** `api/ruff.toml` excludes
   `alembic/versions/*.py`, so the lint ratchet does not read it. There is no
   test gate for backend work (`TEST-004`). `compileall` proves it parses. A
   transcription error in row 13's note or a channel changed from `none` to
   `unknown` would pass every gate the contract has.

3. **The protection is doing real work here.** `api/alembic/**` is protected
   because a migration is an irreversible schema change against production with
   no test gate behind it. That is precisely this file. `dd-order-filters.yaml`
   already sets the precedent in the other direction — it keeps
   `api/analytics/migrations/**` protected *and says so in the spec*, because a
   task that reached for a schema change would be making a decision nobody
   asked for.

Note also that protected paths are **not** only in the contract YAML:
`runner.yaml` records that they live in the database and are checked at insert.
Widening is a change to the queue's own guarantees, not a local edit — a heavier
act than it looks.

**So: two tasks, and task 1 leaves the fleet.** Task 2 (`utm-source-alias-route.md`)
runs under the existing `dd_api` contract with `writable_paths` narrowed. Task 1
is an operator commit of an already-written artefact.

**If it must go through the fleet anyway**, the honest form is a dedicated
contract — `work_type: dd_api_migration` — with `writable_paths` holding exactly
one new file and an acceptance check that diffs the produced INSERT against
`specs/data/utm_source_alias_seed.sql` byte-for-byte. At which point the check is
doing the work and the agent is transcription with extra steps. That contract is
deliberately **not** written here; writing it would make the easy path the
default one.

## What the file is

`api/alembic/versions/20260901_1000_utm_source_alias.py`.

Verified 31 Aug 2026: the current alembic head is **`monthly_price_override`**
(`20260827_1300_tenant_monthly_price_override.py`), and it is the only head. So:

```python
revision = "utm_source_alias"
down_revision = "monthly_price_override"
```

`public.utm_source_alias` does not exist on `dd-prod` — checked, `to_regclass`
returns NULL. `public.tenants` holds ids 1 and 2, so the FK is satisfiable and
the seed's `tenant_id = 2` resolves.

The nearest precedent is `20260825_1100_meta_campaign_alias.py`: same repo, same
shape (a `public` alias table keyed by `tenant_id, alias_norm`), and its header
is the model for how much reasoning belongs in the file. Copy that habit — the
notes in the seed are the reasoning and they should ship with the rows, not be
summarised away.

### `upgrade()`

```
utm_source_alias
  id                BigInteger    PK, autoincrement
  tenant_id         Integer       NOT NULL, FK tenants.id ON DELETE CASCADE
  alias_norm        String(255)   NOT NULL   -- lower(btrim(utm_source)); '' is a real key
  alias_raw         String(255)   NOT NULL   -- verbatim, for auditing a normalisation change
  canonical_source  String(128)   NOT NULL   -- DISPLAY CASE. Rendered and grouped by
  channel           String(24)    NOT NULL   -- a DEFAULT, overridable on the read path
  is_paid_meta      Boolean       NOT NULL, server_default false
  allow_override    Boolean       NOT NULL, server_default true
  origin            String(16)    NOT NULL, server_default 'seed'
  note              Text          NULL
  UNIQUE (tenant_id, alias_norm)   name='uq_utm_source_alias'
  CHECK  channel IN ('paid','organic','referral','social','email','sms',
                     'direct','none','not-a-channel','unknown')
         name='chk_utm_source_alias_channel'
```

Two of these are amendments the analysis forced, and both matter:

- **`allow_override`** exists because flag 6 requires it. Five of the twenty
  rows opt out of the medium override. The column's existence is the admission
  that the override is not the closed universal rule the original proposal
  described.
- **`social` in the CHECK.** It was absent from the proposed vocabulary while
  being `ig`'s override target and row 20's stored value. Against an
  unconstrained `VARCHAR(24)` it would have inserted silently.

**No separate lookup index.** `UNIQUE (tenant_id, alias_norm)` already provides
the btree the loader's only query needs (`WHERE tenant_id = :t`). Adding
`ix_utm_source_alias_lookup` beside it would duplicate the same index —
`meta_campaign_alias` needs its explicit one because its unique key carries a
third column.

**No CHECK on `canonical_source`.** Deliberate and left open: a vocabulary
constraint there would need extending on every new merchant-visible source name,
which is the opposite of the maintenance property this table exists for.

### The seed

`specs/data/utm_source_alias_seed.sql`, PART 2 — the `INSERT` between `BEGIN;`
and `COMMIT;`, 20 rows, verbatim including every note. Do not re-order, re-word,
or "tidy" the notes: they are the record of six decisions and the reason each
row is what it is.

Lex-checked 31 Aug 2026: one `INSERT`, 20 value tuples, balanced parens, all
string literals terminated. Four rows carry `is_paid_meta=true` (`meta_paid`,
`fb`, `ig`, `facebook`) and five carry `allow_override=false` (`''`,
`(direct)`, `undefined`, `com.google.android.gm`, `sms`). Both counts are
asserted by `contracts/checks/utm_alias_cutover_diff.py`.

Seed under the alembic connection (`op.get_bind()`), not as a separate script,
so table and rows arrive together — a created-but-unseeded table maps every
source to `unknown`, which is worse than no table at all because the route's
"missing table" fallback would not fire.

### `downgrade()`

`op.drop_table('utm_source_alias')`. The CHECK and UNIQUE go with it.

## What is not in this

- **Tenant 1.** The seed is tenant 2 only. Tenant 1 has its own spellings and
  nobody has measured them. It will map everything to `unknown` until seeded —
  acceptable, and it is why the route's fallback in
  `utm-source-alias-route.md` §5 exists.
- **A seeder job.** Unlike `meta_campaign_alias`, nothing derives these rows
  from an API. They are hand-decided, `origin='seed'`, and the column exists so
  that a future derived row is distinguishable rather than indistinguishable.
- **The 154 orders `_META_PAID_SOURCES` misses.** `ATTR-001` item 1. Adding
  those spellings to this seed would change the paid population and break the
  0/0 check — correctly. Do it as its own change with the check re-baselined in
  the same commit.
- **Backfilling or rewriting `analytics_2.orders`.** Nothing about this touches
  order rows. The mapping is applied on read.

## How it is checked

`contracts/checks/utm_alias_cutover_diff.py` prefers a migration matching
`api/alembic/versions/*utm_source_alias*.py` in the worktree over the canonical
seed, and prints which it used. So the same check that guards the route task
also verifies this file's seed: 20 rows, five override opt-outs, four
`is_paid_meta` rows, and the measured 0/0 diff against `analytics_2.orders`.

Run it against the branch before merging:

    cd <worktree> && /home/ubuntu/fleet/.venv/bin/python \
        /home/ubuntu/fleet/contracts/checks/utm_alias_cutover_diff.py

Beyond that: apply to staging, confirm the row count is 20, and confirm the
sources page still renders before it reaches production. There is no gate that
does this for you.
