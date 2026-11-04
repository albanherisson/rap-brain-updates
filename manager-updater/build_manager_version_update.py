"""Build one code-only Manager update from the exact published capability.

This is an unsigned candidate. Publication requires the owner's Manager key
and a separate macOS copy installation/rollback gate.
"""
import hashlib
import io
from pathlib import Path
import stat
import zipfile

from manager_version_label_candidate import prepare_launcher


CAPABILITY_SHA256 = '963ca5733de48d7d336b1c214a0b8f308aa582aa3484a5ae51769daafe0cf8a7'
UPDATE_SHA256 = 'eee67d2a0902fc308dadefa33cdc3deea294ce2862e0ee61b09856d1868b9cf1'
NAME = 'app/launch_manager.py'


def build(capability):
    raw = Path(capability).read_bytes()
    if hashlib.sha256(raw).hexdigest() != CAPABILITY_SHA256:
        raise ValueError('manager_version_capability_changed')
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        baseline = source.read(NAME)
    candidate = prepare_launcher(baseline)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        member = zipfile.ZipInfo(NAME, (1980, 1, 1, 0, 0, 0))
        member.create_system = 3
        member.compress_type = zipfile.ZIP_DEFLATED
        member.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(member, candidate)
    package = output.getvalue()
    if hashlib.sha256(package).hexdigest() != UPDATE_SHA256:
        raise ValueError('manager_version_update_changed')
    return package


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3:
        raise SystemExit('Usage: build_manager_version_update.py CAPABILITY_ZIP OUTPUT_ZIP')
    destination = Path(sys.argv[2])
    if destination.exists() or destination.is_symlink():
        raise SystemExit('Candidate already exists')
    package = build(sys.argv[1])
    destination.write_bytes(package)
    print(hashlib.sha256(package).hexdigest(), len(package))
