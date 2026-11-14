#!/usr/bin/env python3
"""Run only the reviewed, hash-pinned rhyme tests in a disposable source copy."""

import hashlib
import os
import re
import resource
import subprocess
import sys

from mac_private_source_trial import github_file, trial_commit


COMMIT = "a0b917cf04ee9f4de8852a1fc093c6691f51ca05"
MANIFEST_SHA256 = "31cab964c01d12f7110f398ca710b372beff013b0f459dbded9effc8e9949adf"
SERVER_SHA256 = "4cdab9087a33855e79e8fee5d639cae3489fc7a4399cdc6e0099b15ad8a7e16c"
TEST_SHA256 = "edd08bf9ab19af6ef127707ef03878bad21807d6af48a356c5ef66db73c1a8ab"
MODULE_SHA256 = "e04be3025b47035e68bfe613798a669c0890cdd402299effb51101fb4578be72"
TEST_PATH = "rap_brain/test_rhyme_validator.py"
MODULE_PATH = "rap_brain/rhyme_validator.py"


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def run_reviewed_test(token, home=None, fetch=github_file, call=subprocess.run):
    def check(workspace, manifest):
        indexed = {item["path"]: item["sha256"] for item in manifest}
        if indexed.get(TEST_PATH) != TEST_SHA256 or indexed.get(MODULE_PATH) != MODULE_SHA256:
            raise RuntimeError("Tests revus absents du manifeste")
        for path, expected in ((TEST_PATH, TEST_SHA256), (MODULE_PATH, MODULE_SHA256)):
            if hashlib.sha256((workspace / path).read_bytes()).hexdigest() != expected:
                raise RuntimeError("Code de test différent de la version revue")
        app = workspace / "rap_brain"
        output = workspace / "reviewed-test-output.log"
        environment = {"HOME": str(workspace), "TMPDIR": str(workspace),
                       "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
        command = [sys.executable, "-I", "-B", "-m", "unittest", "discover",
                   "-s", str(app), "-p", "test_rhyme_validator.py", "-q"]
        try:
            with output.open("xb") as stream:
                result = call(command, cwd=app, env=environment, stdin=subprocess.DEVNULL,
                              stdout=stream, stderr=subprocess.STDOUT, timeout=20,
                              check=False, close_fds=True, start_new_session=True,
                              preexec_fn=limits)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Tests revus trop longs ; copie supprimée") from None
        if result.returncode != 0:
            raise RuntimeError("Tests revus échoués ; copie supprimée")
        log = output.read_bytes()[:65537]
        match = re.search(rb"Ran (\d+) tests? in [0-9.]+s\s+OK\b", log)
        if len(log) > 65536 or not match or int(match.group(1)) != 2:
            raise RuntimeError("Rapport des tests revus inattendu")
        return {"status": "pass", "tests_run": 2, "test_sha256": TEST_SHA256,
                "timeout_seconds": 20}

    result = trial_commit(token, COMMIT, MANIFEST_SHA256, SERVER_SHA256,
                          fetch=fetch, home=home, check=check)
    if result.get("reviewed_test", {}).get("status") != "pass":
        raise RuntimeError("Tests revus incomplets")
    return result
