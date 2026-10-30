import unittest
from unittest.mock import patch
import subprocess

from creative_release import Refused
from process_group_inventory import parse_ps, require_owned_group, read_owned_group


FIXTURE = '''400 1 400
500 400 500
501 500 500
999 1 999
'''


class ProcessGroupInventoryTests(unittest.TestCase):
    def test_exact_owned_parent_worker_group(self):
        members = parse_ps(FIXTURE)
        self.assertEqual(require_owned_group(members, manager_pid=400,
                                              parent_pid=500, worker_pid=501),
                         frozenset((500, 501)))

    def test_orphan_audio_wrong_parent_or_duplicate_pid_refused(self):
        for text in (FIXTURE + '502 500 500\n',
                     FIXTURE.replace('501 500 500', '501 1 500'),
                     FIXTURE.replace('501 500 500', '501 500 999')):
            with self.subTest(text=text), self.assertRaises(Refused):
                require_owned_group(parse_ps(text), manager_pid=400,
                                    parent_pid=500, worker_pid=501)
        for text in (FIXTURE + '500 400 500\n',
                     FIXTURE + 'not a pid\n',
                     FIXTURE.replace('501 500 500', '501 500 500 42')):
            with self.subTest(text=text), self.assertRaises(Refused):
                parse_ps(text)

    def test_collector_refuses_os_enumeration_failure(self):
        with patch('process_group_inventory.subprocess.run',
                   side_effect=subprocess.CalledProcessError(1, '/bin/ps')):
            with self.assertRaisesRegex(Refused, 'process_inventory_unavailable'):
                read_owned_group(manager_pid=400, parent_pid=500, worker_pid=501)

if __name__ == '__main__':
    unittest.main()
