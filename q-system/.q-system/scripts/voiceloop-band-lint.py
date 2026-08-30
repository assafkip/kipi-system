#!/usr/bin/env python3
"""voiceloop-band-lint: run the OTHER half of the voice engine on written drafts.

Pairs with `.claude/rules/voice-loop-anywhere.md` (status DETECTED).

WHY THIS EXISTS, AND WHY IT IS NOT `voice-check` (measured 2026-08-29):
The voice engine has two halves. `voice-lint.py` owns banned vocabulary and
phrasing; it is ALREADY wired PostToolUse and it already exits 2 on a blocking
violation. `voiceloop` owns the half voice-lint structurally cannot see: measured
style BANDS, TEMPLATED SHAPES, and verbatim ECHO of the corpus. Only the first
half was reaching drafts. So "the voice engine fires on drafts" was half true,
and a half-run check reads exactly like a clean one -- the same scar that made
`voice-check` chain the two in the first place.

This hook is the missing half, not the chokepoint. Shelling `voice-check` here
would re-run voice-lint on every draft write and double-report it, because
voice-lint is its own wired hook. The chokepoint property lives at the settings
level instead: both halves fire on every draft write, one blocking, one detecting.
`voice-check` remains the chokepoint for a HUMAN running a draft by hand, where
nothing else is wired.

WHY DETECTED AND NOT ENFORCED (the measurement that decided it):
Over the 2577 files that `is_published_path` accepts across the 26 live instances,
a 200-file random sample tripped voice-check on 122 of them -- 61%. This hook
ships to every instance via `settings-template.json`, so exit 2 would block ~60%
of all draft writes fleet-wide on day one. A gate red on its own population gets
switched off, and a gate that is off protects nothing. Same call, same reason, as
`coding-audhd.md` (ASK-132). Flipping this to blocking is a founder decision made
in the open, after the population is clean enough to survive it.

SCOPE IS IMPORTED, NOT REIMPLEMENTED:
`is_published_path` comes from voice-lint.py itself. A second copy of that regex
list would drift, and then the two halves of one engine would disagree about what
a draft is. Importing it also means this hook cannot silently widen its own blast
radius.

THE SELF-MATCH EXEMPTION (a measured false positive, not a hypothetical):
Of the 3 files in that sample where voiceloop fired and voice-lint did not, one
was `q-consult/voice/linkedin-comment-granola-actual-2026-08-27.md` -- a file that
LIVES IN THE CORPUS. It was reported as echoing corpus phrasing because it IS the
corpus phrasing. Scoring a corpus member against the corpus containing it is
guaranteed to fire and carries no information, so corpus members are skipped.

EXIT CONTRACT: 0 on every path. DETECTED means surfaces, never blocks.
A crash must not wedge draft writes fleet-wide, so unexpected errors also exit 0
-- but they SAY SO on stderr rather than passing quietly.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKIP_MARKER = "voiceloop-band-lint-skip"
TIMEOUT_SECONDS = 30


def _load_voice_lint():
    """Import voice-lint.py as a module. Hyphenated name, so importlib not import."""
    here = Path(__file__).resolve().parent
    target = here / "voice-lint.py"
    if not target.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_voice_lint_for_bands", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _corpus_dir():
    raw = os.environ.get("VOICE_LOOP_CORPUS") or "~/projects/consulting/q-consult/voice"
    return Path(os.path.expanduser(raw))


def _is_corpus_member(file_path, corpus):
    """True when the draft lives inside the corpus it would be scored against."""
    try:
        Path(file_path).resolve().relative_to(corpus.resolve())
        return True
    except (ValueError, OSError):
        return False


def _emit(message):
    print(message, file=sys.stderr)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if payload.get("tool_name", "") not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)

    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path:
        sys.exit(0)

    voice_lint = _load_voice_lint()
    if voice_lint is None:
        # A MISSING GATE IS NOT A PASS. Without voice-lint we cannot even tell
        # whether this path is a draft, so scope is unknown, not empty.
        _emit("voiceloop-band-lint NOT CHECKED: voice-lint.py not found next to "
              "this script, so draft scope could not be resolved.")
        sys.exit(0)

    if not voice_lint.is_published_path(file_path):
        sys.exit(0)

    corpus = _corpus_dir()
    if _is_corpus_member(file_path, corpus):
        sys.exit(0)

    try:
        text = Path(file_path).read_text(encoding="utf-8")
    except OSError:
        sys.exit(0)
    if SKIP_MARKER in text:
        sys.exit(0)
    if not text.strip():
        sys.exit(0)

    if shutil.which("voiceloop") is None:
        _emit("voiceloop-band-lint NOT CHECKED: `voiceloop` is not on PATH, so "
              "bands, templated shapes and corpus echo were NOT checked on "
              f"{file_path}. Vocabulary was still checked by voice-lint.")
        sys.exit(0)

    if not corpus.is_dir():
        _emit("voiceloop-band-lint NOT CHECKED: corpus directory does not exist "
              f"at {corpus}, so bands, shapes and echo were NOT checked on "
              f"{file_path}. Set VOICE_LOOP_CORPUS for this instance.")
        sys.exit(0)

    env = dict(os.environ)
    env["VOICE_LOOP_CORPUS"] = str(corpus)
    try:
        result = subprocess.run(
            ["voiceloop", "score", file_path],
            capture_output=True, text=True, env=env, timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _emit(f"voiceloop-band-lint NOT CHECKED: voiceloop exceeded "
              f"{TIMEOUT_SECONDS}s on {file_path}.")
        sys.exit(0)
    except OSError as exc:
        _emit(f"voiceloop-band-lint NOT CHECKED: could not run voiceloop ({exc}).")
        sys.exit(0)

    if result.returncode != 0:
        body = (result.stdout or "").strip() or (result.stderr or "").strip()
        _emit(f"voiceloop (bands, templated shapes, corpus echo) on {file_path}:\n"
              f"{body}\n"
              "DETECTED, not blocking. Add "
              f"<!-- {SKIP_MARKER} --> to silence this file deliberately.")

    sys.exit(0)


if __name__ == "__main__":
    main()
