"""One holder of a named job at a time, and a refusal that names the other one.

WHY THIS EXISTS
---------------
`fleet-chain.timer` fires at 08/12/16/20 and `chain.yaml` allows
`wall_clock_seconds: 7200`, so a scheduled run can still be going when the next
fires -- and a by-hand `run_chain.py` overlaps trivially, because it leaves
nothing in the journal for anybody to notice. Nothing stopped two chains
running at once, and two chains do not fail loudly. They destroy each other:

  `console/reverify.py` names the trial clone from the task id alone --
  `fleet-accept-trial-<id>` -- and `runner/worktree.create_trial_clone()` does
  `shutil.rmtree(path)` when that path exists. So the second chain deletes the
  first one's live trial out from under a running check, and the first one's
  `finally` deletes the second one's.

Measured 17 Sep 2026 on task 125, in 27 seconds: a by-hand chain started 15:20
had its `tests/analytics` sweep collapse at ~16:00:10 with roughly 19 of 52
files done, and reported "the branch verifies on its own and FAILS when merged
into main as it stands now" about a merged tree that was byte-identical to the
branch tree (`df2a1e3e`). The timer's chain then died at 16:00:27 on
`[Errno 2] No such file or directory: '/home/ubuntu/.fleet-trials/
fleet-accept-trial-125'` -- a `subprocess.run(cwd=<deleted trial>)`. Re-run
uncontended, the same gate was 52/52 in 1125s.

None of the could-not-run classifiers can catch that shape, which is why it
has to be prevented rather than detected: the failures are real non-zero exits
from pytest, so `verify.run`'s deadline branch, `killed_by` and
`_cgroup_oom_kills` all see an ordinary failing check and report a false
statement about the diff.

REFUSING, NOT QUEUEING
----------------------
`pg_try_advisory_lock`, never `pg_advisory_lock`. A second chain that waits
would start the moment the first finished, unattended, at whatever hour that
is -- and the operator who typed the hand run would have no idea a scheduled
one was stacked behind it. Refusing says so at once, and the next timer slot
considers the same work anyway; that is `fleet-chain.timer`'s own
`Persistent=false` argument.

AND THE REFUSAL IS LOUD. `chain.main()` returns a distinct non-zero, because a
unit that always refuses looks exactly like a unit with nothing to do -- which
is how `run_autodeploy.py` went seven runs without deploying and read as seven
quiet nights.

WHY A POSTGRES ADVISORY LOCK AND NOT A LOCKFILE
-----------------------------------------------
The same three reasons `api/tests/db_lock.py` gives, and one more that is
specific to this caller:

  * it is released when the holding CONNECTION goes away, so `kill -9`, a
    systemd `TimeoutStartSec` kill or a closed laptop leaves nothing to clear
    by hand. A lockfile's failure mode is a file nobody dares delete;
  * it covers anything that reaches the database, not just processes that
    remembered the same path on the same host;
  * the holder is identifiable -- `pg_locks` joined to `pg_stat_activity` is
    what turns "something else is running" into a message you can act on;
  * AND THE CHAIN UNIT SETS `PrivateTmp=true`. A flock under `/tmp` would be a
    different inode in the unit's namespace than in a hand run's, so the two
    could never see each other -- the lock would be perfectly silent about the
    one collision it exists to stop. `console/config.py` carries the same
    measurement for the trial root.

Advisory locks are scoped per database, so this excludes other users of the
`fleet` database and nothing else.
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg


class AlreadyRunning(RuntimeError):
    """Someone else holds this job's lock. Carries a description of who."""


def _key(name: str) -> int:
    """A stable NON-NEGATIVE 63-bit key from a name.

    Hashed rather than a hand-assigned integer so a second job cannot be given
    a number that already means something. `sha256` because it is stable across
    interpreters and runs -- `hash()` is not, and a lock key that changes
    between processes is not a lock.

    NON-NEGATIVE ON PURPOSE, and it is not cosmetic. `pg_locks` splits a
    bigint advisory key across `classid` (high 32 bits) and `objid` (low 32),
    both of them `oid`, which is UNSIGNED. A negative key reappears there as
    two large positives, so `_holder` below could not find its own lock and
    every refusal would read "a session that has since disconnected". Masking
    to 63 bits keeps the split exact in both directions.
    """
    digest = hashlib.sha256(name.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, "big", signed=False) & 0x7FFF_FFFF_FFFF_FFFF


def _holder(conn: psycopg.Connection, key: int) -> str:
    """Who holds `key`, in a sentence an operator can act on.

    The key is split in PYTHON and the two columns compared directly, rather
    than reassembled in SQL with a shift. Same answer, no signedness to get
    wrong, and it reads as what the catalogue actually stores.

    `objsubid = 1` is the single-bigint form of the lock; the two-int form is
    2, and matching on it would be matching a different lock that happens to
    share a number.

    Best effort by construction: the holder can disconnect between the failed
    acquisition and this query, and a caller must still get a refusal rather
    than an exception from the code that explains the refusal.
    """
    try:
        row = conn.execute(
            """
            SELECT a.pid, a.application_name, a.client_addr,
                   date_trunc('second', now() - a.backend_start)::text AS age
              FROM pg_locks l
              JOIN pg_stat_activity a ON a.pid = l.pid
             WHERE l.locktype = 'advisory' AND l.granted
               AND l.classid = %s AND l.objid = %s AND l.objsubid = 1
             LIMIT 1
            """,
            ((key >> 32) & 0xFFFF_FFFF, key & 0xFFFF_FFFF),
        ).fetchone()
    except Exception:                                             # noqa: BLE001
        return "another session, which could not be identified"
    if not row:
        return "another session that has since disconnected -- try again"
    pid, who, addr, age = row
    return (f"pid {pid}"
            + (f" ({who})" if who else "")
            + (f" from {addr}" if addr else " on this host")
            + (f", running for {age}" if age else ""))


@contextmanager
def only_one(name: str, dsn: str, *, identity: str = "") -> Iterator[None]:
    """Hold `name` exclusively for the block, or raise `AlreadyRunning`.

    The connection is opened here and closed on the way out, and it exists for
    nothing but the lock -- so the lock's lifetime is this block's lifetime and
    cannot be extended by a caller holding a row open somewhere else.

    TCP keepalives are set because the holder is idle for the whole run. A
    2-hour chain against RDS is long enough for a middlebox to drop a silent
    connection, and a dropped connection here releases the lock and quietly
    restores the behaviour this module removes. Keepalives make that a
    connection error somebody sees rather than a lock that stopped existing.
    """
    key = _key(name)
    conn = psycopg.connect(
        dsn,
        application_name=(identity or f"fleet {name} pid {os.getpid()}")[:63],
        keepalives=1, keepalives_idle=30, keepalives_interval=10,
        keepalives_count=3,
        autocommit=True,
    )
    try:
        got = conn.execute("SELECT pg_try_advisory_lock(%s::bigint)",
                           (key,)).fetchone()
        if not got[0]:
            raise AlreadyRunning(
                f"another {name} is already running: {_holder(conn, key)}. "
                f"Refusing rather than queueing -- two of these sweep the same "
                f"task and delete each other's trial clone, which reports as "
                f"'the branch FAILS when merged' about a tree that is fine. "
                f"Nothing was done. The next slot considers the same work.")
        yield
    finally:
        # CLOSING THE CONNECTION IS THE RELEASE, and there is deliberately no
        # `pg_advisory_unlock` call to go with it. The lock is session-scoped,
        # so the close covers every exit -- return, exception, and the kills a
        # `finally` never runs for at all. An explicit unlock would add a
        # second way to release that only works on the paths that were already
        # covered, and a way for teardown to raise.
        #
        # Wrapped anyway: a close that fails must not become the error the
        # caller sees instead of whatever the block was really doing.
        try:
            conn.close()
        except Exception:                             # noqa: BLE001, S110
            pass
