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
Artist/title metadata is serialized as untrusted JSON. Numbered target lyrics
follow a separate marker after the quoted context, so a title or lyric that
contains a lookalike target label cannot redefine the batch boundary.
New reports also carry a per-claim `evidence_audit` showing whether a slang
term, wordplay expression or reference name appears literally on the target
line, in nearby lines, or nowhere in that local text. The audit does not
reject or relabel homophones, indirect allusions or other model hypotheses;
literal absence is a prompt for human review, not proof of an error.
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
The signed runtime guard suffix is checked byte-for-byte against its baseline.

Run the repository's self-contained synthetic suite:

```sh
python3 -B -m unittest -v decoder-next/test_decoder_checkpoints.py
```

The separate `test_release_compat.py` requires the Manager's internal source
modules and `cryptography`. They are available in the local development
workspace but are not currently committed to this public repository. Its
three tests passed locally on copies; GitHub CI does not run them.

No production installation or signed release is included. The Mac runtime,
real Ollama output and release signing still require separate validation.
`mac_isolated_ollama_probe.py` is prepared for that later Mac check. It pins
the candidate source hash, imports only inside a temporary directory, sends
three invented lines to the local Ollama API, and never opens the live SQLite
database. It has only been tested with a fake HTTP response so far.
The probe reports counts of quoted claims found literally on their line,
found in nearby lines, or not found literally. These are review hints, not
semantic truth labels: homophones and indirect allusions may be valid.
The first real Mac run returned structurally valid JSON but treated ordinary
contrasts and actions as wordplay. The revised prompt reserves wordplay for
two distinct supported readings, and the next synthetic probe pairs a clear
`sole`/`Seoul` homophone with two plain control lines. Its output still needs
human review; no model result is hard-coded as a guaranteed pass.
It also returns a short, bounded sample of French interpretations, proposed
wordplay, references and writing lessons for the three invented lines. This
sample is for a person to judge whether the model is useful and cautious;
`PASS_ISOLATED` certifies structure and isolation, not artistic correctness.
The release compatibility test creates an archive and a disposable signature
in memory only. It proves the existing Manager verifier accepts `server.py`
and refuses database/configuration paths, then drills the candidate code swap
and exact rollback on disposable app/server copies. Its validation flags are
fixtures, not evidence that a real Mac release has passed these gates.

`mac_sign_decoder_release.py` is the next Mac-only gate. It pins this server,
checks the active baseline and accepted Manager sequence 3, verifies the app
signature, rehearses a server-only swap and exact rollback on disposable Mac
copies, and uses the existing local publisher identity to create one public
sequence-4 ZIP in Downloads. It does not install anything. The private key,
SQLite, library and Ollama configuration never enter that ZIP. Its Mac copy
and signing path still needs to be run on the owner's Mac before publication.
