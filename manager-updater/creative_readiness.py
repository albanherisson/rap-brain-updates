"""Read-only, fail-closed SQLite job check for the Creative Engine transaction.

This check is necessary but insufficient: the lifecycle adapter must also
exclude new jobs, identify the server/worker/audio processes and stop only
verified owned processes. The query returns counts, never lyrics or analyses.
"""
import sqlite3
from creative_release import Refused
from creative_transaction import safe_path

TERMINAL = {'done', 'error', 'cancelled'}


def assert_no_pending_jobs(source):
    db = safe_path(source / 'data' / 'rapbrain.sqlite3')
    con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        con.execute('PRAGMA query_only=ON')
        rows = con.execute('SELECT status, COUNT(*) FROM jobs GROUP BY status').fetchall()
    finally:
        con.close()
    if any(type(status) is not str or status not in TERMINAL for status, count in rows):
        raise Refused('jobs_active_or_unknown_status')
    return {'jobs_idle': True, 'terminal_count': sum(count for status, count in rows)}
