# Scheduling

Installed and enabled. Reconciliation runs hourly at :20, the heartbeat every
five minutes at :30 past the boundary. To reproduce on another host:

    sudo cp fleet-detector@.service fleet-reconciliation.timer fleet-heartbeat.timer \
            /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now fleet-reconciliation.timer fleet-heartbeat.timer

To stop them without uninstalling:

    sudo systemctl disable --now fleet-reconciliation.timer fleet-heartbeat.timer

The observation cycle is a third unit, not installed and not enabled:

    sudo cp fleet-proposer-cycle.service fleet-proposer-cycle.timer \
            /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now fleet-proposer-cycle.timer

It is `Persistent=true` and the detectors' timers are not, for opposite
reasons. A detector cannot re-derive a missed slot by running late, so
catching up buys nothing. The cycle reads current state, so a run missed
because the host was off is worth doing when it comes back: the morning's
five items are still the morning's five items an hour later.

Check with `systemctl list-timers 'fleet-*'` and
`journalctl -u 'fleet-detector@*' -f` or
`journalctl -u fleet-proposer-cycle -f`.

Timers rather than cron: the unit carries the sandboxing, the failure state is
queryable, and `systemctl list-timers` answers "when did this last run" without
a second source of truth.

Neither timer catching up matters much. A missed slot cannot be re-derived by
running late -- open_scheduled_run always derives the current slot from now()
-- so a gap is recovered by a backfill, and noticed by fleet_heartbeat.
