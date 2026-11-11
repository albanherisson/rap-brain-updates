#!/usr/bin/env python3
"""Read-only, compact worker contract for safe update integration.

Parse source text only. Extract database job SQL with SQL literals removed,
and small state/route constants from selected worker/HTTP functions. Never
imports the server, accesses SQLite, or prints free-form source literals.
"""
import ast
import hashlib
from pathlib import Path
import re
import subprocess
import sys

FUNCTIONS = {'init', 'resume_jobs', 'job_runner', 'worker_main', 'supervise_worker',
             'audio_status', 'audio_start', 'audio_stop', 'do_GET', 'do_POST'}
SAFE_WORD = re.compile(r'^[a-z][a-z0-9_-]{0,23}$')
SQL_START = re.compile(r'^\s*(?:SELECT|UPDATE|INSERT|CREATE\s+TABLE|ALTER\s+TABLE|PRAGMA)', re.I)
SQL_STRINGS = re.compile(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"")
SQL_COMMENTS = re.compile(r'--[^\n]*|/\*[\s\S]*?\*/')


def contract(raw):
    tree = ast.parse(raw)
    parts = ['RAP BRAIN — CONTRAT DU WORKER (lecture seule, valeurs libres masquées)',
             'SHA256 source: ' + hashlib.sha256(raw).hexdigest()]
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in FUNCTIONS:
            continue
        parts.append('\n' + node.name + ':')
        statements = list(ast.walk(node))
        sql_seen = set()
        labels = set()
        routes = set()
        for item in statements:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                continue
            value = item.value
            if SQL_START.match(value) and re.search(r'\b(?:job|analys|worker|audio|queue)\w*\b', value, re.I):
                clean = SQL_COMMENTS.sub('', value)
                clean = SQL_STRINGS.sub("'? '".replace(' ', ''), clean)
                clean = ' '.join(clean.split())
                if len(clean) <= 450 and not re.search(r'[^\x20-\x7e]', clean):
                    sql_seen.add(clean)
            elif value in {'/api/jobs', '/api/status'}:
                routes.add(value)
            elif SAFE_WORD.fullmatch(value) and value in {
                'queued', 'pending', 'running', 'processing', 'in-progress',
                'done', 'completed', 'finished', 'failed', 'error', 'paused',
                'cancelled', 'stopped', 'idle', 'retry', 'interrupted', 'status'}:
                labels.add(value)
        parts.append('states: ' + ', '.join(sorted(labels)))
        parts.append('routes: ' + ', '.join(sorted(routes)))
        parts.extend('SQL: ' + item for item in sorted(sql_seen))
        parts.append('calls: ' + ', '.join(sorted({item.func.id for item in statements
                    if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
                    and item.func.id in {'job_runner', 'resume_jobs', 'init', 'rows',
                                          'audio_status', 'audio_start', 'audio_stop'}})))
    return '\n'.join(parts) + '\n'


def main():
    path = Path.home() / 'Downloads' / 'rap-brain' / 'server.py'
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file() or path.stat().st_size > 1_000_000:
        raise SystemExit('server.py absent ou chemin non sûr.')
    result = contract(path.read_bytes())
    if sys.platform == 'darwin':
        subprocess.run(['/usr/bin/pbcopy'], input=result.encode(), timeout=10, check=True)
        print('Relevé court copié. Reviens dans ChatGPT et colle-le dans la zone de message.')
    else:
        print(result)


if __name__ == '__main__':
    main()
