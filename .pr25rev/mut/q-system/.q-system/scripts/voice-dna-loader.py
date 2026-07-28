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


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    user_prompt = payload.get("prompt", "")
    if not user_prompt or not looks_like_writing_request(user_prompt):
        sys.exit(0)
    voice_dna_path = resolve_path(VOICE_DNA_REL_PATH)
    samples_path = resolve_path(WRITING_SAMPLES_REL_PATH)
    context = build_context(voice_dna_path, samples_path)
    output = {"hookSpecificOutput": {"additionalContext": context}}
    sys.stdout.write(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
