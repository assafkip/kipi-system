#!/usr/bin/env python3
"""The send-time voice check: the exit verifies the bytes that LEAVE (ASK-4969 part 3).

    voice_send_check.py --hook                       # PreToolUse payload on stdin
    voice_send_check.py --surface client-email file  # a sender script; - for stdin
    from voice_send_check import send_check; send_check(text, surface).ok

Exit 0: the bytes passed the full check, or the tool is not a sender. Exit 2: refused.

## Not a second engine

The check is `voice_full_gate.check` (#851), the fleet's one entry point. This file adds only
the two things a SEND needs that a draft check does not:

  - which bytes: the tool input of the send call, not a draft file. why: a hook on the draft
    file (PostToolUse) runs before the edit that changes it, and a Stop hook reads the chat
    turn; neither sees what the sender is about to transmit. The ASK-4637 census found drafts
    that were checked and then edited before they left.
  - a receipt keyed by sha256(bytes) and the surface. The full check takes about 70 s, so a
    send of bytes that already passed spends the receipt instead of running it again. A
    receipt for text A never clears text B: the key is the hash of what leaves, and the
    receipt body is compared to the recomputed hash, so a renamed file clears nothing.

## Single writer

`_mint` is the only writer of the receipt directory (KIPI_VOICE_RECEIPTS, default
~/.local/state/kipi/voice-receipts) and only after a PASS. A REFUSE or OUTAGE mints nothing.

## Limit, stated

A receipt is a cache of a verdict, not a signature. Anything that can write the receipt
directory can forge one. The directory is outside every checkout; this is tamper-evident
against an accident (a stale file, a renamed file), not against an adversary with the user's
shell. Closing that needs the signed receipt the engine mints (gate_draft.verify), which is a
later step and not claimed here.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voice_full_gate  # noqa: E402

RECEIPTS_ENV = "KIPI_VOICE_RECEIPTS"
# The Gmail connector's senders. A tool that sends is wired here AND in settings-template.json's
# PreToolUse matcher; a test holds the two lists together.
SEND_TOOLS = {
    "mcp__claude_ai_Gmail__send_message": "client-email",
    "mcp__claude_ai_Gmail__reply": "client-email",
    "mcp__claude_ai_Gmail__forward": "client-email",
}
# A sender is any Gmail-connector tool whose name has the token send, reply or forward. By
# token, not substring: list_forwarding_addresses is not a sender. why a verb pattern and not
# a name list (PR #859 round 2): a name allowlist refused mcp__claude_ai_Gmail__gmail_search_messages,
# a read the fleet's preflight calls, and a second connector spells its senders differently.
# Limit, stated: a sender renamed to a verb outside this set is not seen. SEND_TOOLS above
# names the three known ones exactly; the pattern widens it to renamed or second-connector ones.
SENDER_MATCHER = r"mcp__[A-Za-z0-9_]*[Gg]mail[A-Za-z0-9_]*__(.*_)?(send|reply|forward)(_.*)?"
_SENDER_RE = re.compile(SENDER_MATCHER)
MODE_ENV = "KIPI_VOICE_SEND_MODE"   # "report": log the verdict and let the send through
LOG_ENV = "KIPI_VOICE_SEND_LOG"
RECEIPT_TTL_S = 24 * 3600
_TAGS = re.compile(r"<[^>]+>")


def receipts_dir() -> Path:
    env = os.environ.get(RECEIPTS_ENV)
    return Path(env).expanduser() if env else Path.home() / ".local" / "state" / "kipi" / "voice-receipts"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def text_that_leaves(tool_name: str, tool_input: dict) -> str | None:
    """The text the sender will transmit, or None when the hook cannot read it.

    None for a send of an existing Gmail draft (`draftId`): those bytes live in Gmail and the
    tool input does not carry them, so no check here could be about what leaves."""
    if not isinstance(tool_input, dict) or tool_input.get("draftId"):
        return None
    parts = []
    for key in ("subject", "body"):
        if isinstance(tool_input.get(key), str):
            parts.append(tool_input[key])
    if isinstance(tool_input.get("htmlBody"), str):
        parts.append(html.unescape(_TAGS.sub(" ", tool_input["htmlBody"])))
    text = "\n\n".join(p for p in parts if p.strip())
    return text or None


def _receipt_path(directory: Path, sha: str, surface: str) -> Path:
    return directory / ("%s-%s.json" % (sha, surface))


def _spend(directory: Path, text: str, surface: str) -> bool:
    sha = _sha(text)
    try:
        rec = json.loads(_receipt_path(directory, sha, surface).read_text())
    except (OSError, ValueError):
        return False
    # why the TTL (PR #859 round 1): the receipt carries no manifest hash, so a rule change
    # would otherwise leave a PASS valid for the same bytes forever. A day bounds that.
    fresh = isinstance(rec, dict) and isinstance(rec.get("ts"), (int, float)) \
        and 0 <= time.time() - rec["ts"] <= RECEIPT_TTL_S
    return (isinstance(rec, dict) and fresh and rec.get("sha256") == sha
            and rec.get("surface") == surface and rec.get("verdict") == "PASS")


def _mint(directory: Path, text: str, surface: str, verdict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    sha = _sha(text)
    path = _receipt_path(directory, sha, surface)
    tmp = path.with_suffix(".tmp-%d" % os.getpid())
    tmp.write_text(json.dumps({"sha256": sha, "surface": surface, "verdict": "PASS",
                               "ts": int(time.time()), "parts": verdict.parts}))
    os.replace(tmp, path)  # atomic: a reader never sees half a receipt


def send_check(text: str, surface: str, *, receipts_dir: Path | str | None = None,
               **check_kw) -> "voice_full_gate.Verdict":
    """PASS only if the full check passes on exactly these bytes (or a receipt for exactly
    these bytes and this surface was minted by a prior PASS)."""
    directory = Path(receipts_dir) if receipts_dir is not None else globals()["receipts_dir"]()
    if _spend(directory, text, surface):
        return voice_full_gate.Verdict("PASS", surface, notes=["receipt spent: same bytes passed before"])
    verdict = voice_full_gate.check(text, surface, **check_kw)
    if verdict.ok:
        try:
            _mint(directory, text, surface, verdict)
        except OSError:
            verdict.notes.append("receipt not minted (directory unwritable); the next send re-runs the check")
    return verdict


def _log(row: dict) -> None:
    """One row per hook decision: the block rate is measured, not guessed. Never changes a verdict."""
    path = Path(os.environ.get(LOG_ENV) or Path.home() / ".local" / "state" / "kipi" / "voice-send-log.jsonl")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (json.dumps(dict(row, ts=int(time.time()))) + "\n").encode())
        finally:
            os.close(fd)
    except OSError:
        pass


def _hook(payload_text: str) -> int:
    try:
        payload = json.loads(payload_text)
        tool = payload["tool_name"]
    except (ValueError, KeyError, TypeError):
        print("voice_send_check: hook payload unreadable: the send gate cannot run", file=sys.stderr)
        return voice_full_gate.EXIT_REFUSE
    surface = SEND_TOOLS.get(tool) or ("client-email" if _SENDER_RE.fullmatch(tool) else None)
    if surface is None:
        return voice_full_gate.EXIT_PASS  # not a sender: nothing leaves
    text = text_that_leaves(tool, payload.get("tool_input") or {})
    if text is None:
        print("voice_send_check: REFUSE: %s carries no text this hook can read (a draftId send "
              "transmits bytes held in Gmail). Send the text itself so the bytes that leave are "
              "the bytes checked." % tool, file=sys.stderr)
        return voice_full_gate.EXIT_REFUSE
    verdict = send_check(text, surface)
    if verdict.ok:
        _log({"tool": tool, "decision": "pass", "surface": surface})
        return voice_full_gate.EXIT_PASS
    # The founder's override, set in the environment the hook is launched from (his shell or a
    # launchd plist), so a session cannot grant it to itself mid-run. Logged on every use.
    if os.environ.get(MODE_ENV) == "report":
        _log({"tool": tool, "decision": "report-only-pass", "verdict": verdict.verdict,
              "reasons": verdict.reasons[:3], "surface": surface})
        print("voice_send_check: %s on the bytes that leave, NOT blocking (%s=report):\n%s"
              % (verdict.verdict, MODE_ENV, verdict.to_json()), file=sys.stderr)
        return voice_full_gate.EXIT_PASS
    _log({"tool": tool, "decision": "refuse", "verdict": verdict.verdict,
          "reasons": verdict.reasons[:3], "surface": surface})
    print("voice_send_check: %s on the bytes that leave (%s):\n%s"
          % (verdict.verdict, tool, verdict.to_json()), file=sys.stderr)
    return voice_full_gate.EXIT_REFUSE


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="voice_send_check")
    ap.add_argument("file", nargs="?", help="the bytes that leave, or - for stdin")
    ap.add_argument("--hook", action="store_true", help="read a PreToolUse payload on stdin")
    ap.add_argument("--surface", help="the gated surface of a sender script's text")
    args = ap.parse_args(argv)
    if args.hook:
        return _hook(sys.stdin.read())
    if not (args.file and args.surface):
        ap.print_usage(sys.stderr)
        return voice_full_gate.EXIT_USAGE
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print("voice_send_check: cannot read the bytes (%s)" % exc, file=sys.stderr)
        return voice_full_gate.EXIT_REFUSE
    verdict = send_check(text, args.surface)
    print(verdict.to_json())
    return voice_full_gate.EXIT_PASS if verdict.ok else voice_full_gate.EXIT_REFUSE


if __name__ == "__main__":
    sys.exit(main())
