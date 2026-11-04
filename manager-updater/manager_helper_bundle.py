"""Assemble the reviewed external helper from source, without installing it.

This produces an unsigned candidate for a future Manager-key signed
capability release. It never reads the owner's app, database, configuration,
Ollama settings or publisher private key.
"""
import ast
import io
from pathlib import Path
import stat
import zipfile

from build_first_bootstrap_app import dependencies
from creative_release import Refused, digest
from manager_helper_inventory import HELPER_FILES


ROOT = Path(__file__).resolve().parent
ENTRIES = ('manager_update_parent', 'manager_update_helper',
           'manager_update_recovery')
def assemble(root=ROOT):
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise Refused('manager_helper_source_missing')
    closure = {path.name for entry in ENTRIES
               for path in dependencies(root, entry=entry)}
    if closure != set(HELPER_FILES) - {'verify_ed25519.swift'}:
        raise Refused('manager_helper_import_inventory_changed')
    members = {}
    for name in HELPER_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise Refused('manager_helper_source_unsafe')
        raw = path.read_bytes()
        if not 0 < len(raw) <= 250_000:
            raise Refused('manager_helper_member_size')
        if name.endswith('.py'):
            ast.parse(raw, filename=name, feature_version=(3, 10))
        elif (b'import CryptoKit' not in raw or
              b'isValidSignature(signature, for: message)' not in raw):
            raise Refused('manager_helper_verifier_changed')
        members[name] = raw
    if sum(map(len, members.values())) > 1_000_000:
        raise Refused('manager_helper_total_size')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for name in HELPER_FILES:
            info = zipfile.ZipInfo('helper/' + name,
                                   date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(info, members[name],
                             compress_type=zipfile.ZIP_DEFLATED,
                             compresslevel=9)
    raw = buffer.getvalue()
    if len(raw) > 1_000_000:
        raise Refused('manager_helper_archive_size')
    return raw, {name: digest(members[name]) for name in HELPER_FILES}
