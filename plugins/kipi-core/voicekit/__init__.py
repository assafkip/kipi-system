"""voicekit: the METHOD half of the voice architecture. Fleet code, founder-agnostic.

The split is deliberate and a test holds it (2026-08-06, voice-architecture PRD):

- This package is MACHINERY: fingerprint math, corpus loading, deterministic exemplar
  selection, prompt assembly, validators. It ships fleet-wide with kipi-core.
- A founder's DATA -- exemplars, lexicon values, computed bands, corrections -- lives in
  that founder's own instance repo (its `voice/` dir) and must never appear in this tree.
  `tests/test_no_founder_data.py` fails this package if it ever quotes a corpus.

Nothing here reads a network, calls a model, or knows a path outside the `voice_dir` it
is handed. Pure functions of (files, counters), so every consumer can test offline.
"""
