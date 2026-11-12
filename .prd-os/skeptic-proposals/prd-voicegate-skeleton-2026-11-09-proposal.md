# Skeptic anti-pattern proposal - prd-voicegate-skeleton-2026-11-09

Generated: 2026-11-12T01:41:20Z

## Findings the Skeptic did not catch

### finding-5 (major, routed to uncategorized, class: no-known-class)

Alternatives considered leaves out the option that needs no new op. Instance mode already accepts an additive insert_after on .claude/settings.json: consulting's gate-draft-wiring-2026-11-07 proposal used it (ASK-3873). An instance could add a separate PostToolUse entry 'test -f X || exit 2' beside the existing one, and the ratchet would see only growth. That closes the deleted-file hole with no ratchet exemption and no new abuse surface. Fix: add it to Alternatives. Either take it, or record the measured reason it fails (for example, if the kipi update merge drops it as a basename duplicate of the real hook).

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-6 (major, routed to uncategorized, class: no-known-class)

K8 maps x and threads to 'short', but the band lint passes its channel straight to 'voiceloop review' (voiceloop-band-lint.py:111). The engine's channel option accepts any string and defaults to x (voice-loop voiceloop/cli.py:434), and its short-form length rules apply only to x_format.SHORT_FORM_CHANNELS = ('x', 'threads') (voice-loop voiceloop/x_format.py:92). Passing 'short' would silently drop the X and Threads length checks, the same mismeasurement the comment at voiceloop-band-lint.py:59-66 records from 2026-09-29. Fix: state that the lane name only picks rows and the engine still receives x or threads, or list the voice-loop change as an upstream dependency. The K8 red test should assert that an over-length x draft still reports its length row when the manifest is present.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-8 (major, routed to uncategorized, class: no-known-class)

K7 (Goals, Scenarios) covers only the absent and expired cases. voice-lint.py is a blocking gate. If a malformed suppression file, a missing field or an unparseable expires date raises while being read, the hook exits 1, which Claude Code treats as non-blocking. One bad row then fails the gate open for every draft: gap class 9, the same class the ASK-1180 header of test_hook_fail_closed_population.py describes. Fix: an unreadable or invalid file or row suppresses nothing and is reported. Pin the timezone of 'expires'. Add red tests for malformed JSON, a missing owner or reason, a bad date, and an expiry exactly at today.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-12 (major, routed to uncategorized, class: no-known-class)

K5 only requires the key to exist. A free-text held_by is the same unenforced prose the Problem describes. Fix: held_by must name a path that exists, is a hook, script or test, and contains the lesson id. That is the same linkage rule_gate.py already enforces for rules under RULE-2026-11-08-CODE. prose_accepted must carry a reason and a date. Red tests: refuse a held_by naming a missing file, and one naming a file that lacks the id.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

## Skeptic Q-A pairs captured

**Q1:** What is the strongest argument against doing this?

These are fleet-wide tools changed to serve one instance. And a skeleton change does not reliably reach instance origins: consulting's origin/main missed the whole prd-os overhaul until ASK-4199 (RULE-2026-11-09-A). Answered in Proposed approach: each dependent consulting spec checks the blob on consulting origin/main before it starts.

**Q2:** What is the smallest experiment that would disprove the thesis?

For K1: delete `automation/gate_draft_hook.py` in a temp copy of consulting and write a dated draft that names a price. If that draft is refused today, the guard is not needed (consulting K1b's red test). For K8: run the band lint on one x draft with and without a manifest. If the engine argv is the same, K8 adds nothing (spec 1's red test).

**Q3:** What is the cheapest non-build alternative?

Hand-edit consulting's `settings.json`. Measured 2026-11-09: the integrity tripwire reverts unsanctioned `.claude/` edits in the running checkout, and RULE-2026-11-06-A rules out review discipline as the holder.

## How to merge (Sana, through the normal issue flow)

1. Read each finding above. The 'routed to Qx' label tells you which Skeptic question should have surfaced it.
2. Rewrite the proposed phrasing so it reads as a watched-for pattern, not as a template.
3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` under '## Anti-patterns the Skeptic watches for'.
4. Open a PR so Codex review fires on the diff, then merge it. Reject a finding here by saying why in the PR; a rejection is an outcome, an unread proposal is not.
