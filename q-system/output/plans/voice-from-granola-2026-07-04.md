# Plan: Enrich the founder-voice skill from Granola transcripts

## What / why
Mine Granola meeting transcripts for the durable patterns of how Assaf actually
speaks, clean out disfluency, and fold those patterns into the ONE unified
founder-voice skill. Founder's frame: "how I write and how I sound are the same."
The transcript is a SOURCE; the skill's output stays clean-written but more
authentically Assaf (vocabulary, metaphors, stories, stance, cadence).

## Key insight (feasibility gate — PASSED)
Granola tags every utterance: Assaf = `Me:`, everyone else = `Them:`. So
isolating "just Assaf talking" is DETERMINISTIC (script, not LLM). But spoken
text is full of `like` / `you know` / false starts / transcription garble. The
value is the durable DNA underneath, NOT the literal text. Extraction MUST
separate `durable` (belongs in skill) from `spoken-only` (quarantined).

## Approach (2 stages, multi-pass)
- **Stage 1 — deterministic harvest.** Pull curated transcripts via Granola MCP
  (persist to disk). One Python script parses each transcript, splits on the
  `Me:` / `Them:` speaker markers, extracts ONLY `Me:` segments → clean corpus +
  a per-meeting talk-volume ranking. Reproducer: `grep -c "Them:" corpus == 0`.
- **Stage 2 — LLM pattern synthesis (separate next step).** `claude -p` runs a
  structured extraction prompt over the corpus. Each pattern classified
  `durable | spoken-only` with 2+ evidence quotes. Then an adversarial critic
  pass rejects anything a generic articulate founder would also say. Only
  `durable`, critic-surviving patterns are proposed for merge.
- **Merge — founder-gated.** Findings are shown as a diff against `voice-dna.md`.
  Founder approves before any write. No auto-apply to the voice skill.

## Corpus scope (curated high-talk, ~10 meetings)
Opinion / strategy / personal / relationship conversations (where Assaf expresses
himself), not pure tool-demos:
- Laid off from Meta (personal)
- AI autonomy and accountability
- Personal check-in — product / consulting / family
- Operations, investigations, part-time role with Chris
- Agent authority and liability framework
- AI decision engine and pipeline monitoring with Blake
- Threat intelligence tools and agent-driven investigations with Jay
- Catalyst security platform — market fit / design partner with Duffy
- Teach skill — stateful learning, ZPD
- Account fraud investigation with Nigel

## Files to touch
- READ/MERGE (source of truth): `plugins/kipi-core/skills/founder-voice/references/voice-dna.md`
- Harvest script: `q-system/.q-system/scripts/granola-voice-harvest.py` (deterministic Stage 1)
- Corpus output: `q-system/output/voice-corpus/me-corpus.txt` + `talk-ranking.json`
- Stage 2 findings: `q-system/output/voice-corpus/voice-findings.json`

## Acceptance criteria
- [ ] Stage 1: `me-corpus.txt` contains ONLY Assaf utterances; `grep -c "Them:" == 0`
- [ ] Per-meeting talk-volume ranking produced (word count of Me: segments)
- [ ] Stage 2: findings JSON, each pattern tagged `durable|spoken-only` + 2+ quotes
- [ ] Adversarial critic pass runs; generic patterns rejected with rationale
- [ ] Only `durable` patterns reach the merge proposal; `spoken-only` quarantined
- [ ] Merge shown as a diff; founder approves before `voice-dna.md` is written
- [ ] Load-path: edit skeleton source, then propagate via `kipi update` /
      marketplace sync (founder-voice is a PLUGIN skill — running copy is the
      marketplace clone, not this repo's `plugins/`)

## Harness limitations (captured, not dropped)
- Granola diarization can DEGRADE mid-transcript: a transcript starts with
  `Me:`/`Them:` markers, then loses them, so one `Me:` chunk silently swallows
  the other speaker's lines (seen in "Agent authority and liability framework",
  2026-07-04). A pure marker split then mis-attributes the interviewer's words to
  Assaf. Guard added: `granola-voice-harvest.py` warns (does NOT auto-skip, since
  Assaf gives real long monologues) when a single turn exceeds MAX_TURN_WORDS
  (700). Flagged meetings need a human eyeball before feeding Stage 2. The
  Agent-authority transcript is excluded from the corpus by hand for this reason.
- `Speaker A/B/C` panel diarization has no Assaf tag and is auto-skipped (correct,
  but it means panels/multi-party recordings never contribute).

## Patterns to follow (from this instance's own code)
- voice-lint discipline: a pattern counts only with 2+ occurrences + citations
- script-over-LLM: speaker isolation is deterministic, not an LLM judgment
- sycophancy critic pattern: an independent adversarial pass before accepting
- No auto-apply to canonical/voice files without founder sign-off
