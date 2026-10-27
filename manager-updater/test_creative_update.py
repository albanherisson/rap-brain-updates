import base64
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from creative_release import (Refused, canonical, digest, verify_manifest, verify_archive,
                              allowed_url, NoRedirect, download_release, CREATIVE_KEY_PIN)
from creative_transaction import Transaction
from disposable_update_lifecycle import DisposableLifecycle, MARKER
from owned_child_supervisor_lab import CHILD
from server_lifetime_guard import prepare as prepare_guarded_server


class FixtureLifecycle:
    """Test-only; never imported by production modules. No actual processes."""
    def __init__(self, *, busy=False, health=None):
        self.busy = busy
        self.health = iter(health or [True])
        self.stopped = True

    @contextmanager
    def maintenance(self, source):
        if self.busy:
            raise Refused('analysis_running')
        self.stopped = True
        yield self

    def assert_stopped(self):
        if not self.stopped:
            raise Refused('process_not_stopped')

    def start_and_check(self):
        self.stopped = False
        return next(self.health)

    def stop_candidate(self):
        self.stopped = True


class CreativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'
        (self.source / 'data').mkdir(parents=True)
        self.before = b'VALUE = 1\n'
        self.after = b'VALUE = 2\n'
        (self.source / 'creative_engine.py').write_bytes(self.before)
        (self.source / 'server.py').write_bytes(b'# server fixture, never executed\n')
        (self.source / 'data' / 'ollama_model.json').write_text('{"model":"fixture"}')
        db = sqlite3.connect(self.source / 'data' / 'rapbrain.sqlite3')
        db.execute('CREATE TABLE analyses (text TEXT)')
        db.execute('CREATE TABLE jobs (id INTEGER PRIMARY KEY, status TEXT)')
        db.execute('INSERT INTO analyses VALUES (?)', ('must survive',))
        db.commit()
        db.close()
        (self.source / 'data' / 'audio.wav').write_bytes(b'untouched audio')
        self.original_data = self.data_snapshot()
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.pin = digest(self.pub)
        self.archive = self.zip_bytes()
        now = int(time.time())
        self.manifest = {
            'schema': 'rapbrain-creative-production-v1', 'component': 'creative_engine',
            'target': 'creative_engine.py', 'sequence': 1, 'issued_at': now - 1,
            'expires_at': now + 3600, 'production_install_authorized': True,
            'baseline_sha256': digest(self.before),
            'required_server_sha256': digest((self.source / 'server.py').read_bytes()),
            'payload_sha256': digest(self.after), 'archive_sha256': digest(self.archive),
            'archive_bytes': len(self.archive),
            'archive_url': 'https://albanherisson.github.io/rap-brain-updates/creative-stable/engine-1.zip',
            'data_migrations': [], 'validation': {'real_ollama': 'passed', 'full_server': 'passed'}}

    def data_snapshot(self):
        return {p.name: p.read_bytes() for p in (self.source / 'data').iterdir()}

    def zip_bytes(self, name='creative_engine.py', data=None, mode=None):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            info = zipfile.ZipInfo(name)
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, self.after if data is None else data)
        return buffer.getvalue()

    def signed(self):
        return canonical({'signed_payload': self.manifest, 'signature_algorithm': 'Ed25519',
                          'signature_base64': base64.b64encode(self.key.sign(canonical(self.manifest))).decode(),
                          'public_key_base64': base64.b64encode(self.pub).decode()})

    def transaction(self, lifecycle=None):
        return Transaction(self.source, self.root / 'state', lifecycle or FixtureLifecycle(), pinned_key=self.pin)

    def test_signature_and_payload(self):
        result = verify_manifest(self.signed(), pinned_key=self.pin)
        self.assertEqual(verify_archive(self.archive, result), self.after)

    def test_guarded_restart_handoff_during_signed_transaction(self):
        fixture = b'''import time
if __name__ == '__main__':
    print('READY', flush=True)
    time.sleep(20)
'''
        guarded = prepare_guarded_server(fixture, digest(fixture))
        (self.source / 'server.py').write_bytes(guarded)
        self.manifest['required_server_sha256'] = digest(guarded)
        home = self.root / 'test-home'
        home.mkdir()
        env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
        script = self.source / 'server.py'
        updated = self.after
        owner = self

        class TicketedFixture:
            def __init__(self):
                self.process = None
                self.ticket = 'c' * 64
                self.marker = None
                self.handoff_checked = False
                self.start_and_check(initial=True)

            def stop_candidate(self):
                if self.process is not None:
                    self.process.terminate()
                    self.process.communicate(timeout=5)
                    self.process = None

            def assert_stopped(self):
                if self.process is not None:
                    raise Refused('fixture_process_running')

            def start_and_check(self, initial=False):
                candidate_env = dict(env)
                if not initial:
                    candidate_env['RB_UPDATE_LAUNCH_TICKET'] = self.ticket
                    blocked = subprocess.run([sys.executable, '-B', str(script)], env=env,
                                             capture_output=True, timeout=5)
                    self.handoff_checked = blocked.returncode != 0
                self.process = subprocess.Popen([sys.executable, '-B', str(script)],
                                                env=candidate_env, stdout=subprocess.PIPE,
                                                stderr=subprocess.PIPE, text=True)
                return self.process.stdout.readline().strip() == 'READY'

            @contextmanager
            def maintenance(self, source):
                if Path(source) != owner.source:
                    raise Refused('different_source')
                self.stop_candidate()
                lock = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update' / 'update.lock'
                import fcntl
                fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.marker = lock.with_name('maintenance.ticket')
                    with self.marker.open('xb') as stream:
                        stream.write((self.ticket + '\n').encode())
                    os.chmod(self.marker, 0o600)
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    yield self
                finally:
                    # Fixture cleanup only; production must retain its marker
                    # until the durable transaction is terminal.
                    if self.marker is not None:
                        self.marker.unlink(missing_ok=True)
                    os.close(fd)

        lifecycle = TicketedFixture()
        self.addCleanup(lifecycle.stop_candidate)
        result = self.transaction(lifecycle).install(self.signed(), self.archive)
        self.assertEqual(result['state'], 'committed')
        self.assertTrue(lifecycle.handoff_checked)
        self.assertIsNotNone(lifecycle.process)
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), updated)
        self.assertEqual(self.data_snapshot(), self.original_data)

    def test_test_key_not_trusted_by_production(self):
        self.assertNotEqual(self.pin, CREATIVE_KEY_PIN)
        with self.assertRaises(Refused):
            verify_manifest(self.signed())

    def test_p8_rehearsal_cannot_be_promoted(self):
        self.manifest['schema'] = 'rapbrain-creative-engine-signed-candidate-v1'
        self.manifest['production_install_authorized'] = False
        with self.assertRaises(Refused):
            verify_manifest(self.signed(), pinned_key=self.pin)

    def test_signature_tampering(self):
        raw = json.loads(self.signed())
        raw['signed_payload']['sequence'] = 9
        with self.assertRaises(Exception):
            verify_manifest(canonical(raw), pinned_key=self.pin)

    def test_duplicate_signed_json(self):
        with self.assertRaises(ValueError):
            verify_manifest(b'{"signed_payload":{},"signed_payload":{}}', pinned_key=self.pin)

    def test_expiry_sequence_runtime_and_target_gates(self):
        for key, value in [('expires_at', 1), ('sequence', 0), ('sequence', True),
                           ('target', '../data/rapbrain.sqlite3'), ('data_migrations', ['sql']),
                           ('validation', {'real_ollama': 'failed', 'full_server': 'passed'})]:
            with self.subTest(key=key, value=value):
                original = self.manifest[key]
                self.manifest[key] = value
                with self.assertRaises(Refused):
                    verify_manifest(self.signed(), pinned_key=self.pin)
                self.manifest[key] = original

    def test_zip_traversal_symlink_duplicate_and_corruption(self):
        bad = [self.zip_bytes('../creative_engine.py'), self.zip_bytes(mode=stat.S_IFLNK | 0o777),
               self.archive[:-8]]
        duplicate = io.BytesIO(self.archive)
        with zipfile.ZipFile(duplicate, 'a') as z:
            z.writestr('extra.py', self.after)
        bad.append(duplicate.getvalue())
        for archive in bad:
            self.manifest.update(archive_sha256=digest(archive), archive_bytes=len(archive))
            with self.assertRaises((Refused, zipfile.BadZipFile)):
                verify_archive(archive, self.manifest)

    def test_syntax_error_is_rejected_without_execution(self):
        archive = self.zip_bytes(data=b'def broken(:\n')
        self.manifest.update(archive_sha256=digest(archive), archive_bytes=len(archive),
                             payload_sha256=digest(b'def broken(:\n'))
        with self.assertRaises(SyntaxError):
            verify_archive(archive, self.manifest)

    def test_download_rejects_other_repositories_and_redirects(self):
        for url in ['http://albanherisson.github.io/rap-brain-updates/creative-stable/a.zip',
                    'https://evil.example/a.zip',
                    'https://albanherisson.github.io/other/creative-stable/a.zip',
                    'https://albanherisson.github.io/rap-brain-updates/creative-stable/%2e%2e/a.zip',
                    self.manifest['archive_url'] + '?redirect=evil']:
            with self.assertRaises(Refused):
                allowed_url(url)
        with self.assertRaises(Refused):
            NoRedirect().redirect_request(None, None, 302, '', {}, self.manifest['archive_url'])

    def test_download_checks_manifest_before_fetching_archive(self):
        with patch('creative_release.fetch', return_value=b'{"untrusted":true}') as request:
            with self.assertRaises(Refused):
                download_release()
            self.assertEqual(request.call_count, 1)

    def test_no_real_adapter_means_no_writes(self):
        tx = Transaction(self.source, self.root / 'state')
        with self.assertRaisesRegex(Refused, 'lifecycle'):
            tx.install(self.signed(), self.archive)
        self.assertFalse((self.root / 'state').exists())

    def test_commit_backs_up_and_preserves_all_data(self):
        result = self.transaction().install(self.signed(), self.archive)
        self.assertEqual(result['state'], 'committed')
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), self.after)
        self.assertEqual(self.data_snapshot(), self.original_data)
        folder = self.root / 'state' / result['backup_id']
        self.assertEqual(json.loads((folder / 'backup.json').read_text())['restore_test'], 'passed')
        self.assertEqual((folder / 'creative_engine.before.py').read_bytes(), self.before)

    def test_failed_health_restores_code_only(self):
        result = self.transaction(FixtureLifecycle(health=[False, True])).install(self.signed(), self.archive)
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), self.before)
        self.assertEqual(self.data_snapshot(), self.original_data)

    def test_failed_original_restart_leaves_code_restored_and_stopped(self):
        lease = FixtureLifecycle(health=[False, False])
        result = self.transaction(lease).install(self.signed(), self.archive)
        self.assertEqual(result['state'], 'restored_stopped')
        self.assertTrue(lease.stopped)
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), self.before)

    def test_busy_server_is_not_interrupted(self):
        with self.assertRaisesRegex(Refused, 'analysis_running'):
            self.transaction(FixtureLifecycle(busy=True)).install(self.signed(), self.archive)
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), self.before)
        self.assertFalse((self.root / 'state' / 'transaction.json').exists())

    def test_queued_and_running_jobs_block_install(self):
        for status in ('queued', 'pending', 'retry', 'interrupted', 'running', 'unexpected'):
            with self.subTest(status=status):
                db = sqlite3.connect(self.source / 'data' / 'rapbrain.sqlite3')
                db.execute('DELETE FROM jobs')
                db.execute('INSERT INTO jobs (status) VALUES (?)', (status,))
                db.commit()
                db.close()
                with self.assertRaisesRegex(Refused, 'jobs_active_or_unknown'):
                    self.transaction().install(self.signed(), self.archive)
                self.assertEqual((self.source / 'creative_engine.py').read_bytes(), self.before)
                self.assertFalse((self.root / 'state' / 'transaction.json').exists())

    def test_known_terminal_jobs_allow_staging(self):
        db = sqlite3.connect(self.source / 'data' / 'rapbrain.sqlite3')
        db.executemany('INSERT INTO jobs (status) VALUES (?)', [('done',), ('error',), ('cancelled',)])
        db.commit()
        db.close()
        self.assertEqual(self.transaction().install(self.signed(), self.archive)['state'], 'committed')

    def test_real_owned_subprocess_transaction_and_rollback(self):
        # Create the same shape as the owner's code/data tree under a marker
        # that explicitly forbids use with a real installation.
        fixture = self.root / 'DisposableProcessFixture'
        self.source.rename(fixture)
        self.source = fixture
        (fixture / 'fixture.marker').write_bytes(MARKER)
        (fixture / 'owned_child.py').write_text(CHILD)
        for fail, expected in [(True, 'rolled_back'), (False, 'committed')]:
            with self.subTest(fail_health=fail):
                lease = DisposableLifecycle(fixture, self.before, self.after,
                                            fail_new_health=fail)
                try:
                    result = self.transaction(lease).install(self.signed(), self.archive)
                    self.assertEqual(result['state'], expected)
                    self.assertIsNone(lease.child.process)
                    self.assertEqual((fixture / 'creative_engine.py').read_bytes(),
                                     self.before if fail else self.after)
                    self.assertEqual(self.data_snapshot(), self.original_data)
                finally:
                    lease.child.stop()

    def test_backup_failure_prevents_switch(self):
        (self.source / 'data' / 'ollama_model.json').unlink()
        with self.assertRaises(Refused):
            self.transaction().install(self.signed(), self.archive)
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), self.before)

    def test_damaged_sqlite_prevents_switch(self):
        (self.source / 'data' / 'rapbrain.sqlite3').write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            self.transaction().install(self.signed(), self.archive)
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), self.before)

    def test_concurrent_update_refused(self):
        tx = self.transaction()
        with tx.locked():
            with self.assertRaises(BlockingIOError):
                self.transaction().install(self.signed(), self.archive)

    def test_path_and_baseline_refusals(self):
        with self.assertRaises(Refused):
            Transaction(self.source, self.source / 'state', FixtureLifecycle())
        (self.source / 'creative_engine.py').write_bytes(b'# unexpected local edit')
        with self.assertRaisesRegex(Refused, 'baseline_changed'):
            self.transaction().install(self.signed(), self.archive)
        self.assertFalse((self.root / 'state' / 'transaction.json').exists())

    def test_symlink_ancestor_refused(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(Refused):
            Transaction(alias, self.root / 'state', FixtureLifecycle())

    def test_accepted_sequence_prevents_replay(self):
        self.transaction().install(self.signed(), self.archive)
        with self.assertRaisesRegex(Refused, 'stale_or_expired'):
            self.transaction().install(self.signed(), self.archive)

    def test_committed_journal_repairs_missing_receipt(self):
        self.transaction().install(self.signed(), self.archive)
        receipt = self.root / 'state' / 'accepted.json'
        receipt.unlink()
        with self.assertRaisesRegex(Refused, 'stale_or_expired'):
            self.transaction().install(self.signed(), self.archive)
        self.assertEqual(json.loads(receipt.read_text())['sequence'], 1)

    def test_state_cannot_be_reused_for_different_installation(self):
        self.transaction().install(self.signed(), self.archive)
        other = self.root / 'other'
        other.mkdir()
        tx = Transaction(other, self.root / 'state', FixtureLifecycle(), pinned_key=self.pin)
        with self.assertRaisesRegex(Refused, 'journal_source_mismatch'):
            tx.recover()

    def crash_at(self, phase='switched'):
        (self.root / 'manifest.json').write_bytes(self.signed())
        (self.root / 'update.zip').write_bytes(self.archive)
        program = '''import os, sys
from pathlib import Path
from creative_transaction import Transaction
from test_creative_update import FixtureLifecycle
root = Path(sys.argv[1])
tx = Transaction(root/'source', root/'state', FixtureLifecycle(), pinned_key=sys.argv[2])
save = tx.record
def crash(record, phase):
    if phase == sys.argv[3]:
        if phase != 'switched': save(record, phase)
        os._exit(91)
    save(record, phase)
tx.record = crash
tx.install((root/'manifest.json').read_bytes(), (root/'update.zip').read_bytes())
'''
        result = subprocess.run([sys.executable, '-c', program, str(self.root), self.pin, phase],
                                cwd=Path(__file__).parent, timeout=15)
        self.assertEqual(result.returncode, 91)
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(),
                         self.after if phase == 'switched' else self.before)

    def test_actual_process_crash_recovery(self):
        self.crash_at()
        result = self.transaction().recover()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), self.before)
        self.assertEqual(self.data_snapshot(), self.original_data)
        self.assertIsNone(self.transaction().recover())

    def test_crash_after_backup_aborts_without_installing(self):
        self.crash_at('backup_ready')
        result = self.transaction().recover()
        self.assertEqual(result['state'], 'aborted')
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), self.before)
        self.assertEqual(self.data_snapshot(), self.original_data)

    def test_crash_before_swap_rolls_back_copy(self):
        self.crash_at('switch_pending')
        result = self.transaction().recover()
        self.assertEqual(result['state'], 'rolled_back')
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), self.before)
        self.assertEqual(self.data_snapshot(), self.original_data)

    def test_corrupt_backup_is_preserved_not_used(self):
        self.crash_at()
        record = json.loads((self.root / 'state' / 'transaction.json').read_text())
        (self.root / 'state' / record['id'] / 'creative_engine.before.py').write_bytes(b'bad')
        with self.assertRaisesRegex(Refused, 'rollback_backup_corrupt'):
            self.transaction().recover()
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), self.after)

    def test_recovery_does_not_overwrite_unexpected_edit(self):
        self.crash_at()
        (self.source / 'creative_engine.py').write_bytes(b'# manual repair')
        with self.assertRaisesRegex(Refused, 'unexpected_live_code'):
            self.transaction().recover()
        self.assertEqual((self.source / 'creative_engine.py').read_bytes(), b'# manual repair')


if __name__ == '__main__':
    unittest.main()
