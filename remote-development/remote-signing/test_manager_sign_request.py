import json
import time
import unittest
from unittest.mock import Mock

from mac_manager_sign_request import authorize, candidate_notice, parse_sign_task, run_sign_task, sha


class RemoteSignerTest(unittest.TestCase):
    def task(self, archive=b"archive", **changes):
        now = int(time.time())
        return {"schema": "rapbrain-remote-task-v4", "action": "manager_sign_dashboard",
                "id": "sign-19", "sequence": 19, "authorization_commit": "a" * 40,
                "archive_sha256": sha(archive), "candidate_dashboard_sha256": "b" * 64,
                "baseline_dashboard_sha256": "c" * 64, "stable_manifest_sha256": "d" * 64,
                "expected_server_sha256": "e" * 64, "issued_at": now - 1,
                "expires_at": now + 600, **changes}

    def test_private_authorization_must_match_before_downloading_candidate(self):
        task = self.task()
        grant = parse_sign_task(task)
        fetch = Mock(return_value=json.dumps(grant | {"sequence": 20}).encode())
        with self.assertRaisesRegex(ValueError, "private_authorization_mismatch"):
            authorize(task, grant, token=lambda: "test-token", fetch=fetch)
        fetch.assert_called_once_with("remote-development/manager-signing/sign-19/authorization.json",
                                      "test-token", "a" * 40)

    def test_candidate_hash_is_checked_and_never_signed_if_different(self):
        task = self.task()
        grant = parse_sign_task(task)
        fetch = Mock(side_effect=[json.dumps(grant).encode(), b"changed"])
        signer = Mock()
        result = run_sign_task(task, authorize_candidate=lambda a, b: authorize(
            a, b, token=lambda: "test-token", fetch=fetch), sign=signer)
        self.assertEqual(result, {"state": "refused", "reason": "manager_sign_archive_hash_changed"})
        signer.assert_not_called()

    def test_expired_or_extra_action_is_terminal_without_signing(self):
        now = int(time.time())
        expired = self.task(issued_at=now-120, expires_at=now-10)
        accept = Mock()
        self.assertEqual(run_sign_task(expired, authorize_candidate=accept),
                         {"state": "refused", "reason": "manager_sign_task_expired"})
        self.assertEqual(parse_sign_task(expired, allow_expired=True)["sequence"], 19)
        self.assertEqual(run_sign_task(self.task(command="whoami"), authorize_candidate=accept)["state"], "refused")
        accept.assert_not_called()

    def test_only_success_notice_text_can_change(self):
        old = "['committed',['Mise à jour installée','Contrôle réussi.','yes']]".encode()
        good = old.replace("Contrôle réussi.".encode(), "Contrôle terminé.".encode())
        candidate_notice(old, good)
        for other in (good+b"<script>", old, old.replace(b"yes", b"warn"),
                      old.replace("Contrôle réussi.".encode(), b"';alert(1)//")):
            with self.subTest(other=other), self.assertRaisesRegex(ValueError, "notice_scope"):
                candidate_notice(old, other)


if __name__ == "__main__":
    unittest.main()
