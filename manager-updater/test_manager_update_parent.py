"""Disposable handoff preparation: no real server, app or database."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from creative_release import Refused
from manager_update_parent import prepare_handoff


class ManagerParentHandoffTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'source'
        self.source.mkdir()
        (self.source / 'server.py').write_bytes(b'old server')
        self.launcher = root / 'Manager.app' / 'Contents' / 'Resources' / 'launch_manager.py'
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_bytes(b'old launcher')
        self.state = root / 'state'
        self.state.mkdir(mode=0o700)
        self.helper = self.state / 'helper.py'
        self.helper.write_text('pass\n')
        self.helper.chmod(0o600)
        self.supervisor = {'process': object()}
        self.owned = Mock(handle=object(), start='start', token='token')
        self.stopped = Mock()
        self.child = Mock()
        self.spawn_args = None
        self.read_fd = None

    def spawn(self, args, **kwargs):
        self.spawn_args = args
        self.read_fd = os.dup(kwargs['pass_fds'][0])
        return self.child

    def prepare(self, **kwargs):
        return prepare_handoff(self.source, self.launcher, self.state,
            self.supervisor, self.helper,
            downloader=lambda: (b'manifest', b'archive', {}),
            launch_verifier=lambda _: {'files': [],
                'required_server_sha256': hashlib.sha256(b'old server').hexdigest()},
            archive_verifier=lambda *_: {}, binder=lambda *_a, **_k: self.owned,
            stopper=kwargs.get('stopper', lambda **_: self.stopped),
            spawner=self.spawn, start_reader=lambda _: 'parent-start')

    def test_handoff_keeps_pipe_and_marker_until_parent_releases(self):
        handoff = self.prepare()
        self.assertTrue((self.state / 'maintenance.ticket').is_file())
        self.assertTrue((self.state / 'bootstrap-intent.json').is_file())
        self.assertEqual(self.spawn_args[0:3],
                         [os.sys.executable, '-B', str(self.helper)])
        intent = json.loads((self.state / 'bootstrap-intent.json').read_text())
        ticket = (self.state / 'maintenance.ticket').read_bytes()
        self.assertEqual(intent['ticket_sha256'], hashlib.sha256(ticket).hexdigest())
        self.assertEqual(intent['id'], handoff.identifier)
        nonce = os.read(self.read_fd, 32)
        self.assertEqual(len(nonce), 32)
        self.assertEqual(hashlib.sha256(nonce).hexdigest(),
                         self.spawn_args[self.spawn_args.index('--nonce-sha256') + 1])
        handoff.release_for_parent_exit()
        self.stopped.close.assert_called_once()
        self.assertEqual(os.read(self.read_fd, 1), b'')
        os.close(self.read_fd)
        with self.assertRaises(Refused):
            handoff.release_for_parent_exit()

    def test_refused_stop_leaves_intent_for_recovery(self):
        def refuse(**_):
            raise Refused('busy')
        with self.assertRaises(Refused):
            self.prepare(stopper=refuse)
        self.assertTrue((self.state / 'maintenance.ticket').is_file())
        self.assertTrue((self.state / 'bootstrap-intent.json').is_file())
        os.close(self.read_fd)

    def test_pending_ticket_refuses_before_download(self):
        (self.state / 'maintenance.ticket').write_text('pending')
        with self.assertRaises(Refused):
            self.prepare()
        self.assertIsNone(self.spawn_args)

    def test_helper_inside_app_refused(self):
        with self.assertRaises(Refused):
            prepare_handoff(self.source, self.launcher, self.state,
                            self.supervisor, self.launcher)


if __name__ == '__main__':
    unittest.main()
