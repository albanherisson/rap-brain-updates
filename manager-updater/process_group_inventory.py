"""Read-only OS process-group inventory for a Manager-owned server.

No process signaling or discovery by port. A snapshot is only supporting
evidence; the retained Popen handle, authenticated endpoint, job lock and fresh
start identity must also agree immediately before any future stop.
"""
from dataclasses import dataclass
import subprocess

from creative_release import Refused


@dataclass(frozen=True)
class Member:
    pid: int
    ppid: int
    pgid: int


def parse_ps(text):
    if type(text) is not str or len(text) > 2_000_000 or not text.strip():
        raise Refused('process_inventory_missing')
    members = {}
    for line in text.splitlines():
        parts = line.split()
        if (len(parts) != 3 or any(not value.isascii() or not value.isdecimal()
                                  for value in parts)):
            raise Refused('process_inventory_unparseable')
        pid, ppid, pgid = map(int, parts)
        if pid < 1 or ppid < 0 or pgid < 1 or pid in members:
            raise Refused('process_inventory_ambiguous')
        members[pid] = Member(pid, ppid, pgid)
    return members


def require_owned_group(members, *, manager_pid, parent_pid, worker_pid):
    if (type(members) is not dict or
            any(type(pid) is not int or pid < 2 for pid in
                (manager_pid, parent_pid, worker_pid)) or
            len({manager_pid, parent_pid, worker_pid}) != 3):
        raise Refused('process_identity_invalid')
    parent, worker = members.get(parent_pid), members.get(worker_pid)
    if (parent is None or worker is None or
            parent.ppid != manager_pid or worker.ppid != parent_pid or
            parent.pgid != parent_pid or worker.pgid != parent_pid):
        raise Refused('process_parentage_changed')
    group = frozenset(pid for pid, member in members.items()
                      if member.pgid == parent_pid)
    if group != frozenset((parent_pid, worker_pid)):
        raise Refused('unexpected_process_in_server_group')
    return group


def read_owned_group(*, manager_pid, parent_pid, worker_pid):
    try:
        result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid='],
                                capture_output=True, text=True, timeout=5,
                                stdin=subprocess.DEVNULL, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused('process_inventory_unavailable') from exc
    if result.stderr or len(result.stdout) > 2_000_000:
        raise Refused('process_inventory_unexpected_output')
    return require_owned_group(parse_ps(result.stdout),
                               manager_pid=manager_pid, parent_pid=parent_pid,
                               worker_pid=worker_pid)
