#!/usr/bin/env python3
"""Read server.py as text, redact literals, copy structure for lifecycle review.

Never imports/runs server.py, never opens data, never changes source files.
No file output. On macOS copies the redacted text to the clipboard; otherwise
prints it. All comments, docstrings and literal values are removed except an
explicit small vocabulary of lifecycle labels, routes and booleans/None.
This intentionally cannot be executed as a replacement server.py.
"""
import ast
import hashlib
from pathlib import Path
import subprocess
import sys

SAFE_LABELS = {'running', 'queued', 'pending', 'paused', 'completed', 'failed',
               'cancelled', 'idle', 'status', 'state', 'jobs', 'id', 'model',
               '__main__', 'GET', 'POST', '/api/status', '/api/jobs',
               '127.0.0.1', 'localhost'}


class Redact(ast.NodeTransformer):
    def visit_Constant(self, node):
        if node.value is None or type(node.value) is bool:
            return node
        if type(node.value) is str and node.value in SAFE_LABELS:
            return node
        return ast.copy_location(ast.Constant(value='<literal removed>'), node)

    def visit_Module(self, node):
        node.body = self.strip_doc(node.body)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node):
        node.body = self.strip_doc(node.body)
        node.type_comment = None
        return self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    @staticmethod
    def strip_doc(body):
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body = body[1:]
        return body or [ast.Pass()]


def structural_text(raw):
    tree = ast.parse(raw)
    tree = Redact().visit(tree)
    ast.fix_missing_locations(tree)
    return ('RAP BRAIN — STRUCTURE DU SERVEUR (littéraux masqués, non exécutable)\n'
            'SHA256 source: ' + hashlib.sha256(raw).hexdigest() + '\n\n' + ast.unparse(tree))


def main():
    path = Path.home() / 'Downloads' / 'rap-brain' / 'server.py'
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file() or path.stat().st_size > 1_000_000:
        raise SystemExit('Lecture refusée : server.py absent, trop volumineux ou lien symbolique.')
    output = structural_text(path.read_bytes())
    if sys.platform == 'darwin':
        subprocess.run(['/usr/bin/pbcopy'], input=output.encode(), check=True, timeout=10)
        print('Structure masquée copiée. Colle-la dans la conversation avec Cmd+V.\n'
              'Aucun fichier modifié. Aucune base ouverte. Serveur non exécuté.')
    else:
        print(output)


if __name__ == '__main__':
    main()
