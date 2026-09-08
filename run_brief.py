#!/usr/bin/env python3
"""Run the daily brief.

    python run_brief.py --dry-run    # render to stdout, write nothing
    python run_brief.py              # write one brief to fleet, then ping
    python run_brief.py --no-notify  # write the brief, send nothing
    python run_brief.py --ping-only  # exercise the ping path, write no brief

Reads as dd_detector_login (FLEET_DSN / DD_DSN), writes as
fleet_brief_writer_login (FLEET_BRIEF_WRITER_DSN). See specs/daily-brief.md.
"""
import argparse
import logging
import sys

from detectors import config
from brief import notify as notify_mod
from brief.pass_ import run_pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="render and print, write nothing")
    ap.add_argument("--no-notify", action="store_true",
                    help="write the brief and send no Telegram ping")
    ap.add_argument("--ping-only", action="store_true",
                    help="build and send the ping without writing a brief, "
                         "to exercise the path without waiting for 07:45")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    fleet_dsn = config.require("FLEET_DSN")

    if args.ping_only:
        # The same escape hatch api/drift-check.sh gives itself with --test: a
        # delivery path nobody can exercise without waiting for the real event
        # is one that gets discovered broken by the event.
        result = notify_mod.notify(fleet_dsn, dry_run=args.dry_run)
        print(result.text)
        print(f"--- {'sent' if result.sent else 'NOT sent'}"
              + (f": {result.reason}" if result.reason else ""))
        return 0 if (result.sent or result.unconfigured or args.dry_run) else 1

    dd_dsn = config.require("DD_DSN")
    write_dsn = config.get("FLEET_BRIEF_WRITER_DSN")
    if not write_dsn and not args.dry_run:
        # Named rather than defaulted to the read DSN. Falling back would give
        # the reader write access, which is the boundary this exists to keep.
        print("FLEET_BRIEF_WRITER_DSN is not set. The brief will not write as "
              "the reading identity; set it or use --dry-run.", file=sys.stderr)
        return 2

    result = run_pass(fleet_dsn, dd_dsn, write_dsn or "",
                      dry_run=args.dry_run)
    print(result["markdown"])
    print(f"--- {result['claims_total']} claims, "
          f"{result['claims_uncomputed']} uncomputed, "
          f"{result['sources_ok']} sources ok, "
          f"{result['sources_failed']} failed"
          + (f", brief #{result['run_id']}" if "run_id" in result else
             " (dry run, nothing written)")
          + (f", {result['disk_path']}" if result.get("disk_path")
             else ", NOT written to disk"))

    # THE PING IS LAST, AND ITS RETURN VALUE IS DISCARDED.
    #
    # The brief is written and on disk by this line. notify() cannot raise --
    # see brief/notify.py -- but the ordering is what actually makes the brief
    # independent of the ping: nothing below can change what was already
    # recorded, and the exit code is a constant.
    #
    # Not sent on --dry-run: a dry run writes nothing, so pinging about it
    # would announce a brief that does not exist.
    if not args.dry_run and not args.no_notify:
        notify_mod.notify(fleet_dsn)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
