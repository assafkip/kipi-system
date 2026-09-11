# Skeptic anti-pattern proposal - prd-enforced-claim-verification-2026-08-21

Generated: 2026-08-21T19:23:14Z

## Findings the Skeptic did not catch

### finding-2 (blocker, routed to uncategorized, class: no-known-class)

The disposition grammar says one fenced block contains one entry per clause, but defines only a single flat mapping and no list marker or record delimiter. Multiple entries would repeat clause/status/exec/config keys, leaving the parser behavior undefined.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-3 (blocker, routed to uncategorized, class: no-known-class)

The proposed clause model is still heading-level, not clause-level. The PRD distinguishes 118 normative directives from 30 ENFORCED files, but requires coverage only for headings and matches entries by heading text. One disposition can therefore green every directive beneath a broad heading, reproducing the file-level false-positive at a slightly narrower boundary.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-4 (blocker, routed to uncategorized, class: no-known-class)

An ENFORCED heading can pass with an ADVISORY disposition. The PRD explicitly allows the author to satisfy a missing disposition by declaring ADVISORY while retaining the ENFORCED heading, and lint condition 1 checks only that an entry exists. The original false claim remains visible and mechanically accepted.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-5 (blocker, routed to uncategorized, class: no-known-class)

Exit posture is not implementably specified. Deciding ENFORCED versus DETECTED from whether source contains a non-zero exit path does not prove that path is reachable for the wired hook invocation. A script with an unrelated CLI error path would pass as ENFORCED, while determining that a DETECTED executable actually blocks requires an execution contract or mutation probe the PRD does not define.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-6 (major, routed to uncategorized, class: no-known-class)

The fenced format does not survive future sanctioned maintenance as claimed. apply_claude_changes.py lines 748-749 ratchet every referenced .py/.sh basename and lines 809-815 reject disappearance of any mark. After adding an exec field, replacing an obsolete enforcer with a new basename removes the old mark and is refused, contradicting the PRD claim that entries can be reworded.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-7 (major, routed to uncategorized, class: no-known-class)

Heading identity is unstable and collision-prone. The PRD normalizes case and punctuation but defines neither the exact normalization algorithm nor rejection of duplicate normalized headings. Two distinct headings can collapse to one key, and normal editorial heading changes can orphan dispositions without a stable clause ID.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-8 (major, routed to uncategorized, class: no-known-class)

The declared config field is not actually validated. The PRD requires a specific config per entry, but lint condition 3 only asks whether the basename appears in any wired config. A false config value can pass as long as some other config references the executable.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-9 (major, routed to uncategorized, class: no-known-class)

Executable identity is reduced to a basename. The grounded skill-hook-audit.py uses the same basename-only pattern at lines 58-75 and 93-105, which can pair one wired command with a different same-named file elsewhere. The new design needs canonical resolved paths and an ambiguity failure, not inherited basename matching.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-10 (major, routed to uncategorized, class: no-known-class)

The cross-cutting invariant has no durable whole-tree gate. The PRD wires only PostToolUse Edit/Write and leaves whole-tree validator integration unresolved. Direct shell writes, updater propagation, merges, and pre-existing files bypass that hook, violating gap classes 19-21 requirement for an explicit scope and a self-enumerating guard.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-12 (major, routed to uncategorized, class: no-known-class)

The lesson change replaces a bounded read with an unbounded SessionStart payload. The PRD requires every title and only measures today's token cost, with no maximum accepted cost, growth test, or failure threshold. lessons-index.py lines 55-68 reads and emits the full selected corpus every session, so cost grows without bound as lessons accumulate.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-13 (major, routed to uncategorized, class: no-known-class)

The skill-hook onboarding inherits a known unsafe reader. skill-hook-audit.py lines 52-55 treats settings.local.json as authoritative wiring, while apply_claude_changes.py lines 512-532 states that file is untracked, machine-local, and outside the auditable sanctioned path. Adding the manifest can therefore report a skeleton hook as wired based only on a local override.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

### finding-14 (major, routed to uncategorized, class: no-known-class)

The mutation proof covers only a fictional missing executable. It does not falsify malformed or repeated block entries, duplicate normalized headings, wrong config values, basename collisions, nested rule paths, unreachable non-zero exits, neutering variants, or bypass writes. Gap class 20 requires the guard test to derive and enumerate its target surface rather than trust one hand-built mutation.

**Proposed anti-pattern phrasing:**

Codex flagged this issue but it does not match any pre-defined anti-pattern class. Treat this as a candidate for a new Skeptic question or a different persona (PM, Architect, UX).

## Skeptic Q-A pairs captured

**Q1:** What is the strongest argument against doing this?

It adds ceremony to every rule file to solve a documentation-accuracy

**Q2:** What is the smallest experiment that would disprove the thesis?

Run `--all` against the real tree before the disposition pass. If it flags

**Q3:** What is the cheapest non-build alternative?

Write the skeleton `skill-hook-manifest.json` only, which turns on five

## How to merge

1. Read each finding above. The 'routed to Qx' label tells you which Skeptic question should have surfaced it.
2. Edit the proposed anti-pattern phrasing to match your voice.
3. Append accepted anti-patterns to `plugins/prd-os/personas/skeptic.md` under '## Anti-patterns the Skeptic watches for'.
4. Commit through normal git flow so Codex review fires on the diff.
