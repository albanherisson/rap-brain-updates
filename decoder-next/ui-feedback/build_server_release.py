"""Build a server-only signed-release candidate with a checked UI response.

The installed static/app.js remains untouched. The server serves reviewed UI
bytes only when that installed resource matches the exact owner-supplied hash.
"""
from difflib import SequenceMatcher
import hashlib
from pathlib import Path


HERE = Path(__file__).resolve().parent
SERVER = HERE.parent / 'server.py'
ORIGINAL_UI = HERE / 'app-original.js'
UPDATED_UI = HERE / 'app.js'
BASE_SERVER = '8e790b1a8e008afa7e6715807ee55184f327d51a50445aab8ca67f6f41efdf17'
BASE_UI = '3fdd85c514dbd5d0625b1c592682d9299c6c8394c30330b128d0462d841327c8'
UPDATED_UI_HASH = '7735df3d917005673708b7706794dea30e92b756da1ce9f500e0a3489e6bb7ea'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build(server, original_ui, updated_ui):
    if (digest(server) != BASE_SERVER or digest(original_ui) != BASE_UI or
            digest(updated_ui) != UPDATED_UI_HASH):
        raise ValueError('reviewed_input_changed')
    original = original_ui.decode('utf-8').splitlines(keepends=True)
    updated = updated_ui.decode('utf-8').splitlines(keepends=True)
    changes = []
    for tag, start, end, new_start, new_end in SequenceMatcher(
            None, original, updated, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        before = ''.join(original[start:end])
        after = ''.join(updated[new_start:new_end])
        if not before:
            # An insertion is anchored to the following complete source line.
            before = original[start]
            after += before
        if ''.join(original).count(before) != 1:
            raise ValueError('ui_patch_anchor_ambiguous')
        changes.append((before, after))
    block = ("\n# Signed server-only response for the reviewed Library/Lexicon UI repair.\n"
             "# static/app.js is read and checked, never replaced by this release.\n"
             f"_UI_BASE_SHA256 = {BASE_UI!r}\n"
             f"_UI_RELEASE_SHA256 = {UPDATED_UI_HASH!r}\n"
             "_UI_PATCHES = (\n" + ''.join(f'    ({a!r}, {b!r}),\n' for a, b in changes) +
             ")\n\n"
             "def _reviewed_ui(raw):\n"
             " if hashlib.sha256(raw).hexdigest() != _UI_BASE_SHA256:\n"
             "  raise ValueError('Installed interface changed; signed UI response refused')\n"
             " text=raw.decode('utf-8')\n"
             " for before,after in _UI_PATCHES:\n"
             "  if text.count(before)!=1:raise ValueError('UI patch anchor changed')\n"
             "  text=text.replace(before,after,1)\n"
             " output=text.encode('utf-8')\n"
             " if hashlib.sha256(output).hexdigest()!=_UI_RELEASE_SHA256:\n"
             "  raise ValueError('UI response digest changed')\n"
             " return output\n")
    text = server.decode('utf-8')
    anchor = 'MAX_BODY=8*1024*1024\n'
    if text.count(anchor) != 1:
        raise ValueError('server_insert_anchor_changed')
    text = text.replace(anchor, anchor + block, 1)
    old = "  b=path.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)"
    new = "  b=path.read_bytes()\n  if p.path=='/app.js':\n   try:b=_reviewed_ui(b)\n   except ValueError:self.send_error(409,'Signed UI baseline changed');return\n  self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b)"
    if text.count(old) != 1:
        raise ValueError('server_route_anchor_changed')
    text = text.replace(old, new, 1)
    candidate = text.encode('utf-8')
    compile(candidate, 'server.py', 'exec')
    namespace = {'hashlib': hashlib}
    exec(block + '\n', namespace)
    if namespace['_reviewed_ui'](original_ui) != updated_ui:
        raise ValueError('ui_response_mismatch')
    return candidate


if __name__ == '__main__':
    result = build(SERVER.read_bytes(), ORIGINAL_UI.read_bytes(), UPDATED_UI.read_bytes())
    target = HERE / 'server-release.py'
    if target.exists():
        raise ValueError('candidate_already_exists')
    target.write_bytes(result)
    print('SERVER_UI_CANDIDATE:', digest(result), len(result))
