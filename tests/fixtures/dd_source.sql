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
INSERT INTO analytics_2.orders (wc_order_id, status, total) VALUES
 (2001,'completed',20.00),
 (2002,'completed',21.00),
 (2003,'refunded', 22.00),   -- drift: status
 (2004,'completed',99.00),   -- drift: total
 (2005,'completed',24.00),
 (2999,'completed',99.99);   -- orphan: no such source order

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
