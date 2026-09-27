---
description: The style half of the voice engine (bands, templated shapes, corpus echo) on written drafts
paths:
  - "**/*.md"
---

# Voice Loop Anywhere: the style half of the voice engine reaches written drafts

The voice engine is two halves. `voice-lint.py` owns banned vocabulary and
phrasing. `voiceloop` owns what vocabulary lists cannot see: measured style
BANDS, TEMPLATED SHAPES, and verbatim ECHO of the founder's corpus. Until
2026-08-29 only the first half ran on drafts, so "the voice engine fires on
drafts" was half true, and a half-run check reads exactly like a clean one.

`voiceloop-band-lint.py` is the missing half, wired PostToolUse on Edit/Write/
MultiEdit in BOTH `.claude/settings.json` and `settings-template.json`, so the
fleet updater ships the switch and not only the script. It self-scopes by
`tool_input.file_path` using `is_published_path` IMPORTED from `voice-lint.py`,
so both halves of one engine agree about what a draft is and neither can widen
its blast radius alone.

## Why the status below is DETECTED and not ENFORCED

Measured 2026-08-29, not reasoned about. Across the 26 live instances in
`instance-registry.json`, 2577 files satisfy `is_published_path`. A 200-file
random sample was run through both halves: 122 of 200 (61%) produced at least
one finding. This hook ships fleet-wide, so exit 2 would block roughly 60% of
all draft writes on day one. A gate red on its own population gets switched
off, and a gate that is off protects nothing. Same call and same reason as
`coding-audhd.md` (ASK-132).

DETECTED means it runs on every draft write and surfaces findings as feedback,
and the write still lands. It exits 0 on every path, deliberately. Flipping it
to blocking is a founder decision made in the open, once the population is
clean enough to survive it.

## What the status does and does not cover

Read it narrowly. `test_voiceloop_band_lint.py` pins the hook's CONTRACT: that
it never blocks, that a finding is actually surfaced rather than swallowed, that
an out-of-scope path fast-exits, that the skip marker works, and that a missing
engine or missing corpus ANNOUNCES itself instead of passing quietly. It does
not pin voiceloop's scoring, which belongs to the public package.

Two measured limits, recorded because they bound what the silence means:

- The vocabulary branch INSIDE voiceloop is inert against this corpus. It prints
  "no `negative` list in lexicon.json" and checks nothing. That half is covered
  by `voice-lint.py`, which is why `voice-check` chains the two (sp-e1c6b26c).
- A corpus member scored against the corpus containing it always echoes itself.
  Corpus members are therefore skipped. This was a real false positive in the
  2026-08-29 sample, not a hypothetical.

Bypass one file deliberately with `<!-- voiceloop-band-lint-skip -->`.

```json
[
  {
    "clause": "Voice Loop Anywhere: the style half of the voice engine reaches written drafts",
    "status": "DETECTED",
    "exec": "q-system/.q-system/scripts/voiceloop-band-lint.py",
    "config": ".claude/settings.json",
    "test": "q-system/.q-system/scripts/test/test_voiceloop_band_lint.py",
    "directives": 0
  }
]
```
