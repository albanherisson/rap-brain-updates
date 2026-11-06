#!/usr/bin/env python3
"""Read-only Mac gate for the pinned Lyric Decoder candidate, using invented lyrics."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unicodedata
import urllib.parse
import urllib.request


REPOSITORY = 'https://raw.githubusercontent.com/albanherisson/rap-brain-updates/'
COMMIT = 'c618608182df6b8c8f408786ad6c17df0c90e85b'
CANDIDATE_SHA256 = '0e156174f245423ba90188a66f47ee33dfb03fcd7567cfcd44d86e0221087464'
BASELINE_SHA256 = 'e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27'
SYNTHETIC_LYRICS = (
    'I took the last train past a paper moon\n'
    'My old map folds but the street stays new\n'
    'I count each stop and write a different route'
)


def _words(value):
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', value).casefold()))


def claim_alignment(entries, lines):
    """Count literal surface matches only; an unmatched allusion is not disproved."""
    totals = {'target_literal': 0, 'neighbor_literal': 0, 'not_literal': 0}
    sources = {line['index']: _words(line['text']) for line in lines}
    for entry in entries:
        number = entry['line']
        for category, key in (('slang', 'expression'), ('wordplay', 'expression'),
                              ('references', 'name')):
            for claim in entry.get(category, []):
                if not isinstance(claim, dict) or not isinstance(claim.get(key), str):
                    continue
                variants = [_words(part) for part in claim[key].split('/')]
                variants = [part for part in variants if part]
                if not variants:
                    continue
                def found(text):
                    return any(' ' + part + ' ' in ' ' + text + ' ' for part in variants)
                if found(sources.get(number, '')):
                    totals['target_literal'] += 1
                elif any(found(source) for line_no, source in sources.items()
                         if line_no != number and abs(line_no - number) <= 3):
                    totals['neighbor_literal'] += 1
                else:
                    totals['not_literal'] += 1
    return totals


def review_sample(entries):
    """Small, bounded model excerpt for human review; input is synthetic only."""
    sample = []
    for entry in entries:
        sample.append({
            'line': entry['line'],
            'interpretation_fr': entry['interpretation'].strip()[:280],
            'wordplay': [{'expression': item['expression'][:100],
                          'mechanism': item['mechanism'][:180],
                          'evidence': item['evidence']}
                         for item in entry['wordplay'][:4]],
            'references': [{'name': item['name'][:100],
                            'verification': item['verification']}
                           for item in entry['references'][:4]],
            'writing_lesson_fr': entry['writing_lesson'].strip()[:280],
        })
    return sample


def _read_model(active_root):
    cfg = active_root / 'data' / 'ollama_model.json'
    try:
        model = json.loads(cfg.read_text(encoding='utf-8')).get('model')
    except (OSError, ValueError, TypeError, AttributeError):
        model = None
    model = model or os.getenv('RAP_BRAIN_MODEL', 'qwen3:8b')
    if not isinstance(model, str) or not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,120}', model):
        raise ValueError('invalid_local_model_name')
    return model


def _ollama_endpoint():
    root = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434')
    url = urllib.parse.urlparse(root)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
        raise ValueError('ollama_must_be_local')
    return root.rstrip('/') + '/api/chat'


def _load_candidate(path, isolated_data):
    old_data = os.environ.get('RAP_BRAIN_DATA')
    old_home = os.environ.get('HOME')
    prior = {name: sys.modules.get(name) for name in ('creative_engine', 'creative_rag')}
    try:
        os.environ['RAP_BRAIN_DATA'] = str(isolated_data)
        os.environ['HOME'] = str(isolated_data.parent)
        for name in prior:
            sys.modules[name] = types.ModuleType(name)
        spec = importlib.util.spec_from_file_location('isolated_decoder_candidate', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if old_data is None:
            os.environ.pop('RAP_BRAIN_DATA', None)
        else:
            os.environ['RAP_BRAIN_DATA'] = old_data
        if old_home is None:
            os.environ.pop('HOME', None)
        else:
            os.environ['HOME'] = old_home
        for name, value in prior.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def run_probe(active_root=None):
    active_root = Path(active_root or Path.home() / 'Downloads' / 'rap-brain')
    active_server = active_root / 'server.py'
    before = hashlib.sha256(active_server.read_bytes()).hexdigest()
    if before != BASELINE_SHA256:
        raise ValueError('active_server_baseline_mismatch')
    model = _read_model(active_root)
    endpoint = _ollama_endpoint()
    url = REPOSITORY + COMMIT + '/decoder-next/server.py'
    with urllib.request.urlopen(url, timeout=20) as response:
        if response.geturl() != url:
            raise ValueError('candidate_redirect_refused')
        data = response.read(100000)
        if response.read(1):
            raise ValueError('candidate_too_large')
    if hashlib.sha256(data).hexdigest() != CANDIDATE_SHA256:
        raise ValueError('candidate_hash_mismatch')
    with tempfile.TemporaryDirectory(prefix='rapbrain-decoder-probe-') as temp:
        path = Path(temp) / 'server.py'
        path.write_bytes(data)
        candidate = _load_candidate(path, Path(temp) / 'data')
        lines = candidate.split_lyric_lines(SYNTHETIC_LYRICS)
        prompt = candidate.decoder_prompt({'artist': 'Invented', 'title': 'Synthetic'}, lines, 0, len(lines))
        payload = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                              'stream': False, 'think': False,
                              'options': {'temperature': 0.25, 'num_predict': 2300}}).encode()
        request = urllib.request.Request(endpoint, data=payload,
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=480) as response:
            output = json.load(response)
        content = (output.get('message') or {}).get('content', '')
        result = candidate.parse_batch(content, [line['index'] for line in lines])
        alignment = claim_alignment(result, lines)
        if hashlib.sha256(active_server.read_bytes()).hexdigest() != before:
            raise ValueError('active_server_changed_during_probe')
        return {'status': 'PASS_ISOLATED', 'line_count': len(result),
                'structured_slang': sum(len(line['slang']) for line in result),
                'structured_wordplay': sum(len(line['wordplay']) for line in result),
                'structured_references': sum(len(line['references']) for line in result),
                'literal_alignment': alignment,
                'review_sample': review_sample(result),
                'live_database_opened': False, 'live_files_modified': False,
                'server_started': False, 'candidate_sha256': CANDIDATE_SHA256}


if __name__ == '__main__':
    try:
        print(json.dumps(run_probe(), sort_keys=True))
    except Exception as exc:
        print('DECODER PROBE REFUSED:', type(exc).__name__, '/', str(exc))
        raise SystemExit(1)
