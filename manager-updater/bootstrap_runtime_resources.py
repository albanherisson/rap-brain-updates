"""Exact resources needed by the parent-side Creative installer.

The first signed bootstrap must include these files alongside the guarded
server, launcher and dashboard. This module only validates in-memory members;
it never extracts an archive or writes an application bundle.
"""
from creative_release import Refused, digest


PYTHON_MODULES = (
    'authenticated_runtime_client.py',
    'creative_install_controller.py',
    'creative_readiness.py',
    'creative_release.py',
    'creative_shutdown_policy.py',
    'creative_transaction.py',
    'ed25519_runtime.py',
    'owned_graceful_stop.py',
    'owned_guarded_lifecycle.py',
    'owned_supervisor_binding.py',
    'pending_attempt_recovery.py',
    'prejournal_intent.py',
    'process_group_inventory.py',
    'process_start_identity.py',
    'runtime_evidence.py',
    'strict_json.py',
    'worker_activity_gate.py',
)
RUNTIME_FILES = PYTHON_MODULES + ('verify_ed25519.swift',)


def verify_runtime_resources(members, signed_hashes):
    """Validate a signed bundle's exact flat updater resource inventory."""
    if (type(members) is not dict or members.keys() != set(RUNTIME_FILES) or
            type(signed_hashes) is not dict or signed_hashes.keys() != set(RUNTIME_FILES)):
        raise Refused('bootstrap_runtime_inventory')
    total = 0
    for name in RUNTIME_FILES:
        raw = members[name]
        expected = signed_hashes[name]
        if (type(raw) is not bytes or not 0 < len(raw) <= 250_000 or
                type(expected) is not str or len(expected) != 64 or
                any(c not in '0123456789abcdef' for c in expected) or
                digest(raw) != expected):
            raise Refused('bootstrap_runtime_integrity')
        total += len(raw)
        if name.endswith('.py'):
            try:
                compile(raw, name, 'exec')
            except (SyntaxError, ValueError, UnicodeError) as exc:
                raise Refused('bootstrap_runtime_python_invalid') from exc
        else:
            try:
                text = raw.decode('utf-8')
            except UnicodeError as exc:
                raise Refused('bootstrap_runtime_swift_invalid') from exc
            if ('import CryptoKit' not in text or
                    'isValidSignature(signature, for: message)' not in text):
                raise Refused('bootstrap_runtime_swift_invalid')
    if total > 1_000_000:
        raise Refused('bootstrap_runtime_size')
    return True
