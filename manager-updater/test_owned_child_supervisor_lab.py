import unittest,tempfile
from pathlib import Path
from owned_child_supervisor_lab import OwnedChild,ChildError,CHILD,transaction

class Tests(unittest.TestCase):
    def test_success(self):self.assertEqual(transaction(),"COMMITTED")
    def test_rollback(self):self.assertEqual(transaction(fail_health=True),"ROLLED_BACK")
    def test_failed_child_start_restores_old_version(self):
        self.assertEqual(transaction(fail_start=True),"ROLLED_BACK")
    def test_owned_process_stops(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"fixture_child.py";p.write_text(CHILD)
            owner=OwnedChild()
            pid=owner.start(p,"old")
            self.assertGreater(pid,1)
            owner.stop()
            self.assertIsNone(owner.process)
    def test_double_start_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"fixture_child.py";p.write_text(CHILD)
            owner=OwnedChild()
            try:
                owner.start(p,"old")
                with self.assertRaises(ChildError):owner.start(p,"new")
            finally:owner.stop()
    def test_unknown_version_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"fixture_child.py";p.write_text(CHILD)
            with self.assertRaises(ChildError):OwnedChild().start(p,"danger")
    def test_nonexistent_child_refused(self):
        with self.assertRaises(ChildError):OwnedChild().start("/does/not/exist","old")
    def test_bad_handshake_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"fixture_child.py";p.write_text("print('BAD',flush=True)")
            owner=OwnedChild()
            with self.assertRaises(ChildError):owner.start(p,"old")
            self.assertIsNone(owner.process)
    def test_stop_without_child(self):OwnedChild().stop()
if __name__=="__main__":unittest.main()
