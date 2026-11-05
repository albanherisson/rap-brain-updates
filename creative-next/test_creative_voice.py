"""Regression cases against the exact installed Creative Engine P8 copy."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parents[1] / 'artistic_baseline/creative_engine.py'


def load(path):
    spec = importlib.util.spec_from_file_location('isolated_creative', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CreativeVoiceTest(unittest.TestCase):
    def test_exact_installed_baseline_then_equal_hard_quality_keeps_first(self):
        import hashlib
        self.assertEqual(hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(),
            'b770bdf034caa600f75497325f80759d4f372258fa0e911e28f29d214abe85f3')
        stub = types.SimpleNamespace(verified_end_rhymes=lambda bars: [],
                                     verified_pair=lambda a, b: False)
        first = ('I left the lights on in the hall\n'
                 'You heard the silence through the wall\n'
                 'I kept the receipt inside my coat\n'
                 'You saw the words I never wrote')
        weaker = ('I got a car beside the lake\n'
                  'I got a bar for my own sake\n'
                  'I got a star to make me shine\n'
                  'I got a name to put in line')
        responses = ['{}', first, json.dumps({'pass':False,'issues':['Keep the scene coherent.']}),
                     weaker, json.dumps({'pass':False,'issues':['Scene lost.']}),
                     weaker, json.dumps({'pass':False,'issues':['Scene lost.']})]
        scripted = iter(responses)
        iter_old = iter(responses)
        prompts = []
        def llm(messages, predict, timeout):
            prompts.append(messages)
            return next(scripted)
        with patch.dict(sys.modules, {'rhyme_validator': stub}):
            installed = load(ORIGINAL)
            candidate = load(HERE / 'creative_engine.py')
            # The installed P8 bug promotes an equally sound but worse rewrite.
            old_output = installed.generate('Écris 4 lignes sur une lettre jamais envoyée',
                                            [], [], lambda *a, **k: next(iter_old), 3)
        # Keep the old-path counterexample isolated from the candidate calls.
        self.assertEqual(old_output, weaker)
        with patch.dict(sys.modules, {'rhyme_validator': stub}):
            output = candidate.generate('Écris 4 lignes sur une lettre jamais envoyée',
                                        [], [], llm, 3)
        self.assertEqual(output, first)
        self.assertIn('direct conversational bar talk', prompts[0][0]['content'])


if __name__ == '__main__':
    unittest.main()
