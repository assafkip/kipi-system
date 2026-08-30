#!/usr/bin/env python3
"""
voice-dna-loader.py - Inject voice DNA into context on writing requests.

UserPromptSubmit hook for Claude Code.

Detects writing requests (post, draft, comment, reply, etc.) and reads the
canonical voice-dna.md + writing-samples.md from the kipi-core founder-voice
skill. Injects both as additionalContext so Claude literally cannot draft
without seeing the voice profile.

This is the deterministic counterpart to the voice-lint PostToolUse hook.
Lint catches deterministic violations after the write. Loader makes sure the
positive voice anchor is in context before the write.

Resolution order for voice DNA path:
  1. <project_root>/plugins/kipi-core/skills/founder-voice/references/voice-dna.md
  2. ~/projects/kipi-system/plugins/kipi-core/skills/founder-voice/references/voice-dna.md

If the local file is the empty template, fall back to the canonical kipi-system
file. If neither is populated, inject a warning so the founder knows the DNA
is missing.

Stdlib only.
"""

import json
import os
import re
import sys
from pathlib import Path


WRITING_TRIGGER_PATTERNS = [
    # Direct write intents
    r"\bwrit\w*\b", r"\bdraft\w*\b", r"\bcompose\w*\b",
    r"\brewrite\w*\b", r"\brevise\w*\b", r"\bedit\w*\b",
    r"\bredraft\w*\b", r"\bredo\b", r"\bpolish\w*\b",
    # Content surfaces
    r"\bpost\b", r"\bemail\w*\b", r"\bdm\b", r"\bmessage\b", r"\bmsg\b",
    r"\breply\w*\b", r"\brespond\w*\b", r"\bcomment\w*\b", r"\bresponse\b",
    r"\barticle\b", r"\bessay\b", r"\bnewsletter\b",
    r"\bsend\b", r"\btext\b", r"\bping\b",
    # Platform-specific
    r"\blinkedin\b", r"\btwitter\b", r"\bmedium\b",
    r"\bsubstack\b", r"\bthread\b", r"\btweet\w*\b",
    r"\binstagram\b", r"\btiktok\b", r"\breddit\b",
    # Outreach / negotiation
    r"\boutreach\b", r"\bsales letter\b", r"\bcold email\b",
    r"\bcounter\b", r"\bcounter-?offer\b", r"\bnegotiat\w*\b",
    r"\bpitch\b", r"\bproposal\b", r"\boffer\b", r"\brebut\w*\b",
    # Structural elements
    r"\bcaption\b", r"\bheadline\b", r"\bsubject line\b",
    r"\bhook\b", r"\bopener\b", r"\bcloser\b", r"\bcta\b",
    # Meta intents
    r"\bvoice\b", r"\bcadence\b", r"\bdraft a\b",
    r"\bwhat (should|do) I (write|say|send|reply)\b",
    r"\bcan you (write|draft|compose)\b",
]

VOICE_DNA_REL_PATH = "plugins/kipi-core/skills/founder-voice/references/voice-dna.md"
WRITING_SAMPLES_REL_PATH = "plugins/kipi-core/skills/founder-voice/references/writing-samples.md"
CANONICAL_KIPI_SYSTEM = Path.home() / "projects" / "kipi-system"

EMPTY_TEMPLATE_MARKERS = ("(paste here)", "{{SETUP_NEEDED}}", "{{NAME}}")
MIN_POPULATED_BYTES = 1500


def looks_like_writing_request(text):
    text_lower = text.lower()
    for pattern in WRITING_TRIGGER_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    return False


def find_project_root():
    cwd_env = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if cwd_env and Path(cwd_env).exists():
        return Path(cwd_env)
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".claude").exists():
            return parent
    return None


def file_is_populated(path):
    if not path.exists():
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return False
    if len(content) < MIN_POPULATED_BYTES:
        return False
    for marker in EMPTY_TEMPLATE_MARKERS:
        if marker in content:
            return False
    return True


def resolve_path(relative_path):
    project_root = find_project_root()
    if project_root:
        local = project_root / relative_path
        if file_is_populated(local):
            return local
    canonical = CANONICAL_KIPI_SYSTEM / relative_path
    if file_is_populated(canonical):
        return canonical
    return None


def build_context(voice_dna_path, samples_path):
    parts = [
        "[voice-dna-loader] Writing request detected. You MUST apply the founder's "
        "voice DNA below before drafting any text another person will read. Do not "
        "paraphrase the rules. Match the specific patterns documented: witness lines, "
        "namer pattern, tester pattern, the 4-beat declarative WITH specifics (not "
        "the cadence alone), show-don't-explain. If the draft has the shape of the "
        "voice without the substance (scar, named thing, test, evidence), it reads "
        "as AI cadence. The voice-lint PostToolUse hook will catch some violations "
        "but not all. Subjective checks (specificity, scar, personality) are on you."
    ]
    if voice_dna_path:
        voice_dna_content = voice_dna_path.read_text(encoding="utf-8")
        parts.append(f"\n\n=== VOICE DNA (from {voice_dna_path}) ===\n\n{voice_dna_content}")
    else:
        parts.append(
            "\n\n[WARNING] No populated voice-dna.md found at the local instance or in "
            f"the canonical kipi-system path ({CANONICAL_KIPI_SYSTEM}). Drafts will lack "
            "voice anchor. Populate the file before drafting."
        )
    if samples_path:
        samples_content = samples_path.read_text(encoding="utf-8")
        parts.append(f"\n\n=== WRITING SAMPLES (from {samples_path}) ===\n\n{samples_content}")
    return "".join(parts)


def build_context_from_corpus():
    """The one voice corpus, through voiceloop. Returns None when unavailable.

    why this replaced the 40KB dump (2026-08-13): this hook read
    `founder-voice/references/voice-dna.md` + `writing-samples.md`, 40,527 bytes of
    voice prose that the 2026-08-13 consolidation had already retired. The skill
    pointed at the consulting corpus while the RUNTIME kept loading the private
    copies, so the two-source drift that consolidation removed was still live on
    every writing request. An adversarial review found it; the docs said it was gone.

    Two things were wrong with the old payload regardless of which source it read:
    55K of voice prose was MEASURED making output worse, and a fixed dump cannot
    match the channel or the length of the piece, which is what produced a formal
    long-form X draft that same day.
    """
    root = find_project_root()
    if not root:
        return None
    sys.path.insert(0, str(root / "plugins" / "kipi-core"))
    try:
        from voiceloop import corpus, selector
    except Exception:
        return None

    voice_dir = os.environ.get("KIPI_VOICE_DIR") or str(
        Path.home() / "projects" / "consulting" / "q-consult" / "voice")
    if not Path(voice_dir, "exemplars.jsonl").exists():
        return None
    try:
        voice = corpus.load(voice_dir)
        rows = voice.active_exemplars()
    except Exception:
        return None
    if not rows:
        return None

    # Small and deliberately NOT length-matched: this hook cannot know the channel or
    # the target length from a prompt, and guessing is the thing the selector exists
    # to stop. It ships identity plus three rows as an anchor and names the command
    # that does the matching. Do not grow this into a second selector.
    picked = selector.select(rows, "x", 0, k=3)
    parts = [
        "[voice-dna-loader] Writing request detected. The voice corpus is "
        f"{voice_dir}. This hook reads that corpus only; the "
        "founder-voice/references copies are retired and are no longer loaded.\n\n"
        "Before drafting anything another person reads, run the selector so the "
        "exemplars match the CHANNEL and the LENGTH of the piece:\n\n"
        f"    KIPI_VOICE_DIR={voice_dir} python3 "
        f"{root}/plugins/kipi-core/voiceloop/voice_ref.py --channel x --words <target>\n\n"
        "Length is a real axis: the x corpus runs 5 to 55 words with one 479-word "
        "row, so a long piece written against short rows comes out formal. "
        "Substance over cadence: with no scar, named thing, test or evidence, the "
        "shape of the voice still reads as AI. voice-lint catches part of it.\n",
        f"\n=== WHO IS WRITING ===\n\n{voice.identity.strip()}\n",
    ]
    corrections = voice.active_corrections()
    if corrections:
        parts.append("\n=== CORRECTIONS (these override anything older) ===\n\n")
        for c in corrections[-4:]:
            parts.append(f"- [{c.get('date', '?')}] {c.get('instruction', '').strip()}\n")
    parts.append("\n=== A FEW REAL ROWS (anchor only, NOT length-matched) ===\n")
    for r in picked:
        words = r.get("words") or len((r.get("text") or "").split())
        parts.append(f"\n--- [{r.get('id')}] {words} words\n{(r.get('text') or '').strip()}\n")
    return "".join(parts)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    user_prompt = payload.get("prompt", "")
    if not user_prompt or not looks_like_writing_request(user_prompt):
        sys.exit(0)
    # The corpus path first. The legacy dump stays reachable ONLY when voiceloop or the
    # corpus is absent, so this cannot leave an instance with no voice anchor at all;
    # it is no longer the normal path anywhere that has both.
    context = build_context_from_corpus()
    if context is None:
        voice_dna_path = resolve_path(VOICE_DNA_REL_PATH)
        samples_path = resolve_path(WRITING_SAMPLES_REL_PATH)
        context = build_context(voice_dna_path, samples_path)
    output = {"hookSpecificOutput": {"additionalContext": context}}
    sys.stdout.write(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
