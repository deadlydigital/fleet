# Read source normalisation from `utm_source_alias` instead of hardcoding it

**This is backend work, and it is the second of two tasks.** The table this
reads does not exist yet — `specs/utm-source-alias-migration.md` creates and
seeds it, and that one is deliberately **not** a fleet task. Read
*Ordering, and why this can merge first* before assuming this blocks on it.

Read at `6d5c755`. Verified against the repo 31 Aug 2026:

| what | where | confirmed |
|---|---|---|
| the three CTEs that select `utm_source` | `api/analytics/routes/sources.py:152`, `:492`, `:664` | yes — each is the `COALESCE(…utm_source, '(direct)') AS utm_source` line inside `get_sources()` (105-270), `get_sources_insights()` (428-638) and `_compute_ltv_sources()` (641-790) |
| the hardcoded set | `sources.py:854` | yes — **854, not 851**. 851 is the first line of its three-line `#:` comment |
| its only reader | `sources.py:857-858` (`_is_meta_paid`), called at `:956` | yes |
| the pattern to copy | `api/services/meta_campaign_alias.py:87` (`load_alias_map`) | yes — loaded at `sources.py:260` and `:570`, passed into `_enrich_sources_with_spend` |

## What it does

The sources page fragments its largest channel across spellings. The Meta
family alone arrives as `m.facebook.com`, `facebook.com`, `l.facebook.com`,
`fb`, `meta_paid`, `Meta_Paid`, `l.instagram.com`, `ig` and more, so a merchant
reads Meta as 19% when it is 27% (`research/gap-list-open-questions.md` §1).

This task makes the three source queries read a stored mapping instead:
`alias_norm → canonical_source, channel`, with a medium override and a per-row
opt-out from it. It also deletes `_META_PAID_SOURCES` in favour of the table's
`is_paid_meta` column.

**It changes what the page displays. It must not change what
`spend_attribution` counts.** That is asserted, not hoped for — see *How it is
checked*.

## What done means

### 1. A loader service, `api/services/utm_source_alias.py`

Mirror `services/meta_campaign_alias.py:87` closely — same shape, same
degradation:

```python
def load_source_alias_map(db: Session, tenant_id: int) -> Dict[str, Dict[str, Any]]:
    """{alias_norm: {canonical_source, channel, is_paid_meta, allow_override}}."""
```

One query per request over a table whose size is tens of rows per tenant.
Return plain dicts so the enrichment helpers stay pure functions over dicts and
remain testable without a database.

**A missing table must degrade to `{}`, not to a 500** — `except Exception`,
`logger.warning`, `db.rollback()`, `return {}`, exactly as `load_alias_map`
does for the same reason. This is the property that lets this task merge before
the migration is applied, and it is not optional.

### 2. The alias join, in all three CTEs

Join key is **`lower(btrim(utm_source))`**, matching the seed's stated lookup
key. The canonical form, taken from the analysis:

```sql
LEFT JOIN public.utm_source_alias a
       ON a.tenant_id = :tenant_id
      AND a.alias_norm = lower(btrim(COALESCE(<the raw utm_source column>, '')))
```

and the two projected values:

```sql
COALESCE(a.canonical_source, NULLIF(btrim(<raw>), ''), '(unmapped)') AS utm_source,
COALESCE(a.channel, 'unknown')                                      AS channel
```

**Join on the raw column, coalescing NULL to `''` — not to `'(direct)'`.**
The three CTEs currently write `COALESCE(fo.utm_source, '(direct)')`. Measured:
`analytics_2.orders` holds **zero** NULL `utm_source` and **833,497** empty
strings, so that COALESCE never fires today and the empty string flows through
as itself. If it ever did fire, folding NULL into `(direct)` would put
untagged orders under a sentinel the connector writes deliberately — and the
seed is explicit that these are different facts that never co-occur (row 1:
*"NOT direct … the two never co-occur"*). Row 1 maps `''` to `(untagged)`.
Keep them separate.

`:tenant_id` binds. Every route in this module already has `tenant.id` or a
`tenant_id` argument in scope, and each already derives `schema =
analytics_schema_name(...)` on the line after.

### 3. The medium override, and `allow_override`

The stored `channel` is a **default**, not a verdict — row 5 (`google`) is one
alias row covering 229,267 organic and 27,459 cpc orders. The read path
promotes on the medium:

```sql
CASE
  WHEN a.channel IS NULL                                                       THEN 'unknown'
  WHEN a.allow_override AND lower(btrim(utm_medium)) IN ('cpc','paid')         THEN 'paid'
  WHEN a.allow_override AND lower(btrim(utm_medium)) = 'organic'               THEN 'organic'
  WHEN a.allow_override AND lower(btrim(utm_medium)) = 'referral'              THEN 'referral'
  WHEN a.allow_override AND lower(btrim(utm_medium)) = 'social'                THEN 'social'
  WHEN a.allow_override AND lower(btrim(utm_medium)) IN ('campaign','flow','email') THEN 'email'
  ELSE a.channel
END AS channel
```

Reproduce this rule **exactly**, including the `IS NULL → 'unknown'` arm
first. Do not add mediums to it and do not remove `'referral'` from it —
removing `referral` is a real open question (it would make `bing.com` and
`google.com` symmetric) and it is FOLLOW-UP 2 in the seed artefact,
deliberately not bundled here because it changes every row that is not
`allow_override=false`.

Five of the twenty rows set `allow_override=false`: `''`, `(direct)`,
`undefined`, `com.google.android.gm`, `sms`. Each opts out for a stated reason
in its note. `sms` is the load-bearing one — all 1,306 of its uppercase-spelling
orders carry `utm_medium='paid'`, and the override applied blindly would file an
owned SMS list as paid media, beside CPA and ROAS.

### 4. `_META_PAID_SOURCES` is replaced, not supplemented

Delete the set at `sources.py:854` and its comment. `_is_meta_paid` becomes a
lookup into the loaded map:

```python
def _is_meta_paid(utm_source: str, alias: Optional[Dict[str, Any]]) -> bool:
```

or equivalently a set of `alias_norm` where `is_paid_meta` is true, threaded
into `_enrich_sources_with_spend` beside the existing `alias_map` parameter
(`sources.py:876`) and passed at `:260` and `:570` beside
`load_alias_map(db, tenant.id)`.

The single call site is `sources.py:956`, which decides
`unattributable_paid` vs `not_paid`. **That decision is what must not move.**

**Note the deliberate mismatch it now has to tolerate:** rows 11 (`ig`) and 20
(`facebook`) store `channel='social'` with `is_paid_meta=true`. These answer
different questions — channel is what an order defaults to, `is_paid_meta` is
whether the spelling can carry Meta spend at all. Anything that treats
`channel='paid'` as the test will silently drop `ig`'s 1,459 paid-word orders
out of `unattributable_paid`. Read `is_paid_meta`, never the channel.

### 5. When the map is empty, behaviour is today's behaviour

If `load_source_alias_map` returns `{}` (table absent, or a tenant with no
rows), every source falls through to its raw spelling with `channel='unknown'`,
and `_is_meta_paid` must fall back to the historical set so
`spend_attribution` is unchanged. Keep the historical set as a module-level
fallback constant with a comment saying it is the pre-table behaviour and that
`ATTR-001` tracks its removal. **Do not leave the page's paid accounting
dependent on a migration having run.**

## What is not in this task

- **The migration and the seed.** `api/alembic/versions/**` is a protected
  path; the task will be rejected for touching it. See
  `specs/utm-source-alias-migration.md`.
- **Fixing the 154 orders `_META_PAID_SOURCES` misses.** `ATTR-001` item 1 in
  `docs/TODO.md` — 112 of them carry joinable ad set ids and are counted
  `not_paid` today. That is a live defect and a deliberate population change;
  landing it here would break the 0/0 check for the right reason at the wrong
  time. Do it separately and re-baseline the check in the same commit.
- **FOLLOW-UP 2**, dropping `referral` from the override list.
- **The frontend.** `platform/**` is protected. The page groups by and renders
  `canonical_source`, which is why the seed stores display case (`Meta`,
  `Klaviyo`) rather than the lowercase the DDL comment suggested. No CHECK is
  proposed on `canonical_source`; anything comparing it to a lowercase literal
  will silently miss.
- **Cleaning up anything else in these files.** The lint gate is a ratchet — it
  tolerates findings already present and rejects only new ones, so an unrelated
  cleanup is pure diff nobody scoped.

## Ordering, and why this can merge first

The migration must be applied to production before this changes anything a
merchant sees. It does not have to be applied before this **merges**, because
§1 degrades to `{}` and §5 makes `{}` mean today's behaviour. So the branch is
safe in either order, and the acceptance check does not need the table to
exist — it reads the seed from the fleet repo and `analytics_2.orders`.

That is the whole reason §1 and §5 are written the way they are. If either is
dropped, this task acquires a hard dependency on a migration nobody has run.

## How it is checked

    the changed files still compile
    they introduce no ruff finding that was not already there
    the 0/0 cutover diff: replacing _META_PAID_SOURCES moves no order

The third is `contracts/checks/utm_alias_cutover_diff.py`. It asserts that the
seed's four `is_paid_meta=true` rows classify **exactly** the orders the
hardcoded set classifies — measured 31 Aug 2026 as 105,540 each, lost 0,
gained 0.

It asserts the **invariant**, not the number: `analytics_2.orders` is live and
that count moved +4 in the 40 minutes between measurement and the check being
written. A literal `== 105540` would be red by morning for reasons unrelated to
anyone's change, and an unreachable gate teaches everyone to ignore it —
`TEST-004`'s finding in a new place. The count is printed with its drift, and
floor-checked only to catch a query aimed at the wrong tenant.

**There is no test gate for backend work.** The api suite has roughly 81
pre-existing failures on a clean database and cannot be run on this host at all
(`TEST-004`). A passing run means this compiles, lints clean, and does not move
the paid population. Whether the SQL groups the right rows is a question for a
human reading the diff.
