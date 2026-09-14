"""A failing check does not stop the ones after it.

specs/verification-collects-its-evidence.md. `verify.run` stopped at the first
failure until 14 Sep 2026, which made the first failure the only fact a run
recorded. Task 87 was refused by a 72ms citation check and the four checks
behind it never ran; the branch had never passed its own test, and nobody
found out for a day.

These assert the three things that change and the three that must not.
"""
from __future__ import annotations

from runner import verify

ABORT = "kill -ABRT $$"          # exit -6: died, did not decide


# ---- what changes --------------------------------------------------------

def test_a_failing_check_does_not_stop_the_ones_after_it(tmp_path):
    result = verify.run(tmp_path, ["exit 1", "true", "true"], 30)
    assert len(result.checks) == 3, result.summary()
    assert [c.ran for c in result.checks] == [True, True, True]
    assert [c.passed for c in result.checks] == [False, True, True]
    # The refusal is unchanged. boundary.size_only's sentence: this only
    # decides whether the evidence gets collected first.
    assert not result.passed


def test_every_failing_check_is_recorded_and_not_only_the_first(tmp_path):
    """The reader needs to know whether it is one fix from green or three."""
    result = verify.run(tmp_path, ["exit 1", "exit 3", "true"], 30)
    assert [c.exit_code for c in result.checks] == [1, 3, 0]
    assert not result.passed


def test_the_output_of_a_later_failure_is_kept(tmp_path):
    """console/automerge.log_failing_checks prints these; an empty tail on the
    check that explains the branch is the defect that made it worth printing."""
    result = verify.run(
        tmp_path, ["exit 1", "echo the-second-reason >&2; exit 1"], 30)
    assert "the-second-reason" in result.checks[1].output_tail


# ---- what must not change ------------------------------------------------

def test_a_green_run_runs_everything_exactly_as_before(tmp_path):
    """The whole cost argument rests on this: a passing run always ran every
    check, because this only ever stopped on failure."""
    result = verify.run(tmp_path, ["true", "true", "true"], 30)
    assert result.passed
    assert len(result.checks) == 3


def test_a_killed_check_alone_still_establishes_nothing(tmp_path):
    result = verify.run(tmp_path, [ABORT], 30)
    assert result.undecided
    assert not result.failed_outright, "nothing here returned a verdict"
    assert not result.passed


# ---- the two classes in one run, which could not happen before -----------

def test_a_check_killed_after_a_real_failure_does_not_erase_the_failure(tmp_path):
    """Both callers branch on `undecided` to say "this says nothing about the
    branch". On a run that also holds a genuine failing verdict that sentence
    is false, and it would bury the one finding the run did make."""
    result = verify.run(tmp_path, ["exit 1", ABORT], 30)
    assert result.undecided, "the second check died"
    assert result.failed_outright, "and the first one returned a verdict"
    assert not result.passed


def test_a_failure_after_a_killed_check_counts_the_same_way(tmp_path):
    """Order must not decide which class the run reports."""
    result = verify.run(tmp_path, [ABORT, "exit 1"], 30)
    assert result.undecided and result.failed_outright


# ---- the ceiling ---------------------------------------------------------

def test_the_deadline_is_one_budget_for_the_phase_not_one_per_check(tmp_path):
    """N checks must not burn N deadlines: that is the one way running them
    all could be worse than the fail-fast it replaces. `remaining` subtracts
    what the earlier checks already spent."""
    result = verify.run(tmp_path, ["sleep 5", "sleep 5"], 0.4)
    assert result.checks[0].timed_out
    # The second never started, so the run cost about one deadline and not two.
    assert sum(c.duration_ms for c in result.checks) < 2000


def test_every_check_the_deadline_stopped_is_recorded(tmp_path):
    """Recorded rather than dropped, so the report shows the whole contract --
    the argument the unresolved branch already makes. It bites harder now:
    stopping early no longer means "the rest are unknown by convention"."""
    result = verify.run(tmp_path, ["sleep 5", "true", "true"], 0.4)
    assert len(result.checks) == 3, result.summary()
    assert all(c.undecided_reason for c in result.checks[1:])
    assert not any(c.ran for c in result.checks[1:])
    # And an unrun check is never read as a pass.
    assert not result.passed
    assert not any(c.passed for c in result.checks[1:])
