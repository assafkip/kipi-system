---
id: feedback-lands-where-artifacts-exist
kind: pattern
title: Feedback lands where artifacts exist, so a layer without a file absorbs no fixes
date: 2026-08-12
---

When an operator gives the same feedback repeatedly and the output keeps failing the same way, check which layers of the system have editable artifacts before diagnosing the feedback as vague or the model as weak. Fixes flow to whatever has a file: a prompt, a corpus, a gate list, a config. A concern with no artifact -- purpose, audience, the job the output is supposed to do -- cannot absorb a fix, so every round of feedback about it gets translated into the nearest layer that CAN be edited, and the actual complaint survives untouched.

Observed across six feedback events in four days on a content pipeline. The operator's complaint each time reduced to "these posts do not serve my business or my reader." Voice had a corpus, defects had fifteen gates, supply had seven lanes; the post's job had nothing. All six responses landed in voice, style, or supply. A later audit counted 13 of 51 negative rules as patches for damage earlier patches caused -- the signature of fixes circling a layer that was never the problem. The seventh batch passed every gate and failed the operator 0 for 8.

The companion trap: the system's documentation read as more connected than its runtime. Gate docstrings cited the audience research files as justification, so every audit-by-reading concluded the context was wired in. Rendering the actual prompt and searching it showed the entire business context was one sentence, and the audience files were read by nothing in the generation path.

How to apply:

1. **When feedback repeats, list the system's editable artifacts and ask which one the feedback is ABOUT.** If none matches, the fix is a new artifact, not an edit. Creating it is the fix; everything else is displacement.
2. **Purpose is runtime data, not documentation.** Whatever the system generates, its inputs must include who it is for and what it must do, in a file the renderer provably reads, with a test pinning that it arrives. Prose someone once read does not count.
3. **A citation is not a wire.** A docstring citing a source file is a note about why a rule exists. Prove connection claims by rendering the output and searching it, or by a runtime trace, never by reading the documentation.
4. **Bound the patch count.** The second rule written to fix damage a previous rule caused is the signal to stop editing that layer and ask which layer has no artifact.
