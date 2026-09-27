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
import re
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
    """Say it on BOTH channels, because one of them is discarded.

    Codex major, PR #278. This hook exits 0 by design -- it DETECTS, it does not
    block. But the PostToolUse contract is that stderr is fed to Claude only on
    exit 2; on exit 0 it goes nowhere. So every finding this script produced,
    and every NOT CHECKED warning it produced, was written to a channel nobody
    reads. The DETECTED claim in the rule surfaced exactly nothing.

    The documented non-blocking channel is exit 0 plus
    hookSpecificOutput.additionalContext, the same shape
    code_claim_grounding_guard.py uses and for the same reason. The nesting is
    load-bearing: a TOP-LEVEL additionalContext is silently ignored (the scar is
    recorded at token-guard.py:743), which would have reproduced this defect in
    a new place.

    stderr is kept as well. It is where a human tailing the hook log looks, and
    it costs nothing.
    """
    print(message, file=sys.stderr)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": message,
    }}))


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
    except UnicodeDecodeError:
        # Codex minor, PR #278: the docstring promises exit 0 on every path, and
        # a non-UTF-8 draft raised an uncaught UnicodeDecodeError and exited 1 --
        # which a PostToolUse hook reports as a failed hook, on a file this
        # script has no opinion about. Not silent: a draft it cannot read is a
        # draft it did not check, and NOT CHECKED is the honest word.
        _emit("voiceloop-band-lint NOT CHECKED: could not decode "
              f"{file_path} as UTF-8, so bands, templated shapes and corpus "
              "echo were NOT checked on it.")
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

        # A MISSING FINGERPRINT IS NOT A STYLE FINDING (Codex minor, PR #278).
        # `voiceloop score` emits `fingerprint: no fingerprint.json ...` as a
        # finding and exits 1, so branching on the return code alone reported
        # "the corpus has no fingerprint" as though the draft had a style
        # problem -- on EVERY draft write, in any instance whose corpus has not
        # been fingerprinted. That is a false positive that arrives constantly,
        # which is how a detector gets ignored.
        #
        # The two are separated by reading the lines, not the exit code: a
        # `fingerprint:` line is a NOT CHECKED condition about the corpus, and
        # only what remains is about this draft.
        lines = [l for l in body.splitlines() if l.strip()]

        # DID THE ENGINE ACTUALLY SCORE? (Codex major + minor, PR #278 round 2.)
        #
        # A completed `voiceloop score` always prints its tally --
        # "N finding(s) against M exemplar(s)" -- whether N is 0 or 12. Its
        # absence means the run did not complete: a crash, a bad argument, a
        # corpus it could not read. The previous version had no such check, so a
        # FAILED ENGINE was reported as style findings about the draft, under a
        # message telling the author to add the skip marker. That is the worst
        # possible remedy for an engine fault: it silences the detector on that
        # file permanently, and the file was never the problem.
        #
        # And a nonzero exit with NO output emitted nothing at all, on either
        # channel -- a missing gate reading as a pass, which is the exact defect
        # class this hook's own docstring is about.
        scored = any(re.search(r"\d+ finding\(s\) against \d+ exemplar", l)
                     for l in lines)
        if not scored:
            detail = " | ".join(l.strip() for l in lines[:3]) or (
                "no output at all (exit %d)" % result.returncode)
            _emit("voiceloop-band-lint NOT CHECKED: `voiceloop score` did not "
                  f"complete on {file_path}, so bands, templated shapes and "
                  "corpus echo were NOT checked. This is an ENGINE fault, not a "
                  "finding about the draft, so the skip marker is the wrong fix: "
                  f"look at voiceloop itself. Output: {detail}")
            sys.exit(0)

        not_checked = [l for l in lines if l.strip().startswith("fingerprint:")]
        findings = [l for l in lines
                    if l not in not_checked and not l.strip().startswith("NOT CHECKED:")]
        # The tally counts the fingerprint line too, so it cannot stand in for a
        # real finding.
        real = [l for l in findings
                if not re.match(r"^\s*\d+ finding\(s\) against \d+ exemplar", l)]

        if not_checked and not real:
            _emit("voiceloop-band-lint NOT CHECKED: the corpus has no "
                  f"fingerprint, so bands were NOT computed for {file_path}. "
                  "Run `voiceloop fingerprint` in the corpus directory. "
                  f"({not_checked[0].strip()})")
        elif real:
            _emit(f"voiceloop (bands, templated shapes, corpus echo) on {file_path}:\n"
                  + "\n".join(real) + "\n"
                  + ("(bands were NOT computed: "
                     + not_checked[0].strip() + ")\n" if not_checked else "")
                  + "DETECTED, not blocking. Add "
                  f"<!-- {SKIP_MARKER} --> to silence this file deliberately.")

    sys.exit(0)


if __name__ == "__main__":
    main()
