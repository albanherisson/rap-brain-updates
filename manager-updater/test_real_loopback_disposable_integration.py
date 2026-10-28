"""Actual loopback cooperative-stop HTTP plus isolated transaction test.

Network targets are OS-assigned ephemeral localhost ports only; no installed
Rap Brain application or live server is accessed.
"""
import secrets
import tempfile
import unittest
from pathlib import Path
from fixture_authenticated_http import FixtureServer, authenticated_stop
from disposable_bundle_transaction import drill,inventory

class RealLoopbackIntegration(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix="rapbrain-auth-fixture-")
  self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)/"DisposableBundleFixture.app"
  (self.root/"Contents/Resources").mkdir(parents=True)
  (self.root/"Contents/Resources/manager.py").write_bytes(b"version=1\n")
  (self.root/"Contents/Info.plist").write_bytes(b"metadata")
  (self.root/"Contents/Resources/custom.icns").write_bytes(b"icon")
  self.before=inventory(self.root)
  self.key=secrets.token_bytes(32)
  self.server=FixtureServer(self.key)
  self.port=self.server.start()
  self.addCleanup(self.server.stop_as_owner)
 def test_authenticated_stop_then_atomic_commit(self):
  self.assertTrue(authenticated_stop(self.server,self.key,self.port))
  self.assertFalse(self.server.thread.is_alive())
  result=drill(self.root,signed_verified=True,healthy=True)
  self.assertEqual(result,"COMMITTED_FIXTURE")
  self.assertEqual((self.root/"Contents/Resources/custom.icns").read_bytes(),b"icon")
 def test_authenticated_stop_then_bad_health_rollback(self):
  self.assertTrue(authenticated_stop(self.server,self.key,self.port))
  self.assertEqual(drill(self.root,signed_verified=True,healthy=False),"ROLLED_BACK")
  self.assertEqual(inventory(self.root),self.before)
 def test_wrong_secret_prevents_mutation(self):
  from urllib.error import HTTPError
  with self.assertRaises(HTTPError) as error:
   authenticated_stop(self.server,secrets.token_bytes(32),self.port)
  error.exception.close()
  self.assertTrue(self.server.thread.is_alive())
  self.assertEqual(inventory(self.root),self.before)
 def test_unsigned_candidate_prevents_stop(self):
  from disposable_bundle_transaction import BundleRefused
  with self.assertRaises(BundleRefused):
   drill(self.root,signed_verified=False,healthy=True)
  self.assertTrue(self.server.thread.is_alive())
  self.assertEqual(inventory(self.root),self.before)
if __name__=="__main__":unittest.main()
