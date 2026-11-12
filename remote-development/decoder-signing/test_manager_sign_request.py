import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import mac_manager_sign_request as signing
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

    def decoder_task(self):
        task = self.task(action="manager_sign_decoder", candidate_server_sha256=signing.DECODER_SERVER_SHA,
                         source_manifest_sha256="f" * 64)
        task.pop("candidate_dashboard_sha256")
        return task

    def test_decoder_action_is_bound_to_the_reviewed_server_hash(self):
        task = self.decoder_task()
        self.assertEqual(parse_sign_task(task)["schema"], signing.DECODER_GRANT)
        with self.assertRaisesRegex(ValueError, "decoder_unreviewed"):
            parse_sign_task(task | {"candidate_server_sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "task_invalid"):
            parse_sign_task(task | {"candidate_dashboard_sha256": "0" * 64})

    def test_decoder_probe_refuses_wrong_runner_before_executing(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp).resolve()
            work = home / "source-copy"
            path = work / signing.DECODER_TEST
            path.parent.mkdir(parents=True)
            path.write_bytes(b"unreviewed")
            run = Mock()
            grant = parse_sign_task(self.decoder_task())
            def trial(*args, check, **kwargs):
                return {"reviewed_test": check(work, None)}
            with patch.object(signing, "trial_commit", trial), patch.object(signing, "keychain_token", return_value="fixture"), patch.object(signing.subprocess, "run", run):
                with self.assertRaisesRegex(ValueError, "decoder_source_changed"):
                    signing.decoder_copy(home, grant, "a" * 40, b"reviewed")
            run.assert_not_called()

    def test_decoder_probe_uses_only_fixed_test_and_local_model(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp).resolve()
            work = home / "source-copy"
            path = work / signing.DECODER_TEST
            path.parent.mkdir(parents=True)
            path.write_bytes(b"reviewed test")
            candidate = b"reviewed server"
            (work / "rap_brain/server.py").write_bytes(candidate)
            model_path = home / signing.SOURCE / "data/ollama_model.json"
            model_path.parent.mkdir(parents=True)
            config = b'{"model":"qwen3.5:27b"}'
            model_path.write_bytes(config)
            proof = {"real_ollama": "verified", "sqlite_and_config": "preserved"}
            run = Mock(side_effect=[subprocess.CompletedProcess([], 0, b"", b""),
                                    subprocess.CompletedProcess([], 0, json.dumps(proof).encode(), b"")])
            grant = parse_sign_task(self.decoder_task())
            def trial(token, commit, manifest, server, *, fetch, home, check):
                self.assertEqual((token, commit, manifest, server),
                                 ("fixture", "a" * 40, "f" * 64, signing.DECODER_SERVER_SHA))
                return {"reviewed_test": check(work, None)}
            with patch.object(signing, "trial_commit", trial), patch.object(signing, "keychain_token", return_value="fixture"), patch.object(signing, "DECODER_TEST_SHA", sha(path.read_bytes())), patch.object(signing.subprocess, "run", run):
                self.assertEqual(signing.decoder_copy(home, grant, "a" * 40, candidate), proof)
            normal, live = run.call_args_list
            self.assertEqual(normal.args[0][1:], ["-I", "-B", str(path)])
            self.assertEqual(live.args[0][1:], ["-I", "-B", str(path), "--real-ollama", "qwen3.5:27b"])
            self.assertEqual(live.kwargs["env"]["HOME"], str(work))
            self.assertEqual(model_path.read_bytes(), config)


if __name__ == "__main__":
    unittest.main()
