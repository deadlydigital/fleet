-- =====================================================================
-- public.utm_source_alias — seed, tenant 2 (analytics_2)
--
-- 22 raw utm_source spellings -> 20 rows.
-- Lookup key is lower(btrim(utm_source)): 'Meta_Paid' folds into
-- 'meta_paid', and 'SMS' folds into 'sms' ALONGSIDE a genuine lowercase
-- 'sms' sibling of 144 orders. The earlier header asserted there was no
-- such sibling; there is. See row 19 -- the merged key is 1,450 orders,
-- not 1,306, and it was live until 9 May 2026.
--
-- NOT APPLIED. Read-only artefact.
--
-- STATUS OF THE COUNTS: RE-MEASURED 31 Aug 2026 ~20:30 UTC against
-- analytics_2.orders @ dd-prod, read-only
-- (default_transaction_read_only=on), as `listmonk`. All four queries at
-- the foot have been run and their results are recorded there. Row 20 is
-- SETTLED.
--
-- The per-row narrative figures below are the earlier session's
-- 16:30 UTC reading and have deliberately NOT been rewritten in place --
-- query (4)'s output at the foot is the authority, and the delta column
-- is itself evidence. Fourteen of nineteen rows drifted upward in four
-- hours; the table is live and ingesting. Treat every count here as
-- "as at a stated time", never as a fixed census.
--
-- SIX FLAGS: all decided by the operator, 31 Aug 2026. Each row's note
-- records the decision and its reasoning. Two decisions changed a value;
-- two changed nothing but are now closed; two became follow-ups.
-- =====================================================================


-- =====================================================================
-- PART 1 — TWO AMENDMENTS TO THE PROPOSED DDL
--
-- The table has not been created yet, so these are folded into the
-- CREATE TABLE rather than run as migrations. ALTER equivalents follow,
-- commented, in case it has since shipped.
-- =====================================================================
--
-- (a) allow_override — required by flag 6, non-negotiable. Five of the
--     twenty rows opt out of the medium override. Its existence is the
--     admission that the override is NOT the closed universal rule the
--     proposal described.
--
--         allow_override BOOLEAN NOT NULL DEFAULT true,
--
-- (b) A CHECK on channel, including 'social'. 'social' was absent from
--     the proposed vocabulary while flag 2 named it as ig's override
--     target and row 20 stores it — it would have inserted silently
--     against an unconstrained VARCHAR(24).
--
--         CONSTRAINT chk_utm_source_alias_channel CHECK (channel IN (
--             'paid','organic','referral','social','email','sms',
--             'direct','none','not-a-channel','unknown')),
--
-- ALTER form, if the table already exists:
--
--   ALTER TABLE public.utm_source_alias
--     ADD COLUMN allow_override BOOLEAN NOT NULL DEFAULT true;
--
--   ALTER TABLE public.utm_source_alias
--     ADD CONSTRAINT chk_utm_source_alias_channel CHECK (channel IN (
--         'paid','organic','referral','social','email','sms',
--         'direct','none','not-a-channel','unknown'));
--
-- STILL OPEN, deliberately not resolved here: canonical_source case.
-- The DDL comment gives lowercase examples ('meta','google','klaviyo');
-- these rows are display-cased ('Meta','Google','Klaviyo') because the
-- page groups by and renders that column. No CHECK is proposed on it —
-- a vocabulary constraint on canonical_source would have to be extended
-- on every new merchant-visible source name, which is the opposite of
-- the maintenance property this table exists for. Any code comparing
-- canonical_source to a lowercase literal will silently miss.
-- =====================================================================


-- =====================================================================
-- PART 2 — THE SEED
-- =====================================================================

BEGIN;

INSERT INTO public.utm_source_alias
    (tenant_id, alias_norm, alias_raw, canonical_source, channel,
     is_paid_meta, allow_override, origin, note)
VALUES

-- 1 | 833,493 orders | override suppressed
(2, '', '', '(untagged)', 'none', false, false, 'seed',
 'Empty string, not NULL: sync_engine.py:422 skips _text() on the three UTM '
 'columns, so 833,493 rows hold '''' and zero hold NULL. 832,817 of them also '
 'carry an empty utm_medium -- the whole triple is absent together. NOT direct: '
 '(direct) is written deliberately by the connector and the two never co-occur. '
 'Must be excluded from any percentage-of-attributed denominator.'),

-- 2 | 630,483 orders | override suppressed
(2, '(direct)', '(direct)', '(direct)', 'direct', false, false, 'seed',
 'Deliberate connector sentinel, uninterpretable from this side: no referrer, '
 'stripped referrer and in-app browser are indistinguishable. 594,021 carry an '
 'empty medium, 35,727 the literal (none). Override suppressed because 224 rows '
 'carry utm_medium=''referral'' and must not drag a sentinel into referral.'),

-- 3 | 552,258 orders
(2, 'm.facebook.com', 'm.facebook.com', 'Meta', 'referral', false, true, 'seed',
 'Mobile Facebook app referrer. 550,418 referral, 1,761 social, 0 ad set ids. '
 'Fails all three paid tests: no id, no paid word, host-shaped spelling. '
 'Meta-attributable revenue that no ad can be billed for.'),

-- 4 | 334,955 orders
(2, 'klaviyo', 'Klaviyo', 'Klaviyo', 'email', false, true, 'seed',
 '333,550 campaign (broadcast) + 1,283 flow (automated). Both are email; the '
 'broadcast/automation split belongs in the medium, not the channel.'),

-- 5 | 256,962 orders | channel is a default, not a property of the spelling
(2, 'google', 'google', 'Google', 'organic', false, true, 'seed',
 '229,267 organic and 27,459 cpc. The stored channel is the DEFAULT; the medium '
 'override promotes the cpc rows to paid on the read path. One alias row, two '
 'channels, correctly.'),

-- 6 | 71,616 + 9,013 = 80,629 orders | FLAG 1 — DECIDED: keep paid
(2, 'meta_paid', 'meta_paid', 'Meta', 'paid', true, true, 'seed',
 'FLAG 1 -- DECIDED 31 Aug 2026: KEEP PAID. Merged key: meta_paid (71,616) + '
 'Meta_Paid (9,013) = 80,629 orders. The meta_paid side carries 43,326 ad set '
 'ids (test 1) and is effectively all of the store''s joinable spend. The '
 'Meta_Paid side carries ZERO ad set ids and ZERO paid-words -- every medium is '
 'an audience name (ADV+ 1,916, ASC_HOLIDAYS 1,847, RETARGET_CASH 1,054) -- so '
 'it is paid on test 3 alone. Rationale for keeping: the spelling asserts intent '
 'even where nothing measures it, and moving GBP 60,469 of lifetime revenue out '
 'of paid on a hunch is the worse error. Accepted consequence: those 9,012 '
 'revenue orders sit in unattributable_paid and hold spend_attribution at '
 '''partial'' permanently. That is intended and should stay visible.'),

-- 7 | 48,637 orders
(2, 'facebook.com', 'facebook.com', 'Meta', 'referral', false, true, 'seed',
 'Desktop Facebook referrer. 48,340 referral, 215 social, 0 ad set ids. '
 'On the page''s live window this is the single biggest Meta fragment and it is '
 'entirely unpaid.'),

-- 8 | 37,886 orders
(2, 'l.facebook.com', 'l.facebook.com', 'Meta', 'referral', false, true, 'seed',
 'Facebook outbound link shim. 37,872 referral, 0 ad set ids. It appears '
 'precisely because a link was clicked without tags surviving.'),

-- 9 | 18,884 orders
(2, 'fb', 'fb', 'Meta', 'paid', true, true, 'seed',
 '11,494 carry utm_medium=''paid'' (test 2); the rest are ad set names '
 '(RETARGET++PURCHASE 464, lal1 335) across 100 distinct mediums. Only 4 ad set '
 'ids, so this is paid that can never be costed. Dead since 14 Aug 2026.'),

-- 10 | 12,086 orders
(2, 'l.instagram.com', 'l.instagram.com', 'Meta', 'referral', false, true, 'seed',
 'Instagram link shim; same mechanism as l.facebook.com. 12,084 referral, '
 '0 ad set ids.'),

-- 11 | 5,430 orders | FLAG 2 — DECIDED: changed paid -> social
(2, 'ig', 'ig', 'Meta', 'social', true, true, 'seed',
 'FLAG 2 -- DECIDED 31 Aug 2026: CHANGED from paid to social. 3,291 social vs '
 '1,459 paid, plus 82 distinct mediums of ad set names. The row now defaults to '
 'its own majority and the medium override promotes the 1,459 paid-word orders '
 'on the read path -- same output as the paid default, honest stored value. '
 'Rationale: a stored channel describing a minority of its own traffic is what '
 'misleads whoever reads this table next. '
 'NOTE THE DELIBERATE MISMATCH: channel=''social'' with is_paid_meta=true. These '
 'answer different questions -- channel is what an order defaults to, '
 'is_paid_meta is whether this spelling can carry Meta spend at all (test 3 '
 'membership, replacing _META_PAID_SOURCES). Keeping is_paid_meta true preserves '
 'the 1,459 paid-word orders in spend_attribution''s unattributable_paid count. '
 'Flipping it would hide them. That two-questions split is the whole thesis of '
 'this table and this row is where it becomes visible.'),

-- 12 | 4,204 orders | FLAG 5 — DECIDED: leave as-is
(2, 'bing.com', 'bing.com', 'Bing', 'referral', false, true, 'seed',
 'FLAG 5 -- DECIDED 31 Aug 2026: LEAVE AS-IS. 4,185 referral. A search engine '
 'arriving as a referrer host, kept referral rather than organic because '
 '''referral'' sits in the override list: an organic default would be overridden '
 'straight back and the stored value would misstate what decided the row. '
 'Dropping ''referral'' from the override list is logged as its own decision -- '
 'see FOLLOW-UP 2. Do not fix this row in isolation.'),

-- 13 | 4,152 orders | FLAG 3 — DECIDED: (untagged) -> (broken)
(2, 'undefined', 'undefined', '(broken)', 'none', false, false, 'seed',
 'FLAG 3 -- DECIDED 31 Aug 2026: canonical_source CHANGED from (untagged) to '
 '(broken). A JavaScript undefined stringified into BOTH source and medium on '
 'all 4,152 rows. Dead 10 Jan - 16 Feb 2024. Rationale: burying a front-end '
 'defect inside a bucket meaning "the connector had nothing to say" is how it '
 'stays unfixed for another two years. (broken) keeps it countable and separately '
 'nameable from the 833k genuine (untagged). '
 'CHANNEL LEFT AT ''none'', NOT MOVED TO ''unknown'' -- flagging this, because the '
 'artefact''s stated alternative was "(broken) / unknown" and only the '
 'canonical_source half was ruled on. ''unknown'' is the read path''s fall-through '
 'for UNMAPPED values (COALESCE(a.channel,''unknown'')), so storing it on a mapped '
 'row makes the two indistinguishable -- the same sentinel collision already '
 'flagged for (direct) and (none). (broken) carries the "this is a bug" signal on '
 'its own; the channel does not need to. Reverse if you disagree. '
 'Override suppressed: source and medium are both the same defect.'),

-- 14 | 3,653 orders | FLAG 4 — DECIDED: referral, unchanged
(2, 'loquax.co.uk', 'loquax.co.uk', 'Loquax', 'referral', false, true, 'seed',
 'FLAG 4 -- DECIDED 31 Aug 2026: REFERRAL, unchanged. Competition-listing site. '
 '3,653 referral orders carrying GBP 285.95 between them -- a GBP 0.08 average '
 'order. The classification was never in doubt; the risk is a reader sorting by '
 'orders and reading a free-entry firehose as a top-15 acquisition channel. '
 'Nothing in this table can fix that. Logged separately -- see FOLLOW-UP 1.'),

-- 15 | 2,738 orders
(2, 'lm.facebook.com', 'lm.facebook.com', 'Meta', 'referral', false, true, 'seed',
 'Facebook lite/mobile shim. 2,738 referral, one medium, no ambiguity.'),

-- 16 | 2,535 orders | override suppressed
(2, 'com.google.android.gm', 'com.google.android.gm', '(email client)', 'email', false, false, 'seed',
 'Gmail Android package name arriving as a referrer: 2,438 referral, 85 organic. '
 'The click came from an email so the channel is right, but WHICH email is '
 'unrecoverable -- it must not merge into Klaviyo. Override suppressed, or the '
 'referral medium would call it referral.'),

-- 17 | 1,704 orders
(2, 'duckduckgo.com', 'duckduckgo.com', 'DuckDuckGo', 'referral', false, true, 'seed',
 '1,696 referral. Same treatment and reasoning as bing.com -- see flag 5.'),

-- 18 | 1,308 orders | FLAG 5 — DECIDED: leave as-is
(2, 'google.com', 'google.com', 'Google', 'organic', false, true, 'seed',
 'FLAG 5 -- DECIDED 31 Aug 2026: LEAVE AS-IS. 1,301 of 1,301 revenue orders '
 'carry organic -- so this host-shaped value is organic while bing.com is '
 'referral, and the difference is the connector, not the traffic. First seen '
 '17 Feb 2026 with no row before it: part of the unexplained connector change. '
 'Merges into Google. The asymmetry with bing.com is accepted, not smoothed.'),

-- 19 | 1,306 orders | FLAG 6 — DECIDED: allow_override = false
(2, 'sms', 'SMS', 'SMS', 'sms', false, false, 'seed',
 'FLAG 6 -- DECIDED 31 Aug 2026: allow_override FALSE. Non-negotiable. The '
 'override applied as written makes an owned SMS list a paid-media channel and '
 'parks it beside CPA and ROAS -- the exact boundary the canonical_source/channel '
 'split exists to protect. This row is why the allow_override column exists. '
 'CORRECTED 31 Aug 2026 20:30 UTC, and the correction does not change the '
 'decision: the key is TWO raw spellings, not one. ''SMS'' = 1,306 orders, all '
 'utm_medium=''paid'', 5 Jan - 24 Aug 2025. ''sms'' = 144 orders, all '
 'utm_medium=''sms'', 22 Feb - 9 May 2026. Merged key = 1,450 orders. The two '
 'earlier claims that were wrong: "all 1,306 carry utm_medium=paid" describes only '
 'the uppercase spelling, and "Dead since 24 Aug 2025" is false -- the key was live '
 'to 9 May 2026. The lowercase run begins within days of the 17 Feb 2026 connector '
 'change that rows 18 and 20 also record. allow_override=false is if anything '
 'reinforced: ''sms'' is not in the override list, so the 144 would fall through '
 'to the stored channel anyway, and the 1,306 are exactly the rows the flag protects.'),

-- =====================================================================
-- 20 | 559 orders | rank 26 all-time | SETTLED 31 Aug 2026 20:30 UTC
--
-- Queries (1) and (2) have been run. Both caveats are discharged, and
-- the row's own headline was wrong.
--
--  (a) MEASURED, and the row STANDS. All-time distribution for
--      'facebook' is 559 orders: social 403 (72.1%), weekly 153
--      (27.4%), paid 3 (0.5%). ZERO ad set ids on any of them. The
--      condition this row was held on -- "if ad set ids or a paid-word
--      majority appear, the channel must go back to 'paid'" -- DID NOT
--      FIRE. channel='social' now rests on a census, not on one day.
--
--  (b) THE RANK-21 CLAIM IS REFUTED, and the artefact was right.
--      'facebook' is rank 26 all-time at 559 orders. The value
--      immediately below sms is 'draw+day+single+3' at 1,019 orders --
--      exactly the "ad name worth 1,019 orders" the artefact named.
--      Rank 21 is 'meta_80k100kwinners' (980). Nothing about this row
--      was ever rank 21; the brief was wrong and this file repeated it.
--
--      The row's ACTUAL justification is untouched by that, because it
--      was never the all-time rank: on the window the page opens
--      (Today, preset 0, page.tsx:405) 'facebook' rendered GBP 159.65
--      from 7 customers -- 6th of 37 rows by revenue at source/medium
--      grain, 5th once the (direct) sentinel is set aside -- and
--      unmapped it falls through to its raw spelling at
--      channel='unknown' near the top of a page rendering CPA and ROAS.
--      It is also still live: last order 31 Aug 2026.
--
--      What the corrected rank DOES expose: six unmapped keys sit above
--      'facebook' by all-time volume -- draw+day+single+3 (1,019),
--      meta_80k100kwinners (980), 125k_cash_22824 (849),
--      150_cash_031024 (640), full+|+defender+...campaign (637),
--      uk.search.yahoo.com (624). Four are Meta ad names in the source
--      field. All six carry zero ad set ids, and all but yahoo are dead
--      (last orders 2024-2025). Leaving them unseeded is defensible;
--      leaving them unseeded WITHOUT SAYING SO was not. It is now a
--      stated omission.
--
--  (c) NEW, found while settling (a) -- THIS ROW IS TWO POPULATIONS.
--      The 153 'weekly' orders run 2024-01-10 -> 2025-09-22. The 403
--      'social' orders ALL begin 2026-02-17 -- the exact date row 18
--      records for google.com as "part of the unexplained connector
--      change". So the social majority this row defaults to is an
--      artefact of that connector change, not a property of the
--      spelling, and it is the same change that produced the lowercase
--      'sms' sibling in row 19. Three rows now point at 17 Feb 2026.
--      Consequence to accept: 'weekly' is not in the medium override
--      list, so those 153 email-shaped orders render as social/Meta.
--      Same "one alias row, two channels" shape as row 5 (google), but
--      here the override does NOT rescue the minority.
--
-- is_paid_meta HELD TRUE -- now on evidence, not as a placeholder.
-- 3 orders carry utm_medium='paid'. Flipping the flag would drop them
-- from spend_attribution's unattributable_paid count silently, which is
-- the exact failure FOLLOW-UP 3 exists to prevent. Same deliberate
-- channel='social' + is_paid_meta=true split as row 11 (ig), and it
-- keeps cutover behaviour for spend_attribution identical: this row
-- changes what the page DISPLAYS, not what it COUNTS as paid.
-- Accepted consequence: with 0 ad set ids, 'facebook' can carry no
-- costable spend at all, so those 3 orders hold spend_attribution at
-- 'partial' permanently -- as row 6's 9,013 already do.
-- =====================================================================
(2, 'facebook', 'facebook', 'Meta', 'social', true, true, 'seed',
 'VERIFIED 31 Aug 2026 20:30 UTC -- census, not a sample. 559 orders all-time: '
 '403 social, 153 weekly, 3 paid, and ZERO ad set ids. Defaults to social on its '
 'own majority per the ig precedent; the medium override promotes the 3 paid-word '
 'orders on the read path. is_paid_meta TRUE: ''facebook'' is in _META_PAID_SOURCES '
 'today, and holding the flag keeps those 3 orders in unattributable_paid so '
 'spend_attribution counts identically at cutover -- this row changes the display, '
 'not the count. Rank 26 all-time, NOT rank 21: that claim came from the brief and '
 'is refuted -- the value below sms is ''draw+day+single+3'' at 1,019 orders, as the '
 'artefact said. The row is justified by the page''s default Today window (GBP 159.65 '
 'from 7 customers, rank 5-6 by revenue) and by still being live, not by all-time '
 'volume. KNOWN SPLIT: the 153 ''weekly'' orders (2024-01-10 to 2025-09-22) predate '
 'the 17 Feb 2026 connector change that produced all 403 social orders; ''weekly'' is '
 'not in the override list, so they render as social/Meta. With 0 ad set ids this '
 'spelling can carry no costable spend, so the 3 paid orders hold spend_attribution '
 'at ''partial''.');

COMMIT;


-- =====================================================================
-- PART 3 — COVERAGE (MEASURED 31 Aug 2026 20:30 UTC, query (3))
--
--   All 20 keys:   2,834,834 of 2,851,916 orders = 99.401%
--   Rows 1-19only: 99.381%
--   Row 20 adds:   +0.020pp (559 orders)
--
--   The 99.381% carried from the earlier session RE-VERIFIES EXACTLY on
--   rows 1-19, four hours and ~833 orders later. That is the one relayed
--   figure that survived unchanged, and it survived because it is a
--   ratio: numerator and denominator drifted together. Every absolute
--   count in this file drifted; the ratio did not. Worth remembering the
--   next time a relayed figure looks stable.
--
--   Uncovered remainder: 17,082 orders (0.599%), the long tail of ad
--   names and campaign strings written into utm_source. The six largest
--   are enumerated in row 20 note (b) and are deliberately not seeded.
-- =====================================================================


-- =====================================================================
-- PART 4 — FOLLOW-UPS LOGGED, NOT ACTIONED HERE
--
-- FOLLOW-UP 1 (from flag 4) — PARTLY ALREADY DONE. Verified in source
--   31 Aug 2026: platform/app/(dashboard)/analytics/sources/page.tsx:407
--   is useState<string>('revenue'), so the page's DEFAULT sort is already
--   revenue, not orders. The flag 4 worry does not apply to the view a
--   merchant lands on. What remains: sortKey is user-settable (line 760),
--   so an orders-sorted click still puts loquax.co.uk — 3,653 orders at
--   GBP 0.08 each — in the top 15; and the seed ranking in the source
--   artefact is itself orders-ranked, which is where the row looked
--   alarming. No page change is required for the default. Decide only
--   whether an orders-sorted view needs a revenue column alongside it.
--
-- FOLLOW-UP 2 (from flag 5) — decide whether to drop 'referral' from
--   the medium override list. Doing so would let alias defaults classify
--   search hosts as organic and would make bing.com/google.com
--   symmetric. It is a change to the override rule itself, affecting
--   every row that is not allow_override=false, and is deliberately NOT
--   bundled with the seed.
--
-- FOLLOW-UP 3 (from row 20) — reconcile _META_PAID_SOURCES with this
--   table at cutover. RAISED TO ITS OWN TODO ENTRY, `ATTR-001` in
--   docs/TODO.md, 31 Aug 2026 — it is a cutover-safety gap in
--   spend_attribution, not a note on this seed.
--
--   RE-MEASURED 31 Aug 2026 20:30 UTC. The headline number is right and
--   the enumeration under it was not:
--
--     - 154 Meta-paid orders counted not_paid today: CONFIRMED EXACTLY.
--     - 'instagram' and 'meta' match zero orders: CONFIRMED.
--     - 'facebook' is here as channel=social with is_paid_meta=true, so
--       spend_attribution is unchanged by it: CONFIRMED (see row 20).
--     - "all four differences": WRONG. The 154 orders are spread over
--       TWELVE raw spellings, not four, and one whole family --
--       `meta_paid-WebsiteKeyInfo` (4 orders, 4 ad set ids, live to
--       19 Jul 2026) -- was never named. The numbered variants
--       (fb-SiteLink-1/-2/-3/-5, meta_paid-SiteLink-2/-3/-5) were not
--       named either. Porting "the four" ports 143 of 154.
--
--   AND THE FOLLOW-UP'S OWN PREMISE DOES NOT HOLD, measured: "deleting
--   the set changes spend_attribution silently" is FALSE for this seed
--   as written. The set classes 105,540 orders Meta-paid; the four
--   is_paid_meta=true rows here class THE SAME 105,540. Lost at
--   cutover: 0. Gained: 0. That is by construction -- row 20 holds
--   is_paid_meta TRUE exactly to buy this, and instagram/meta match
--   nothing so dropping them costs nothing. The exposure is any EDIT to
--   this seed made without that diff in hand, not the cutover itself.
--
--   And the substance is worse than a miscount: 108 of the 114
--   `meta_paid-SiteLink` orders CARRY AD SET IDS. Those are joinable,
--   costable Meta spend being counted not_paid right now, on a spelling
--   that is still live (last order 31 Aug 2026). That is not a cutover
--   risk -- it is a live defect the cutover would merely preserve.
--
--   Full enumeration and the adjacent 23-order finding are in ATTR-001.
-- =====================================================================


-- =====================================================================
-- PART 5 — THE FOUR QUERIES: ALL RUN, 31 Aug 2026 ~20:30 UTC
--
-- Connection: deadly_digital @ dd-prod, user `listmonk`, sslmode=require,
-- session forced read-only at connect time
-- (PGOPTIONS='-c default_transaction_read_only=on'; SHOW confirmed `on`
-- before any statement ran). Identity check: analytics_2.orders present
-- and SELECTable, ~2.85M rows, alongside analytics_1 and public --
-- i.e. this is the right database, not the listmonk instance the
-- earlier session was pointed at.
--
-- READ THIS FIRST: the counts are a MOVING TARGET, not a census.
-- `google` returned 257,066 in query (2) and 257,068 in query (4),
-- minutes apart. And row 6's `Meta_Paid` held 9,013 orders across both
-- readings while its gross total moved GBP 60,469 -> 60,479.81 -- so
-- EXISTING rows are being updated, not only new ones inserted. Any
-- figure in this file is "as at a stated time" and nothing stronger.
-- =====================================================================

-- ---------------------------------------------------------------------
-- (1) SETTLES ROW 20. RUN. Result: channel='social' STANDS.
-- ---------------------------------------------------------------------
-- SELECT utm_medium,
--        count(*) AS orders,
--        count(*) FILTER (WHERE utm_medium ~ '^[0-9]{10,}$') AS adset_ids
--   FROM analytics_2.orders
--  WHERE lower(btrim(utm_source)) = 'facebook'
--  GROUP BY utm_medium
--  ORDER BY orders DESC;
--
--   utm_medium | orders | adset_ids | first_order | last_order
--   -----------+--------+-----------+-------------+------------
--   social     |    403 |         0 | 2026-02-17  | 2026-08-31
--   weekly     |    153 |         0 | 2024-01-10  | 2025-09-22
--   paid       |      3 |         0 | 2026-01-08  | 2026-01-08
--                559 total, ZERO ad set ids anywhere.
--
-- The escalation condition ("ad set ids or a paid-word majority") did
-- not fire: paid is 3 orders, 0.5%. The date columns are the extra --
-- they are what exposed the two-population split in row 20 note (c).

-- ---------------------------------------------------------------------
-- (2) SETTLES THE RANK CONFLICT. RUN. Result: THE ARTEFACT WAS RIGHT.
-- ---------------------------------------------------------------------
-- SELECT lower(btrim(utm_source)) AS alias_norm, count(*) AS orders
--   FROM analytics_2.orders
--  GROUP BY 1 ORDER BY orders DESC OFFSET 18 LIMIT 6;
--
--   rank | alias_norm                          | orders
--   -----+-------------------------------------+--------
--     19 | google.com                          |   1314
--     20 | draw+day+single+3                   |   1019   <-- the artefact's "ad name worth 1,019"
--     21 | meta_80k100kwinners                 |    980   <-- the actual rank 21
--     22 | 125k_cash_22824                     |    849
--     23 | 150_cash_031024                     |    640
--     24 | full+|+defender+...+campaign        |    637
--     25 | uk.search.yahoo.com                 |    624
--     26 | facebook                            |    559   <-- the row in question
--
-- 'facebook' is rank 26. It was never rank 21. Note also that seed rows
-- 18 and 19 are now in the wrong relative order: sms (1,450) outranks
-- google.com (1,314), because the sms count was understated by the
-- missing lowercase sibling.

-- ---------------------------------------------------------------------
-- (3) EXACT COVERAGE. RUN. Result: 99.401% on 20 keys. See PART 3.
-- ---------------------------------------------------------------------
-- SELECT round(100.0 * count(*) FILTER (
--          WHERE lower(btrim(utm_source)) IN (
--            '', '(direct)', 'm.facebook.com', 'klaviyo', 'google',
--            'meta_paid', 'facebook.com', 'l.facebook.com', 'fb',
--            'l.instagram.com', 'ig', 'bing.com', 'undefined',
--            'loquax.co.uk', 'lm.facebook.com', 'com.google.android.gm',
--            'duckduckgo.com', 'google.com', 'sms', 'facebook'))
--        / count(*), 3) AS pct_covered
--   FROM analytics_2.orders;
--
--   total_orders | covered   | pct_covered
--   -------------+-----------+-------------
--      2,851,916 | 2,834,834 |      99.401
--   rows 1-19 only:                 99.381   (relayed figure, re-verified)

-- ---------------------------------------------------------------------
-- (4) RE-VERIFY THE RELAYED COUNTS. RUN. Result: 14 of 19 DRIFTED.
-- ---------------------------------------------------------------------
-- SELECT lower(btrim(utm_source)) AS alias_norm, count(*) AS orders
--   FROM analytics_2.orders
--  WHERE lower(btrim(utm_source)) IN ( ...the 20 keys... )
--  GROUP BY 1 ORDER BY orders DESC;
--
--  row | alias_norm            | relayed | measured | delta | verdict
--  ----+-----------------------+---------+----------+-------+---------
--    1 | (empty string)        | 833,493 |  833,497 |    +4 | DRIFT
--    2 | (direct)              | 630,483 |  630,716 |  +233 | DRIFT
--    3 | m.facebook.com        | 552,258 |  552,313 |   +55 | DRIFT
--    4 | klaviyo               | 334,955 |  335,149 |  +194 | DRIFT
--    5 | google                | 256,962 |  257,068 |  +106 | DRIFT
--    6 | meta_paid             |  80,629 |   80,662 |   +33 | DRIFT
--    7 | facebook.com          |  48,637 |   48,827 |  +190 | DRIFT
--    8 | l.facebook.com        |  37,886 |   37,888 |    +2 | DRIFT
--    9 | fb                    |  18,884 |   18,884 |     0 | match
--   10 | l.instagram.com       |  12,086 |   12,086 |     0 | match
--   11 | ig                    |   5,430 |    5,433 |    +3 | DRIFT
--   12 | bing.com              |   4,204 |    4,207 |    +3 | DRIFT
--   13 | undefined             |   4,152 |    4,152 |     0 | match
--   14 | loquax.co.uk          |   3,653 |    3,653 |     0 | match
--   15 | lm.facebook.com       |   2,738 |    2,738 |     0 | match
--   16 | com.google.android.gm |   2,535 |    2,536 |    +1 | DRIFT
--   17 | duckduckgo.com        |   1,704 |    1,704 |     0 | match
--   18 | google.com            |   1,308 |    1,314 |    +6 | DRIFT
--   19 | sms                   |   1,306 |    1,450 |  +144 | DRIFT **
--   20 | facebook              |       - |      559 |     - | NEW
--
-- ** Row 19's +144 is NOT drift. Every other delta is four hours of
--    ingestion on a live table, and they scale with row volume. Row 19
--    is a supposedly-dead row that gained 144 orders, which is the
--    wrong shape -- and it was the wrong shape because the relayed
--    1,306 counted only the raw spelling 'SMS'. A separate lowercase
--    'sms' (144 orders, utm_medium='sms', 22 Feb - 9 May 2026) exists
--    and the seed header explicitly denied it. See row 19.
--
--    The general lesson, since this file exists to be trusted later: a
--    delta that does not scale with the row's volume is a DEFINITION
--    difference, not a measurement difference. Fourteen deltas here are
--    ingestion. One is a bug in the earlier query's grouping.
--
-- The five 'match' rows are all dead spellings (fb, l.instagram.com,
-- undefined, loquax.co.uk, lm.facebook.com) -- they match because they
-- receive nothing, which is confirmation of the "dead since" notes, not
-- of the counting.

-- =====================================================================
-- PART 6 — DECISION-DRIVING CLAIMS, SPOT RE-VERIFIED 31 Aug 2026 20:30
--
-- The four queries above cover volume. The flags turned on medium
-- splits, so those were re-measured too. ALL FOUR HOLD:
--
--   FLAG 1 (row 6)  meta_paid: 43,394 ad set ids (was 43,326), 1,734
--                   paid-words, 539 distinct mediums, GBP 645,454.76.
--                   Meta_Paid: 9,013 orders, ZERO ad set ids, ZERO
--                   paid-words, 12 mediums, GBP 60,479.81 (was 60,469).
--                   The asymmetry the decision rests on is real.
--                   Caveat: 8,974 orders have total > 0, not the 9,012
--                   the note claims -- a definitional difference in
--                   "revenue order", not a contradiction, but the note's
--                   figure should not be quoted as measured.
--
--   FLAG 2 (row 11) ig: 5,433 orders, 3,295 social vs 1,459 paid-words,
--                   82 distinct mediums, 0 ad set ids. Matches (3,291
--                   social relayed; +4 is ingestion). Social majority
--                   confirmed -- the decision to default to it stands.
--
--   FLAG 4 (row 14) loquax.co.uk: 3,653 orders, GBP 285.95,
--                   GBP 0.0783 average. EXACT match, all three figures.
--
--   FLAG 6 (row 19) see row 19 -- decision holds, population corrected.
--
--   ROW 1  833,502 orders, 832,936 empty medium, ZERO NULL medium.
--          The "empty string, not NULL" premise is confirmed.
--   ROW 2  (direct) 630,717 orders, 594,091 empty medium, 36,104
--          literal '(none)', and EXACTLY 224 with utm_medium='referral'
--          -- the 224 that justified suppressing the override. Confirmed
--          to the order.
-- =====================================================================
