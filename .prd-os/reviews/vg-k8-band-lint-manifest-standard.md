Reviewer: claude-review (Opus general-purpose subagent, read-only), 2026-11-09.
Verdict: REQUEST CHANGES.
1. major: `channel not in TABLE_CHANNELS` raises TypeError for a list or object engine_channel; hook exits 1. Reproduced live.
2. minor: resolver refusals other than ambiguity dropped silently when a voice-check.json exists.
Both fixed in the follow-up edit; 47 tests pass.
