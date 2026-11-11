"""Fixture-only update lock regression tests: never touch installed Rap Brain."""
import multiprocessing
from pathlib import Path
import tempfile
import unittest

from disposable_supervisor_lab import MARKER
from fixture_update_lock import LockBusy, exclusive_fixture_lock, locked_fixture_transaction


def try_lock(root, queue):
    try:
        with exclusive_fixture_lock(root):
            queue.put("acquired")
    except LockBusy:
        queue.put("busy")


class FixtureLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "DisposableSupervisorFixture"
        self.root.mkdir()
        (self.root / "fixture.marker").write_text(MARKER)
        (self.root / "manager.txt").write_text("old")
        (self.root / "candidate.txt").write_text("new")

    def tearDown(self):
        self.temp.cleanup()

    def test_exclusive_across_processes(self):
        queue = multiprocessing.Queue()
        with exclusive_fixture_lock(self.root):
            proc = multiprocessing.Process(target=try_lock, args=(self.root, queue))
            proc.start()
            proc.join(timeout=5)
            self.assertEqual(proc.exitcode, 0)
            self.assertEqual(queue.get(timeout=2), "busy")
        proc = multiprocessing.Process(target=try_lock, args=(self.root, queue))
        proc.start()
        proc.join(timeout=5)
        self.assertEqual(proc.exitcode, 0)
        self.assertEqual(queue.get(timeout=2), "acquired")
        queue.close()

    def test_lock_released_after_exception(self):
        with self.assertRaisesRegex(RuntimeError, "test"):
            with exclusive_fixture_lock(self.root):
                raise RuntimeError("test")
        with exclusive_fixture_lock(self.root):
            pass

    def test_symlink_lock_refused(self):
        (self.root / ".update.lock").symlink_to(self.root / "manager.txt")
        with self.assertRaises(OSError):
            with exclusive_fixture_lock(self.root):
                pass
        self.assertEqual((self.root / "manager.txt").read_text(), "old")

    def test_commit_under_lock(self):
        self.assertEqual(locked_fixture_transaction(self.root), "COMMITTED")
        self.assertEqual((self.root / "manager.txt").read_text(), "new")

    def test_rollback_under_lock(self):
        self.assertEqual(locked_fixture_transaction(self.root, health=False), "ROLLED_BACK")
        self.assertEqual((self.root / "manager.txt").read_text(), "old")

    def test_real_app_path_refused(self):
        with self.assertRaises(ValueError):
            with exclusive_fixture_lock("/Applications/Rap Brain Manager.app"):
                pass


if __name__ == "__main__":
    unittest.main()
