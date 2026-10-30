"""Configure the observed owner's server port without changing its code."""
import ast
from pathlib import Path

from creative_release import Refused, digest


def disposable_environment(candidate, expected_sha256, port, home):
    if (type(candidate) is not bytes or digest(candidate) != expected_sha256 or
            type(port) is not int or not 1024 <= port <= 65535 or port == 8765):
        raise Refused('isolated_port_input_invalid')
    home = Path(home).absolute()
    if (not home.is_dir() or home.is_symlink() or
            any(parent.is_symlink() for parent in home.parents)):
        raise Refused('isolated_home_invalid')
    try:
        tree = ast.parse(candidate)
    except (UnicodeError, SyntaxError) as exc:
        raise Refused('isolated_server_invalid') from exc
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == 'PORT']
    expected = ast.dump(ast.parse("PORT = int(os.getenv('RAP_BRAIN_PORT', '8765'))").body[0].value)
    if len(assignments) != 1 or ast.dump(assignments[0].value) != expected:
        raise Refused('isolated_port_declaration_unknown')
    return {'HOME': str(home), 'RAP_BRAIN_PORT': str(port),
            'PYTHONDONTWRITEBYTECODE': '1'}
