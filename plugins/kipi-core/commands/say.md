---
description: Read the previous assistant response aloud via OpenAI TTS (manual; macOS).
argument-hint: [stop]
allowed-tools: Bash
---

Read the previous response aloud. No copy-paste into a TTS app.

`/say` synthesizes the last assistant prose response with OpenAI TTS and plays
it in the background. `/say stop` stops playback.

Call the script FIRST, with no preamble text. (The script reads the last
*prose* assistant message from the transcript; any text you emit before the
tool call would become that message and get read instead of the founder's
intended response.)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/say-last-response.py" $ARGUMENTS
```

After it runs, report its one-line stdout verbatim and stop. If it exits
non-zero, surface stderr verbatim (e.g. the no-key setup line) and do not retry.
