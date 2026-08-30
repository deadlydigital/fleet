#!/usr/bin/env python3
"""The fleet console.

    python run_console.py                 serve on 127.0.0.1:8787
    python run_console.py --port 9000

Binds to loopback and nothing else. The console has no authentication of its
own -- basic auth belongs to the Caddy instance already running on this box --
so a build that bound 0.0.0.0 would be an unauthenticated view of operational
state on the public interface for however long it took someone to notice.
Loopback is the default and `--host` exists so that choice is deliberate when
it is made.

Read-only. It refuses to start as a credential that can write; see
console/db.assert_read_only.
"""
from __future__ import annotations

import argparse
import sys

import uvicorn

from console import db


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="run_console.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--reload", action="store_true")
    args = p.parse_args(argv)

    try:
        who = db.assert_read_only()
    except db.NotReadOnly as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:                                    # noqa: BLE001
        print(f"cannot reach the fleet database: {exc}", file=sys.stderr)
        return 2

    print(f"fleet console on http://{args.host}:{args.port} as {who} (read-only)")
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"  WARNING: bound to {args.host}, which is not loopback. This app "
              f"has no authentication of its own.", file=sys.stderr)
    uvicorn.run("console.app:app", host=args.host, port=args.port,
                reload=args.reload, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
