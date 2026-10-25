import json
from pathlib import Path
import unittest
from process_identity_gate import UnsafeProcess,parse_state,exact_process_command,may_prepare_restart

SCRIPT=Path("/Users/gns/Applications/Rap Brain Manager.app/Contents/Resources/manager.py")
CMD="/usr/bin/python3 "+str(SCRIPT)
GOOD=json.dumps({"pid":48297,"port":62788}).encode()
class Tests(unittest.TestCase):
    def test_good(self):self.assertEqual(parse_state(GOOD),(48297,62788))
    def test_exact_command(self):self.assertTrue(exact_process_command(CMD,SCRIPT))
    def test_healthy(self):self.assertTrue(may_prepare_restart(GOOD,CMD,SCRIPT,True))
    def test_wrong_health(self):
        with self.assertRaises(UnsafeProcess):may_prepare_restart(GOOD,CMD,SCRIPT,False)
    def test_wrong_script(self):self.assertFalse(exact_process_command("/usr/bin/python3 /Users/gns/Downloads/rap-brain/server.py",SCRIPT))
    def test_suffix(self):self.assertFalse(exact_process_command(CMD+".evil",SCRIPT))
    def test_extra_args(self):self.assertFalse(exact_process_command(CMD+" --other",SCRIPT))
    def test_bad_json(self):
        with self.assertRaises(UnsafeProcess):parse_state(b"{bad")
    def test_extra_json(self):
        with self.assertRaises(UnsafeProcess):parse_state(b'{"pid":48297,"port":62788,"signal":true}')
    def test_bool_pid(self):
        with self.assertRaises(UnsafeProcess):parse_state(b'{"pid":true,"port":62788}')
    def test_low_port(self):
        with self.assertRaises(UnsafeProcess):parse_state(b'{"pid":48297,"port":80}')
    def test_huge(self):
        with self.assertRaises(UnsafeProcess):parse_state(b" "*8193)
    def test_missing_pid(self):
        with self.assertRaises(UnsafeProcess):parse_state(b'{"port":62788}')
    def test_newline(self):self.assertFalse(exact_process_command(CMD+"\nother",SCRIPT))
    def test_wrong_interpreter(self):self.assertFalse(exact_process_command("/usr/bin/bash "+str(SCRIPT),SCRIPT))
    def test_mismatch(self):
        with self.assertRaises(UnsafeProcess):may_prepare_restart(GOOD,"/usr/bin/python3 /elsewhere/manager.py",SCRIPT,True)
if __name__=="__main__":unittest.main()
