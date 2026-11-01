"""End-to-end fixture-only supervisor transaction; never targets an installed app.

This models authenticated cooperative stop, byte-verified replacement, restart
readiness supplied as a simulated result, and rollback. It is NOT a production updater.
"""
import tempfile
import unittest
from pathlib import Path
from disposable_cooperative_supervisor import DummyServer, Rejected, fixture_transaction
from external_supervisor_fixture import MARKER
from disposable_bundle_transaction import inventory, drill

SECRET=b"fixture-test-secret-that-is-not-a-production-key"

class FullTransactionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.addCleanup(self.temp.cleanup)
  root=Path(self.temp.name)
  self.transaction=root/"DisposableSupervisorFixture"
  self.transaction.mkdir()
  (self.transaction/"fixture.marker").write_bytes(MARKER)
  (self.transaction/"manager.txt").write_bytes(b"VERSION_A")
  (self.transaction/"candidate.txt").write_bytes(b"VERSION_B")
  self.bundle=root/"DisposableBundleFixture.app"
  (self.bundle/"Contents/Resources").mkdir(parents=True)
  (self.bundle/"Contents/Info.plist").write_bytes(b"PLIST")
  (self.bundle/"Contents/Resources/manager.py").write_bytes(b"V1")
  (self.bundle/"Contents/Resources/custom-icon.icns").write_bytes(b"ICON")
  self.original=inventory(self.bundle)

 def test_healthy_path(self):
  stop=DummyServer(SECRET)
  self.assertEqual(fixture_transaction(self.transaction,stop,SECRET),"COMMITTED")
  self.assertFalse(stop.alive)
  self.assertEqual(drill(self.bundle,signed_verified=True,healthy=True),"COMMITTED_FIXTURE")
  self.assertEqual((self.bundle/"Contents/Resources/custom-icon.icns").read_bytes(),b"ICON")

 def test_failed_health_restores_both_fixtures(self):
  stop=DummyServer(SECRET)
  self.assertEqual(fixture_transaction(self.transaction,stop,SECRET,health=False),"ROLLED_BACK")
  self.assertEqual(drill(self.bundle,signed_verified=True,healthy=False),"ROLLED_BACK")
  self.assertEqual(inventory(self.bundle),self.original)
  self.assertEqual((self.transaction/"manager.txt").read_bytes(),b"VERSION_A")

 def test_wrong_secret_changes_nothing(self):
  with self.assertRaises(Rejected):
   fixture_transaction(self.transaction,DummyServer(SECRET),b"z"*32)
  self.assertEqual(inventory(self.bundle),self.original)
  self.assertEqual((self.transaction/"manager.txt").read_bytes(),b"VERSION_A")

 def test_unsigned_changes_nothing(self):
  with self.assertRaises(Rejected):
   fixture_transaction(self.transaction,DummyServer(SECRET),SECRET,signed=False)
  self.assertEqual(inventory(self.bundle),self.original)

if __name__=="__main__":unittest.main()
