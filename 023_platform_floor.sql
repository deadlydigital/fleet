-- ============================================================================
-- 023_platform_floor.sql  —  the platform tree gets a floor before it gets a
--                            contract
--
-- 017 floored email, 018 and 019 floored erasure, and all three did it on one
-- argument: UNREACHABLE BY CONTRACT IS NOT THE SAME AS UNREACHABLE BY FLOOR.
-- 018 said it about two files that were safe only because a contract happened
-- not to name them, and 019 moved them because "a property of a contract
-- rather than of the database" is not a property anybody can rely on.
--
-- Everything under platform/ is in that position today, and only by accident.
-- `contracts/deadly-digital-platform.yaml` declares platform/app/**,
-- platform/components/** and platform/lib/** writable, which reaches
-- platform/lib/auth.ts, roles.ts, csrf.ts, app/api/auth/impersonate/route.ts,
-- app/api/billing/checkout/route.ts and the campaign send route. Nothing in the
-- database objects, because the floor has never had a platform row on it that
-- was not a test-configuration file.
--
-- That contract is being retired in the same change as this file. This
-- migration is what makes retiring it a decision rather than the only thing
-- standing between an unattended fleet and the session layer, and it lands
-- FIRST for the same reason 017 landed before the api contract was narrowed:
-- a floor added after the writable path is a floor that was not there when it
-- mattered.
--
-- ============================================================================
-- WHAT IS HERE, AND WHY EACH GROUP
-- ============================================================================
--
-- AUTH AND SESSION. The frontend's whole notion of who you are. An agent that
-- can edit platform/lib/auth.ts can change what a session means; one that can
-- edit platform/lib/roles.ts can change what an owner may do; one that can edit
-- platform/lib/csrf.ts can remove the check that a request came from the app.
-- platform/app/api/auth/** includes impersonate. None of that is analytics
-- work, and none of it is work a suite of render tests can judge.
--
--   platform/middleware.ts IS ON THIS LIST BECAUSE OF WHERE IT SITS. It is not
--   under app/, components/ or lib/, so the wide contract missed it by
--   accident rather than by design -- and it is the file that decides which
--   requests reach an authenticated route at all. A boundary that holds only
--   because of how somebody's glob happened to be spelled is the thing 019
--   exists to say is not a boundary.
--
-- BILLING. Checkout, subscriptions, the admin billing surface and the settings
-- page behind them. Same class as erasure in one respect that matters here:
-- reverting the commit does not un-charge a card, and does not un-cancel a
-- subscription that was cancelled while the code was wrong.
--
-- EMAIL, MATCHING 017. 017 floored the email platform on the api side and said
-- why at length; the frontend half of the same platform was left standing
-- because no contract reached it yet. The globs below are the proxies and the
-- pages for the endpoints 017 named -- campaigns, flows, deliverability
-- domains, suppression -- plus the three that are email machinery under other
-- names: scheduled-campaigns (the send queue), inline-css (juice, which
-- inlines styles into email HTML), and listmonk (the delivery system itself).
--
-- GDPR, MATCHING 018 AND 019. The erasure request surface and the page it is
-- made from. 018's argument transfers unchanged: an erasure that deletes too
-- much cannot be undone by reverting the commit, and one that deletes too
-- little is a breach that looks like success.
--
-- ============================================================================
-- TWO GROUPS THAT ARE NOT IN THE BRIEF THIS CAME FROM, WITH THEIR ARGUMENTS
-- ============================================================================
--
-- THE STOREFRONT INGEST, platform/app/api/track/**. It was handed to this
-- migration in the email group, and it is not email: route.ts reads an api_key,
-- resolves a tenant and INSERTs into `events` with visitor_id, page_url,
-- referrer and device. It is the storefront event feed, not an open-tracking
-- pixel. Filing it under email would have been a rationale that lies, and the
-- rationale is what enforce_contract_floor() prints when it refuses.
--
-- It is floored anyway, on its own argument: it is an INGEST endpoint whose
-- writer is somebody else's storefront JavaScript. An event dropped because
-- this route was wrong for an hour is not re-sent by fixing the route, and the
-- analytics the fleet exists to improve are computed downstream of it. Same
-- class as erasure -- the revert does not bring the rows back -- arrived at
-- from the other direction.
--
-- THE INTERVENTION SURFACE, three globs inside the analytics tree. This is
-- 017's E3 case at the frontend, and it is the reason that assertion exists:
-- api/analytics/services/trigger_router.py sits INSIDE the tree the fleet owns
-- and is floored because "the day it sends, it is the email platform".
--
--   platform/app/api/analytics/churn/intervene/route.ts is the proxy that
--   POSTs to the endpoint whose handler 017 floored.
--   platform/app/api/analytics/interventions/** reads and writes that surface.
--   platform/app/(dashboard)/analytics/interventions/** is its page.
--
-- The proxy sends nothing itself, and that is exactly what
-- api/analytics/routes/interventions.py could say about itself in 017. The
-- floor is not about what the file does today; it is about which file an
-- autonomous fleet grows into the email platform through.
--
-- THE PRICE, STATED PLAINLY. These three make `platform/app/api/analytics/**`
-- and `platform/app/(dashboard)/analytics/**` illegal as writable globs -- the
-- floor is checked against writable_paths, so a glob that reaches a floored
-- path is refused. contracts/dd-analytics-frontend.yaml therefore enumerates
-- its analytics directories instead of globbing the tree. That is the same
-- trade 017 forced on the api contract, and the api contract's own header says
-- what it buys: "no wildcard hiding a file nobody thought about".
--
-- ============================================================================
-- WHAT IS DELIBERATELY NOT HERE
-- ============================================================================
--
-- platform/app/(dashboard)/subscribers/**, lists/**, segments/** and sms/**.
-- They are audience management, and a campaign's audience is chosen from them,
-- so an argument for flooring them exists. It is not the same argument: none of
-- them sends, schedules or suppresses anything, and 017's line was drawn at the
-- sending platform rather than at everything email touches. They are named here
-- so that the next person widening a frontend contract knows they are outside
-- the floor by decision rather than by oversight -- the same service 018 did
-- for gdpr_identity.py, and the same reason 019 then had to move it.
--
-- platform/components/** and the rest of platform/lib/**. Not floored, and not
-- writable either: contracts/dd-analytics-frontend.yaml names the components it
-- may touch one by one. A shared UI primitive changed for an analytics reason
-- renders on the billing page too, and the analytics render tests would not
-- show it -- but that is an argument about what a contract should declare, not
-- about what the database must refuse, and putting it on the floor would freeze
-- a component list nobody can revise without a migration.
--
-- .github/**, platform/package.json and the other build manifests. Protected by
-- every contract, floored by none, unchanged here. Adding them is a real
-- proposal and a separate one; doing it inside a migration about auth, billing
-- and email would be the silent widening 018 refused to do to 017.
-- ============================================================================

INSERT INTO protected_path_floor (repo, glob, rationale) VALUES

 -- ---- auth and session -------------------------------------------------
 ('deadly-digital-platform', 'platform/middleware.ts',
  'decides which requests reach an authenticated route at all; it is not under app/, components/ or lib/, so the wide frontend contract missed it by accident rather than by design'),
 ('deadly-digital-platform', 'platform/lib/auth.ts',
  'what a session is and how one is established'),
 ('deadly-digital-platform', 'platform/lib/api-auth.ts',
  'how a route authenticates the caller before it answers'),
 ('deadly-digital-platform', 'platform/lib/roles.ts',
  'what each role may do; editing it is editing the permission model'),
 ('deadly-digital-platform', 'platform/lib/csrf.ts',
  'the check that a request came from the app; a change here fails open and silently'),
 ('deadly-digital-platform', 'platform/app/api/auth/**',
  'sign-in, sign-out and impersonation - no analytics task needs it and no render test can judge it'),

 -- ---- billing ----------------------------------------------------------
 ('deadly-digital-platform', 'platform/app/api/billing/**',
  'checkout and subscription; reverting the commit does not un-charge a card'),
 ('deadly-digital-platform', 'platform/app/api/admin/billing/**',
  'the same money, from the admin side'),
 ('deadly-digital-platform', 'platform/app/(dashboard)/settings/billing/**',
  'the page those routes are driven from'),

 -- ---- email, matching 017 ---------------------------------------------
 ('deadly-digital-platform', 'platform/app/api/campaigns/**',
  'the campaign surface; 017 floored its backend and Fleet does not go near email'),
 ('deadly-digital-platform', 'platform/app/api/flows/**',
  'automated flows: the thing that sends without anybody pressing send'),
 ('deadly-digital-platform', 'platform/app/api/domains/**',
  'sending domains and their DNS verification'),
 ('deadly-digital-platform', 'platform/app/api/suppression/**',
  'who must not be emailed; a bug here mails somebody who asked not to be'),
 ('deadly-digital-platform', 'platform/app/api/scheduled-campaigns/**',
  'the send queue'),
 ('deadly-digital-platform', 'platform/app/api/inline-css/**',
  'inlines styles into email HTML before it is sent'),
 ('deadly-digital-platform', 'platform/app/api/listmonk/**',
  'the delivery system itself'),
 ('deadly-digital-platform', 'platform/app/(dashboard)/campaigns/**',
  'the page campaigns are composed and sent from'),
 ('deadly-digital-platform', 'platform/app/(dashboard)/flows/**',
  'the page flows are built in'),
 ('deadly-digital-platform', 'platform/app/(dashboard)/settings/domains/**',
  'the page sending domains are added and verified on'),

 -- ---- the storefront ingest -------------------------------------------
 ('deadly-digital-platform', 'platform/app/api/track/**',
  'the storefront event ingest, written to by somebody elses JavaScript; an event dropped while this route was wrong is not re-sent by fixing it'),

 -- ---- GDPR, matching 018 and 019 --------------------------------------
 ('deadly-digital-platform', 'platform/app/api/gdpr/**',
  'erasure and export requests; deleting too much cannot be undone by reverting, and deleting too little is a breach that looks like success'),
 ('deadly-digital-platform', 'platform/app/(dashboard)/settings/privacy/**',
  'the page an erasure is requested from'),

 -- ---- the intervention surface, 017 E3 at the frontend ----------------
 ('deadly-digital-platform', 'platform/app/api/analytics/churn/intervene/**',
  'inside the analytics tree, but it proxies the endpoint 017 floored - this is where analytics grows into email by accident'),
 ('deadly-digital-platform', 'platform/app/api/analytics/interventions/**',
  'the same surface, read and written; floored with its proxy rather than left as the half a glob still reaches'),
 ('deadly-digital-platform', 'platform/app/(dashboard)/analytics/interventions/**',
  'its page; floored so the analytics tree is enumerated rather than globbed')

ON CONFLICT (repo, glob) DO NOTHING;
