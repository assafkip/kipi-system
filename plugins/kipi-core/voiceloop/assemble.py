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

BUDGET_CHARS = 24000     # asserted by validate.feasible + the consumer's suite,
                         # NEVER enforced by a runtime raise or slice (ASK-461:
                         # a cap you cannot see is the same bug; a cap that kills
                         # the daily job is a worse one).
                         #
                         # RAISED FROM 20000 ON 2026-08-31, and this is a headroom
                         # alarm being re-set, not a gate being switched off. It is a
                         # round number with no model limit behind it -- 20000 chars
                         # is roughly 5k tokens -- and it fires at suite time only.
                         # What tripped it: landing the four measured 2026-08-24 shape
                         # corrections from the stranded fix/restatement branch took
                         # linkedin's worst assembly from 18731 to 20315 (measured,
                         # both numbers, by rendering 12 counters each way). Dropping
                         # a measured correction to stay under a round number would be
                         # the redundancy dismissal the brief bans.
                         #
                         # THE REAL SIGNAL IS STILL REAL and is captured as spillover:
                         # every correction renders into every in-scope prompt, so the
                         # ledger grows without bound and this alarm will trip again.
                         # Raising it buys room; it does not fix growth.


#: Corrections carrying this source were derived from aggregate performance
#: research on OTHER accounts, not from the founder correcting his own draft.
#: They render as options under their own header instead of the override header,
#: because "posts he has written" and his own corrections are measurements of HIM,
#: while an external lift number is a hypothesis about what might also work for
#: him. Unmarked rows render exactly as they always did, so a corpus that never
#: uses this field behaves byte for byte as before (ASK fleet-wide).
EXTERNAL_SOURCE = "external-performance"

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
                  slot_kind="post", target_words=None):
    """(text, provenance) for one slot. Pure; empty Voice -> ('', empty provenance).

    `target_words` threads the length axis (selector.length_band) to the one place
    that assembles a prompt. Default None is the pre-2026-08-13 answer byte for byte.
    """
    picked = selector.select(voice.active_exemplars(), channel, counter,
                             slot_index=slot_index, k=k, slot_kind=slot_kind,
                             target_words=target_words)
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
    # Filter ONCE, and let the same list feed the prompt and the receipt below
    # (ASK-508, sp-9642b63d). These were two independent readers of one fact: the
    # prompt honoured `scope` and provenance ignored it, so a correction withheld
    # from the model was still recorded as applied. Same class as the notify_cap
    # scar -- a receipt for an action that did not occur. The echo gate and every
    # audit downstream trust correction_ids, so the cheapest wrong answer here is
    # the one that looks authoritative.
    applied = [r for r in (corrections or [])
               if not r.get("scope") or channel in r["scope"]]
    his = [r for r in applied if r.get("source") != EXTERNAL_SOURCE]
    researched = [r for r in applied if r.get("source") == EXTERNAL_SOURCE]
    if his:
        lines = "\n".join(f"- {r['instruction']}" for r in his)
        if lines:
            parts.append("STANDING CORRECTIONS (these override everything above):\n"
                         + lines)
    if researched:
        lines = "\n".join(f"- {r['instruction']}" for r in researched)
        parts.append(
            "RESEARCHED SHAPES (measured on other writers' posts, not on the posts "
            "above. Optional: use a shape when it fits the idea, ignore it when it "
            "fights how he writes. The posts above and the standing corrections win "
            "anywhere they disagree):\n" + lines)

    provenance = {
        "exemplar_ids": [str(r.get("id")) for r in picked],
        "exemplar_texts": [(r.get("text") or "") for r in picked],
        "correction_ids": [str(r.get("id")) for r in applied],
        "external_correction_ids": [str(r.get("id")) for r in researched],
        "selection_reason": selector.selection_reason(picked, channel, counter,
                                                      slot_index),
        "skipped_rows": voice.skipped_rows,
    }
    return "\n\n".join(parts), provenance
