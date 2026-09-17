"""One chain at a time, refusing rather than queueing.

The defect these exist for is not "two chains ran". It is that two chains
running produced a confident, specific, FALSE statement about a branch --
"the branch verifies on its own and FAILS when merged into main as it stands
now" -- about a merged tree that shared its tree object with the branch.
Task 125, 17 Sep 2026. `runner/exclusive.py` carries the measurements.

So these tests are about the refusal being REAL (a second holder is turned
away, not queued) and LEGIBLE (it says who holds it). A lock that silently
queued would reintroduce the collision one run later; a lock whose refusal
said "could not acquire" would cost the same afternoon again.
"""
from __future__ import annotations

import psycopg
import pytest

from runner import exclusive


class TestTheKey:
    def test_it_is_stable_across_processes(self):
        """`hash()` is salted per interpreter. A key that differs between two
        processes is not a lock -- it is two locks that never meet."""
        assert exclusive._key("chain") == exclusive._key("chain")
        # The literal, so a refactor that changes the derivation has to change
        # this line and say why. Two runs of two interpreters must agree.
        assert exclusive._key("chain") == int.from_bytes(
            __import__("hashlib").sha256(b"chain").digest()[:8],
            "big", signed=False) & 0x7FFF_FFFF_FFFF_FFFF

    def test_it_is_never_negative(self):
        """`pg_locks` stores the key as two UNSIGNED oids. A negative key
        reappears there as two large positives, so `_holder` could not find
        its own lock and every refusal would read 'a session that has since
        disconnected'."""
        for name in ("chain", "automerge", "runner", "a", "", "x" * 300):
            assert 0 <= exclusive._key(name) <= 0x7FFF_FFFF_FFFF_FFFF

    def test_different_names_are_different_locks(self):
        assert exclusive._key("chain") != exclusive._key("automerge")


class TestItRefuses:
    def test_a_second_holder_is_refused(self, dsns):
        with exclusive.only_one("t-refuse", dsns["runner"]):
            with pytest.raises(exclusive.AlreadyRunning):
                with exclusive.only_one("t-refuse", dsns["runner"]):
                    pytest.fail("the second holder was let in")

    def test_it_refuses_rather_than_queueing(self, dsns):
        """The property, stated as a timing: a refusal is immediate. A
        `pg_advisory_lock` would block here until the outer block exited,
        which for a chain is up to two hours -- and would then start a second
        unattended run at whatever hour that is."""
        import time
        with exclusive.only_one("t-nowait", dsns["runner"]):
            started = time.monotonic()
            with pytest.raises(exclusive.AlreadyRunning):
                with exclusive.only_one("t-nowait", dsns["runner"]):
                    pass
            assert time.monotonic() - started < 5.0

    def test_the_refusal_names_the_holder(self, dsns):
        """The whole point of an advisory lock over a lockfile: `pg_locks`
        joined to `pg_stat_activity` turns 'something else is running' into a
        message you can act on.

        This is also the test that catches a classid/objid mistake in
        `_holder`'s query -- get the split wrong and the text falls back to
        'has since disconnected' while the lock itself still works, so nothing
        else here would fail.
        """
        with exclusive.only_one("t-name", dsns["runner"],
                                identity="fleet chain pid 4242"):
            with pytest.raises(exclusive.AlreadyRunning) as caught:
                with exclusive.only_one("t-name", dsns["runner"]):
                    pass
        message = str(caught.value)
        assert "fleet chain pid 4242" in message, message
        assert "disconnected" not in message, message
        assert "pid " in message, message

    def test_the_refusal_says_nothing_was_done(self, dsns):
        """An operator reading it must not have to wonder whether a partial
        run happened."""
        with exclusive.only_one("t-said", dsns["runner"]):
            with pytest.raises(exclusive.AlreadyRunning) as caught:
                with exclusive.only_one("t-said", dsns["runner"]):
                    pass
        assert "Nothing was done" in str(caught.value)

    def test_two_different_names_do_not_exclude_each_other(self, dsns):
        with exclusive.only_one("t-a", dsns["runner"]):
            with exclusive.only_one("t-b", dsns["runner"]):
                pass


class TestItReleases:
    def test_the_block_exiting_releases_it(self, dsns):
        with exclusive.only_one("t-rel", dsns["runner"]):
            pass
        with exclusive.only_one("t-rel", dsns["runner"]):
            pass

    def test_an_exception_inside_the_block_releases_it(self, dsns):
        with pytest.raises(ValueError):
            with exclusive.only_one("t-exc", dsns["runner"]):
                raise ValueError("the run died")
        with exclusive.only_one("t-exc", dsns["runner"]):
            pass

    def test_a_dead_holder_leaves_nothing_to_clear_by_hand(self, dsns):
        """The reason this is not a lockfile.

        A holder that is killed outright -- `kill -9`, a systemd
        `TimeoutStartSec` kill, a dropped laptop -- releases the lock when its
        CONNECTION goes away. A lockfile's failure mode is a file nobody dares
        delete, and the fix for that is invariably `rm` plus a guess.

        Simulated by taking the lock on a raw connection and closing it
        without unlocking, which is what a killed process looks like to the
        server.
        """
        key = exclusive._key("t-dead")
        conn = psycopg.connect(dsns["runner"], autocommit=True)
        got = conn.execute("SELECT pg_try_advisory_lock(%s::bigint)",
                           (key,)).fetchone()
        assert got[0] is True
        conn.close()                      # no unlock: the holder just died
        with exclusive.only_one("t-dead", dsns["runner"]):
            pass


class TestTheChainRefuses:
    """The integration: `chain.main` is where the lock is taken."""

    def test_main_refuses_and_never_reaches_the_loop(self, dsns, monkeypatch):
        import chain

        def must_not_run(*a, **k):
            pytest.fail("the loop ran while another chain held the lock")

        monkeypatch.setattr(chain, "run", must_not_run)
        with exclusive.only_one("chain", dsns["runner"]):
            assert chain.main([]) == chain.REFUSED_CONCURRENT

    def test_a_dry_run_is_refused_too(self, dsns, monkeypatch):
        """--dry-run builds a REAL trial clone at the real path: `reverify.run`
        is the same call either way and only the merge is skipped. So a dry run
        can delete a live run's trial exactly as a real one can, and a lock it
        could walk past would have a hole in it the shape of the
        safest-looking flag."""
        import chain

        monkeypatch.setattr(chain, "run", lambda *a, **k: pytest.fail(
            "the dry run walked past the lock"))
        with exclusive.only_one("chain", dsns["runner"]):
            assert chain.main(["--dry-run"]) == chain.REFUSED_CONCURRENT

    def test_the_refusal_code_is_not_the_safety_stop_code(self):
        """Different mornings, different questions: 1 means the loop ran and
        stopped on something it found; 3 means it never started."""
        import chain
        assert chain.REFUSED_CONCURRENT not in (0, 1)

    def test_it_runs_when_nothing_holds_the_lock(self, dsns, monkeypatch):
        import chain
        seen = []
        monkeypatch.setattr(chain, "run",
                            lambda *a, **k: seen.append(1) or _idle())
        monkeypatch.setattr(chain, "describe", lambda r: [])
        assert chain.main([]) == 0
        assert seen == [1]


def _idle():
    """The shape `chain.run` returns on an ordinary idle night."""
    import chain
    return chain.ChainResult(stopped_by=chain.IDLE)


class TestAutomergeSharesTheLock:
    """Both entry points build `fleet-accept-trial-<id>` through the same
    `reverify.run`, so both must be excluded by ONE lock. Two locks would be
    two answers to one question."""

    def test_automerge_is_refused_while_a_chain_holds_it(self, dsns,
                                                         monkeypatch):
        import run_automerge
        from console import automerge as automerge_mod

        monkeypatch.setattr(automerge_mod, "sweep", lambda **k: pytest.fail(
            "automerge swept while a chain held the merge lock"))
        with exclusive.only_one("chain", dsns["runner"]):
            assert run_automerge.main([]) == 3

    def test_a_chain_is_refused_while_automerge_holds_it(self, dsns,
                                                         monkeypatch):
        """The other direction, which is the one a by-hand sweep creates."""
        import chain

        monkeypatch.setattr(chain, "run", lambda *a, **k: pytest.fail(
            "the chain ran while an automerge sweep held the merge lock"))
        with exclusive.only_one("chain", dsns["runner"]):
            assert chain.main([]) == chain.REFUSED_CONCURRENT

    def test_they_name_the_same_lock(self):
        """Structural: if either entry point is ever given its own name, the
        hole reopens silently."""
        import pathlib
        for entry in ("run_chain.py", "chain.py", "run_automerge.py"):
            src = pathlib.Path(
                exclusive.__file__).parent.parent.joinpath(entry).read_text()
            if "only_one(" in src:
                assert 'only_one("chain"' in src, (
                    f"{entry} takes a lock under a different name")
