"""Copy-only native handoff: exit the app after the Python child reports handoff.

The native executable must be rebuilt and signed in an offline repair, after
the entire original app has been backed up and its signature checked.
"""
import hashlib

BASELINE = 'd996f4812cd612241d39dea9595d06903754372e4664b7c1b95ced6deae91b68'
ANCHOR = '                self.openButton.isEnabled = self.dashboardURL != nil\n'
REPLACEMENT = (ANCHOR +
    '                if proc.terminationReason == .exit && proc.terminationStatus == 42 {\n'
    '                    NSApp.terminate(nil)\n'
    '                    return\n'
    '                }\n')


def prepare(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != BASELINE:
        raise ValueError('native_handoff_baseline_changed')
    source = raw.decode('utf-8')
    if source.count(ANCHOR) != 1:
        raise ValueError('native_handoff_anchor_changed')
    return source.replace(ANCHOR, REPLACEMENT, 1).encode('utf-8')
