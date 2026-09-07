\set ON_ERROR_STOP on
-- Assertions for 012_daily_brief.sql.

-- K1. A COMPUTED claim without a source or an as_of is the artefact the whole
-- spec exists to prevent. The constraint must refuse it, not the renderer.
DO $$ DECLARE ok bool := false; BEGIN
    BEGIN
        INSERT INTO brief_runs (code_version, objectives_version, claims_total,
                                claims_uncomputed, rendered_markdown,
                                started_at, completed_at)
        VALUES ('assert','assert',0,0,'x',now(),now());
        INSERT INTO brief_claims (run_id, section, metric_key, statement,
                                  status, value_num)
        VALUES (currval('brief_runs_id_seq'),'CHANGED','k1','sourceless',
                'COMPUTED', 1);
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'K1 FAIL: a COMPUTED claim was inserted with no source '
                        'and no as_of; the brief can now assert things it '
                        'cannot attribute';
    END IF;
    RAISE NOTICE 'K1 pass  a computed claim must carry a source and a recency';
END $$;
ROLLBACK;

-- K2. An UNCOMPUTED claim must say why, and must not carry a value beside the
-- excuse -- "could not check, but here is a number anyway" is worse than either.
BEGIN;
DO $$ DECLARE ok bool := false; BEGIN
    INSERT INTO brief_runs (code_version, objectives_version, claims_total,
                            claims_uncomputed, rendered_markdown,
                            started_at, completed_at)
    VALUES ('assert','assert',0,0,'x',now(),now());
    BEGIN
        INSERT INTO brief_claims (run_id, section, metric_key, statement,
                                  status, uncomputed_reason, value_num)
        VALUES (currval('brief_runs_id_seq'),'UNCOMPUTED','k2','no bill',
                'UNCOMPUTED','no AWS credential', 42);
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'K2 FAIL: an UNCOMPUTED claim carried a value';
    END IF;
    RAISE NOTICE 'K2 pass  an uncomputed claim says why and carries no value';
END $$;
ROLLBACK;

-- K3. Section and status cannot disagree about what a row is.
BEGIN;
DO $$ DECLARE ok bool := false; BEGIN
    INSERT INTO brief_runs (code_version, objectives_version, claims_total,
                            claims_uncomputed, rendered_markdown,
                            started_at, completed_at)
    VALUES ('assert','assert',0,0,'x',now(),now());
    BEGIN
        INSERT INTO brief_claims (run_id, section, metric_key, statement,
                                  status, uncomputed_reason)
        VALUES (currval('brief_runs_id_seq'),'CHANGED','k3','mislabelled',
                'UNCOMPUTED','because');
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'K3 FAIL: an UNCOMPUTED row was filed under CHANGED, so '
                        'the brief can hide a gap in the body';
    END IF;
    RAISE NOTICE 'K3 pass  section and status agree';
END $$;
ROLLBACK;

-- K4. A delta must be arithmetic on the two values it claims to relate. A brief
-- that computed its delta from today's database instead of yesterday's row
-- would silently restate history whenever a source is backfilled.
BEGIN;
DO $$ DECLARE ok bool := false; BEGIN
    INSERT INTO brief_runs (code_version, objectives_version, claims_total,
                            claims_uncomputed, rendered_markdown,
                            started_at, completed_at)
    VALUES ('assert','assert',0,0,'x',now(),now());
    BEGIN
        INSERT INTO brief_claims (run_id, section, metric_key, statement,
                                  status, source, as_of, value_num,
                                  previous_num, delta_num)
        VALUES (currval('brief_runs_id_seq'),'CHANGED','k4','bad delta',
                'COMPUTED','s',now(), 10, 4, 99);
    EXCEPTION WHEN check_violation THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'K4 FAIL: delta_num need not equal value - previous';
    END IF;
    RAISE NOTICE 'K4 pass  a delta is arithmetic on its own operands';
END $$;
ROLLBACK;

-- K5. Briefs are append-only. A brief that can be edited afterwards is a brief
-- that can be made to have predicted things.
BEGIN;
DO $$ DECLARE ok bool := false; BEGIN
    INSERT INTO brief_runs (code_version, objectives_version, claims_total,
                            claims_uncomputed, rendered_markdown,
                            started_at, completed_at)
    VALUES ('assert','assert',0,0,'x',now(),now());
    BEGIN
        UPDATE brief_runs SET rendered_markdown = 'rewritten'
         WHERE id = currval('brief_runs_id_seq');
    EXCEPTION WHEN others THEN ok := true;
    END;
    IF NOT ok THEN
        RAISE EXCEPTION 'K5 FAIL: a brief was rewritten after the fact';
    END IF;
    RAISE NOTICE 'K5 pass  briefs are append-only';
END $$;
ROLLBACK;

-- K6. The reader may read and may not write; the writer may write and may not
-- read. One identity holding both is the boundary this design is about.
DO $$ BEGIN
    IF NOT has_table_privilege('dd_detector_login','decision_log','SELECT') THEN
        RAISE EXCEPTION 'K6 FAIL: the brief cannot read decision_log, so it '
                        'cannot say whether what was decided happened';
    END IF;
    IF has_table_privilege('dd_detector_login','brief_runs','INSERT') THEN
        RAISE EXCEPTION 'K6 FAIL: the reader can write briefs';
    END IF;
    IF NOT has_table_privilege('fleet_brief_writer_login','brief_runs','INSERT') THEN
        RAISE EXCEPTION 'K6 FAIL: the writer cannot write briefs';
    END IF;
    IF has_table_privilege('fleet_brief_writer_login','brief_runs','SELECT') THEN
        RAISE EXCEPTION 'K6 FAIL: the writer can read briefs back, and could be '
                        'written to compare itself against yesterday';
    END IF;
    RAISE NOTICE 'K6 pass  reader reads, writer writes, neither does both';
END $$;

-- K7. The grants are individual, not schema-wide. A blanket grant would hand
-- the reader every table added later without anyone deciding to.
DO $$ DECLARE n int; BEGIN
    SELECT count(*) INTO n
      FROM information_schema.table_privileges
     WHERE grantee = 'dd_detector_login' AND privilege_type <> 'SELECT';
    IF n > 0 THEN
        RAISE EXCEPTION 'K7 FAIL: dd_detector_login holds % non-SELECT '
                        'privilege(s) in fleet', n;
    END IF;
    RAISE NOTICE 'K7 pass  the reader holds SELECT and nothing else';
END $$;
