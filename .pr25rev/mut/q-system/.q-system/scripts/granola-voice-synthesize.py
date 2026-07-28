#!/usr/bin/env python3
"""granola-voice-synthesize.py — Stage 2 LLM synthesis for founder-voice enrichment.

Pairs with plan: q-system/output/plans/voice-from-granola-2026-07-04.md
Consumes Stage 1 output (me-corpus.txt) and produces classified, critic-survived
voice-DNA findings ready for a founder-gated merge into the founder-voice skill.

Two passes, both via `claude -p` (subscription-backed LLM, per the "Claude CLI as
LLM client" pattern):
  Pass 1 — extraction: pull DURABLE patterns (vocab, metaphor, recurring
           story/scar, stance, argument structure, rhythm) and separate them from
           SPOKEN-ONLY disfluency. Every pattern needs 2+ cited occurrences.
  Pass 2 — adversarial critic: for each durable pattern, keep only what is
           DISTINCTIVELY Assaf; reject anything a generic articulate founder
           would also say. Default-reject on uncertainty.

Determinism note: the extraction itself is LLM judgment (not deterministic) — the
harness is what is reusable and auditable. The critic is the anti-slop gate. The
MERGE into voice-dna.md is NOT done here; findings are emitted for founder review.

Output (in <corpus_dir>):
  voice-findings-raw.json   full pass-1 output (durable + spoken-only)
  voice-findings.json       {durable_kept, durable_rejected, spoken_only}

Usage: python3 granola-voice-synthesize.py <corpus_dir>
       (expects <corpus_dir>/me-corpus.txt)
"""
import json
import re
import subprocess
import sys
import os

MODEL = os.environ.get("VOICE_SYNTH_MODEL", "")  # empty = CLI default; set to pin


def run_claude(full_prompt):
    """Pipe a full prompt to `claude -p`, return parsed JSON (array)."""
    cmd = ["claude", "-p",
           "Follow the instructions in the piped input exactly. "
           "Output ONLY a raw JSON array. No markdown fences, no prose."]
    if MODEL:
        cmd += ["--model", MODEL]
    r = subprocess.run(cmd, input=full_prompt, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"claude -p failed (exit {r.returncode}):\n{r.stderr[:2000]}")
    out = r.stdout.strip()
    # be tolerant of stray fences/prose: slice from first '[' to last ']'
    i, j = out.find("["), out.rfind("]")
    if i == -1 or j == -1:
        sys.exit(f"no JSON array in claude output:\n{out[:2000]}")
    return json.loads(out[i:j + 1])


EXTRACT_INSTRUCTIONS = """\
You are given a corpus of verbatim SPOKEN utterances by one person, Assaf,
extracted from meeting transcripts (only his lines; other speakers removed). The
text is raw speech: it has disfluencies (like, you know, false starts, repetition)
and transcription errors.

Extract the DURABLE patterns of how Assaf thinks and communicates — the traits
that should inform how an AI writes in his voice — and separate them from
SPOKEN-ONLY artifacts that must NEVER appear in written output.

Rules for every pattern:
- classification: "durable" (a stable trait: coined vocabulary, metaphor/analogy,
  recurring story or scar, stance/opinion, argument structure, rhythm/cadence,
  humor, value) OR "spoken-only" (filler, false start, transcription artifact).
- Include a pattern ONLY if it is evidenced by 2+ independent occurrences in the
  corpus. Cite the exact quotes (verbatim substrings).
- REJECT anything a generic articulate tech founder would also say. Isolate what
  is DISTINCTIVELY Assaf.

Output ONLY a JSON array (no prose, no fences) with this schema:
[{"category": "vocabulary|metaphor|story-scar|stance|argument-structure|rhythm|humor|value",
  "pattern": "one-line description of the trait",
  "classification": "durable|spoken-only",
  "evidence_quotes": ["verbatim quote 1", "verbatim quote 2"],
  "why_distinctive": "why this is Assaf-specific, not generic"}]

CORPUS:
"""

CRITIC_INSTRUCTIONS = """\
You are an ADVERSARIAL critic protecting a person's voice-DNA reference from
generic slop. Below is a JSON array of claimed DURABLE voice patterns for a person
named Assaf, each with evidence quotes.

For EACH pattern decide: is it genuinely DISTINCTIVE to Assaf, or is it something
any articulate tech founder would say or do (generic)? Default to "reject" when
uncertain. Only high-signal, distinctive patterns should survive.

Output ONLY a JSON array (no prose, no fences), one entry per input pattern:
[{"pattern": "<copy the input pattern text verbatim>",
  "verdict": "keep|reject",
  "reason": "one line"}]

PATTERNS:
"""


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: granola-voice-synthesize.py <corpus_dir>")
    cdir = sys.argv[1]
    corpus = open(os.path.join(cdir, "me-corpus.txt"), encoding="utf-8").read()

    # Pass 1 — extraction
    findings = run_claude(EXTRACT_INSTRUCTIONS + corpus)
    json.dump(findings, open(os.path.join(cdir, "voice-findings-raw.json"), "w"), indent=2)
    durable = [f for f in findings if f.get("classification") == "durable"]
    spoken = [f for f in findings if f.get("classification") == "spoken-only"]

    # Pass 2 — adversarial critic over durable only
    verdicts = run_claude(CRITIC_INSTRUCTIONS + json.dumps(durable, indent=2))
    vmap = {v.get("pattern", ""): v for v in verdicts}
    kept, rejected = [], []
    for f in durable:
        v = vmap.get(f.get("pattern", ""), {"verdict": "reject", "reason": "no critic verdict returned"})
        (kept if v.get("verdict") == "keep" else rejected).append({**f, "critic": v})

    out = {
        "durable_kept": kept,
        "durable_rejected": rejected,
        "spoken_only": spoken,
    }
    json.dump(out, open(os.path.join(cdir, "voice-findings.json"), "w"), indent=2)
    print(json.dumps({
        "durable_found": len(durable),
        "kept_after_critic": len(kept),
        "rejected_by_critic": len(rejected),
        "spoken_only_quarantined": len(spoken),
        "kept": [f["pattern"] for f in kept],
        "rejected": [{"pattern": f["pattern"], "reason": f["critic"].get("reason")} for f in rejected],
    }, indent=2))


if __name__ == "__main__":
    main()
