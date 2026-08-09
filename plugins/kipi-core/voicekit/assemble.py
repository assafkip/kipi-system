#!/usr/bin/env python3
"""Assemble the voice section of a generation prompt from a loaded Voice.

Order is the design (voice-architecture PRD, 2026-08-06), and each position is a
decision:

    identity -> pov -> lexicon positives -> EXEMPLARS -> active corrections

- Exemplars sit LAST-but-one, adjacent to the source material the caller appends:
  the strong context position ("lost in the middle" is why 19k of samples inside a
  57k prompt taught nothing).
- Corrections load LAST: recency weight, the coded replacement for gotchas.md's
  "loaded last, overrides" convention.
- The lexicon contributes ONLY its positive slices (prefer/voiceprint_terms). The
  banned lists live in gate scripts; restating them in the prompt is negative
  priming, and `test_prompt_gate_coherence` in the consuming repo asserts absence.

Returns (text, provenance). Provenance carries exemplar ids, correction ids, the
selection reason and the exemplar BODIES -- the bodies feed the echo gate, which
must compare the final text against exactly what the prompt showed the model.
"""
from __future__ import annotations

from . import selector

BUDGET_CHARS = 20000     # asserted by validate.feasible + the consumer's suite,
                         # NEVER enforced by a runtime raise or slice (ASK-461:
                         # a cap you cannot see is the same bug; a cap that kills
                         # the daily job is a worse one).


def _lexicon_positive(lexicon):
    lines = []
    prefer = lexicon.get("prefer") or []
    if prefer:
        pairs = ", ".join(f"{p.get('use')} (not {p.get('not')})"
                          for p in prefer if p.get("use"))
        if pairs:
            lines.append(f"Words he reaches for: {pairs}.")
    terms = lexicon.get("voiceprint_terms") or []
    if terms:
        lines.append("His recurring vocabulary: " + ", ".join(terms) + ".")
    return "\n".join(lines)


def voice_section(voice, channel, counter, slot_index=0, k=selector.DEFAULT_K,
                  slot_kind="post"):
    """(text, provenance) for one slot. Pure; empty Voice -> ('', empty provenance)."""
    picked = selector.select(voice.active_exemplars(), channel, counter,
                             slot_index=slot_index, k=k, slot_kind=slot_kind)
    corrections = voice.active_corrections()

    parts = []
    if voice.identity.strip():
        parts.append("WHO IS WRITING:\n" + voice.identity.strip())
    if voice.pov.strip():
        parts.append("WHAT HE WRITES ABOUT AND BELIEVES:\n" + voice.pov.strip())
    lex = _lexicon_positive(voice.lexicon)
    if lex:
        parts.append(lex)
    if picked:
        bodies = "\n\n---\n\n".join((r.get("text") or "").strip() for r in picked)
        parts.append("POSTS HE HAS WRITTEN. Match their rhythm, register and "
                     "length. Never reuse their sentences or openings:\n\n" + bodies)
    if corrections:
        lines = "\n".join(f"- {r['instruction']}" for r in corrections
                          if not r.get("scope") or channel in r["scope"])
        if lines:
            parts.append("STANDING CORRECTIONS (these override everything above):\n"
                         + lines)

    provenance = {
        "exemplar_ids": [str(r.get("id")) for r in picked],
        "exemplar_texts": [(r.get("text") or "") for r in picked],
        "correction_ids": [str(r.get("id")) for r in corrections],
        "selection_reason": selector.selection_reason(picked, channel, counter,
                                                      slot_index),
        "skipped_rows": voice.skipped_rows,
    }
    return "\n\n".join(parts), provenance
