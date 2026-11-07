import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from beta14_launch_gate import prepare


FIXTURE = b'''from pathlib import Path
def handle_launch_request(root, rap_dir, backup_dir, state):
    request_file = root / 'launch-request.json'
    if not request_file.exists(): return
    try:
        request_file.unlink()
        state['spawned'] = True
    except Exception as exc:
        state['refused'] = str(exc)
'''


class LaunchGateTests(unittest.TestCase):
    def test_exact_source_required(self):
        with self.assertRaisesRegex(ValueError, 'unknown_beta14_launcher'):
            prepare(FIXTURE)
        modified = prepare(FIXTURE, hashlib.sha256(FIXTURE).hexdigest())
        self.assertIn(b'__rb_ordinary_launch_guard_v1(backup_dir, rap_dir)', modified)
        with self.assertRaisesRegex(ValueError, 'already_patched'):
            prepare(modified, hashlib.sha256(modified).hexdigest())

    def test_pending_marker_and_journal_block_ordinary_launch(self):
        namespace = {}
        exec(prepare(FIXTURE, hashlib.sha256(FIXTURE).hexdigest()), namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            backup = root / 'backups'
            backup.mkdir()
            state_dir = backup / 'secure-update'
            state_dir.mkdir(mode=0o700)
            marker = state_dir / 'maintenance.ticket'
            request = root / 'launch-request.json'
            state = {}

            marker.write_text('a' * 64 + '\n')
            os.chmod(marker, 0o600)
            request.touch()
            namespace['handle_launch_request'](root, root, backup, state)
            self.assertEqual(state.get('refused'), 'update_recovery_required')
            self.assertNotIn('spawned', state)

            marker.unlink()
            journal = state_dir / 'transaction.json'
            journal.write_text(json.dumps({'phase': 'switch_pending'}))
            os.chmod(journal, 0o600)
            state.clear()
            namespace['handle_launch_request'](root, root, backup, state)
            self.assertEqual(state.get('refused'), 'update_recovery_required')
            self.assertNotIn('spawned', state)

            journal.write_text(json.dumps({'phase': 'committed', 'source': str(root),
                                           'sequence': 1, 'mode': 0o644, 'id': 'a' * 32}))
            state.clear()
            namespace['handle_launch_request'](root, root, backup, state)
            self.assertTrue(state.get('spawned'))

            request.touch()
            journal.write_text(json.dumps({'phase': 'committed', 'source': str(root / 'other'),
                                           'sequence': 1, 'mode': 0o644, 'id': 'a' * 32}))
            state.clear()
            namespace['handle_launch_request'](root, root, backup, state)
            self.assertEqual(state.get('refused'), 'update_recovery_required')

    def test_malformed_and_symlink_marker_fail_closed(self):
        namespace = {}
        exec(prepare(FIXTURE, hashlib.sha256(FIXTURE).hexdigest()), namespace)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            backup = root / 'backups'
            backup.mkdir()
            state_dir = backup / 'secure-update'
            state_dir.mkdir(mode=0o700)
            journal = state_dir / 'transaction.json'
            journal.write_text('{invalid')
            os.chmod(journal, 0o600)
            (root / 'launch-request.json').touch()
            result = {}
            namespace['handle_launch_request'](root, root, backup, result)
            self.assertEqual(result.get('refused'), 'update_recovery_required')
            journal.unlink()
            (state_dir / 'maintenance.ticket').symlink_to(root / 'missing')
            result.clear()
            namespace['handle_launch_request'](root, root, backup, result)
            self.assertEqual(result.get('refused'), 'update_recovery_required')


if __name__ == '__main__':
    unittest.main()
