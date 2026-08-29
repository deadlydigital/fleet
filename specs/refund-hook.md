# Does the WooCommerce connector hook `woocommerce_order_refunded`?

Produced 2026-08-29. Read-only investigation; nothing was changed in any repo,
plugin, or database.

**Answer: yes. Both spec'd hooks are registered, and the refund-driven backfill
pass the V3 spec recommends is also already implemented.** Neither of the two
items this investigation was scoped to cost needs to be built.

The question this leaves is not *what to write* but *what is actually deployed*
and *whether the path has ever been exercised*. Those are costed in
[What remains](#what-remains).

---

## How to read this

Every claim below is sourced to a file and line, or to a named commit in the
connector's own git history, which is on this box. Where the evidence is
behavioural rather than read from source, it says so.

**A scratchpad copy is not evidence of what is deployed.** That rule is applied
throughout and is the reason [Deployment](#what-is-actually-deployed) is a
separate section from [Source](#what-the-source-says) rather than folded into it.

---

## Summary

| Claim | Status | Evidence |
|---|---|---|
| `woocommerce_order_refunded` is hooked | **Yes** | source, every commit |
| `woocommerce_refund_created` is hooked | **Yes** | source, every commit |
| Refund handlers bypass the dedup guards that would otherwise swallow a partial refund | **Yes** | source |
| The push carries `refund_total` from `get_total_refunded()` | **Yes** | source |
| The V3 §2 refund-driven backfill pass exists in code | **Yes** — `wp dd sync-refunds` | source |
| That pass has ever been *run* on either tenant | **No evidence either way** | absence of any record |
| The refund path has ever been exercised behaviourally | **No** | no partial refund has ever occurred |
| The deployed builds contain the hooks | **Very probably** — not directly verified | inference, see below |

---

## The three copies on this box, and which version each is

`~/deadly-digital-platform` contains zero PHP files, as stated. Three copies of
`deadly-digital-connector.php` exist in scratchpads from earlier sessions:

| # | Path | Header `Version:` | `DD_CONNECTOR_VERSION` | Lines | Refund hooks | Backfill pass |
|---|---|---|---|---|---|---|
| A | `…/c791cd96-…/scratchpad/plugin/` | `2.3.0` | `2.3.0` | 1,754 | **No** | **No** |
| B | `…/c791cd96-…/scratchpad/conn2/` | `2.3.1` | **`2.4.0`** | 3,191 | **Yes** | **Yes** |
| C | `…/dfa4d175-…/scratchpad/conn/deadly-digital-connector/` | `2.5.0` | `2.5.0` | 4,207 | **Yes** | **Yes** |

**Copy A has no refund machinery at all** — no `refund_total`, no
`get_total_refunded()`, no `build_order_payload()`. Its only matches for
"refund" are the `wc-refunded` status string in count queries. This matters
later.

### Copy B is the mislabelled one, and it is no longer ambiguous

Copy B is not a loose file. **It is a git working tree with the connector's full
history — 8 commits.** That settles what it is:

```
3cbe7cf v2.4.0: batch retries, error classification, and wp dd sync-order
8910a34 Count records accepted, not dispatched, and never tick on a failed type
0229d5e Omit categories on WP_Error instead of sending an empty array
362e33a Extract build_product_payload() so the two product sites cannot drift
8ce7db8 Send null instead of false for absent image and permalink URLs
7ba9d9f Decouple sync processing order from checkbox DOM order
4f964a7 Fix customer count query and apply the activity filter to the fetch
27d4566 Baseline: v3 payload, keyset pagination, redesigned settings page
```

Copy B is `3cbe7cf`, the head — **the v2.4.0 source**. The header/constant
disagreement is not corruption; the release commit bumped the constant and left
the plugin header at `2.3.1`. `TODO.md:7901` and `TODO.md:6250` already identify
`3cbe7cf` this way independently.

### The hooks are present at every commit, including at version 2.3.1

Walking the history and reading the two version strings and the two refund
markers out of each commit:

| commit | header | constant | refund hooks | backfill pass |
|---|---|---|---|---|
| `27d4566` baseline | 2.3.1 | **2.3.1** | **present** | **present** |
| `4f964a7` | 2.3.1 | **2.3.1** | present | present |
| `7ba9d9f` | 2.3.1 | **2.3.1** | present | present |
| `8ce7db8` | 2.3.1 | **2.3.1** | present | present |
| `362e33a` | 2.3.1 | **2.3.1** | present | present |
| `0229d5e` | 2.3.1 | **2.3.1** | present | present |
| `8910a34` | 2.3.1 | **2.3.1** | present | present |
| `3cbe7cf` | 2.3.1 | **2.4.0** | present | present |

`git log -S` confirms all three of `woocommerce_order_refunded`,
`sync_refunded_orders` and `dd sync-refunds` were introduced by the **baseline
commit** and never removed. There is no commit in this repository that reports
`2.3.1` or `2.4.0` and lacks the hooks.

---

## What the source says

Line references are to copy B (`3cbe7cf`, v2.4.0). Copy C (2.5.0) is identical
in this area at lines 2229–2230 and 214–215.

### Registration — `deadly-digital-connector.php:1264`

```php
// Refund-driven re-push (v3 section 2). Refunds arrive minutes to weeks after
// the order was synced and a partial refund does not change the order's status,
// so nothing above re-sends the order. Without these two hooks refund_total
// stays 0 forever and the feature is silently useless. Both handlers force
// past the dedup guards in sync_order().
add_action('woocommerce_order_refunded', [$this, 'sync_order_after_refund'], 10, 2);
add_action('woocommerce_refund_created', [$this, 'sync_order_from_refund'], 10, 2);
```

Both hooks named by `CONNECTOR-V3-SPEC.md:201-202` are registered, with the
handler signatures the spec's own pseudocode implies.

`init_sync_hooks()` is called at line 145, **gated on `get_option('dd_connected')`**.
That gate is satisfied on any tenant we receive data from at all, so it is not a
live risk — but it is the one conditional in the path.

### The guards, and why they do not swallow a partial refund — line 1387

This was the standing open hypothesis in `TODO.md`, and the source closes it:

```php
public function sync_order($order_id, $force = false) {
    static $synced = [];
    if (!$force && isset($synced[$order_id])) return;      // in-request static
    $synced[$order_id] = true;
    $order = wc_get_order($order_id);
    if (!$order) return;
    $synced_status = $order->get_meta('_dd_order_synced');
    if (!$force && $synced_status === $order->get_status()) return;   // cross-request meta
    …
}
```

**`$force` bypasses both guards, not just the static.** `TODO.md:5400` flags
exactly this as the thing that needed reading — *"Read whether `$force` bypasses
the meta check or only an in-request static. If it only resets the static … the
handlers are dead on arrival for every backfilled order."* It bypasses both. The
handlers are not dead on arrival.

Both refund handlers pass `true`:

- `sync_order_after_refund($order_id, $refund_id)` — line 1418 — calls `sync_order($order_id, true)`
- `sync_order_from_refund($refund_id, $args)` — line 1431 — resolves the parent from `$args['order_id']`, falling back to `wc_get_order($refund_id)->get_parent_id()`, then calls `sync_order($parent_id, true)`

The parent resolution is correct: `woocommerce_refund_created` passes the
refund's own ID first, not the order's, and the handler accounts for that
explicitly.

### The payload carries the refund — line 1405

```php
$this->send_sync_data('/sync/orders', [
    $this->build_order_payload($order, (float) $order->get_total_refunded()),
]);
```

The realtime path deliberately *does* pay for the extra `get_total_refunded()`
lookup, with a comment saying the batch backfill must not. That is the V3 spec's
cost guidance implemented as written.

### The backfill pass exists too — lines 134 and 1461

This is the part the investigation was scoped to cost as missing. It is not
missing:

```php
if (defined('WP_CLI') && WP_CLI) {
    // Refund backfill pass, run after a historical sync (v3 section 2).
    \WP_CLI::add_command('dd sync-refunds', [$this, 'cli_sync_refunds']);
```

`sync_refunded_orders()` at line 1461 implements `CONNECTOR-V3-SPEC.md:219-226`
almost line for line — `wc_get_orders(['type' => 'shop_order_refund', …])`,
unique parent IDs, re-push **with** `refund_total` set, batched. The CLI wrapper
supports `--batch-size=<n>` and `--dry-run`. It is kept out of the admin sync UI
and the batch scheduler on purpose, so it cannot change the cost of a normal
backfill.

**So the framing this investigation started from — "the gap is the refund-driven
backfill pass, which never ran" — is half right.** The pass was designed *and
implemented*. What is unevidenced is whether it was ever **run**. That is a
different and much cheaper gap.

---

## What is actually deployed

Per `tenants.settings->>'plugin_version'`: **tenant 1 reports 2.3.1, tenant 2
reports 2.4.0.**

That string is self-reported, and it is `DD_CONNECTOR_VERSION` — the constant,
not the header the site installed. `TODO.md:8036` and
`CONNECTOR-V4-SPEC.md:156` both record this, and BUG-012 is the standing
instance of it going wrong. **The version string is not evidence of capability**
and is not used as such here.

What can be said:

1. **Every build in the repository that reports `2.3.1` or `2.4.0` has the
   hooks.** Tenant 1's reported version maps to the range `27d4566..8910a34`;
   whichever of those seven it is, it has them. Tenant 2's maps to `3cbe7cf`,
   which has them.
2. **A behavioural argument closes most of the remaining gap.** `refund_total`
   landed as `0.69` on `analytics_2.orders` for order `3570823`
   (`TODO.md:5428`). `refund_total` does not appear *anywhere* in copy A, the
   only pre-baseline source on this box. So the deployed build is at or after
   the baseline commit — and every build at or after the baseline registers both
   hooks.
3. **BUG-012's specific drift is explained by the repo, not left open.** The zip
   whose header read `2.3.1` while its constant read `2.4.0` is `3cbe7cf`
   exactly. That is a tracked commit, not an untracked working tree, so
   "version-bumped older build" does not apply to the refund path.

**Residual uncertainty, stated rather than buried:** no installed plugin file
was read, and no zip is on this box to diff against. The chain above is
inference from a reported version plus one behavioural observation. It is tight,
but it is not the one grep that would settle it.

---

## The prior finding that this overturns

`TODO.md` NET-REV-001 at one point concluded **"`woocommerce_refund_created` is
not registered"** and made installing the hooks a blocking dependency for net
revenue (`TODO.md:5467`, still an open unchecked box).

**That conclusion was already retracted in `TODO.md:5205` on 26 Aug** — the
partial refund it rested on never happened, so the absence of a push was not
evidence of anything. The retraction was correct, and **the source now confirms
it independently**: the hooks are registered, and the `$force`/`_dd_order_synced`
hypothesis recorded alongside it is also resolved in the plugin's favour.

Two live checkboxes should be closed against the source rather than left open:

- `TODO.md:5467` — *"Install the two refund hooks in the connector, or accept
  that net revenue cannot be computed"* — **void, they are installed**
- `TODO.md:5400` — *"Read whether `$force` bypasses the meta check"* —
  **answered: it bypasses both guards**

One should be closed for a different reason:

- `TODO.md:5403` — *"add `woocommerce_order_partially_refunded` to the spec"*.
  **Not needed.** WooCommerce's `wc_create_refund()` fires both
  `woocommerce_refund_created` and `woocommerce_order_refunded` unconditionally
  on every refund creation, full or partial;
  `woocommerce_order_partially_refunded` is itself downstream of
  `woocommerce_order_refunded`. `CONNECTOR-V3-SPEC.md` §2 is correct as written.
  **Confidence: high, but this is the one claim here not read off a file on this
  box** — no WooCommerce source is installed. Confirm against WC 10.3.8 before
  relying on it.

---

## What remains

Neither costed item exists as work. What is left is verification and one
operational run.

| # | Work | Cost | Blocked on |
|---|---|---|---|
| **V1** | Read the installed plugin on each tenant: `grep -n "woocommerce_order_refunded\|woocommerce_refund_created" deadly-digital-connector.php`, plus header vs constant | **~15 min/tenant** | Filesystem or WP-admin access to each WordPress host |
| **V2** | Genuine **partial** refund on a `completed` order; watch `analytics_N.orders.refund_total` and `updated_at` | **~30 min** incl. observation | A real order to refund; merchant consent |
| **R1** | Run `wp dd sync-refunds --dry-run`, then for real, per tenant | **~10 min + runtime** | WP-CLI on each host |
| **R1 runtime** | O(refunds), not O(orders) | **Tenant 2: seconds** — exactly 1 refund in 2.84M orders. **Tenant 1: unknown**, dry-run reports it first | — |
| **F1** | *Contingency only* — if V1 finds a build without the hooks: rebuild and ship a corrected zip | **~0.5–1 day** incl. release and per-tenant update | V1 outcome |

**V1 and V2 are independent and can run in either order.** V1 is cheaper and
settles the source question; V2 is the only thing that settles the *behavioural*
question, and it is the test that has never actually been run — the one attempt
was recorded as run, then retracted as never having happened.

**R1 is worth running on tenant 1 regardless of V1**, because it is idempotent
(the backend upserts on `woo_order_id`), cheap, and its dry-run answers "how
many refunds does this store even have" — which is currently unknown and is the
input to every other decision here.

### Sequencing note

Do **V1 before V2**. If V1 shows the hooks are present, a V2 failure localises
immediately to the push path rather than reopening the registration question —
which is the loop this investigation has already been through twice.

---

## Related defects found, not part of this question

Disclosed here because they were found while reading this source. None of them
changes the answer above.

### D1 — BUG-012's remediation cannot work as written

BUG-012 concludes the production build predates the migration-0010 item payload
change, and prescribes *"item price/SKU will require a re-sync once a correct
build is installed."*

Reading the source:

- **`order_items.price` is absent from `build_order_payload()` in *every* copy on
  this box, including 2.5.0.** There is no build to install that would send it.
- **`sku` *is* present** in both v2.4.0 (line 1312) and v2.5.0 (line 2277), yet
  BUG-012 measured `sku` arriving **0/74**. A stale build does not explain that.

So the two fields have different causes and BUG-012 treats them as one. `price`
is unimplemented; `sku` is implemented and not arriving, which is a live and
undiagnosed defect. **This belongs against BUG-012, not here** — flagged rather
than folded in, because it changes that entry's prescription.

### D2 — refund pushes are fire-and-forget by construction

`sync_order()` calls `send_sync_data()` with the default `$blocking = false`.
The function's own comment is accurate: *"nothing waits on the response, so the
outcome is genuinely unknowable."* The in-request retry and error classification
added in v2.4.0 apply **only** to the blocking path.

**Consequence for this question:** a refund push that fails is invisible from the
store side and leaves no log. It is not a bug — it is the documented design —
but it means V2 is the only instrument that can detect a broken refund push, and
a V2 failure will not come with a reason.

### D3 — `send_event()` has an inert `$blocking` parameter

Line 1212 in v2.4.0, line 2194 in v2.5.0:

```php
'timeout'  => $blocking ? 30 : 5,
'blocking' => false,          // hardcoded
```

The timeout honours the parameter; the request never blocks. Calling
`send_event($data, true)` buys a 30-second timeout on a request whose result is
discarded. **Tracking path only — not on the order sync or refund path**, and
`send_sync_data()` at line 1605 does this correctly (`'blocking' => $blocking`).
Cosmetic, ~5 minutes, no data impact.

---

## What would settle the question definitively

One command, on each tenant's WordPress host:

```bash
grep -n "woocommerce_order_refunded\|woocommerce_refund_created" \
  wp-content/plugins/deadly-digital-connector/deadly-digital-connector.php
sed -n '5p;22p' wp-content/plugins/deadly-digital-connector/deadly-digital-connector.php
```

Two hits on the first command means the hooks are installed. The second prints
the header and the constant together, so the BUG-012 drift is visible in the
same breath.

**Nothing on this box can substitute for it.** Everything above is source in a
scratchpad git tree plus one behavioural observation, and this codebase has been
burned twice — BUG-012, and NET-REV-001's double retraction — by treating that
class of evidence as settled.
