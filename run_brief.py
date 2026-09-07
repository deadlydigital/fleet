#!/usr/bin/env python3
"""Run the daily brief.

    python run_brief.py --dry-run    # render to stdout, write nothing
    python run_brief.py              # write one brief to fleet

Reads as dd_detector_login (FLEET_DSN / DD_DSN), writes as
fleet_brief_writer_login (FLEET_BRIEF_WRITER_DSN). See specs/daily-brief.md.
"""
import argparse
import logging
import sys

from detectors import config
from brief.pass_ import run_pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="render and print, write nothing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    fleet_dsn = config.require("FLEET_DSN")
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
             " (dry run, nothing written)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
