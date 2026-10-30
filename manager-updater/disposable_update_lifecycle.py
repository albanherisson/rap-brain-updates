"""Real subprocess lifecycle for *disposable fixtures only*.

Connects the transaction to owned_child_supervisor_lab for an integration test.
It deliberately refuses an installed Rap Brain directory, arbitrary PID and
unowned processes. It is not the production adapter.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib

from owned_child_supervisor_lab import OwnedChild, CHILD
from creative_release import Refused

MARKER = b'RAPBRAIN_DISPOSABLE_UPDATE_V1\n'


class DisposableLifecycle:
    def __init__(self, root, original, candidate, *, fail_new_health=False):
        self.root = Path(root).resolve()
        if (self.root.name != 'DisposableProcessFixture'
                or self.root.joinpath('fixture.marker').is_symlink()
                or self.root.joinpath('fixture.marker').read_bytes() != MARKER
                or self.root.joinpath('owned_child.py').is_symlink()
                or self.root.joinpath('owned_child.py').read_bytes() != CHILD.encode()):
            raise Refused('disposable_fixture_required')
        self.child = OwnedChild()
        self.original = hashlib.sha256(original).hexdigest()
        self.candidate = hashlib.sha256(candidate).hexdigest()
        self.fail_new_health = fail_new_health
        self.start_and_check()

    @contextmanager
    def maintenance(self, source):
        if Path(source).resolve() != self.root:
            raise Refused('different_fixture')
        self.child.stop()
        try:
            yield self
        finally:
            # In a real adapter this is a durable admission gate; a failed
            # fixture transaction must not leave an accidentally running child.
            self.child.stop()

    def assert_stopped(self):
        if self.child.process is not None:
            raise Refused('child_still_running')

    def stop_candidate(self):
        self.child.stop()

    def start_and_check(self):
        digest = hashlib.sha256((self.root / 'creative_engine.py').read_bytes()).hexdigest()
        if digest not in (self.original, self.candidate):
            raise Refused('unexpected_engine')
        is_new = digest == self.candidate
        self.child.start(self.root / 'owned_child.py', 'new' if is_new else 'old')
        return not (is_new and self.fail_new_health)
