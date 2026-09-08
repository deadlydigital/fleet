"""The morning ping.

  the brief never depends on the ping        -> TestTheBriefIsIndependent
  the ordinary morning reads as an answer    -> TestTheOrdinaryMorning
  a failure is loud in the log, not silent   -> TestWhenTheSendFails
  an unconfigured bot is not a failure       -> TestNoBotConfigured
"""
from __future__ import annotations

import logging

import pytest

from brief import notify


class TestTheOrdinaryMorning:
    def test_nothing_blocking_reads_as_an_answer_not_an_empty_message(self):
        """Most mornings. The same sentence the page uses, on purpose."""
        text = notify.compose({"specs": 0, "branches": 0, "candidates": 0,
                               "queued": 2}, None)
        assert "nothing is waiting on you" in text.lower()
        assert "2 tasks queued" in text

    def test_an_empty_queue_says_why_rather_than_showing_a_zero(self):
        text = notify.compose({"specs": 0, "branches": 0, "candidates": 0,
                               "queued": 0}, None)
        assert "nothing has been approved" in text
        assert "0 task" not in text

    def test_blockers_are_counted_and_the_headline_agrees(self):
        text = notify.compose({"specs": 1, "branches": 2, "candidates": 3,
                               "queued": 0}, None)
        assert "3 things waiting on you" in text
        assert "2 branches ready for review" in text
        assert "1 drafted spec awaiting your approval" in text
        assert "3 candidates awaiting a tick" in text

    def test_the_link_is_included_when_configured(self):
        text = notify.compose({"specs": 1}, "https://console.example/")
        assert "https://console.example/" in text

    def test_no_link_configured_still_sends_a_useful_message(self):
        """A missing URL must not cost the whole ping."""
        text = notify.compose({"specs": 1}, None)
        assert "1 drafted spec" in text

    def test_the_message_carries_no_markdown_that_could_break_it(self):
        """Sent without parse_mode, so nothing here may rely on markup."""
        text = notify.compose({"specs": 1, "candidates": 2}, "https://x/",
                              extra=["a line with _underscores_ and *stars*"])
        assert "_underscores_" in text  # passed through, not escaped or eaten


class TestNoBotConfigured:
    def test_an_unset_token_is_reported_as_a_choice_not_an_error(self, monkeypatch):
        """A box with no bot is a decision.

        Logging it as an error would train the reader to ignore errors from
        this unit, which is the only place a real send failure will appear.
        """
        monkeypatch.setattr(notify.config, "get", lambda name, default=None: None)
        r = notify.send("hello")
        assert r.sent is False
        assert r.unconfigured is True


class TestWhenTheSendFails:
    def test_a_transport_error_never_raises(self, monkeypatch):
        monkeypatch.setattr(notify.config, "get",
                            lambda name, default=None: "x")

        def boom(*a, **k):
            raise OSError("network unreachable")
        monkeypatch.setattr(notify.httpx, "post", boom)

        r = notify.send("hello")
        assert r.sent is False
        assert "network unreachable" in r.reason

    def test_a_non_200_is_recorded_with_the_body(self, monkeypatch):
        """Telegram puts the useful part in the body, not the status."""
        monkeypatch.setattr(notify.config, "get",
                            lambda name, default=None: "x")

        class R:
            status_code = 400
            text = '{"description":"chat not found"}'
        monkeypatch.setattr(notify.httpx, "post", lambda *a, **k: R())

        r = notify.send("hello")
        assert r.sent is False
        assert "chat not found" in r.reason

    def test_the_failure_is_logged_at_error_so_journalctl_has_it(
        self, monkeypatch, caplog
    ):
        """Nothing retries and nothing alerts, so the log is the only record."""
        monkeypatch.setattr(notify, "read_blockers", lambda dsn: {"queued": 0})
        monkeypatch.setattr(notify, "credit_line", lambda dsn: None)
        monkeypatch.setattr(notify, "send",
                            lambda text: notify.Result(False, reason="HTTP 500"))
        with caplog.at_level(logging.ERROR):
            notify.notify("postgresql:///nowhere")
        assert any("FAILED" in r.message or "FAILED" in r.getMessage()
                   for r in caplog.records)


class TestTheBriefIsIndependent:
    """The property the whole module is arranged around."""

    def test_notify_never_raises_even_when_the_read_explodes(self, monkeypatch):
        """Called after the brief is written. An escaping exception here would
        turn a successful brief into a failed unit."""
        def boom(dsn):
            raise RuntimeError("the database went away")
        monkeypatch.setattr(notify, "read_blockers", boom)

        r = notify.notify("postgresql:///nowhere")
        assert r.sent is False
        assert "compose failed" in r.reason

    def test_notify_swallows_a_send_that_raises_despite_promising_not_to(
        self, monkeypatch
    ):
        """Defence against send() breaking its own contract.

        send() is written never to raise. notify() catches it anyway, because
        "never raises" that depends on a second function keeping its promise is
        one promise away from turning a written brief into a failed unit.
        """
        monkeypatch.setattr(notify, "read_blockers", lambda dsn: {"queued": 0})
        monkeypatch.setattr(notify, "credit_line", lambda dsn: None)

        def boom(text):
            raise RuntimeError("send blew up")
        monkeypatch.setattr(notify, "send", boom)

        r = notify.notify("postgresql:///nowhere")
        assert r.sent is False
        assert "send blew up" in r.reason

    def test_run_brief_computes_its_exit_code_before_pinging(self):
        """Structural, not careful.

        The ping is the last statement in main() and its result is discarded;
        the exit code is a literal. If someone ever makes the return value
        depend on the ping, this reads the source and fails.
        """
        src = open("run_brief.py").read()
        tail = src.split("if not args.dry_run and not args.no_notify:")[1]
        assert "notify_mod.notify(fleet_dsn)" in tail
        assert "return 0" in tail
        # The ping's result is not bound to anything.
        assert "= notify_mod.notify(fleet_dsn)" not in tail
