from dataclasses import replace
import unittest

from creative_release import Refused
from creative_shutdown_policy import RuntimeProof, assert_safe_to_stop


class ShutdownPolicyTests(unittest.TestCase):
    def setUp(self):
        self.proof = RuntimeProof(
            parent_pid=5100, worker_pid=5101, audio_pid=None,
            process_group_pids=frozenset((5100, 5101)),
            authenticated_parent=True, parent_owned_handle_alive=True,
            worker_same_script=True, worker_idle_verified=True,
            audio_idle_verified=True, admission_marker_held=True,
            http_requests_drained=True,
            job_status_counts={'done': 12, 'error': 1, 'cancelled': 0})

    def test_owned_idle_server_can_reach_shutdown_boundary(self):
        self.assertTrue(assert_safe_to_stop(self.proof, owned_pid=5100))

    def test_unowned_worker_or_extra_group_member_is_refused(self):
        for changed in (replace(self.proof, authenticated_parent=False),
                        replace(self.proof, worker_same_script=False),
                        replace(self.proof, worker_idle_verified=False),
                        replace(self.proof, worker_pid=5102),
                        replace(self.proof, process_group_pids=frozenset((5100, 5101, 5102)))):
            with self.subTest(changed=changed), self.assertRaises(Refused):
                assert_safe_to_stop(changed, owned_pid=5100)
        with self.assertRaisesRegex(Refused, 'owned_process'):
            assert_safe_to_stop(self.proof, owned_pid=9999)

    def test_audio_jobs_and_admission_races_are_refused(self):
        for changed in (replace(self.proof, audio_pid=5102),
                        replace(self.proof, audio_idle_verified=False),
                        replace(self.proof, admission_marker_held=False),
                        replace(self.proof, http_requests_drained=False),
                        replace(self.proof, job_status_counts={'queued': 1}),
                        replace(self.proof, job_status_counts={'running': 1}),
                        replace(self.proof, job_status_counts={'done': True})):
            with self.subTest(changed=changed), self.assertRaises(Refused):
                assert_safe_to_stop(changed, owned_pid=5100)


if __name__ == '__main__':
    unittest.main()
