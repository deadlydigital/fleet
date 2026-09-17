"""A truncated check output must SAY it was truncated, and keep the count.

THE DEFECT THESE EXIST FOR, 17 Sep 2026, task 125.

`console/reverify.py` narrowed `verify.Check.output_tail` again to its last 800
bytes before recording it. `contracts/checks/pytest_unit_per_file.sh` prints a
`--- FAILED <path>` block per failing file and only then its closing summary:

    FAIL: 33 of 52 files in tests/analytics failed:
      tests/analytics/test_migrations.py
      ... one line per file ...

800 bytes is about 19 of those path lines. So the record kept the END of the
list and dropped the one line carrying the number -- and nothing said so. The
refusal read as "19 files failed, test_migrations.py first". Both halves were
false: that file is merely the 34th name in `find | sort` order, which is where
the byte window happened to open, and the true count was about 33. The only
clue was that the first surviving line had lost its own two leading spaces.

An identical tree -- the merged sha and the branch sha shared one tree object
-- was believed broken on that reading, and the re-run was 52/52 in 1125s.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from console import reverify
from runner import verify

from tests.test_reverify import (branch_with, contract, repo, sh,  # noqa: F401
                                 task_for, wt_root)


def gate_output(failed: int, total: int = 52,
                target: str = "tests/analytics") -> str:
    """What the gate really prints, in the real order: per-file blocks first,
    the summary that carries the count last."""
    names = [f"{target}/test_file_{i:03d}.py" for i in range(failed)]
    out = []
    for n in names:
        out.append(f"--- FAILED {n}")
        out += [f"E       assert 0 == 1  # line {j} of the pytest tail"
                for j in range(15)]
    out.append("")
    out.append(f"FAIL: {failed} of {total} files in {target} failed:")
    out += [f"  {n}" for n in names]
    return "\n".join(out) + "\n"


class TestKeptTail:
    def test_short_output_is_returned_whole_and_unmarked(self):
        assert verify.kept_tail("one\ntwo\n", budget=4000) == "one\ntwo\n"
        assert "TRUNCATED" not in verify.kept_tail("one\ntwo\n")

    def test_output_at_exactly_the_budget_is_not_marked(self):
        text = "x" * 100
        assert verify.kept_tail(text, budget=100) == text

    def test_a_cut_output_is_marked(self):
        text = "\n".join(f"line {i}" for i in range(500)) + "\n"
        kept = verify.kept_tail(text, budget=200)
        assert kept.startswith("[... TRUNCATED:"), kept[:80]
        assert "dropped from the START" in kept

    def test_the_marker_names_how_many_lines_went(self):
        text = "\n".join(f"line {i}" for i in range(100)) + "\n"
        kept = verify.kept_tail(text, budget=100)
        # Lines as a READER counts them: `count("\n") + 1` claims a phantom
        # final line for any output ending in a newline, which is almost all
        # of them.
        total = len(text.splitlines())
        shown = kept.splitlines()[1:]
        assert f"of {total} lines" in kept
        # The number it claims to have dropped agrees with what it shows.
        claimed = int(kept.split("TRUNCATED: ")[1].split(" of ")[0])
        assert claimed == total - len(shown), kept.splitlines()[0]

    def test_it_keeps_the_end_not_the_beginning(self):
        """The tail is where a check puts its count; the head is paths."""
        text = "\n".join(f"line {i}" for i in range(500)) + "\n"
        kept = verify.kept_tail(text, budget=200)
        assert "line 499" in kept
        assert "line 0\n" not in kept

    def test_the_leading_partial_line_is_dropped(self):
        """A mid-line cut produces a fragment that reads as a whole line of a
        different kind -- an indented path losing its indent looks exactly
        like a `--- FAILED` line's path. That fragment is the entire reason
        task 125 was misread, so it is dropped rather than shown."""
        text = "aaaaaaaaaa\nbbbbbbbbbb\ncccccccccc\n"
        kept = verify.kept_tail(text, budget=15)
        body = kept.splitlines()[1:]
        assert body == ["cccccccccc"], body
        assert not any(line.startswith("a") or line.startswith("b")
                       for line in body)

    def test_one_enormous_line_yields_the_marker_and_no_fragment(self):
        kept = verify.kept_tail("x" * 5000, budget=100)
        assert kept.startswith("[... TRUNCATED:")
        assert "x" not in kept

    def test_it_warns_against_reading_a_count_off_the_fragment(self):
        kept = verify.kept_tail("\n".join(str(i) for i in range(900)),
                                budget=100)
        assert "first failure" in kept
        assert "not about the run" in kept


class TestTheGateSummarySurvives:
    """The regression test for task 125, stated as the property that failed."""

    def test_the_count_line_survives_a_realistic_failing_sweep(self):
        out = gate_output(failed=33)
        assert len(out) > verify.OUTPUT_TAIL_BYTES, (
            "the fixture must be big enough to be truncated, or this test "
            "proves nothing")
        kept = verify.kept_tail(out)
        assert "FAIL: 33 of 52 files in tests/analytics failed:" in kept

    def test_a_sweep_where_every_file_failed_still_names_the_count(self):
        kept = verify.kept_tail(gate_output(failed=52))
        assert "FAIL: 52 of 52 files in tests/analytics failed:" in kept

    def test_the_reader_can_tell_33_from_19(self):
        """The exact misreading. With 800 bytes the kept text held 19 path
        lines, no count and no marker, and 19 was the only number available."""
        kept = verify.kept_tail(gate_output(failed=33))
        assert "33 of 52" in kept
        shown_paths = [l for l in kept.splitlines() if l.startswith("  tests/")]
        assert len(shown_paths) == 33, (
            f"{len(shown_paths)} of 33 path lines survived; the count line is "
            f"then the only way to know the real number")

    def test_800_bytes_would_have_lost_it(self):
        """Named so nobody narrows it back. This is the old behaviour."""
        kept = verify.kept_tail(gate_output(failed=33), budget=800)
        assert "FAIL: 33 of 52" not in kept
        # ...but it is no longer silent about having done so.
        assert "TRUNCATED" in kept


class TestTheRecordDoesNotCutItAgain:
    def test_reverify_records_the_whole_tail_it_was_given(self, repo, wt_root):
        """Two truncations in series, and the second destroyed what the first
        was sized to keep. There must be ONE cut, in `verify.kept_tail`.

        A real re-verification, with a check that fails after printing more
        than 800 bytes -- so a second cut would be visible as a short record.
        """
        point, _ = branch_with(repo, "fleet/task-1",
                               {"api/provides.txt": "v2\n"})
        noisy = ("i=0; while [ $i -lt 400 ]; do "
                 "echo \"  tests/analytics/test_file_$i.py\"; i=$((i+1)); done; "
                 "echo 'FAIL: 400 of 400 files in tests/analytics failed:'; "
                 "exit 1")
        r = reverify.run(repo, wt_root, task_for(repo),
                         contract(verification=[noisy]), "fleet/task-1",
                         recorded_base=point,
                         changed_files=["api/provides.txt"])
        assert not r.ok
        failing = [c for c in r.checks if c["exit_code"] == 1]
        assert failing, r.checks
        tail = failing[0]["output_tail"]
        assert len(tail) > 800, (
            f"the record kept {len(tail)} bytes: something is cutting it a "
            f"second time")
        assert len(tail) <= verify.OUTPUT_TAIL_BYTES + 400, len(tail)
        # The closing line -- the one 800 bytes threw away -- is present.
        assert "FAIL: 400 of 400" in tail

    def test_no_second_slice_survives_in_the_source(self):
        """Structural, because the behavioural test above can only catch a cut
        on the path it exercises. `test_unit_ceilings.py`'s precedent: a
        comment saying two numbers should match is what this repository had,
        and it was not enough."""
        src = Path(reverify.__file__).read_text()
        assert "output_tail[-" not in src, (
            "console/reverify.py is slicing output_tail again; the size "
            "belongs to verify.OUTPUT_TAIL_BYTES alone")
