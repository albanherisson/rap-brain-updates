# Lyric Decoder checkpoint candidate

Source baseline: installed guarded server from the owner-signed bootstrap,
SHA-256 `e7947990aec65830375b5e5e5fb6241f0161ead56309c970a8cc7c0970e56f27`.

This candidate checks the saved report before treating a decoding checkpoint as
complete. It inserts a new analysis when a checkpoint is stale or the source
lyrics change. Existing analyses and the user's library are not rewritten.
It also refuses malformed structured claims (slang, wordplay, references,
rhyme cues), prompts Ollama to repair its JSON on retry, and keeps the
existing line-by-line fallback for incomplete batches. An empty category is
represented by `[]`; the validator does not prove the truth of an inference.
The Lexicon indexer skips damaged legacy fields and continues to index healthy
lines from the same report. This does not change or erase existing reports.
Previously cached Lexicon rows are not rebuilt in this candidate; a separate
read-only inventory should precede any migration of derived index rows.
Blank or null lyrics in the existing single-track and bulk import routes no
longer erase saved lyrics or replace the track's source metadata.
When lyrics change during an in-flight decode, the job returns to `pending`
and restarts from the current text; historical reports remain untouched.
The normal three-line prompt, Ollama settings, worker guard and HTTP routes
remain in the copied server.
The synthetic tests use a temporary home directory and run through the
signed server's normal worker lock; a maintenance ticket blocks decoding.

Run only on synthetic data:

```sh
python3 -B -m unittest -v test_decoder_checkpoints.py
```

No production installation or signed release is included. The Mac runtime,
real Ollama output and release signing still require separate validation.
