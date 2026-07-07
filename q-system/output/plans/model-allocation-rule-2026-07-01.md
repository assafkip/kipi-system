# Model allocation: single rule + deterministic checker

**What/why:** The Haiku-pulls / Sonnet-analysis / Opus-synthesis policy exists only as prose in morning-pipeline.md (duplicated in folder-structure.md, SETUP.md) and de-facto in 5 agent frontmatters. No checker; version drift live (opus/sonnet pinned at 4-6 while 4-8/5 are current). Item #3 of morning-extraction-audit-2026-07-01.md, founder-approved.

**Approach (pick):** One rule file as single source + a Gate 1.1 addition to validate-separation.py that validates `.claude/agents/*.md` model IDs against a per-tier allowlist. Bump stale frontmatter IDs to current. (Alternatives considered: warn-only checker that tolerates legacy IDs — keeps the drift, rejected; separate standalone script — orphan risk, validate-separation already owns skeleton integrity, rejected.)

**Files to touch:**
- `.claude/rules/model-allocation.md` (new; propagates via kipi update)
- `.claude/agents/engagement-hitlist.md`, `synthesizer.md` (opus-4-6 → opus-4-8), `content-reviewer.md` (sonnet-4-6 → sonnet-5)
- `validate-separation.py` (new checks in phase_1, dir-parameterized for testability)
- `.claude/rules/morning-pipeline.md`, `.claude/rules/folder-structure.md`, `SETUP.md` (prose → pointer at the rule)

**Acceptance criteria:**
- [x] Checker FAILS on current tree before frontmatter bump (ran: 3 violations, exactly the drifted agents)
- [x] Checker passes after bump (ran: `validate-separation.py 1` exit 0, 62 PASS / 0 FAIL / 1 WARN)
- [x] Negative self-test: corrupted temp copy (opus-3-9 id + opus on data-ingest) → 2 violations caught; clean tree 0
- [x] Rule file written (enforcement-guard-passing wording); morning-pipeline.md / folder-structure.md / SETUP.md now point at it
- [ ] `kipi update --dry` — batched once at session end together with items 1/2/4

**Patterns to follow:** validate-separation.py's existing check()/warn() idiom in phase_1 Gate 1.1; rules propagate via `.claude/rules/` (wiring-check propagation note); scar-anchored why-comment citing the 4-5/4-6 drift found 2026-07-01.
