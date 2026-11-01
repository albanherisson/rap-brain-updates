import unittest
from supervisor_process_identity import ProcessObservation, IdentityRefused, same_process, preflight

SHA_A="a"*64
SHA_B="b"*64

def observation(**changes):
    data=dict(pid=48297,uid=501,start_ns=1792867724000000000,
              executable_path="/Applications/Xcode.app/Contents/MacOS/Python",
              executable_sha256=SHA_A,
              script_path="/Users/gns/Applications/Rap Brain Manager.app/Contents/Resources/manager.py",
              script_sha256=SHA_B,
              loopback_port=62788,port_owner_pid=48297,authenticated_health=True)
    data.update(changes)
    return ProcessObservation(**data)

class SafetyTests(unittest.TestCase):
    def test_matching_observations(self):
        self.assertTrue(same_process(observation(),observation()))
    def test_pid_reused(self):
        self.assertFalse(same_process(observation(),observation(start_ns=1792867725000000000)))
    def test_changed_pid(self):
        self.assertFalse(same_process(observation(),observation(pid=48298,port_owner_pid=48298)))
    def test_changed_user(self):
        self.assertFalse(same_process(observation(),observation(uid=502)))
    def test_changed_interpreter(self):
        self.assertFalse(same_process(observation(),observation(executable_sha256=SHA_B)))
    def test_changed_script(self):
        self.assertFalse(same_process(observation(),observation(script_sha256=SHA_A)))
    def test_wrong_port(self):
        self.assertFalse(same_process(observation(),observation(loopback_port=62789)))
    def test_port_hijack(self):
        with self.assertRaises(IdentityRefused):observation(port_owner_pid=48298)
    def test_unverified_health(self):
        with self.assertRaises(IdentityRefused):observation(authenticated_health=False)
    def test_health_must_be_boolean(self):
        with self.assertRaises(IdentityRefused):observation(authenticated_health=1)
    def test_pid_boolean_refused(self):
        with self.assertRaises(IdentityRefused):observation(pid=True)
    def test_invalid_hash(self):
        with self.assertRaises(IdentityRefused):observation(script_sha256="unknown")
    def test_unsigned_candidate(self):
        with self.assertRaises(IdentityRefused):preflight(observation(),observation(),signed_release=False,stop_supported=True)
    def test_no_cooperative_stop(self):
        with self.assertRaises(IdentityRefused):preflight(observation(),observation(),signed_release=True,stop_supported=False)
    def test_identity_changed_blocks(self):
        with self.assertRaises(IdentityRefused):preflight(observation(),observation(start_ns=123),signed_release=True,stop_supported=True)
    def test_preflight_not_kill_permission(self):
        self.assertEqual(preflight(observation(),observation(),signed_release=True,stop_supported=True),
                         "COOPERATIVE_STOP_PREFLIGHT_ONLY")

if __name__=="__main__":unittest.main()
