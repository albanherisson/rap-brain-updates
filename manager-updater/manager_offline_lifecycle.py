"""Offline lifecycle for a signed general Manager/server update.

Only an external helper may construct this lifecycle after the Manager and
its owned server have exited. It never attaches to or signals an arbitrary
PID. The one-click handoff and production entrypoint are still separate.
"""
import hashlib
import os

from app_bundle_backup import inventory, read_app_backup
from bootstrap_runtime_resources import RUNTIME_FILES
from creative_release import Refused, digest
from creative_transaction import safe_path, fsync_dir
from manager_update_release import verify_manifest
from offline_bootstrap_lifecycle import MacOfflineBootstrapLifecycle
from pending_attempt_recovery import _private_json
from worker_activity_gate import finish_maintenance


class MacOfflineManagerLifecycle(MacOfflineBootstrapLifecycle):
    def __init__(self, source, launcher, state, signed_manifest, *,
                 pinned_key=None, issued_recovery=False, **kwargs):
        from bootstrap_release import PUBLISHER_PIN
        pin = PUBLISHER_PIN if pinned_key is None else pinned_key
        now = None
        if issued_recovery:
            from strict_json import parse_signed_json
            now = parse_signed_json(signed_manifest)['signed_payload']['issued_at']
        release = verify_manifest(signed_manifest, pinned_key=pin, now=now)
        source = safe_path(source, directory=True)
        launcher = safe_path(launcher)
        resources = launcher.parent
        entries = {entry['path']: entry for entry in release['files']}

        def hashes(name, path):
            old = digest(safe_path(path).read_bytes())
            item = entries.get(name)
            return (item['baseline_sha256'], item['payload_sha256']) if item else (old, old)

        base_server, new_server = hashes('server.py', source / 'server.py')
        base_launcher, new_launcher = hashes('app/launch_manager.py', launcher)
        base_dashboard, new_dashboard = hashes('app/dashboard_beta14.html',
                                               resources / 'dashboard_beta14.html')
        runtime = {}
        for name in RUNTIME_FILES:
            _, runtime[name] = hashes('app/' + name, resources / name)
        shape = {'schema': 'rapbrain-guarded-bootstrap-v2',
            'baseline_server_sha256': base_server,
            'candidate_server_sha256': new_server,
            'baseline_launcher_sha256': base_launcher,
            'candidate_launcher_sha256': new_launcher,
            'baseline_dashboard_sha256': base_dashboard,
            'candidate_dashboard_sha256': new_dashboard,
            'runtime_sha256': runtime}
        super().__init__(source, launcher, state, shape, **kwargs)
        self.release = release
        self.entries = entries

    def _code_state(self):
        baseline = candidate = True
        for name, entry in self.entries.items():
            path = (self.launcher.parent / name[4:] if name.startswith('app/')
                    else self.source / name)
            current = digest(safe_path(path).read_bytes())
            baseline &= current == entry['baseline_sha256']
            candidate &= current == entry['payload_sha256']
        if baseline == candidate:
            raise Refused('manager_lifecycle_mixed_or_unchanged_code')
        state = 'baseline' if baseline else 'candidate'
        server_entry = self.entries.get('server.py')
        expected_server = (server_entry['payload_sha256']
            if state == 'candidate' and server_entry else
            self.release['required_server_sha256'])
        if digest(safe_path(self.source / 'server.py').read_bytes()) != expected_server:
            raise Refused('manager_lifecycle_server_changed')
        return state

    def _sign(self):
        self.assert_stopped()
        state = self._code_state()
        folder = safe_path(self.state / self.transaction_id, directory=True)
        if state == 'candidate':
            original = read_app_backup(folder)
            current = inventory(self.app)
            if current.keys() != original.keys():
                raise Refused('manager_lifecycle_app_inventory_changed')
            for name, before in original.items():
                selected = (self.entries.get('app/' + name.removeprefix('Contents/Resources/'))
                    if name.startswith('Contents/Resources/') else None)
                if selected is None:
                    if current[name] != before:
                        raise Refused('manager_lifecycle_unselected_app_changed')
                elif (current[name]['sha256'] != selected['payload_sha256'] or
                        current[name]['mode'] != before['mode']):
                    raise Refused('manager_lifecycle_candidate_app_changed')
            verified = self.signer(self.app, folder, self.source, self.launcher,
                                   inspector=self.inspector)
        elif (folder / 'app-backup.json').is_file():
            verified = self.restored_verifier(self.app, folder, self.source,
                                              self.launcher, inspector=self.inspector)
        else:
            verified = self.unchanged_verifier(self.app, self.source,
                                               self.launcher, inspector=self.inspector)
        if verified is not True:
            raise Refused('manager_lifecycle_signature_invalid')
        self.app_signed = True

    def start_and_check(self):
        self._sign()
        current = digest(safe_path(self.source / 'server.py').read_bytes())
        self.owned = self.candidate_factory(self.source, self.state,
            self.supervisor_state, current, port=self.port)
        self.owned.transaction_id = self.transaction_id
        self.owned.ticket = self.ticket
        self.owned.lock = self.lock
        try:
            return self.owned.start_and_check()
        finally:
            if self.lock is not None and self.lock.fd is None:
                self.lock = None

    def stop_candidate(self):
        if self.owned is None:
            self.assert_stopped()
            return
        # The candidate may be either the signed update or the restored old
        # guarded server. The inherited stop method authenticates against the
        # candidate hash; supply the hash of the exact child this lease owns.
        old = self.manifest['candidate_server_sha256']
        self.manifest['candidate_server_sha256'] = self.owned.expected_server_sha256
        try:
            return super().stop_candidate()
        finally:
            self.manifest['candidate_server_sha256'] = old

    def _finalize_terminal(self):
        journal = self.state / 'manager-transaction.json'
        if not journal.is_file() or self.transaction_id is None:
            return
        record = _private_json(journal, 8192)
        if (type(record) is not dict or record.get('id') != self.transaction_id or
                record.get('source') != str(self.source) or
                record.get('launcher') != str(self.launcher) or
                record.get('phase') not in
                    ('committed', 'rolled_back', 'aborted', 'restored_stopped')):
            return
        if self.owned is not None:
            self.stop_candidate()
        self.assert_stopped()
        if not self.app_signed:
            return
        expected = 'candidate' if record['phase'] == 'committed' else 'baseline'
        if self._code_state() != expected:
            raise Refused('manager_lifecycle_terminal_code_changed')
        marker = safe_path(self.state / 'maintenance.ticket')
        intent = _private_json(self.state / 'bootstrap-intent.json', 4096)
        if (marker.read_bytes() != self.ticket or intent.get('id') != self.transaction_id or
                intent.get('ticket_sha256') != hashlib.sha256(self.ticket).hexdigest()):
            raise Refused('manager_lifecycle_terminal_ticket_changed')
        marker.unlink()
        (self.state / 'bootstrap-intent.json').unlink()
        fsync_dir(self.state)
