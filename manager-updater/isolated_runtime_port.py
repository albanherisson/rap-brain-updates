"""Adjust only the listening port of an authenticated disposable server copy.

The original candidate remains byte-for-byte unchanged. An unfamiliar port
declaration refuses the rehearsal rather than risking the active port.
"""
import ast

from creative_release import Refused, digest


def disposable_port_copy(candidate, expected_sha256, port):
    if (type(candidate) is not bytes or digest(candidate) != expected_sha256 or
            type(port) is not int or not 1024 <= port <= 65535 or port == 8765):
        raise Refused('isolated_port_input_invalid')
    try:
        source = candidate.decode('utf-8')
        tree = ast.parse(source)
    except (UnicodeError, SyntaxError) as exc:
        raise Refused('isolated_server_invalid') from exc
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == 'PORT']
    if (len(assignments) != 1 or not isinstance(assignments[0].value, ast.Constant) or
            type(assignments[0].value.value) is not int or
            assignments[0].value.value != 8765 or
            assignments[0].lineno != assignments[0].end_lineno):
        raise Refused('isolated_port_declaration_unknown')
    declaration = assignments[0]
    lines = source.splitlines(keepends=True)
    line = lines[declaration.lineno - 1]
    start, end = declaration.value.col_offset, declaration.value.end_col_offset
    if line[start:end] != '8765':
        raise Refused('isolated_port_layout_unknown')
    lines[declaration.lineno - 1] = line[:start] + str(port) + line[end:]
    output = ''.join(lines).encode('utf-8')
    compile(output, 'server.py', 'exec')
    return output
