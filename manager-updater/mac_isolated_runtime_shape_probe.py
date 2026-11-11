#!/usr/bin/env python3
"""Read-only owner check of port and import shape for a future isolated lab.

No server import, database access, process start, or active-file write.
"""
import ast
import hashlib
from pathlib import Path
import stat
import sys


SOURCE = Path.home() / 'Downloads' / 'rap-brain' / 'server.py'
EXPECTED = '4380ab4fd97d727ced4521eb66b11004e21f9f15c0eafaee955f1f0145913ad7'


def inspect(source):
    tree = ast.parse(source)
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'PORT'
                           for target in node.targets)]
    if len(assignments) != 1:
        raise ValueError('port_shape_unknown')
    value = assignments[0].value
    shape = ast.dump(value, include_attributes=False)
    if len(shape) > 250:
        shape = shape[:250] + '...'
    imports = sorted({alias.name.split('.')[0] for node in ast.walk(tree)
                      if isinstance(node, ast.Import) for alias in node.names} |
                     {node.module.split('.')[0] for node in ast.walk(tree)
                      if isinstance(node, ast.ImportFrom) and node.module})
    return shape, imports


def main():
    if sys.platform != 'darwin' or any(p.is_symlink() for p in (SOURCE, *SOURCE.parents)):
        raise ValueError('mac_source_path_refused')
    info = SOURCE.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 200_000:
        raise ValueError('source_size_refused')
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED:
        raise ValueError('source_fingerprint_changed')
    shape, imports = inspect(raw)
    print('FORME DU SERVEUR EN LECTURE SEULE : OK')
    print('PORT : ' + shape)
    print('Imports : ' + ', '.join(imports))
    print('Aucun fichier modifié. Aucune base ouverte. Aucun serveur lancé.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('CONTROLE REFUSE : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'validation_failed'),
              file=sys.stderr)
        raise SystemExit(2)
