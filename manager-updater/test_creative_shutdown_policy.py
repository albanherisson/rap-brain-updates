from dataclasses import replace
import unittest

from creative_release import Refused
from creative_shutdown_policy import RuntimeProof, assert_safe_to_stop


class ShutdownPolicyTests(unittest.TestCase):
    def setUp(self):
        self.sha = 'a' * 64
        self.proof = RuntimeProof(
            parent_pid=5100, worker_pid=5101, audio_pid=None,
            parent_start_token='boot:5100:100', worker_start_token='boot:5101:101',
            parent_script_sha256=self.sha, worker_script_sha256=self.sha,
            process_group_pids=frozenset((5100, 5101)),
            authenticated_parent=True, parent_owned_handle_alive=True,
            worker_same_script=True, worker_idle_verified=True,
            audio_idle_verified=True, admission_marker_held=True,
            http_requests_drained=True,
            job_status_counts={'done': 12, 'error': 1, 'cancelled': 0})

    def check(self, proof, **overrides):
        arguments = dict(owned_pid=5100, owned_start_token='boot:5100:100',
                         expected_server_sha256=self.sha)
        arguments.update(overrides)
        return assert_safe_to_stop(proof, **arguments)

    def test_owned_idle_server_can_reach_shutdown_boundary(self):
        self.assertTrue(self.check(self.proof))

    def test_unowned_worker_or_extra_group_member_is_refused(self):
        for changed in (replace(self.proof, authenticated_parent=False),
                        replace(self.proof, worker_same_script=False),
                        replace(self.proof, worker_idle_verified=False),
                        replace(self.proof, worker_pid=5102),
                        replace(self.proof, process_group_pids=frozenset((5100, 5101, 5102)))):
            with self.subTest(changed=changed), self.assertRaises(Refused):
                self.check(changed)
        with self.assertRaisesRegex(Refused, 'owned_process'):
            self.check(self.proof, owned_pid=9999)

    def test_reused_pid_or_changed_server_source_is_refused(self):
        with self.assertRaisesRegex(Refused, 'process_start_identity_changed'):
            self.check(self.proof, owned_start_token='boot:5100:200')
        for changed in (replace(self.proof, parent_start_token='boot:5100:200'),
                        replace(self.proof, worker_start_token='boot:5100:100'),
                        replace(self.proof, worker_script_sha256='b' * 64),
                        replace(self.proof, parent_script_sha256='b' * 64)):
            with self.subTest(changed=changed), self.assertRaises(Refused):
                self.check(changed)

    def test_audio_jobs_and_admission_races_are_refused(self):
        for changed in (replace(self.proof, audio_pid=5102),
                        replace(self.proof, audio_idle_verified=False),
                        replace(self.proof, admission_marker_held=False),
                        replace(self.proof, http_requests_drained=False),
                        replace(self.proof, job_status_counts={'queued': 1}),
                        replace(self.proof, job_status_counts={'running': 1}),
                        replace(self.proof, job_status_counts={'done': True})):
            with self.subTest(changed=changed), self.assertRaises(Refused):
                self.check(changed)


if __name__ == '__main__':
    unittest.main()
