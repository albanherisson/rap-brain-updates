#!/usr/bin/env python3
"""Read-only isolated Ollama test of the pinned Creative Engine candidate.

No Rap Brain server, database, library, chat history or app is started or
modified. The selected model is read from the existing config without writing.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import types
import urllib.request


COMMIT = 'cda3a5e690d733577eeb089f1b6844a0d9f56d57'
URL = ('https://raw.githubusercontent.com/albanherisson/rap-brain-updates/' +
       COMMIT + '/creative-next/creative_engine.py')
CANDIDATE_SHA256 = '7b565b30526c37ee1cf18798329841c308d8df2cadaa9536b75b36eaa1ea40e5'
ACTIVE_SHA256 = 'b770bdf034caa600f75497325f80759d4f372258fa0e911e28f29d214abe85f3'
RHYME_SHA256 = 'e04be3025b47035e68bfe613798a669c0890cdd402299effb51101fb4578be72'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError('download_redirect_refused')


def read_candidate():
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(urllib.request.Request(URL, headers={'Accept-Encoding': 'identity'}),
                     timeout=20) as response:
        if response.status != 200 or response.geturl() != URL:
            raise ValueError('candidate_url_changed')
        raw = response.read(40_001)
    if not 0 < len(raw) <= 40_000 or hashlib.sha256(raw).hexdigest() != CANDIDATE_SHA256:
        raise ValueError('candidate_hash_mismatch')
    return raw


def selected_model(source):
    path = source / 'data' / 'ollama_model.json'
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_size > 512:
            raise ValueError('model_configuration_size')
        value = json.loads(os.read(fd, 513))
    finally:
        os.close(fd)
    model = value.get('model') if isinstance(value, dict) else None
    if not isinstance(model, str) or not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,120}', model):
        raise ValueError('model_configuration_invalid')
    return model


def run():
    if sys.platform != 'darwin':
        raise ValueError('macos_required')
    source = Path.home() / 'Downloads' / 'rap-brain'
    engine = source / 'creative_engine.py'
    if source.is_symlink() or engine.is_symlink() or not engine.is_file():
        raise ValueError('active_engine_missing')
    if hashlib.sha256(engine.read_bytes()).hexdigest() != ACTIVE_SHA256:
        raise ValueError('active_engine_baseline_changed')
    rhyme = source / 'rhyme_validator.py'
    if (rhyme.is_symlink() or not rhyme.is_file() or
            hashlib.sha256(rhyme.read_bytes()).hexdigest() != RHYME_SHA256):
        raise ValueError('rhyme_validator_baseline_changed')
    model = selected_model(source)
    raw = read_candidate()
    sys.path.insert(0, str(source))  # Existing offline rhyme validator only.
    module = types.ModuleType('creative_candidate')
    exec(compile(raw, 'verified_creative_candidate.py', 'exec'), module.__dict__)
    count = 0
    def llm(messages, predict, timeout):
        nonlocal count
        count += 1
        print('Étape modèle ' + str(count) + ' en cours…', flush=True)
        data = json.dumps({'model': model, 'messages': messages, 'stream': False,
            'options': {'num_predict': predict, 'temperature': 0.55}},
            ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request('http://127.0.0.1:11434/api/chat',
            data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
        return result['message']['content']
    began = time.monotonic()
    output = module.generate('Écris 4 lignes originales en anglais. Scène : un message '
        'que je n’ai jamais envoyé après une dispute. Voix parlée, images concrètes, '
        'sans forcer les rimes. Retourne uniquement les lignes.', [], [], llm, 360)
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) != 4:
        raise ValueError('candidate_bar_count_' + str(len(lines)))
    print('TEST CREATIVE ISOLE : OK', flush=True)
    print('Modèle : ' + model + ' ; lignes : ' + str(len(lines)) +
          ' ; durée : ' + str(round(time.monotonic()-began)) + ' s', flush=True)
    print('--- LIGNES DE TEST ---\n' + output + '\n--- FIN ---', flush=True)
    print('Aucun fichier Rap Brain, aucune base ni analyse modifiés.', flush=True)


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print('TEST REFUSÉ : ' + type(exc).__name__ + ' / ' +
              (str(exc) if isinstance(exc, ValueError) else 'validation_failed'),
              file=sys.stderr)
        raise SystemExit(2)
