"""voiceloop: the METHOD half of the voice architecture. Fleet code, founder-agnostic.

The split is deliberate and a test holds it (2026-08-06, voice-architecture PRD):

- This package is MACHINERY: fingerprint math, corpus loading, deterministic exemplar
  selection, prompt assembly, validators. It ships fleet-wide with kipi-core and is published as the public
voice-loop package under the SAME name.

why the name changed (2026-08-29): this package was called `voicekit` here and the
exporter renamed it to `voiceloop` on the way out, so the public package was a
pseudonym for a third of the engine and there was no single word that meant the
whole voice capability. One name now, private and public.
- A founder's DATA -- exemplars, lexicon values, computed bands, corrections -- lives in
  that founder's own instance repo (its `voice/` dir) and must never appear in this tree.
  `tests/test_no_founder_data.py` fails this package if it ever quotes a corpus.

Nothing here reads a network, calls a model, or knows a path outside the `voice_dir` it
is handed. Pure functions of (files, counters), so every consumer can test offline.
"""
