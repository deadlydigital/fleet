-- A throwaway stand-in for deadly_digital: the same column types that make
-- the invariants non-trivial, and a known, hand-counted gap.
--
--   tenant 1  clean, including two totals whose float representation would
--             manufacture drift without the round-and-cast
--   tenant 2  3 missing, 1 orphaned, 2 drifted, 1 unmatchable
--   tenant 3  active, no analytics schema at all
--   tenant 4  inactive, must never be enumerated
--   tenant 5  active, analytics schema present but not readable

CREATE TABLE public.tenants (
    id        integer PRIMARY KEY,
    name      text NOT NULL,
    is_active boolean NOT NULL DEFAULT true
);

CREATE TABLE public.orders (
    id           bigserial PRIMARY KEY,
    tenant_id    integer NOT NULL REFERENCES public.tenants(id),
    woo_order_id integer,
    status       varchar(50),
    total        double precision NOT NULL,
    created_at   timestamp,
    CONSTRAINT uq_tenant_order UNIQUE (tenant_id, woo_order_id)
);

INSERT INTO public.tenants (id, name, is_active) VALUES
 (1,'clean tenant',true), (2,'broken tenant',true), (3,'no analytics',true),
 (4,'inactive tenant',false), (5,'unreadable analytics',true);

DO $$
DECLARE t int;
BEGIN
  FOREACH t IN ARRAY ARRAY[1,2,4,5] LOOP
    EXECUTE format('CREATE SCHEMA analytics_%s', t);
    EXECUTE format($f$
      CREATE TABLE analytics_%s.orders (
          id          serial PRIMARY KEY,
          wc_order_id bigint,
          status      varchar(20),
          total       numeric(10,2),
          -- Both nullable, as in production, and both load-bearing for
          -- STUCK_ORDER_TRANSITION. updated_at is NULL until a SECOND push
          -- touches the row -- sync_engine.py sets it only in the ON CONFLICT
          -- arm -- so NULL is "mentioned once", which is the whole signal.
          created_at  timestamptz,
          updated_at  timestamptz,
          synced_at   timestamptz DEFAULT now())$f$, t);
  END LOOP;
END $$;

-- ---- tenant 1: fully reconciled -----------------------------------------
INSERT INTO public.orders (tenant_id, woo_order_id, status, total, created_at) VALUES
 (1,1001,'completed',10.00,       '2026-08-18 10:00'),
 (1,1002,'completed',0.1 + 0.2,   '2026-08-18 10:01'),   -- 0.30000000000000004
 (1,1003,'processing',19.99,      '2026-08-18 10:02'),
 (1,1004,'refunded', 1234.56,     '2026-08-18 10:03');
INSERT INTO analytics_1.orders (wc_order_id, status, total) VALUES
 (1001,'completed',10.00), (1002,'completed',0.30),
 (1003,'processing',19.99), (1004,'refunded',1234.56);

-- ---- tenant 2: the known gap --------------------------------------------
INSERT INTO public.orders (tenant_id, woo_order_id, status, total, created_at) VALUES
 (2,2001,'completed',20.00,'2026-08-18 11:00'),
 (2,2002,'completed',21.00,'2026-08-18 11:01'),
 (2,2003,'completed',22.00,'2026-08-18 11:02'),   -- status drift
 (2,2004,'completed',23.00,'2026-08-18 11:03'),   -- total drift
 (2,2005,'completed',24.00,'2026-08-18 11:04'),
 (2,2006,'completed',25.00,'2026-08-18 11:05'),   -- missing downstream
 (2,2007,'completed',26.00,'2026-08-18 11:06'),   -- missing downstream
 (2,2008,'completed',27.00,'2026-08-18 11:07'),   -- missing downstream
 (2,NULL, 'completed',28.00,'2026-08-18 11:08');  -- unmatchable
INSERT INTO analytics_2.orders (wc_order_id, status, total, created_at, updated_at) VALUES
 (2001,'completed',20.00,'2026-08-18 11:00','2026-08-18 11:20'),
 (2002,'completed',21.00,'2026-08-18 11:01','2026-08-18 11:21'),
 (2003,'refunded', 22.00,'2026-08-18 11:02','2026-08-18 11:22'),  -- drift: status
 (2004,'completed',99.00,'2026-08-18 11:03','2026-08-18 11:23'),  -- drift: total
 (2005,'completed',24.00,'2026-08-18 11:04','2026-08-18 11:24'),
 (2999,'completed',99.99,'2026-08-18 11:09','2026-08-18 11:29');  -- orphan: no such source order

-- ---- tenant 2, the stuck transitions ------------------------------------
-- The real shape, from analytics_2 on 12 Sep 2026: one push arrived, the
-- transition never did, and the row sits outside the statuses an order rests
-- in. `updated_at IS NULL` is the signal; age is what makes it a finding
-- rather than an order that simply has not transitioned yet.
--
-- EVERY ROW BELOW MATCHES ITS SOURCE ROW EXACTLY, and that is the point
-- rather than fixture hygiene. Both `public.orders` and `analytics_<t>.orders`
-- are written from the same connector push, so a transition the connector
-- never sent is missing from BOTH copies. The two sides agree perfectly, the
-- other four invariants see nothing, and the order is still wrong. That is why
-- this check had to exist: it is the failure the comparison cannot reach.
INSERT INTO public.orders (tenant_id, woo_order_id, status, total, created_at) VALUES
 (2,2010,'pending',  30.00,'2026-08-18 11:10'),
 (2,2011,'pending',  31.00,'2026-08-18 11:11'),
 (2,2012,NULL,       32.00,'2026-08-18 11:12'),
 (2,2013,'pending',  33.00,'2026-08-18 11:13'),
 (2,2014,'completed',34.00,'2026-08-18 11:14'),
 (2,2015,'cancelled',35.00,'2026-08-18 11:15'),
 (2,2016,'refunded', 36.00,'2026-08-18 11:16'),
 (2,2017,'pending',  37.00,'2026-08-18 11:17'),
 (2,2018,'pending',  38.00,'2026-08-18 11:18');
INSERT INTO analytics_2.orders (wc_order_id, status, total, created_at, updated_at) VALUES
 -- STUCK: one push, still pending, long past any settle lag.
 (2010,'pending',  30.00,'2026-08-18 11:10',NULL),
 (2011,'pending',  31.00,'2026-08-18 11:11',NULL),
 -- STUCK: one push and no status at all. Included on purpose -- `status NOT
 -- IN (...)` is NULL for this row, so three-valued logic would drop it.
 (2012,NULL,       32.00,'2026-08-18 11:12',NULL),
 -- NOT STUCK: pending, but a second push HAS touched it. The store is telling
 -- us about this order; it is just still pending, which is not a defect.
 (2013,'pending',  33.00,'2026-08-18 11:13','2026-08-18 11:40'),
 -- NOT STUCK: one push, but it rests at a terminal status. 22 of these exist
 -- in production -- an order born completed -- and they are harmless.
 (2014,'completed',34.00,'2026-08-18 11:14',NULL),
 (2015,'cancelled',35.00,'2026-08-18 11:15',NULL),
 (2016,'refunded', 36.00,'2026-08-18 11:16',NULL),
 -- NOT STUCK: one push, pending, and created NOW. It has not lost a
 -- transition, it has not had time to make one. This is the row that fails if
 -- the settle lag is ever dropped from the predicate.
 (2017,'pending',  37.00, now(), NULL),
 -- NOT JUDGED: one push, pending, and no creation instant to age it by.
 -- Age is the whole predicate and this row has none. UNMATCHABLE_ORDER is
 -- where rows that cannot be judged belong.
 (2018,'pending',  38.00, NULL, NULL);

-- ---- tenant 3: no analytics schema; tenant 4: inactive -------------------
INSERT INTO public.orders (tenant_id, woo_order_id, status, total, created_at) VALUES
 (3,3001,'completed',30.00,'2026-08-18 12:00'),
 (3,3002,'completed',31.00,'2026-08-18 12:01'),
 (4,4001,'completed',40.00,'2026-08-18 13:00'),
 (5,5001,'completed',50.00,'2026-08-18 14:00');
INSERT INTO analytics_4.orders (wc_order_id, status, total) VALUES (4001,'completed',40.00);
INSERT INTO analytics_5.orders (wc_order_id, status, total) VALUES (5001,'completed',50.00);

-- ---- the read-only principal --------------------------------------------
-- Mirrors dd_detector_login: SELECT and nothing else, and no reach at all
-- into analytics_5, so "unreadable" is a real privilege failure.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dd_test_reader') THEN
    CREATE ROLE dd_test_reader LOGIN PASSWORD 'dd_test_reader';
  END IF;
END $$;
GRANT USAGE ON SCHEMA public, analytics_1, analytics_2, analytics_4 TO dd_test_reader;
GRANT SELECT ON public.tenants, public.orders TO dd_test_reader;
GRANT SELECT ON analytics_1.orders, analytics_2.orders, analytics_4.orders TO dd_test_reader;
