"""Build the code-only part of the Manager repair from the published capability.

This output is unsigned and cannot install. The native executable must be
compiled, backed up, signed and tested on macOS in a separate offline gate.
"""
import hashlib
import io
from pathlib import Path
import stat
import zipfile

from manager_helper_inventory import HELPER_FILES
from manager_capability_inventory import APP_CODE_FILES
from manager_handoff_repair_candidate import prepare_helper, prepare_proof
from manager_locale_identity_candidate import prepare as prepare_identity
from manager_native_handoff_candidate import prepare as prepare_native
from manager_repair_candidate import prepare_launcher


CAPABILITY_SHA256 = '963ca5733de48d7d336b1c214a0b8f308aa582aa3484a5ae51769daafe0cf8a7'
HELPER_REPLACEMENTS = {
    'process_start_identity.py': prepare_identity,
    'manager_handoff_proof.py': prepare_proof,
    'manager_update_helper.py': prepare_helper,
}


def _zip(files, mode=0o600):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for name, raw in files.items():
            member = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(member, raw)
    return buffer.getvalue()


def build(capability, native_source):
    raw = Path(capability).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CAPABILITY_SHA256:
        raise ValueError('manager_repair_capability_changed')
    with zipfile.ZipFile(io.BytesIO(raw)) as published:
        if sorted(published.namelist()) != sorted(
                ['helper.zip'] + ['app/' + name for name in APP_CODE_FILES]):
            raise ValueError('manager_repair_capability_layout')
        launcher = prepare_launcher(published.read('app/launch_manager.py'))
        helper = published.read('helper.zip')
    with zipfile.ZipFile(io.BytesIO(helper)) as original:
        if sorted(original.namelist()) != sorted('helper/' + name for name in HELPER_FILES):
            raise ValueError('manager_repair_helper_layout')
        members = {name: original.read('helper/' + name) for name in HELPER_FILES}
    for name, transform in HELPER_REPLACEMENTS.items():
        members[name] = transform(members[name])
    candidate_helper = _zip({'helper/' + k: v for k, v in members.items()})
    native = prepare_native(Path(native_source).read_bytes())
    return {'app/launch_manager.py': launcher,
            'app/RapBrainManagerNative.swift': native,
            'helper.zip': candidate_helper}
