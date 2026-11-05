#!/usr/bin/env python3
"""Stop only the authenticated orphan from one stopped pre-journal handoff.

The original signed helper lost its Popen handle after a locale-dependent
start-time parse failed. This bridge uses the server's authenticated graceful
stop route, never a PID signal, then execs that same signed recovery helper.
"""
import fcntl
import hashlib
import http.client
import os
from pathlib import Path
import re
import subprocess
import sys
import time


BASELINE = 'e072f29f2416ed286c67f8faa73f517a1fb5deafb20cf125ac8f8417722a6464'
ATTEMPT = 'b8594a2a658747eda1b65e6265bf8d65'
ENV_TOKEN = re.compile(r'(?:^|\s)RB_UPDATE_PROBE_TOKEN=([0-9a-f]{64})(?=\s|$)')
ENV_TICKET = re.compile(r'(?:^|\s)RB_UPDATE_LAUNCH_TICKET=([0-9a-f]{64})(?=\s|$)')


def ps(*args):
    result = subprocess.run(['/bin/ps', *args], capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=8, check=True)
    if result.stderr or not result.stdout or len(result.stdout) > 2_000_000:
        raise ValueError('process_inventory_unavailable')
    return result.stdout


def process_rows():
    rows = {}
    for line in ps('-axww', '-o', 'pid=,ppid=,pgid=,uid=,command=').splitlines():
        parts = line.split(None, 4)
        if len(parts) != 5 or not all(v.isdecimal() for v in parts[:4]):
            raise ValueError('process_inventory_unparseable')
        pid, ppid, pgid, uid = map(int, parts[:4])
        if pid in rows:
            raise ValueError('process_inventory_ambiguous')
        rows[pid] = (ppid, pgid, uid, parts[4])
    return rows


def owned_orphan(rows, parent, worker, source):
    a, b = rows.get(parent), rows.get(worker)
    if not a or not b or len({parent, worker, os.getpid()}) != 3:
        raise ValueError('owned_group_missing')
    script = str(source / 'server.py')
    if (a[:3] != (1, parent, os.getuid()) or
            b[:3] != (parent, parent, os.getuid()) or
            not a[3].endswith(' -u ' + script) or
            not b[3].endswith(' ' + script + ' --worker') or
            {pid for pid, row in rows.items() if row[1] == parent} !=
                {parent, worker}):
        raise ValueError('orphan_group_identity_changed')


def process_secrets(parent, marker):
    # ps -E reports the *same user's* process environment. Never print it.
    raw = ps('-E', '-ww', '-p', str(parent), '-o', 'command=')
    tokens = ENV_TOKEN.findall(raw)
    tickets = ENV_TICKET.findall(raw)
    if (len(tokens) != 1 or len(tickets) != 1 or
            tickets[0].encode() + b'\n' != marker):
        raise ValueError('orphan_launch_ticket_unproven')
    return tokens[0], tickets[0]


def listener_pid():
    r = subprocess.run(['/usr/sbin/lsof', '-nP', '-iTCP:8765',
                        '-sTCP:LISTEN', '-Fp'], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=5, check=True)
    lines = r.stdout.splitlines()
    pids = [int(s[1:]) for s in lines if re.fullmatch(r'p[0-9]+', s)]
    if (r.stderr or len(r.stdout) > 4096 or len(pids) != 1 or
            any(not re.fullmatch(r'(?:p[0-9]+|f[0-9]+[a-zA-Z]?)', s)
                for s in lines)):
        raise ValueError('listener_identity_unavailable')
    return pids[0]


def run():
    os.environ['LC_ALL'] = 'C'
    os.environ['LANG'] = 'C'
    home = Path.home()
    source = home / 'Downloads' / 'rap-brain'
    resources = (home / 'Downloads' / 'RapBrainManager_App_Beta14' /
        'Rap Brain Manager Beta 14.app' / 'Contents' / 'Resources')
    state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
    sys.path.insert(0, str(resources))
    from manager_helper_release import verify_staged
    helper = verify_staged(state)
    sys.path.insert(0, str(helper))
    from authenticated_runtime_client import assert_owned_listener, read_runtime_proof
    from creative_readiness import assert_no_pending_jobs
    from creative_transaction import safe_path
    from manager_update_helper import staged_release
    from manager_update_release import verify_archive, verify_baseline, verify_manifest
    from pending_attempt_recovery import _private_json
    from owned_graceful_stop import _stop_response
    from process_start_identity import read_start
    from strict_json import parse_signed_json
    from worker_activity_gate import _lock, _state

    source = safe_path(source, directory=True)
    launcher = safe_path(resources / 'launch_manager.py')
    state = _state(state)
    if any((state / name).exists() for name in
           ('manager-transaction.json', 'maintenance-intent.json')):
        raise ValueError('other_transaction_present')
    report = _private_json(state / 'manager-handoff-result.json', 4096)
    intent = _private_json(state / 'bootstrap-intent.json', 4096)
    if (report.get('attempt') != ATTEMPT or report.get('state') != 'check_required' or
            intent.keys() != {'id', 'source', 'launcher', 'ticket_sha256'} or
            intent['id'] != ATTEMPT or intent['source'] != str(source) or
            intent['launcher'] != str(launcher) or
            hashlib.sha256(launcher.read_bytes()).hexdigest() != BASELINE):
        raise ValueError('original_attempt_changed')
    original = _private_json(state / ('translocation-intent-' + ATTEMPT + '.json'),
                             4096)
    if (type(original) is not dict or
            {k: original.get(k) for k in ('id', 'source', 'ticket_sha256')} !=
                {k: intent[k] for k in ('id', 'source', 'ticket_sha256')} or
            type(original.get('launcher')) is not str or
            '/AppTranslocation/' not in original['launcher'] or
            Path(original['launcher']).exists()):
        raise ValueError('original_translocation_record_changed')
    marker_path = safe_path(state / 'maintenance.ticket')
    info = marker_path.stat()
    marker = marker_path.read_bytes()
    if (info.st_uid != os.getuid() or info.st_mode & 0o077 or
            len(marker) != 65 or marker[-1:] != b'\n' or
            hashlib.sha256(marker).hexdigest() != intent['ticket_sha256']):
        raise ValueError('maintenance_marker_changed')
    signed, archive = staged_release(state, ATTEMPT)
    issued = parse_signed_json(signed)['signed_payload']['issued_at']
    manifest = verify_manifest(signed, now=issued)
    files = verify_archive(archive, manifest)
    if set(files) != {'app/launch_manager.py'} or manifest['data_migrations'] != []:
        raise ValueError('signed_release_scope_changed')
    verify_baseline(manifest, source, resources)
    app = resources.parents[1]
    signature = subprocess.run(['/usr/bin/codesign', '--verify', '--deep',
        '--strict', str(app)], capture_output=True, stdin=subprocess.DEVNULL,
        timeout=90)
    if signature.returncode:
        raise ValueError('original_app_signature_invalid')

    parent = listener_pid()
    rows = process_rows()
    candidates = [pid for pid, row in rows.items()
        if row[0] == parent and row[1] == parent and row[3].endswith(
            ' ' + str(source / 'server.py') + ' --worker')]
    if len(candidates) != 1:
        raise ValueError('worker_identity_ambiguous')
    worker = candidates[0]
    owned_orphan(rows, parent, worker, source)
    token, ticket = process_secrets(parent, marker)
    start_parent, start_worker = read_start(parent), read_start(worker)
    proof = read_runtime_proof(8765, token, expected_parent_pid=parent)
    if proof['worker_pid'] != worker or proof['audio_pid'] is not None:
        raise ValueError('runtime_proof_changed')

    admission = _lock(state, 'admission.lock', fcntl.LOCK_EX)
    try:
        job = _lock(state, 'worker-job.lock', fcntl.LOCK_EX)
        try:
            assert_no_pending_jobs(source)  # SQLite read-only; never restores data.
            if marker_path.read_bytes() != marker:
                raise ValueError('maintenance_marker_changed')
        finally:
            os.close(job)
    finally:
        os.close(admission)
    # The ticket excludes new jobs. Reprove identity immediately before the
    # server's own route checks the worker lock and performs graceful shutdown.
    owned_orphan(process_rows(), parent, worker, source)
    if (read_start(parent) != start_parent or read_start(worker) != start_worker or
            listener_pid() != parent or marker_path.read_bytes() != marker):
        raise ValueError('process_identity_changed_before_stop')
    proof = read_runtime_proof(8765, token, expected_parent_pid=parent)
    if proof['worker_pid'] != worker or proof['audio_pid'] is not None:
        raise ValueError('runtime_proof_changed_before_stop')
    assert_owned_listener(8765, parent)
    conn = http.client.HTTPConnection('127.0.0.1', 8765, timeout=3)
    try:
        conn.request('POST', '/api/manager-update-stop', body=b'', headers={
            'X-RB-Update-Token': token, 'X-RB-Update-Ticket': ticket})
        response = conn.getresponse()
        if (response.status != 202 or
                response.getheader('Content-Type', '').split(';')[0] !=
                    'application/json'):
            raise ValueError('guarded_server_refused_stop')
        _stop_response(response.read(129))
    finally:
        conn.close()
    deadline = time.monotonic() + 18
    while time.monotonic() < deadline:
        rows = process_rows()
        if (parent not in rows and worker not in rows and
                not any(row[1] == parent for row in rows.values())):
            break
        time.sleep(.1)
    else:
        raise ValueError('orphan_group_not_stopped')
    if marker_path.read_bytes() != marker:
        raise ValueError('maintenance_marker_changed_after_stop')
    print('Serveur de la tentative arrete par sa route authentifiee ; reprise signee.',
          flush=True)
    recovery = helper / 'manager_update_recovery.py'
    os.execv(sys.executable, [sys.executable, '-B', str(recovery),
                             '--recover-existing'])


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print('ARRET REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'verification_failed'),
              file=sys.stderr)
        raise SystemExit(2)
