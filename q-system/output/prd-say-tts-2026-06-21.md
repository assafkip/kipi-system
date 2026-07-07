---
id: prd-say-tts-2026-06-21
title: "/say — read the last assistant response aloud (OpenAI TTS)"
status: idea
created_at: 2026-06-21
updated_at: 2026-06-21
owner: assafkip
reviewers: []
findings_path: .prd-os/findings/prd-say-tts-2026-06-21-findings.jsonl
---

# /say — read the last assistant response aloud (OpenAI TTS)

## Problem

The founder processes audio better than text. Today, every long Claude
response or process explanation gets manually copied out of the terminal and
pasted into Speechify to be listened to. That copy-paste is repeated friction
on the highest-value (longest) outputs, and it pulls focus out of the terminal.
The text the founder wants spoken already exists in the session transcript;
nothing should need pasting.

## Goals

- One command, `/say`, speaks the **last** assistant response aloud.
- The text is **referenced automatically from the session transcript** — no
  copy-paste, no re-typing, no passing the text as an argument.
- Audio plays in the background so work continues; `/say stop` halts it.
- Deterministic and testable: extraction, chunking, and error paths verify
  without an API key or audio device.

## Non-goals

- No auto-fire on every response (manual trigger only, by founder decision).
- No Stop-hook integration in v1.
- No non-macOS playback in v1 (uses `afplay`).
- No streaming/word-highlighting UI; this is fire-and-forget audio.
- No engine abstraction beyond env-overridable model/voice (OpenAI only).

## Proposed approach

A slash command backed by one deterministic script. No pip dependencies.

```
/say  ->  commands/say.md  ->  scripts/say-last-response.py
            (kipi-core plugin, propagates to every instance via kipi update)
```

`say-last-response.py`:
1. Find the active transcript: newest `*.jsonl` in
   `~/.claude/projects/<cwd-slug>/` (slug from `$CLAUDE_PROJECT_DIR`).
2. Extract the last **pure-prose** assistant message (text, no `tool_use`),
   which skips the `/say` turn's own tool call and returns the prior response.
3. Strip markdown so punctuation is not voiced.
4. Chunk to <=4000 chars (API ceiling 4096) on paragraph/sentence boundaries.
5. Synthesize each chunk via `POST /v1/audio/speech`
   (`gpt-4o-mini-tts`, `alloy`; override via `KIPI_TTS_MODEL`/`KIPI_TTS_VOICE`).
6. Concatenate mp3 bytes, play detached via `afplay`, record PID for `stop`.

Key resolution: `$OPENAI_API_KEY`, else `~/.config/kipi/openai-key` (gitignored
secret, same pattern as the Slack webhook). Missing key = one-line error, exit 1.

Flags for verification without a key/device: `--dry-run`, `--dump-chunks`,
`--no-play`, and the `stop` verb.

## Risks and rollback

- **Transcript heuristic mis-picks the message.** If the readable response
  itself contained a tool call, it is skipped and an older prose message is
  read. Mitigation: founder's explanations are pure prose; acceptable for v1.
  Backout: delete the two files; no shared state touched.
- **mp3 byte-concatenation** relies on same-format chunks from one model; safe
  for OpenAI tts mp3 output. If it ever glitches, switch to sequential
  per-chunk `afplay`.
- **Cost.** Each `/say` is a paid OpenAI call. Manual-only trigger bounds it to
  intentional use.
- **Load path.** Live `/say` loads from the marketplace clone, not this repo's
  `plugins/`. Goes live for the founder after a marketplace sync / `kipi update`.
- Rollback is clean: remove `commands/say.md` and `scripts/say-last-response.py`;
  no migrations, no canonical edits, no bus changes.

## Open questions

- Default voice/model — `alloy` / `gpt-4o-mini-tts` chosen; revisit after the
  founder hears it.
- Whether a future v2 adds auto length-gated speaking via a Stop hook.

## Issues

```json
[]
```
