import unittest
from unittest.mock import patch

from creative_release import Refused
from owned_supervisor_binding import bind_owned_launch


class Handle:
    pid = 5100
    def poll(self): return None


class BindingTests(unittest.TestCase):
    def test_exact_retained_handle_and_launch_metadata_required(self):
        handle = Handle()
        state = {'process': handle, 'runtime_token': 'a' * 64,
                 'process_start_token': '5100:Tue Oct 27 21:36:22 2026',
                 'server_sha256': 'b' * 64}
        with patch('owned_supervisor_binding.require_live_owned_handle',
                   return_value=state['process_start_token']) as identity:
            owned = bind_owned_launch(state, expected_server_sha256='b' * 64)
            self.assertIs(owned.handle, handle)
            identity.assert_called_once_with(handle, state['process_start_token'])
            for field, wrong in (('runtime_token', 'wrong'),
                                 ('process_start_token', None),
                                 ('server_sha256', 'c' * 64)):
                with self.subTest(field=field):
                    altered = dict(state, **{field: wrong})
                    with self.assertRaises(Refused):
                        bind_owned_launch(altered, expected_server_sha256='b' * 64)
        with patch('owned_supervisor_binding.require_live_owned_handle',
                   side_effect=Refused('owned_process_start_changed')):
            with self.assertRaisesRegex(Refused, 'start_changed'):
                bind_owned_launch(state, expected_server_sha256='b' * 64)


if __name__ == '__main__':
    unittest.main()
