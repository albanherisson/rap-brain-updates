import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beta14_runtime_token_candidate import prepare


FIXTURE = b'''import os, subprocess, sys
from pathlib import Path
def handle_launch_request(root, rap_dir, backup_dir, state):
    try:
        script = rap_dir / 'server.py'
        with (root / 'launch.log').open('wb') as log:
            proc=subprocess.Popen([sys.executable,'-u',str(script)],cwd=rap_dir,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
        state['process']=proc
    except Exception as exc:
        state['error']=str(exc)
'''


class TokenLauncherTests(unittest.TestCase):
    def test_exact_beta14_launcher_prepares_without_execution(self):
        paths = list(Path(__file__).parents[2].glob(
            'beta14_disposable/**/Contents/Resources/launch_manager.py'))
        if not paths:
            self.skipTest('owner archive not present in repository checkout')
        raw = paths[0].read_bytes()
        output = prepare(raw)
        self.assertEqual(raw, paths[0].read_bytes())
        self.assertIn(b"state['runtime_token']=__rb_token", output)

    def test_token_is_given_only_to_spawned_child_and_kept_out_of_report(self):
        output = prepare(FIXTURE, hashlib.sha256(FIXTURE).hexdigest())
        namespace = {'__name__': 'fixture'}
        exec(output, namespace)
        captured = {}
        def fake_popen(*args, **kwargs):
            captured.update(kwargs)
            return object()
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            backup = root / 'backup'
            backup.mkdir()
            state = {}
            with patch.object(namespace['subprocess'], 'Popen', fake_popen):
                namespace['handle_launch_request'](root, root, backup, state)
            self.assertNotIn('error', state)
            token = state['runtime_token']
            self.assertEqual(len(token), 64)
            self.assertEqual(captured['env']['RB_UPDATE_PROBE_TOKEN'], token)
            self.assertNotEqual(os.environ.get('RB_UPDATE_PROBE_TOKEN'), token)


if __name__ == '__main__':
    unittest.main()
