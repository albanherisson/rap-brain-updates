"""Stage a bounded Python-only source closure for a disposable runtime lab.

No live data, static assets or configuration is copied. This function never
imports or executes staged code and refuses symlinks in its input tree.
"""
import ast
import os
from pathlib import Path
import stat

from creative_release import Refused, digest
from creative_transaction import safe_path


def stage_python_closure(source, target, server_candidate, baseline_sha256):
    source = safe_path(source, directory=True)
    if (type(server_candidate) is not bytes or
            type(baseline_sha256) is not str or len(baseline_sha256) != 64 or
            digest(safe_path(source / 'server.py').read_bytes()) != baseline_sha256):
        raise Refused('isolated_source_baseline_changed')
    target = Path(target).absolute()
    if (target.exists() or os.path.lexists(target) or target.parent.is_symlink() or
            not target.parent.is_dir() or target == source or source in target.parents or
            target in source.parents):
        raise Refused('isolated_target_invalid')
    try:
        compile(server_candidate, 'server.py', 'exec')
        pending = [('server', server_candidate)]
        contents = {'server.py': server_candidate}
        while pending:
            _, raw = pending.pop()
            tree = ast.parse(raw)
            imported = {alias.name.split('.')[0] for node in ast.walk(tree)
                        if isinstance(node, ast.Import) for alias in node.names}
            imported.update(node.module.split('.')[0] for node in ast.walk(tree)
                            if isinstance(node, ast.ImportFrom) and node.module)
            for name in imported:
                if not name.isidentifier():
                    raise Refused('isolated_import_invalid')
                path = source / (name + '.py')
                if not os.path.lexists(path) or path.name in contents:
                    continue
                info = path.lstat()
                if (not stat.S_ISREG(info.st_mode) or info.st_size > 250_000 or
                        len(contents) >= 32):
                    raise Refused('isolated_module_unsafe')
                module = safe_path(path).read_bytes()
                compile(module, path.name, 'exec')
                contents[path.name] = module
                pending.append((name, module))
        target.mkdir(mode=0o700)
        for name, raw in contents.items():
            path = target / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
        return {name: digest(raw) for name, raw in contents.items()}
    except (SyntaxError, UnicodeError) as exc:
        raise Refused('isolated_python_invalid') from exc
