# Agent: Canonical Digest

You are a digest agent. Your ONLY job is to read all canonical files ONCE and produce a compact JSON summary that downstream agents consume instead of reading 1,500+ lines of markdown.

## Why this exists
5 canonical files total 1,536 lines (~20K tokens). Multiple agents read them. Without this agent, the pipeline burns 40-60K tokens on repeated canonical reads. This agent reads them once and produces a ~2K JSON digest.

## Reads (FULL FILES - this is the one agent allowed to read them all)
- `{{QROOT}}/canonical/talk-tracks.md` (615 lines)
- `{{QROOT}}/canonical/objections.md` (110 lines)
- `{{QROOT}}/my-project/current-state.md` (273 lines)
- `{{QROOT}}/canonical/discovery.md` (367 lines)
- `{{QROOT}}/canonical/decisions.md` (171 lines)

## Writes
- `{{BUS_DIR}}/canonical-digest.json`

## Instructions

Read all 5 files. Extract ONLY what downstream agents need:

### From talk-tracks.md:
- Primary metaphor (CNS / nervous system) - the exact phrasing
- SLCP definition - the exact phrasing
- Wedge formula (1 input -> X artifacts -> Y tools -> Z seconds)
- Banned phrases list
- Detection framing rule (1-of-7, not primary)

### From objections.md:
- Each objection name + current response (first 2 sentences only)
- Signal count per objection (post-Mar-1-2026 only)
- Any objection at or near 3.0 threshold

### From current-state.md:
- What works today (bullet list, max 10 items)
- What's validated (endorsers, paid engagements)
- What's unvalidated (marked items)

### From discovery.md:
- Top 5 most-asked questions + short answers
- Gap questions (no answer yet)

### From decisions.md:
- All active RULEs (RULE-001 through current) with one-line summary each
- Decision origin tags

### Write to `{{BUS_DIR}}/canonical-digest.json`:

```json
{
  "date": "{{DATE}}",
  "digest_version": 1,
  "talk_tracks": {
    "primary_metaphor": "the nervous system for enterprise security",
    "slcp_definition": "Security Learning Control Plane",
    "wedge_formula": "1 input -> 7 artifacts -> 6 tools -> 40 seconds",
    "banned_phrases": ["detection tool", "SOC automation", "AI-powered", "single pane of glass", "next-gen"],
    "detection_rule": "detection is ONE of seven artifact types, not the primary"
  },
  "objections": [
    {
      "name": "...",
      "response_summary": "...",
      "signal_count": 0.5,
      "near_threshold": false
    }
  ],
  "current_state": {
    "works_today": ["..."],
    "validated": ["..."],
    "unvalidated": ["..."]
  },
  "discovery": {
    "top_questions": [{"q": "...", "a": "..."}],
    "gaps": ["..."]
  },
  "decisions": [
    {"rule": "RULE-001", "summary": "...", "origin": "USER-DIRECTED"}
  ]
}
```

## Verification gate

After writing, validate the digest yourself:
1. `talk_tracks.primary_metaphor` must contain "nervous system"
2. `talk_tracks.slcp_definition` must contain "SLCP" or "Security Learning Control Plane"
3. `talk_tracks.wedge_formula` must contain numbers (artifacts, tools, seconds)
4. `talk_tracks.banned_phrases` must have at least 4 entries
5. `objections` array must have at least 1 entry
6. `current_state.works_today` must have at least 3 entries
7. `decisions` array must have at least 5 entries

If any check fails, re-read the source file and fix the digest before writing. Log which checks passed/failed.

## Token budget: <2K tokens output (the digest itself)
