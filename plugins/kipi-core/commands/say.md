---
description: Synthesize the previous assistant response to audio; autoplays locally with controls.
argument-hint: [stop]
allowed-tools: Bash
---

Turn the previous response into audio you can play with speed/seek/pause. No
copy-paste into a TTS app.

`/say` synthesizes the last assistant prose response with OpenAI TTS, writes it
to a stable mp3, and AUTOPLAYS it in a new Terminal window (local, mpv present)
so your keyboard drives speed, seek, and pause — a real terminal takes key
presses, a background player cannot. Over SSH, or without mpv, or with
`--no-play`, it skips the window and just prints the play command. `/say stop`
clears any stray playback.

Call the script FIRST, with no preamble text. (The script reads the last
*prose* assistant message from the transcript; any text you emit before the
tool call would become that message and get read instead of the founder's
intended response.)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/say-last-response.py" $ARGUMENTS
```

After it runs, report its stdout verbatim (it prints the autoplay status + the
ready-to-run play command). If it exits non-zero, surface stderr verbatim (e.g.
the no-key setup line) and do not retry.

## Playing it manually (SSH, --no-play, or a second listen)

Autoplay opens a Terminal window for you locally. When you want to drive it
yourself instead — over SSH, or to replay — use these:

- Local / in the SSH session (mini speakers): `mpv ~/.config/kipi/say-last.mp3`
- Laptop audio over the SSH you already have: `ssh <mini> 'cat ~/.config/kipi/say-last.mp3' | mpv -`
- Convenience helper: `say-play` (local) or `say-play --remote <mini>` (laptop)

mpv keys: `[` `]` speed | `<-`/`->` seek 5s | `up`/`down` 60s | `space` pause | `q` quit.
Needs `brew install mpv` (ffplay is a no-speed fallback if mpv is absent).
