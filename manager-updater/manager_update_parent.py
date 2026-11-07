"""Prepare a signed update before the Manager hands off its owned server.

This module is not wired into the installed Manager. The caller must exit
after a successful return; the helper waits for its actual process exit.
No PID is signalled and no arbitrary listener is stopped.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import uuid

from creative_release import Refused, digest
from creative_transaction import atomic_write, fsync_dir, safe_path
from manager_update_release import download_release, verify_archive, verify_baseline, verify_manifest
from owned_graceful_stop import graceful_stop_owned
from owned_supervisor_binding import bind_owned_launch
from process_start_identity import read_start
from worker_activity_gate import _state, begin_maintenance


class Handoff:
    def __init__(self, child, writer, stopped_lease, identifier):
        self.child = child
        self.writer = writer
        self.stopped_lease = stopped_lease
        self.identifier = identifier

    def release_for_parent_exit(self):
        """Call once, immediately before returning from the Manager parent."""
        if self.writer is None or self.stopped_lease is None:
            raise Refused('manager_handoff_already_released')
        os.close(self.writer)
        self.writer = None
        self.stopped_lease.close()
        self.stopped_lease = None


def prepare_handoff(source, launcher, state, supervisor_state, helper_script,
                    *, downloader=download_release, launch_verifier=verify_manifest,
                    archive_verifier=verify_archive, binder=bind_owned_launch,
                    stopper=graceful_stop_owned, spawner=subprocess.Popen,
                    start_reader=read_start, port=8765):
    source = safe_path(source, directory=True)
    launcher = safe_path(launcher)
    state = _state(state)
    helper = safe_path(helper_script)
    app = launcher.parents[2]
    if (app.suffix != '.app' or launcher.parent.name != 'Resources' or
            helper.is_relative_to(app) or helper.is_relative_to(source) or
            not helper.is_relative_to(state)):
        raise Refused('manager_external_helper_required')
    if (helper.stat().st_uid != os.getuid() or helper.stat().st_mode & 0o077):
        raise Refused('manager_helper_unsafe')
    if (helper.parent.stat().st_uid != os.getuid() or
            helper.parent.stat().st_mode & 0o077):
        raise Refused('manager_helper_directory_unsafe')
    if any(os.path.lexists(state / name) for name in
           ('bootstrap-intent.json', 'maintenance.ticket',
            'maintenance-intent.json')):
        raise Refused('manager_previous_attempt_pending')
    release, archive, _files = downloader()
    manifest = launch_verifier(release)
    archive_verifier(archive, manifest)
    verify_baseline(manifest, source, launcher.parent)
    server_hash = digest(safe_path(source / 'server.py').read_bytes())
    owned = binder(supervisor_state, expected_server_sha256=server_hash)

    identifier = uuid.uuid4().hex
    ticket = (secrets.token_hex(32) + '\n').encode('ascii')
    nonce = secrets.token_bytes(32)
    stage = state / ('handoff-' + identifier)
    stage.mkdir(mode=0o700)
    atomic_write(stage / 'release.json', release)
    atomic_write(stage / 'release.zip', archive)
    fsync_dir(stage)
    parent_pid = os.getpid()
    parent_start = start_reader(parent_pid)
    reader, writer = os.pipe()
    child = None
    stopped = None
    intent = state / 'bootstrap-intent.json'
    try:
        child = spawner([sys.executable, '-B', str(helper),
            '--attempt', identifier, '--read-fd', str(reader),
            '--nonce-sha256', hashlib.sha256(nonce).hexdigest(),
            '--parent-pid', str(parent_pid), '--parent-start', parent_start],
            pass_fds=(reader,), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True)
        os.close(reader)
        reader = None
        # The nonce proves the helper was spawned by this parent. The writer
        # remains open until the Manager parent is ready to exit.
        if os.write(writer, nonce) != len(nonce):
            raise Refused('manager_handoff_nonce_write_failed')
        atomic_write(intent, json.dumps({
            'id': identifier, 'source': str(source), 'launcher': str(launcher),
            'ticket_sha256': hashlib.sha256(ticket).hexdigest()},
            sort_keys=True).encode())
        begin_maintenance(state, ticket)
        # This authenticates Popen, process start, worker, audio, idle jobs,
        # loopback listener and ticket before cooperative server shutdown.
        stopped = stopper(source=source, state=state, handle=owned.handle,
            recorded_start=owned.start, recorded_server_sha256=server_hash,
            token=owned.token, ticket=ticket, port=port)
        return Handoff(child, writer, stopped, identifier)
    except BaseException:
        if stopped is not None:
            stopped.close()
        if reader is not None:
            os.close(reader)
        if writer is not None:
            os.close(writer)
        # A marker or uncertain stop retains its intent for authenticated
        # recovery. Before marker creation no live code or data changed.
        if not os.path.lexists(state / 'maintenance.ticket'):
            intent.unlink(missing_ok=True)
        raise
