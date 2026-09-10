"""The loader: a producer's block becomes rows, and nothing is dropped.

specs/auto-approval.md §2.1. What these protect, in one line each:

  the three fields reach the database at all       -> TestNothingIsDropped
  the band is derived once, at the load            -> TestTheBandComesFromTheHeading
  a half-loaded row is refused, not stored         -> TestWhatIsRefused
  the load does not judge the claims               -> TestTheLoaderDoesNotReExecute
  one batch or none of it                          -> TestOneTransaction
  the hand-loaded batches can be completed         -> TestBackfill

THE DEFECT THESE EXIST FOR is not hypothetical: batches 8 and 9 were both
loaded by hand, and thirty-two probes and four hib_signals that the producer's
contract check had already verified were dropped on the way in because there
were no columns to hold them. Nothing failed. The rows looked complete.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from console import load_candidates as loader

REAL_DOC = Path("research/candidates-metorik-gap-2026-09-09.md")

# Indentation here is load-bearing: the tests below edit this text by exact
# string, so it is written at the indentation the block actually uses rather
# than dedented into a different one.
SIGNAL = ("    hib_signal:\n"
          "      value: payment_method populated on 2,782,530 of 2,844,177 orders\n"
          "      as_of: '2026-08-28'\n"
          "      source: specs/metorik-gap.md\n")

PROBE_LINE = "      - path_exists: api/analytics/routes/orders.py"
REPO_LINE = "    repo: deadly-digital-platform"

ONE = (
    "  - title: Forward the four order filters\n"
    "    rationale: >\n"
    "      The API gained the filters and the proxy forwards an allowlist that\n"
    "      excludes all four of them, so an agency cannot filter on any.\n"
    + REPO_LINE + "\n"
    "    objective_ref: null\n"
    "    verified_sha: 4619a76a94b72bc0b11600991779b4f5200117b3\n"
    "    evidence:\n"
    "      - kind: document\n"
    "        document: specs/metorik-gap.md\n"
    "        section: 'Daily — Order filtering: status, payment, location'\n"
    "        sha: b198634063e5f9e3fc17467a6b6fe361013cfee3\n"
    + SIGNAL +
    "    suggested_paths:\n"
    "      - platform/app/api/analytics/orders/route.ts\n"
    "    probes:\n"
    + PROBE_LINE + "\n"
    "      - grep_count:\n"
    "          glob: platform/app/api/analytics/orders/route.ts\n"
    "          pattern: 'payment_method'\n"
    "          expected: 0\n"
)


def _block(candidates: str) -> str:
    """A document carrying one fleet-candidates block."""
    return (
        "# A findings document\n\n"
        "```fleet-candidates\n"
        "source:\n"
        "  document: specs/metorik-gap.md\n"
        "  sha: b198634063e5f9e3fc17467a6b6fe361013cfee3\n"
        "  read_at: '2026-09-09'\n\n"
        "ordering: unranked\n\n"
        "candidates:\n" + candidates + "```\n")


def _doc(tmp_path, body: str, name="findings.md") -> Path:
    p = tmp_path / name
    p.write_text(_block(body))
    return p


def _rows(tmp_path, body: str):
    return loader.validate(loader.parse_block(_doc(tmp_path, body)))


class TestNothingIsDropped:
    def test_the_real_batch_nine_document_yields_its_probes_and_signals(self):
        """The document task 34 produced, parsed as the loader will parse it.

        Asserted against the file rather than a fixture, because the fixture is
        what went wrong the first time: a person read this document and retyped
        a subset of it.
        """
        rows = loader.validate(loader.parse_block(REAL_DOC))
        assert len(rows) == 9
        assert sum(len(r["probes"]) for r in rows) == 32
        assert sum(1 for r in rows if r["hib_signal"]) == 4
        bands = [r["band"] for r in rows]
        assert bands.count("daily") == 8
        assert bands.count("weekly") == 1

    def test_a_loaded_row_carries_all_three_columns(self, dsns, console, tmp_path):
        out = loader.load(_doc(tmp_path, ONE), source_sha="ce90c57", note="t")
        assert out["candidates"] == 1
        row = console.execute(
            "SELECT band, hib_signal, probes, disposition FROM candidates"
            " WHERE id=%s", (out["candidate_ids"][0],)).fetchone()
        assert row["band"] == "daily"
        assert row["hib_signal"]["as_of"] == "2026-08-28"
        assert "2,782,530" in row["hib_signal"]["value"]
        assert len(row["probes"]) == 2
        assert row["probes"][0] == {"path_exists": "api/analytics/routes/orders.py"}
        # 013's trigger is untouched: a loader cannot pre-approve.
        assert row["disposition"] == "PENDING"

    def test_a_null_signal_is_a_fact_and_a_missing_key_is_not(
            self, dsns, console, tmp_path):
        """`hib_signal: null` loads. An absent key is refused.

        The distinction is the producer contract's, and it is the whole reason
        the key is required while the value is not: "the document declares no
        figure" is a finding, and "nobody looked" is not.
        """
        out = loader.load(_doc(tmp_path, ONE.replace(SIGNAL, "    hib_signal: null\n")),
                          source_sha="ce90c57")
        row = console.execute("SELECT hib_signal FROM candidates WHERE id=%s",
                              (out["candidate_ids"][0],)).fetchone()
        assert row["hib_signal"] is None

        with pytest.raises(loader.LoadRefused, match="omits hib_signal"):
            _rows(tmp_path, ONE.replace(SIGNAL, ""))


class TestTheBandComesFromTheHeading:
    @pytest.mark.parametrize("section,want", [
        ("Daily — Order filtering", "daily"),
        ("Weekly — Coupon performance", "weekly"),
        ("Monthly — Something", "monthly"),
        ("Rarely — Cross-store roll-up", "rarely"),
        ("daily — already lower", "daily"),
        ("Daily - a hyphen rather than an em dash", "daily"),
        ("Order filtering with no band at all", None),
    ])
    def test_the_prefix_is_read_once(self, section, want):
        assert loader.band_of({"evidence": [{"section": section}]}) == want

    def test_a_word_outside_the_vocabulary_is_an_error_and_not_a_null(self):
        """The convention changing must not read as "this row has no band".

        A NULL band sorts last and does not gate, so a silent NULL would
        quietly unrank a whole batch and nothing would say so.
        """
        with pytest.raises(loader.LoadRefused, match="not one of"):
            loader.band_of({"evidence": [{"section": "Hourly — something new"}]})

    def test_two_bands_on_one_candidate_are_refused(self):
        with pytest.raises(loader.LoadRefused, match="more than one band"):
            loader.band_of({"evidence": [{"section": "Daily — a"},
                                         {"section": "Weekly — b"}]})


class TestWhatIsRefused:
    def test_a_candidate_with_no_probes_is_refused(self, tmp_path):
        """Zero probes passing is a check that cannot fail.

        Refused at the load rather than stored, because a stored row with no
        probes is one rank.py can never approve and never explains.
        """
        with pytest.raises(loader.LoadRefused, match="declares no probes"):
            _rows(tmp_path, ONE.split("    probes:")[0])

    def test_a_probe_outside_the_vocabulary_is_refused(self, tmp_path):
        with pytest.raises(loader.LoadRefused, match="not in the vocabulary"):
            _rows(tmp_path, ONE.replace(PROBE_LINE, "      - shell: rm -rf /"))

    def test_a_producer_may_not_name_a_disposition(self, tmp_path):
        with pytest.raises(loader.LoadRefused, match="disposition"):
            _rows(tmp_path, ONE.replace(
                REPO_LINE, REPO_LINE + "\n    disposition: APPROVED"))

    def test_every_problem_is_reported_not_only_the_first(self, tmp_path):
        """A load that fails once per fix is a load nobody runs twice."""
        body = ONE.replace(REPO_LINE, REPO_LINE + "\n    work_type: dd_feature")
        body = body.split("    probes:")[0]
        with pytest.raises(loader.LoadRefused) as exc:
            _rows(tmp_path, body)
        assert "work_type" in str(exc.value)
        assert "declares no probes" in str(exc.value)
        assert "2 problem(s)" in str(exc.value)

    def test_two_blocks_in_one_document_are_refused(self, tmp_path):
        p = tmp_path / "two.md"
        p.write_text(_block(ONE) + "\n" + _block(ONE))
        with pytest.raises(loader.LoadRefused, match="2 ```fleet-candidates"):
            loader.parse_block(p)


class TestTheLoaderDoesNotReExecute:
    def test_a_claim_that_has_aged_still_loads(self, dsns, console, tmp_path):
        """THE point of the split between loading and approving.

        This probe asserts a path that exists in neither repository, so it
        would fail if the loader re-ran it. It must still load: a batch is read
        from a document verified at an older sha, and a loader that refused an
        aged claim would refuse to record the very fact that the claim HAD
        aged. Re-execution is §2.2's gate 4, at approval time, against the sha
        about to be spent money on.
        """
        body = ONE.replace(
            PROBE_LINE, "      - path_exists: api/analytics/routes/no_such_file.py")
        out = loader.load(_doc(tmp_path, body), source_sha="ce90c57")
        row = console.execute("SELECT probes FROM candidates WHERE id=%s",
                              (out["candidate_ids"][0],)).fetchone()
        assert row["probes"][0] == {
            "path_exists": "api/analytics/routes/no_such_file.py"}


class TestOneTransaction:
    def test_a_dry_run_writes_nothing(self, dsns, console, tmp_path):
        before = console.execute(
            "SELECT count(*) AS n FROM candidate_batches").fetchone()["n"]
        out = loader.load(_doc(tmp_path, ONE), source_sha="ce90c57", dry_run=True)
        assert out["batch_id"] is None
        assert out["candidates"] == 1
        after = console.execute(
            "SELECT count(*) AS n FROM candidate_batches").fetchone()["n"]
        assert after == before

    def test_a_refused_block_leaves_no_batch_row(self, dsns, console, tmp_path):
        before = console.execute(
            "SELECT count(*) AS n FROM candidate_batches").fetchone()["n"]
        with pytest.raises(loader.LoadRefused):
            loader.load(_doc(tmp_path, ONE.split("    probes:")[0]),
                        source_sha="ce90c57")
        after = console.execute(
            "SELECT count(*) AS n FROM candidate_batches").fetchone()["n"]
        assert after == before, ("a batch row with no candidates is a state "
                                 "the surface renders as a complete batch")


class TestBackfill:
    """Completing a load that a missing column interrupted."""

    def _handload(self, console, title="Forward the four order filters"):
        b = console.execute(
            "INSERT INTO candidate_batches (source_document, source_sha,"
            " source_repo, note) VALUES ('findings.md','ce90c57','fleet',"
            " 'Loaded by hand') RETURNING id").fetchone()["id"]
        cid = console.execute(
            "INSERT INTO candidates (batch_id, title, rationale, repo)"
            " VALUES (%s,%s,'because the finding said so',"
            " 'deadly-digital-platform') RETURNING id", (b, title)).fetchone()["id"]
        console.commit()
        return b, cid

    def test_it_fills_the_three_columns_and_touches_nothing_else(
            self, dsns, console, tmp_path):
        b, cid = self._handload(console)
        out = loader.backfill(_doc(tmp_path, ONE), b)
        assert out["filled"] == [cid]
        row = console.execute(
            "SELECT band, hib_signal, probes, rationale, disposition"
            " FROM candidates WHERE id=%s", (cid,)).fetchone()
        assert row["band"] == "daily"
        assert len(row["probes"]) == 2
        assert row["hib_signal"]["as_of"] == "2026-08-28"
        # The hand-written content is the record of what a person wrote down.
        assert row["rationale"] == "because the finding said so"
        assert row["disposition"] == "PENDING"

    def test_it_refuses_to_overwrite_a_value_already_there(
            self, dsns, console, tmp_path):
        b, cid = self._handload(console)
        console.execute("UPDATE candidates SET band='weekly' WHERE id=%s", (cid,))
        console.commit()
        with pytest.raises(loader.LoadRefused, match="already carries"):
            loader.backfill(_doc(tmp_path, ONE), b)

    def test_a_partial_title_match_is_refused(self, dsns, console, tmp_path):
        """A document that does not account for every row is the wrong document."""
        self._handload(console, title="Something else entirely")
        b, _ = self._handload(console, title="Something else entirely")
        with pytest.raises(loader.LoadRefused, match="not in this document"):
            loader.backfill(_doc(tmp_path, ONE), b)

    def test_a_dry_run_fills_nothing(self, dsns, console, tmp_path):
        b, cid = self._handload(console)
        out = loader.backfill(_doc(tmp_path, ONE), b, dry_run=True)
        assert out["filled"] == [cid]
        row = console.execute("SELECT band, probes FROM candidates WHERE id=%s",
                              (cid,)).fetchone()
        assert row["band"] is None
        assert row["probes"] == []


# ---- the objective may not change silently ---------------------------------

class TestTheObjectiveMayNotChangeSilently:
    """c12 and c13 were dd-trustworthy; the same document rows came back as
    c21 and c22 labelled dd-feature-parity, and nothing compared them.

    Until 027's work key there was nothing to compare them BY -- the titles had
    been rewritten, which is the producer working as designed. The producer
    cannot catch this and must not be asked to: it is forbidden to see previous
    batches, because that is what keeps a reappearing candidate a signal. The
    loader can see them, so the loader is where the comparison belongs.
    """

    OBJ = "    objective_ref: dd-trustworthy\n"

    def _one(self, *, objective: str, title="Forward the four order filters"):
        body = ONE.replace("    objective_ref: null\n",
                           f"    objective_ref: {objective}\n")
        return body.replace("  - title: Forward the four order filters\n",
                            f"  - title: {title}\n")

    def test_the_same_work_under_a_new_objective_is_refused(
            self, dsns, console, tmp_path):
        first = loader.load(_doc(tmp_path, self._one(objective="dd-trustworthy"),
                                 name="a.md"),
                            source_sha="b198634")
        assert first["candidates"] == 1

        # Same document row, same section, RETITLED and relabelled -- which is
        # exactly the shape batch 9 arrived in.
        doc = _doc(tmp_path, self._one(objective="dd-feature-parity",
                                       title="Order filters, restated"),
                   name="b.md")
        with pytest.raises(loader.LoadRefused) as exc:
            loader.load(doc, source_sha="b198634")
        assert "trust ranks above parity" in str(exc.value)
        assert "dd-trustworthy" in str(exc.value)

    def test_the_real_pair_shape_over_a_RESOLVED_document_row(
            self, dsns, console, tmp_path):
        """c12 -> c21, in miniature, keyed to an actual row of the gap list.

        The test above happens to key by heading only, because its section is
        not a prefix of any real row. This one resolves, so the strong path --
        two different quotations of one document row -- is covered rather than
        assumed. If the resolver stops resolving, this fails and the other
        test does not.
        """
        short = ONE.replace(
            "        section: 'Daily — Order filtering: status, payment, location'",
            "        section: 'Weekly — coupon and discount performance'").replace(
            "    objective_ref: null\n",
            "    objective_ref: dd-trustworthy\n").replace(
            "  - title: Forward the four order filters\n", "  - title: Coupons\n")
        full = ONE.replace(
            "        section: 'Daily — Order filtering: status, payment, location'",
            "        section: 'Weekly — Coupon and discount performance: usage, "
            "discount total, orders, AOV with/without'").replace(
            "    objective_ref: null\n",
            "    objective_ref: dd-feature-parity\n").replace(
            "  - title: Forward the four order filters\n",
            "  - title: Coupon and discount performance, restated\n")

        loader.load(_doc(tmp_path, short, name="a.md"), source_sha="b198634")
        key = console.execute(
            "SELECT work_key FROM candidates ORDER BY id DESC LIMIT 1"
        ).fetchone()["work_key"]
        assert "#row:" in key, "the strong path is not being exercised"

        with pytest.raises(loader.LoadRefused) as exc:
            loader.load(_doc(tmp_path, full, name="b.md"), source_sha="b198634")
        assert "dd-trustworthy" in str(exc.value)

    def test_the_refusal_leaves_no_batch_row(self, dsns, console, tmp_path):
        loader.load(_doc(tmp_path, self._one(objective="dd-trustworthy"),
                         name="a.md"), source_sha="b198634")
        before = console.execute(
            "SELECT count(*) AS n FROM candidate_batches").fetchone()["n"]
        with pytest.raises(loader.LoadRefused):
            loader.load(_doc(tmp_path,
                             self._one(objective="dd-feature-parity",
                                       title="Order filters, restated"),
                             name="b.md"), source_sha="b198634")
        after = console.execute(
            "SELECT count(*) AS n FROM candidate_batches").fetchone()["n"]
        assert before == after

    def test_a_note_permits_it_and_is_recorded_on_the_batch(
            self, dsns, console, tmp_path):
        """An override costs a sentence, and the sentence outlives the shell.

        The same discipline approve.py's repeat_overrides carry: a person may
        say it is different this time, and what they said is kept.
        """
        loader.load(_doc(tmp_path, self._one(objective="dd-trustworthy"),
                         name="a.md"), source_sha="b198634")
        out = loader.load(
            _doc(tmp_path, self._one(objective="dd-feature-parity",
                                     title="Order filters, restated"),
                 name="b.md"),
            source_sha="b198634",
            objective_change_note="The netting is not exercised by live data, "
                                  "so this is parity work now.")
        assert len(out["relabelled"]) == 1
        note = console.execute(
            "SELECT note FROM candidate_batches WHERE id=%s",
            (out["batch_id"],)).fetchone()["note"]
        assert "OBJECTIVE CHANGED" in note
        assert "netting is not exercised" in note
        assert "dd-trustworthy -> dd-feature-parity" in note

    def test_the_same_objective_on_the_same_work_is_not_a_change(
            self, dsns, console, tmp_path):
        loader.load(_doc(tmp_path, self._one(objective="dd-trustworthy"),
                         name="a.md"), source_sha="b198634")
        out = loader.load(_doc(tmp_path,
                               self._one(objective="dd-trustworthy",
                                         title="Order filters, restated"),
                               name="b.md"), source_sha="b198634")
        assert out["relabelled"] == []

    def test_different_work_under_a_different_objective_is_not_a_change(
            self, dsns, console, tmp_path):
        """The check is on the WORK, not on the batch.

        A new row that happens to carry a different objective from some
        unrelated earlier row is not a re-labelling, and refusing it would make
        the loader refuse every mixed batch after the first.
        """
        loader.load(_doc(tmp_path, self._one(objective="dd-trustworthy"),
                         name="a.md"), source_sha="b198634")
        other = ONE.replace(
            "    objective_ref: null\n",
            "    objective_ref: dd-feature-parity\n").replace(
            "        section: 'Daily — Order filtering: status, payment, location'",
            "        section: 'Weekly — Coupon and discount performance'").replace(
            "  - title: Forward the four order filters\n",
            "  - title: Coupons\n")
        out = loader.load(_doc(tmp_path, other, name="c.md"),
                          source_sha="b198634")
        assert out["relabelled"] == []

    def test_a_dry_run_reports_the_change_and_writes_nothing(
            self, dsns, console, tmp_path):
        loader.load(_doc(tmp_path, self._one(objective="dd-trustworthy"),
                         name="a.md"), source_sha="b198634")
        before = console.execute(
            "SELECT count(*) AS n FROM candidates").fetchone()["n"]
        out = loader.load(_doc(tmp_path,
                               self._one(objective="dd-feature-parity",
                                         title="Order filters, restated"),
                               name="b.md"),
                          source_sha="b198634", dry_run=True)
        after = console.execute(
            "SELECT count(*) AS n FROM candidates").fetchone()["n"]
        assert before == after
        assert out["batch_id"] is None
        assert [r["before"] for r in out["relabelled"]] == [["dd-trustworthy"]]

    def test_an_unkeyed_row_cannot_trigger_it(self, dsns, console, tmp_path):
        """No work key, no comparison -- and no false positive off the title.

        A row the resolver could not key falls back to (title, repo) for the
        repeat ceiling, but NOT here: charging a title match with an objective
        change would resurrect exactly the identity 027 removed.
        """
        no_section = ONE.replace(
            "        section: 'Daily — Order filtering: status, payment, location'\n",
            "")
        a = no_section.replace("    objective_ref: null\n",
                               "    objective_ref: dd-trustworthy\n")
        b = no_section.replace("    objective_ref: null\n",
                               "    objective_ref: dd-feature-parity\n")
        loader.load(_doc(tmp_path, a, name="a.md"), source_sha="b198634")
        out = loader.load(_doc(tmp_path, b, name="b.md"), source_sha="b198634")
        assert out["relabelled"] == []
