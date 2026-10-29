"""Coordinate a disposable runtime rehearsal without touching live data."""
import os
from pathlib import Path
import tempfile

from creative_release import Refused, digest
from creative_transaction import safe_path
from isolated_runtime_runner import run_disposable
from isolated_runtime_stage import stage_python_closure


def rehearse(source, candidate, baseline_sha256, candidate_sha256, *,
             workspace, runner=run_disposable):
    source = safe_path(source, directory=True)
    workspace = safe_path(workspace, directory=True)
    if (type(candidate) is not bytes or digest(candidate) != candidate_sha256 or
            source == workspace or source in workspace.parents or
            workspace in source.parents):
        raise Refused('isolated_rehearsal_input_invalid')
    original = safe_path(source / 'server.py').read_bytes()
    if digest(original) != baseline_sha256:
        raise Refused('isolated_baseline_changed')
    with tempfile.TemporaryDirectory(prefix='rapbrain-runtime-lab-', dir=workspace) as folder:
        home = Path(folder) / 'home'
        target = home / 'Downloads' / 'rap-brain'
        target.parent.mkdir(parents=True, mode=0o700)
        inventory = stage_python_closure(source, target, candidate, baseline_sha256)
        if inventory['server.py'] != candidate_sha256 or os.path.lexists(target / 'data'):
            raise Refused('isolated_stage_changed')
        result = runner(target, home, candidate_sha256)
        if (result.get('status_ok') is not True or
                digest(safe_path(source / 'server.py').read_bytes()) != baseline_sha256):
            raise Refused('isolated_runtime_or_baseline_changed')
        return {'isolated_health': True, 'original_server_unchanged': True,
                'modules_staged': len(inventory)}
