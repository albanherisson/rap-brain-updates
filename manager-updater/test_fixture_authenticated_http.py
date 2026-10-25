import hashlib,hmac,secrets,unittest,urllib.error,urllib.request
from fixture_authenticated_http import FixtureServer,authenticated_stop

class Tests(unittest.TestCase):
 def setUp(self):
  self.secret=secrets.token_bytes(32)
  self.server=FixtureServer(self.secret)
  self.port=self.server.start()
  self.addCleanup(self.server.stop_as_owner)
 def test_health(self):
  with urllib.request.urlopen('http://127.0.0.1:%d/health'%self.port,timeout=2) as resp:
   self.assertEqual(resp.read(),b'FIXTURE_HEALTH_OK')
 def test_authenticated_cooperative_shutdown(self):
  self.assertTrue(authenticated_stop(self.server,self.secret,self.port))
  self.assertFalse(self.server.thread.is_alive())
 def test_wrong_secret_does_not_shutdown(self):
  with self.assertRaises(urllib.error.HTTPError) as error:
   authenticated_stop(self.server,secrets.token_bytes(32),self.port)
  error.exception.close()
  self.assertTrue(self.server.thread.is_alive())
 def test_replay_rejected(self):
  proof=hmac.new(self.secret,("fixture-stop-v1:"+self.server.nonce).encode(),hashlib.sha256).hexdigest().encode()
  request=lambda:urllib.request.Request('http://127.0.0.1:%d/stop'%self.port,data=proof,method='POST')
  with urllib.request.urlopen(request(),timeout=2) as resp:self.assertEqual(resp.status,204)
  self.server.thread.join(timeout=3)
  self.assertFalse(self.server.thread.is_alive())
  self.assertTrue(self.server.used)
if __name__=="__main__":unittest.main()
