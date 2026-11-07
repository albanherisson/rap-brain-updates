#!/usr/bin/env python3
"""Validate the signed P8 engine with real Ollama on a disposable server.

Read only the four pinned active code files and the existing P8 test ZIP. The
model sees invented evidence in a private SQLite fixture, never the library.
No live process, database, Ollama configuration or app bundle is modified.
"""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import zipfile


MODEL = 'qwen3.5:27b'
BASE = Path.home() / 'Downloads'
SOURCE = BASE / 'rap-brain'
PACKAGE = BASE / 'RapBrain_CreativeEngine_P8_Signed_Candidate.zip'
EXPECTED = {
    'server.py': 'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27',
    'creative_engine.py': 'd68a0d8c175e533a84a16c0b9a5f922d51199be68a291cc0d1e32eac79938a0d',
    'creative_rag.py': 'd43f521c43658fce6b3a7de0463efc3fe4d783c6e02b74a5ccd8266a7d35bfca',
    'rhyme_validator.py': 'e04be3025b47035e68bfe613798a669c0890cdd402299effb51101fb4578be72',
}
CANDIDATE = 'b770bdf034caa600f75497325f80759d4f372258fa0e911e28f29d214abe85f3'
CREATIVE_PIN = 'ae32610121418b50adcc8726df567a22ed7b3af67f804ef9aaaa7a1a4efce504'
BEFORE_SERVER = '4380ab4fd97d727ced4521eb66b11004e21f9f15c0eafaee955f1f0145913ad7'
SWIFT_VERIFY = '''import Foundation
import CryptoKit
let args = CommandLine.arguments
guard args.count == 4, let pub = Data(base64Encoded: args[1]),
  let sig = Data(base64Encoded: args[2]), pub.count == 32, sig.count == 64,
  let key = try? Curve25519.Signing.PublicKey(rawRepresentation: pub),
  let data = try? Data(contentsOf: URL(fileURLWithPath: args[3])),
  key.isValidSignature(sig, for: data) else { exit(2) }
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned_file(path, expected, limit=250_000):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('active_source_symlink')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise ValueError('active_source_size')
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError('active_source_changed_' + path.name)
    return raw


def verify_signature(public, signature, message, folder):
    if len(public) != 32 or len(signature) != 64 or len(message) > 4096:
        raise ValueError('p8_signature_format')
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ModuleNotFoundError:
        target = folder / 'signed-message.json'
        target.write_bytes(message)
        try:
            result = subprocess.run(['/usr/bin/swift', '-e', SWIFT_VERIFY,
                base64.b64encode(public).decode('ascii'),
                base64.b64encode(signature).decode('ascii'), str(target)],
                capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        finally:
            target.unlink(missing_ok=True)
        if result.returncode or result.stdout or result.stderr:
            raise ValueError('p8_signature_invalid')
    else:
        Ed25519PublicKey.from_public_bytes(public).verify(signature, message)


def signed_candidate(folder):
    if PACKAGE.is_symlink() or not PACKAGE.is_file() or PACKAGE.stat().st_size > 100_000:
        raise ValueError('p8_package_missing_or_unsafe')
    with zipfile.ZipFile(PACKAGE) as archive:
        entries = archive.infolist()
        if (len(entries) != 2 or sorted(i.filename for i in entries) !=
                ['creative_engine.py', 'signed_manifest.json'] or
                any(i.flag_bits & 1 or i.is_dir() or i.file_size > 100_000 or
                    i.compress_size > 100_000 for i in entries)):
            raise ValueError('p8_archive_layout')
        candidate = archive.read('creative_engine.py')
        manifest = archive.read('signed_manifest.json')
    envelope = json.loads(manifest)
    if (type(envelope) is not dict or envelope.keys() !=
            {'signed_payload', 'signature_algorithm', 'signature_base64', 'public_key_base64'} or
            envelope['signature_algorithm'] != 'Ed25519'):
        raise ValueError('p8_envelope_invalid')
    signed = envelope['signed_payload']
    if (type(signed) is not dict or signed.get('schema') !=
            'rapbrain-creative-engine-signed-candidate-v1' or
            signed.get('component') != 'creative_engine' or
            signed.get('target') != 'creative_engine.py' or
            signed.get('production_install_authorized') is not False or
            signed.get('publisher_public_key_sha256') != CREATIVE_PIN or
            signed.get('baseline_sha256') != EXPECTED['creative_engine.py'] or
            signed.get('required_server_sha256') != BEFORE_SERVER or
            signed.get('payload_sha256') != CANDIDATE or sha(candidate) != CANDIDATE):
        raise ValueError('p8_identity_changed')
    public = base64.b64decode(envelope['public_key_base64'], validate=True)
    signature = base64.b64decode(envelope['signature_base64'], validate=True)
    if sha(public) != CREATIVE_PIN:
        raise ValueError('p8_publisher_changed')
    message = json.dumps(signed, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False).encode()
    verify_signature(public, signature, message, folder)
    compile(candidate, 'creative_engine.py', 'exec')
    return candidate


def own_listener(port, pid):
    result = subprocess.run(['/usr/sbin/lsof', '-nP', '-iTCP:' + str(port),
        '-sTCP:LISTEN', '-Fp'], capture_output=True, text=True,
        timeout=5, stdin=subprocess.DEVNULL)
    lines = result.stdout.splitlines()
    pids = [int(line[1:]) for line in lines if re.fullmatch(r'p[0-9]+', line)]
    if (result.returncode or result.stderr or len(result.stdout) > 4096 or
            any(not re.fullmatch(r'(?:p[0-9]+|f[0-9]+[a-zA-Z]?)', line) for line in lines) or
            pids != [pid]):
        raise ValueError('isolated_listener_not_owned')


def request(port, method, path, body=None, timeout=3):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    try:
        data = json.dumps(body).encode() if body is not None else None
        connection.request(method, path, body=data,
                           headers={'Content-Type': 'application/json'} if data else {})
        response = connection.getresponse()
        raw = response.read(65_537)
        if response.status != 200 or len(raw) > 65_536:
            raise ValueError('isolated_http_' + str(response.status))
        return json.loads(raw)
    finally:
        connection.close()


def seed_fixture(source):
    with sqlite3.connect(source / 'data' / 'rapbrain.sqlite3') as db:
        track = db.execute("INSERT INTO tracks(artist,title,lyrics) VALUES(?,?,?)",
                           ('Synthetic Fixture', 'Lighthouse Paper Map', '')).lastrowid
        content = 'Synthetic decoder fixture\n' + json.dumps([{'line': 1,
            'techniques': 'A lighthouse scene uses a paper map as a concrete setup, then a decision as payoff.',
            'writing_lesson': 'Keep the lighthouse image consistent across a short four-bar sequence.'}])
        db.execute('INSERT INTO analyses(track_id,kind,content,model) VALUES(?,?,?,?)',
                   (track, 'lyric_decoder_lines', content, 'synthetic-only'))


def check_answer(result):
    if type(result) is not dict or type(result.get('answer')) is not str:
        raise ValueError('creative_answer_missing')
    bars = [line.strip() for line in result['answer'].splitlines() if line.strip()]
    if len(bars) != 4 or any(len(re.findall(r'[A-Za-z]+', line)) < 4 for line in bars):
        raise ValueError('creative_wrong_bar_count_' + str(len(bars)))
    sources = result.get('rag_sources')
    if (type(sources) is not list or not any(type(s) is dict and
            s.get('artist') == 'Synthetic Fixture' for s in sources)):
        raise ValueError('creative_synthetic_rag_missing')
    return len(bars), len(sources)


def port_available():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    if port == 8765 or port < 1024:
        raise ValueError('isolated_port_invalid')
    return port


def server_python():
    if (3, 10) <= sys.version_info[:2] < (4, 0):
        return sys.executable
    for candidate in ('/opt/homebrew/bin/python3', '/usr/local/bin/python3',
                      '/Library/Frameworks/Python.framework/Versions/Current/bin/python3',
                      '/usr/bin/python3'):
        if not Path(candidate).is_file():
            continue
        result = subprocess.run([candidate, '-c',
            'import sys; raise SystemExit(not ((3, 10) <= sys.version_info[:2] < (4, 0)))'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=5)
        if result.returncode == 0:
            return candidate
    raise ValueError('python_3_10_required')


def run_isolated(source, home, *, ollama_url='http://127.0.0.1:11434',
                 listener_check=own_listener):
    if not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}', ollama_url):
        raise ValueError('ollama_endpoint_not_loopback')
    port = port_available()
    env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C',
           'HOME': str(home), 'RAP_BRAIN_PORT': str(port),
           'PYTHONDONTWRITEBYTECODE': '1', 'OLLAMA_URL': ollama_url}
    child = subprocess.Popen([server_python(), '-B', '-u', str(source / 'server.py')],
        cwd=source, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if child.poll() is not None:
                error = child.stderr.read(16_384).decode('utf-8', 'replace')
                known = re.search(r'(update_guard_unsafe_directory|'
                    r'update_guard_private_directory_required|update_in_progress|'
                    r'bootstrap_recovery_required|update_recovery_required|'
                    r'ModuleNotFoundError|SyntaxError)', error)
                raise ValueError('isolated_server_exited' +
                                 ('_' + known.group(1) if known else ''))
            try:
                listener_check(port, child.pid)
                status = request(port, 'GET', '/api/status')
                listener_check(port, child.pid)
                if type(status) is not dict:
                    raise ValueError('isolated_health_invalid')
                break
            except (OSError, http.client.HTTPException, ValueError) as exc:
                if isinstance(exc, ValueError) and str(exc) not in ('isolated_listener_not_owned',):
                    raise
                time.sleep(.1)
        else:
            raise ValueError('isolated_health_timeout')
        seed_fixture(source)
        listener_check(port, child.pid)
        answer = request(port, 'POST', '/api/chat',
                         {'message': 'Write exactly 4 bars about a lighthouse and a paper map. Keep the story coherent.'},
                         timeout=900)
        listener_check(port, child.pid)
        return check_answer(answer)
    finally:
        if child.poll() is None:
            if os.getpgid(child.pid) != child.pid:
                raise ValueError('isolated_process_group_changed')
            os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if child.poll() is None and os.getpgid(child.pid) == child.pid:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)
        child.stderr.close()


def main():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    if BASE.is_symlink() or not BASE.is_dir():
        raise ValueError('downloads_invalid')
    original = {name: pinned_file(SOURCE / name, expected)
                for name, expected in EXPECTED.items()}
    with tempfile.TemporaryDirectory(prefix='rapbrain-p9-isolated-') as tmp:
        # macOS exposes its temporary directory through /var -> /private/var.
        # The installed server's symlink guard requires the canonical path.
        root = Path(tmp).resolve(strict=True)
        candidate = signed_candidate(root)
        home = root / 'home'
        stage = home / 'Downloads' / 'rap-brain'
        stage.mkdir(parents=True, mode=0o700)
        for name, raw in original.items():
            (stage / name).write_bytes(candidate if name == 'creative_engine.py' else raw)
        data = stage / 'data'
        data.mkdir(mode=0o700)
        (data / 'ollama_model.json').write_text(json.dumps({'model': MODEL}))
        bars, evidence = run_isolated(stage, home)
    if any(pinned_file(SOURCE / name, sha0) != original[name]
           for name, sha0 in EXPECTED.items()):
        raise ValueError('live_source_changed_during_probe')
    print('P9 CREATIVE + OLLAMA SUR COPIE : OK')
    print('4 lignes produites ; preuve RAG synthétique consultée : ' + str(evidence))
    print('Serveur de copie arrêté. Bibliothèque, SQLite et configuration Ollama actives non ouvertes.')
    print('Aucune installation effectuée.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        detail = str(exc) if isinstance(exc, ValueError) else 'verification_failed'
        print('P9 REFUSE : ' + type(exc).__name__ + ' / ' + detail, file=sys.stderr)
        raise SystemExit(2)
