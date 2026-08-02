---
description: Founder voice enforcement for external-facing written content
---

# Voice Rule (ENFORCED)

Apply the founder's voice skill ONLY when generating content that will be published or sent to another person. This includes:
- Social posts (LinkedIn, X, Reddit, Medium)
- Comments and replies on other people's posts
- DMs and emails
- Outreach messages
- Slide copy and deck text
- Talk tracks and scripts
- Any text the founder asks to "write," "draft," or "respond with"

Read the founder-voice skill's `references/voice-dna.md` and `references/writing-samples.md` before generating this content. Apply all rules including anti-AI detection patterns.

Do NOT apply voice rules to:
- Conversational responses to the founder (that's governed by AUDHD interaction rules)
- Internal notes, logs, system output
- Analysis, summaries, or recommendations for the founder's eyes only
- Code, config files, documentation

## Enforcement (the executables)

Enforced by `voice-lint.py` and `voice-substance-lint.py` (PostToolUse on Edit/Write) and `voice-stop-gate.py` (Stop hook), each wired in BOTH `.claude/settings.json` and `settings-template.json` so `kipi update` ships the switch and not only the script. Bypass the two lints per file with `<!-- voice-lint-skip -->`; the Stop gate honors no marker. A rule claiming ENFORCED while naming no executable is prompt-only, which is what `test-voice-enforcement-rule-wired.sh` holds.
