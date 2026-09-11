# Reconciliation manifests as a refund-coverage instrument — the readings

Taken 2026-09-11 as `dd_detector_login`, read-only, against `deadly_digital` on
`dd-prod`. Nothing was written. This exists because
`research/refund-coverage.md` (task 57) recommended exactly this instrument as
the next step and could not run it: `analytics_{1,2}.reconciliation_manifests`
was outside the reader grant.

**The grant made for it**, and it is the whole widening:

    GRANT SELECT ON analytics_1.reconciliation_manifests,
                    analytics_2.reconciliation_manifests TO dd_detector_login;

One table, SELECT only, in both tenant schemas. `dd_detector_login` holds no
other privilege on it.

## What the manifests cover

| | `analytics_1` | `analytics_2` |
|---|---|---|
| manifests | 25 | 29 |
| period span | 2025-12-21 → 2026-08-29 | 2026-08-07 → 2026-09-05 |
| last received | 2026-09-10 13:46Z | 2026-09-10 22:18Z |
| orders the store reports | 8,950 | 63,872 |
| orders the platform stored in that span | 325,867 | 64,863 |
| `plugin_version` | 2.5.0 only | 2.5.0 only |

**`analytics_1`'s coverage is 2.7% of the orders in its own span.** The 25
manifests are not contiguous. Any tenant-1 statement below is about the covered
periods and nothing else.

## Reading 1 — the store's refund total against the platform's, per period

Compared per manifest period, not in aggregate: an aggregate comparison over
tenant 1 would have set 8,950 reported orders against 325,867 stored ones and
produced a 15.00 "discrepancy" that is only the coverage gap.

| | periods | refund total agrees | disagrees |
|---|---|---|---|
| `analytics_1` | 25 | **25** | 0 |
| `analytics_2` | 29 | **29** | 0 |

Exact agreement in all 54 covered periods. **Within manifest coverage, the sync
has not lost a refund.** This is the first evidence bearing on requirement 2.2
that is not a re-reading of the same column.

## Reading 2 — the store's own per-status breakdown

Rolled up across every manifest, from `source_status_breakdown`, which the
connector writes from the store's own data rather than from the order-level
field:

| status | `analytics_1` count / refunds | `analytics_2` count / refunds | in `_REVENUE_STATUSES`? |
|---|---|---|---|
| `completed` | 8,950 / **0.00** | 63,871 / **0.00** | yes |
| `processing` | 0 / 0.00 | 0 / 0.00 | yes |
| `refunded` | 0 / 0.00 | 1 / **0.69** | no |
| `on-hold` | 0 / 0.00 | 0 / 0.00 | no |

**This settles the tenant-1 question `refund-coverage.md` left open.** That
document said the per-row statuses for tenant 1 had never been published, that
"if any of those four is `completed`, tenant 1's net figure does move", and that
query 1.3 would settle it. For the covered periods it is settled: every order
tenant 1 reports is `completed` and carries no refund. Tenant 1's net figure does
not move either.

It also confirms, by an independent route, the document's structural finding:
every refund either store reports sits outside `('completed','processing')`, so
`net_revenue == revenue` is structural rather than coincidental.

## What this does NOT settle, and it is the important half

**The manifest is not independent of the plugin.** Both the order-level
`refund_total` and `source_status_breakdown` are produced by the same connector
build — `2.5.0` on both tenants, with no second version anywhere to compare
against. A build that cannot see refunds at all would report zero in both
places, and the agreement above would look exactly as it does now.

So this instrument settles **"did the sync lose what the store sent?"** — no —
and cannot settle **"can the store's build see a refund at all?"**. That is V1
in `specs/refund-hook.md:264-295`, and V2 — a genuine partial refund on a
`completed` order — remains the only behavioural proof. The zero on `completed`
is consistent both with "no such refund has happened" and with "the hook never
fires for one", and nothing in the database distinguishes them.

Requirement 2.1's coverage date is still not answered in the sense asked. What
can now be said is narrower and true: refund capture is verified against the
store's own assertion from **2025-12-21** for tenant 1 (sparsely) and from
**2026-08-07** for tenant 2 (densely), and not before those dates.

## Effect on the verdict

`refund-coverage.md`'s no-go stands. Its load-bearing argument — that
`refund_total` has no state meaning "not reported", so no census of `orders` can
distinguish a quiet store from a silent build — is untouched by this, and the
manifests inherit the same limitation through the same plugin.

What changes is the cost of the remaining work: V1 and V2 are still required,
but "is the zero true" now has a partial answer from the store itself rather
than from an inference about the sync, and the re-sync erasure hazard the
document flagged is queued as task 58.
