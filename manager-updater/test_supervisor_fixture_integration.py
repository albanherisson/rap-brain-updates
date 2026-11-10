"""Read-only preflight integration with the fixture-only transaction system.

No real processes can be signalled; no installed .app may be targeted.
"""
import tempfile
import unittest
from pathlib import Path
from supervisor_process_identity import ProcessObservation, IdentityRefused, preflight
from mac_lifecycle_policy import Stage, Refused, plan
from external_supervisor_fixture import MARKER, run

def obs(**changes):
    record = dict(
        pid=12345, uid=501, start_ns=12000000000,
        executable_path="/Applications/Xcode.app/Contents/MacOS/Python",
        executable_sha256="a"*64,
        script_path="/tmp/DisposableSupervisorFixture/manager.py",
        script_sha256="b"*64,
        loopback_port=62788, port_owner_pid=12345,
        authenticated_health=True,
    )
    record.update(changes)
    return ProcessObservation(**record)

class FixtureIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"DisposableSupervisorFixture"
        self.root.mkdir()
        (self.root/"fixture.marker").write_bytes(MARKER)
        (self.root/"manager.txt").write_bytes(b"VERSION_A")
        (self.root/"candidate.txt").write_bytes(b"VERSION_B")

    def test_authorized_preflight_only_precedes_fixture_commit(self):
        before=obs()
        after=obs()
        decision=preflight(before,after,signed_release=True,stop_supported=True)
        self.assertEqual(decision,"COOPERATIVE_STOP_PREFLIGHT_ONLY")
        self.assertEqual(plan(Stage.PRECHECK,identity_still_matches=True,signed=True).name,
                         "request_cooperative_stop")
        self.assertEqual(run(self.root),"COMMITTED")
        self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_B")

    def test_pid_reuse_cannot_begin_transaction(self):
        with self.assertRaises(IdentityRefused):
            preflight(obs(),obs(start_ns=12000000001),signed_release=True,stop_supported=True)
        self.assertFalse((self.root/"journal.json").exists())
        self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_A")

    def test_unauthenticated_server_cannot_begin_transaction(self):
        with self.assertRaises(IdentityRefused):
            preflight(obs(),obs(authenticated_health=False),signed_release=True,stop_supported=True)
        self.assertFalse((self.root/"journal.json").exists())

    def test_unsigned_release_cannot_begin_transaction(self):
        with self.assertRaises(IdentityRefused):
            preflight(obs(),obs(),signed_release=False,stop_supported=True)
        self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_A")

    def test_cooperative_stop_required(self):
        with self.assertRaises(IdentityRefused):
            preflight(obs(),obs(),signed_release=True,stop_supported=False)
        self.assertFalse((self.root/"journal.json").exists())

    def test_health_failure_restores_old_fixture(self):
        preflight(obs(),obs(),signed_release=True,stop_supported=True)
        self.assertEqual(run(self.root,health=False),"ROLLED_BACK")
        self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_A")

    def test_interrupted_fixture_recovers(self):
        preflight(obs(),obs(),signed_release=True,stop_supported=True)
        with self.assertRaises(RuntimeError):
            run(self.root,crash="switched")
        self.assertEqual(run(self.root),"RECOVERED_OLD")
        self.assertEqual((self.root/"manager.txt").read_bytes(),b"VERSION_A")

if __name__=="__main__":
    unittest.main()
