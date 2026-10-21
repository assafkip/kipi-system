---
description: Run the full voice review on one draft by hand (bands, shapes, echo, gate roster, channel rules).
argument-hint: <file> [--channel linkedin|x|substack|medium|email|dm|comment]
allowed-tools: Bash
---

Run the voice engine on one draft, the same way the draft-write hook does, without
having to write the file first.

The channel comes from the file's path (`linkedin-post-*.md` reviews as linkedin,
`x-thread-*.md` as x, and so on), using the hook's own table, so this command and
the hook never disagree. A path with no channel in it gets the lighter `score`
unless you pass `--channel`. An unknown channel is refused, not guessed.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/voice-loop.py" $ARGUMENTS
```

Report its stdout verbatim: the first line says which engine ran, then the
findings, then the NOT CHECKED lines. Exit 1 means findings, not a failure. Exit 2
means nothing ran; surface stderr verbatim and do not retry with a guessed channel.
