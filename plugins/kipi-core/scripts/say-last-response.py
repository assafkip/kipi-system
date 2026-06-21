#!/usr/bin/env python3
"""
say-last-response.py - Read the last assistant response aloud via OpenAI TTS.

Backs the `/say` slash command (kipi-core). The founder listens to long
responses instead of reading them; this removes the copy-paste-into-Speechify
step. Manual trigger only — nothing auto-fires.

What it does:
  1. Find the active session transcript (newest *.jsonl for this project).
  2. Extract the last *pure-prose* assistant message (skips the tool-calling
     message of the current /say turn, so it reads the PRIOR response).
  3. Strip markdown so punctuation is not read aloud.
  4. Chunk to <=4000 chars (OpenAI hard limit is 4096/request) and synthesize
     each chunk via POST https://api.openai.com/v1/audio/speech.
  5. Write the mp3 to a STABLE path and print the play command. It does NOT
     auto-play: the founder runs the player themselves so they get a keyboard
     for speed/seek/pause controls (a detached player can take no key presses).
     Same stable file is what makes over-SSH playback work — pull it to the
     laptop and play there. (2026-06-21: controls + ssh are one design.)

API key: read from $OPENAI_API_KEY, else ~/.config/kipi/openai-key. No key is a
clean one-line error, not a traceback.

Flags:
  --dry-run       Print the extracted, markdown-stripped text. No API call.
  --dump-chunks   Print chunk count and sizes. No API call. (length-handling proof)
  --no-play       Alias for the default now (synthesize + write file, no play).
  stop            Clear any stray playback (afplay/mpv).

Stdlib only (urllib for HTTP). Playback is the founder's own mpv/ffplay run.

Exit codes: 0 = ok, 1 = user-facing error (no key, no transcript, API failure).
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "kipi"
KEY_FILE = CONFIG_DIR / "openai-key"
PID_FILE = CONFIG_DIR / ".say-playing.pid"
# Stable output path (NOT a random tempfile). The founder plays this file
# themselves in their own terminal so they get a keyboard for speed/seek/pause
# controls — a player Claude launches detached can never take key presses. The
# stable path is also what makes over-SSH playback work: pull THIS file to the
# laptop and play it there. (2026-06-21: controls + ssh are one design.)
SAY_MP3 = CONFIG_DIR / "say-last.mp3"

TTS_URL = "https://api.openai.com/v1/audio/speech"
DEFAULT_MODEL = os.environ.get("KIPI_TTS_MODEL", "gpt-4o-mini-tts")
DEFAULT_VOICE = os.environ.get("KIPI_TTS_VOICE", "alloy")
CHUNK_LIMIT = 4000  # under the 4096-char API ceiling

MIN_TEXT_BYTES = 1  # a real response always clears this; tool-only messages are 0


def project_transcript_dir():
    """Map the project cwd to its Claude Code transcript directory."""
    cwd = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    slug = cwd.replace("/", "-")
    return Path.home() / ".claude" / "projects" / slug


def find_transcript():
    """Return the newest *.jsonl transcript for this project, or None."""
    transcript_dir = project_transcript_dir()
    if not transcript_dir.is_dir():
        return None
    candidates = sorted(
        transcript_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1] if candidates else None


def _message_text_and_tooluse(message):
    """Return (joined_text, has_tool_use) for one transcript message dict."""
    text_parts = []
    has_tool_use = False
    for item in message.get("content", []):
        if isinstance(item, str):
            text_parts.append(item)
        elif isinstance(item, dict):
            if item.get("type") == "text" and item.get("text"):
                text_parts.append(item["text"])
            elif item.get("type") == "tool_use":
                has_tool_use = True
    return ("\n\n".join(text_parts), has_tool_use)


def find_last_prose_response(transcript_path):
    """Last assistant message that is pure prose (has text, no tool_use).

    The current /say turn's assistant message carries a tool_use, so it is
    skipped and the prior real response is returned.
    """
    last_prose = ""
    for line in Path(transcript_path).read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except Exception:
            continue
        message = record.get("message", {})
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        text, has_tool_use = _message_text_and_tooluse(message)
        if has_tool_use or len(text) < MIN_TEXT_BYTES:
            continue
        last_prose = text
    return last_prose


def strip_markdown(text):
    """Remove markdown syntax so the reader voices words, not punctuation."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)   # fenced code
    text = re.sub(r"`([^`]*)`", r"\1", text)                  # inline code
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)         # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)      # links -> text
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)  # headings
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)          # blockquotes
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)      # bullet markers
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.M)      # numbered markers
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)           # bold
    text = re.sub(r"(\*|_)(.*?)\1", r"\2", text)              # italic
    text = re.sub(r"\n{3,}", "\n\n", text)                    # collapse blanks
    return text.strip()


def chunk_text(text, limit=CHUNK_LIMIT):
    """Split text into <=limit pieces on paragraph then sentence boundaries."""
    if len(text) <= limit:
        return [text] if text else []
    chunks = []
    buffer = ""
    for paragraph in text.split("\n\n"):
        for piece in _split_to_limit(paragraph, limit):
            if len(buffer) + len(piece) + 2 <= limit:
                buffer = f"{buffer}\n\n{piece}" if buffer else piece
            else:
                if buffer:
                    chunks.append(buffer)
                buffer = piece
    if buffer:
        chunks.append(buffer)
    return chunks


def _split_to_limit(paragraph, limit):
    """Yield sub-pieces of paragraph, each <=limit, splitting on sentences."""
    if len(paragraph) <= limit:
        return [paragraph]
    pieces = []
    buffer = ""
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        while len(sentence) > limit:                # one giant sentence
            pieces.append(sentence[:limit])
            sentence = sentence[limit:]
        if len(buffer) + len(sentence) + 1 <= limit:
            buffer = f"{buffer} {sentence}".strip()
        else:
            if buffer:
                pieces.append(buffer)
            buffer = sentence
    if buffer:
        pieces.append(buffer)
    return pieces


def read_api_key():
    """Return the OpenAI key from env or the gitignored secret file, or None."""
    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        return env_key.strip()
    if KEY_FILE.is_file():
        return KEY_FILE.read_text(encoding="utf-8").strip() or None
    return None


def synthesize_chunk(text, api_key, model, voice):
    """Call the OpenAI speech endpoint and return mp3 bytes for one chunk."""
    body = json.dumps(
        {"model": model, "voice": voice, "input": text, "response_format": "mp3"}
    ).encode("utf-8")
    request = urllib.request.Request(
        TTS_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def synthesize(chunks, api_key, model, voice):
    """Synthesize all chunks; return combined mp3 bytes or raise on failure."""
    audio = bytearray()
    for index, chunk in enumerate(chunks, start=1):
        sys.stderr.write(f"say: synthesizing chunk {index}/{len(chunks)}\n")
        audio.extend(synthesize_chunk(chunk, api_key, model, voice))
    return bytes(audio)


def ssh_server_ip():
    """Server IP the client SSH'd into, or None if not an SSH session.

    SSH_CONNECTION is "client_ip client_port server_ip server_port"; the
    laptop reaches THIS host (the mini) at server_ip to pull the audio.
    """
    parts = os.environ.get("SSH_CONNECTION", "").split()
    return parts[2] if len(parts) >= 3 else None


def play_instructions(minutes):
    """Build the copy-paste play commands (Option 1: founder launches player).

    No auto-play. The founder runs the player themselves so they get a keyboard
    for the speed/seek/pause controls. mpv is the only common player that does
    all three; ffplay is offered as a no-speed fallback if mpv is missing.
    """
    lines = [f"say: ready (~{minutes} min) at {SAY_MP3}"]
    if shutil.which("mpv"):
        lines.append(f"  play: mpv {SAY_MP3}")
    else:
        lines.append(f"  for controls: brew install mpv  ->  mpv {SAY_MP3}")
        if shutil.which("ffplay"):
            lines.append(
                f"  or now (seek+pause, no speed): "
                f"ffplay -nodisp -autoexit {SAY_MP3}"
            )
    server = ssh_server_ip()
    if server:
        lines.append(
            f"  laptop audio over ssh: ssh {server} 'cat {SAY_MP3}' | mpv -"
        )
    lines.append("  keys: [ ] speed | <-/-> seek 5s | up/down 60s | space pause | q quit")
    return "\n".join(lines)


def stop_playback():
    """Clear any stray playback. Returns a one-line status string.

    Option 1 has no detached player (the founder runs mpv/ffplay in their own
    terminal and quits with q), so this is a best-effort cleanup of leftovers.
    """
    pid = None
    if PID_FILE.is_file():
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = None
        PID_FILE.unlink(missing_ok=True)
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
            return "say: playback stopped."
        except ProcessLookupError:
            pass
    subprocess.run(["pkill", "-x", "afplay"], check=False)
    subprocess.run(["pkill", "-x", "mpv"], check=False)
    return "say: cleared any afplay/mpv playback."


KNOWN_ARGS = {"stop", "--dry-run", "--dump-chunks", "--no-play"}


def usage():
    """One-screen usage text. Printed for --help and on an unrecognized arg."""
    return (
        "say: usage: say-last-response.py [stop|--dry-run|--dump-chunks|--no-play]\n"
        "  (no args)      synthesize the last response to mp3, print the play command\n"
        "  stop           clear any stray playback\n"
        "  --dry-run      print the extracted text only (no API call)\n"
        "  --dump-chunks  print chunk count and sizes (no API call)\n"
        "  --no-play      alias for the default (synthesize, do not auto-play)\n"
        "  --help, -h     show this and exit"
    )


def fail(message):
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(1)


def load_text():
    """Resolve the prose to speak from the active transcript, or fail clean."""
    transcript = find_transcript()
    if transcript is None:
        fail("say: no transcript found for this project. Nothing to read.")
    prose = find_last_prose_response(transcript)
    if not prose.strip():
        fail("say: no prior assistant response found to read.")
    return strip_markdown(prose)


def write_audio(audio):
    """Write mp3 bytes to the stable path, overwriting the prior one."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SAY_MP3.write_bytes(audio)


def main():
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(usage())
        return
    unknown = [a for a in args if a not in KNOWN_ARGS]
    if unknown:
        # Reject before any synthesis. An unrecognized arg used to fall
        # through to a real (paid) OpenAI call; now it never does.
        fail(f"say: unrecognized argument(s): {' '.join(unknown)}\n{usage()}")

    if "stop" in args:
        print(stop_playback())
        return

    text = load_text()

    if "--dry-run" in args:
        print(text)
        return

    chunks = chunk_text(text)
    if "--dump-chunks" in args:
        print(f"chunks: {len(chunks)}")
        for index, chunk in enumerate(chunks, start=1):
            print(f"  chunk {index}: {len(chunk)} chars")
        return

    api_key = read_api_key()
    if not api_key:
        fail(
            "say: no OpenAI key. Set $OPENAI_API_KEY or write "
            f"{KEY_FILE} (chmod 600). Then re-run /say."
        )

    try:
        audio = synthesize(chunks, api_key, DEFAULT_MODEL, DEFAULT_VOICE)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        fail(f"say: OpenAI API error {error.code}: {detail}")
    except urllib.error.URLError as error:
        fail(f"say: network error reaching OpenAI: {error.reason}")

    write_audio(audio)
    minutes = max(1, round(len(text) / 950))  # ~950 chars/min spoken
    print(play_instructions(minutes))


if __name__ == "__main__":
    main()
