"""Prospective parent-side one-click Creative Engine installation controller.

The Beta 14 HTTP child cannot install or spawn anything; the parent retains
the original Popen handle. This module is not in the installed app and no UI
request calls it yet. It must be bundled by a signed first bootstrap before
the Manager can use it.
"""
import hashlib

from creative_release import Refused, download_release
from creative_transaction import Transaction, safe_path
from owned_guarded_lifecycle import OwnedGuardedLifecycle
from owned_supervisor_binding import bind_owned_launch


def install_owned_creative(source, state, supervisor_state, *, port=8765,
                           downloader=download_release,
                           lifecycle_factory=OwnedGuardedLifecycle,
                           transaction_factory=Transaction):
    """Return one recovery or installation result, never both in one click.

    All production defaults are pinned. Injectable callables are for isolated
    tests only; the Manager integration must call this without overrides.
    """
    source = safe_path(source, directory=True)
    server = safe_path(source / 'server.py')
    server_sha = hashlib.sha256(server.read_bytes()).hexdigest()
    lifecycle = lifecycle_factory(source, state, supervisor_state, server_sha, port=port)
    transaction = transaction_factory(source, state, lifecycle)
    # Recovery after a Manager crash has no retained Popen handle. Its
    # separate stopped-attempt proof authenticates the original ticket and
    # exclusive locks; it must run before fresh-launch ownership checks.
    recovered = transaction.recover()
    if recovered is not None:
        return recovered
    # A fresh install requires the exact child owned by this Manager. Reject
    # an unmanaged server before any network request or code replacement.
    bind_owned_launch(supervisor_state, expected_server_sha256=server_sha)
    # The transaction independently checks the pinned Ed25519 publisher key,
    # sequence, baseline, server hash, backup and stopped-writer proof.
    manifest, archive = downloader()
    return transaction.install(manifest, archive)
