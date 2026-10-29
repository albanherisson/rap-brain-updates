"""Crash windows must refuse an ordinary launch, including direct server.py."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from beta14_launch_gate import prepare as prepare_gate
from recovery_start_guards import prepare_server, prepare_launcher
from server_lifetime_guard import prepare as prepare_lifetime


SERVER = b"if __name__ == '__main__':\n    print('READY', flush=True)\n"
LAUNCHER = b'''from pathlib import Path
def handle_launch_request(root, rap_dir, backup_dir, state):
    request_file = root / 'launch-request.json'
    if not request_file.exists(): return
    try:
        request_file.unlink()
        state['spawned'] = True
    except Exception as exc:
        state['refused'] = str(exc)
'''


class RecoveryStartupTests(unittest.TestCase):
    def test_direct_server_rejects_orphan_intent_and_pending_journal(self):
        previous = prepare_lifetime(SERVER, hashlib.sha256(SERVER).hexdigest())
        with patch('recovery_start_guards.prepare_graceful_server', return_value=previous):
            candidate = prepare_server(SERVER)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            home = root / 'home'
            home.mkdir()
            script = root / 'server.py'
            script.write_bytes(candidate)
            env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
            state = home / 'Downloads' / 'RapBrainManagerBackups' / 'secure-update'
            state.mkdir(parents=True, mode=0o700)

            def start():
                return subprocess.run([sys.executable, '-B', str(script)], env=env,
                                      capture_output=True, text=True, timeout=5)

            self.assertEqual(start().stdout.strip(), 'READY')
            bootstrap = state / 'bootstrap-intent.json'
            bootstrap.write_text('{}')
            self.assertNotEqual(start().returncode, 0)
            bootstrap.unlink()
            intent = state / 'maintenance-intent.json'
            intent.write_text('{}')
            self.assertNotEqual(start().returncode, 0)
            intent.unlink()
            journal = state / 'transaction.json'
            journal.write_text(json.dumps({'phase': 'switch_pending', 'source': str(root)}))
            journal.chmod(0o600)
            self.assertNotEqual(start().returncode, 0)
            journal.write_text(json.dumps({'phase': 'committed', 'source': str(root),
                                           'sequence': 1, 'mode': 0o644, 'id': 'a' * 32}))
            self.assertEqual(start().stdout.strip(), 'READY')
            journal.write_text('{"phase":"committed","phase":"aborted"}')
            self.assertNotEqual(start().returncode, 0)

    def test_beta14_refuses_orphan_intent_without_ticket(self):
        previous = prepare_gate(LAUNCHER, hashlib.sha256(LAUNCHER).hexdigest())
        with patch('recovery_start_guards.prepare_owned_launcher', return_value=previous):
            candidate = prepare_launcher(LAUNCHER)
        scope = {}
        exec(candidate, scope)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            backup = root / 'backups'
            state_dir = backup / 'secure-update'
            state_dir.mkdir(parents=True, mode=0o700)
            (state_dir / 'maintenance-intent.json').write_text('{}')
            (root / 'launch-request.json').touch()
            state = {}
            scope['handle_launch_request'](root, root, backup, state)
            self.assertEqual(state.get('refused'), 'update_recovery_required')
            self.assertNotIn('spawned', state)
            (state_dir / 'maintenance-intent.json').unlink()
            (state_dir / 'bootstrap-intent.json').write_text('{}')
            (root / 'launch-request.json').touch()
            state.clear()
            scope['handle_launch_request'](root, root, backup, state)
            self.assertEqual(state.get('refused'), 'bootstrap_recovery_required')
            self.assertNotIn('spawned', state)


if __name__ == '__main__':
    unittest.main()
