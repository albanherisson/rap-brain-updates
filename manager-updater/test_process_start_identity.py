import unittest
from unittest.mock import patch

from creative_release import Refused
from process_start_identity import parse_start, require_live_owned_handle


class FakeHandle:
    pid = 5100
    def __init__(self):
        self.alive = True
    def poll(self):
        return None if self.alive else 1


class ProcessStartTests(unittest.TestCase):
    def test_start_token_binds_pid_and_rejects_ambiguous_output(self):
        raw = 'Tue Oct 27 21:36:22 2026\n'
        self.assertEqual(parse_start(raw, 5100), '5100:Tue Oct 27 21:36:22 2026')
        for changed in ('', raw + raw, 'Oct 27 21:36:22 2026\n',
                        'Tue Oct 27 21:36:22 2026\nERROR'):
            with self.subTest(changed=changed), self.assertRaises(Refused):
                parse_start(changed, 5100)

    def test_retained_handle_must_still_be_alive_and_start_match(self):
        handle = FakeHandle()
        expected = '5100:Tue Oct 27 21:36:22 2026'
        with patch('process_start_identity.read_start', return_value=expected):
            self.assertEqual(require_live_owned_handle(handle, expected), expected)
            with self.assertRaisesRegex(Refused, 'start_changed'):
                require_live_owned_handle(handle, '5100:Tue Oct 27 22:36:22 2026')
            handle.alive = False
            with self.assertRaisesRegex(Refused, 'not_alive'):
                require_live_owned_handle(handle, expected)


if __name__ == '__main__':
    unittest.main()
