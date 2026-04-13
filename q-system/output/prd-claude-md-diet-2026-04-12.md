# PRD: CLAUDE.md Diet - Restructure to Official Spec

**Date:** 2026-04-12
**Author:** Assaf Kipnis
**Status:** Draft
**Priority:** P1 (high)

---

## 1. Problem

The Anthropic docs are explicit: CLAUDE.md should be under 200 lines. It's a map, not a manual. Our setup violates this in three ways.

- **Evidence:**
  - Root `CLAUDE.md`: 90 lines + `@q-system/CLAUDE.md` import (146 lines) = **236 lines loaded every session**
  - 8 rules files are effectively always-loaded: 7 with no `paths:` frontmatter + 1 with `paths: ["**/*"]` which matches everything. (`audhd-interaction` 22L, `auto-detection` 33L, `design-auto-invoke` 27L, `folder-structure` 255L, `memory-freshness` 73L, `social-reaction-gate` 37L, `voice-enforcement` 22L = 469 lines without `paths:`. Plus `token-discipline` 46L and `security` 15L have `paths: ["**/*"]` = functionally always-on on first file read.)
  - Total always-on instruction payload: **~766 lines, ~43KB**
  - Anthropic docs recommend: **<200 lines CLAUDE.md, path-scope everything possible**
  - Note: `token-discipline` content also appears in `CLAUDE.md` lines 77-86, so today it double-loads.

- **Impact:**
  - Every session starts with ~766 lines of instructions burning context tokens
  - `folder-structure.md` alone is 255 lines with no `paths:` scoping. It loads even when we're writing a DM.
  - Docs say: "Bloated CLAUDE.md files cause Claude to ignore your actual instructions!" This is not a style preference. It's a performance degradation documented by the vendor.
  - Token cost: ~43KB of instructions = ~11,000 tokens per session, before the first prompt. At scale (10 sessions/day), that's 110K tokens/day on instructions alone.

- **Root cause:**
  - Organic growth. Instructions were added as problems were discovered. No periodic audit against the docs' sizing spec.
  - Several rules files that fire contextually (design, voice, social reactions) lack `paths:` frontmatter, so they load unconditionally.
  - Two rules files (`token-discipline.md`, `security.md`) use `paths: ["**/*"]` which is functionally identical to no `paths:` at all. Any audit script that checks for the presence of `paths:` frontmatter will misclassify these as conditional.
  - `q-system/CLAUDE.md` contains operating-mode docs, debrief workflows, and language rules that are reference material, not "always do X" rules. The docs say this belongs in skills.
  - `folder-structure.md` is 255 lines of directory tree. Claude can `ls` the directory. Most of this is derivable from code.

## 2. Scope

### In Scope
- Shrink total always-on payload (CLAUDE.md + imports + effectively-always-on rules) to <300 lines
- Add `paths:` frontmatter to 3 rules files that don't need to load every session
- Trim `social-reaction-gate.md` from 37 to ~22 lines (stays always-on, cannot be path-scoped)
- Move reference/workflow content from `q-system/CLAUDE.md` to existing skills
- Deduplicate instructions that appear in both CLAUDE.md and rules files
- Create deterministic audit script that correctly identifies `paths: ["**/*"]` as always-on
- Wire audit script as pre-commit hook for deterministic enforcement
- Token audit: measure before/after always-on token cost
- Code audit: verify no rule contradicts another after restructure
- Regression testing: verify existing behaviors survive the diet

### Out of Scope
- Rewriting skill content (skills are on-demand, not the problem)
- Changing hook behavior (hooks are deterministic, zero context cost)
- Restructuring the agent pipeline (separate concern)
- Modifying the PRD template or folder-structure canonical layout

### Non-Goals
- Making CLAUDE.md "prettier" or better organized for human readers. The audience is Claude, not us.
- Adding new rules or conventions. This is a subtraction exercise.
- Changing any runtime behavior. Same rules, fewer tokens.

## 3. Changes

### Change 1: Slim root CLAUDE.md

- **What:** Remove content Claude can derive from code or that belongs in skills/rules
- **Where:** `CLAUDE.md` (root)
- **Why:** 90 lines + 146-line import = 236 lines. Docs say <200 for CLAUDE.md alone. Combined with always-on rules, total must be <300.
- **Exact change:**
  - Remove "About" section (1 line of fluff, adds nothing actionable)
  - Remove "Tech Stack" section (Claude discovers MCP servers at startup, this is redundant)
  - Compress "Project Structure" to 5 lines max (Claude has `ls` and `folder-structure.md` rule)
  - Remove "Hooks" section (hooks are in settings.json, Claude sees them automatically)
  - Remove "Token Discipline" section (already in `.claude/rules/token-discipline.md` which has `paths: ["**/*"]` and therefore loads on every file read, making it effectively always-on)
  - Remove "Tool Preferences" section (already in MCP config + rules)
  - Keep: Commands, Conventions, Build and Test (things Claude genuinely can't derive)
- **Scope:** Skeleton (propagates to all instances via `kipi update`)

### Change 2: Slim q-system/CLAUDE.md

- **What:** Move reference material to skills, keep only always-on behavioral rules
- **Where:** `q-system/CLAUDE.md`
- **Why:** 146 lines of mixed always-on rules and reference docs. Docs say: "If it's reference material Claude needs sometimes, put it in a skill."
- **Exact change:**
  - Remove "First-Run Setup" section (move to skill `q-setup`, where it already exists)
  - Remove "Operating Modes" table (move to `q-system/methodology/modes.md`, already exists there)
  - Remove "File Authority" section (derivable from folder-structure rule)
  - Remove "Language Rules" section (already in `anti-misclassification.md` rule)
  - Remove "Inter-Skill Review Gates" section (already enforced by `anti-misclassification.md` rule)
  - Remove "Skills and Plugins" section (Claude discovers these at startup automatically)
  - Remove "Reality Check Mode" section (skill description already loaded at startup)
  - Remove "Operator Context" / "Output Format Rules" section (already in `audhd-interaction.md` rule)
  - Remove "Domain Rules" section (rules are auto-discovered, listing them is redundant)
  - Keep: Identity (2 lines), Core Behavioral Rules (never produce fluff, preserve ambiguity), Session Continuity (3 lines), DEBRIEF priority statement (1 line)
- **Scope:** Skeleton

### Change 3: Path-scope 3 rules files + trim social-reaction-gate

- **What:** Add `paths:` frontmatter to 3 rules files so they only load when relevant files are being worked on. Trim `social-reaction-gate.md` to ~22 lines (stays always-on).
- **Where:** `.claude/rules/` (4 files touched)
- **Why:** 469 lines loading unconditionally (not counting `**/*` files). Docs say: "Path-scoped rules trigger when Claude reads files matching the pattern, not on every tool use." Three of these files only matter for specific file types. One (social-reaction-gate) fires on pasted content with no file read, so `paths:` would make it never load when needed.
- **Exact changes:**

  **`folder-structure.md` (255 lines) - ADD `paths:`**
  ```yaml
  ---
  paths:
    - "CLAUDE.md"
    - ".claude/**/*"
    - "plugins/**/*"
    - "q-system/**/*"
    - "kipi"
    - "*.sh"
    - "*.py"
  ---
  ```
  Rationale: Only matters when creating/moving files. Does not need to load for DMs, engagement, or content tasks.

  **`design-auto-invoke.md` (27 lines) - ADD `paths:`**
  ```yaml
  ---
  paths:
    - "**/*.html"
    - "**/*.css"
    - "**/*.tsx"
    - "**/*.jsx"
    - "sites/**/*"
  ---
  ```
  Rationale: Only matters when building UI. Already says "Gate check: Will someone other than the founder see this?"

  **`memory-freshness.md` (73 lines) - ADD `paths:`**
  ```yaml
  ---
  paths:
    - "memory/**/*"
    - "q-system/memory/**/*"
  ---
  ```
  Rationale: Only matters when reading/writing memory files. The deterministic hook (`memory-freshness-check.py`) already enforces at session start regardless.

  **`social-reaction-gate.md` (37 lines) - TRIM to ~22 lines, NO `paths:`**
  Remove the Role Clarity table and Red Flags section (derivable from engagement playbook skill). Keep: the gate steps (extract claims, show to founder, draft, self-check) and the "What Counts as a Reaction" list.
  Rationale: Docs say path-scoped rules trigger on file reads. Social reactions fire on pasted content with no file read. `paths:` would make this rule never load when it's needed. Trim instead.

  **Files that stay always-on, unchanged:**
  - `auto-detection.md` (33 lines) - fires on pasted content, no file path
  - `audhd-interaction.md` (22 lines) - applies to every response, 320 tokens is noise floor
  - `voice-enforcement.md` (22 lines) - applies to all content generation, trivial cost
  - `token-discipline.md` (46 lines) - has `paths: ["**/*"]`, functionally always-on. Stays as-is.
  - `security.md` (15 lines) - has `paths: ["**/*"]`, functionally always-on. Stays as-is.

- **Scope:** Skeleton

### Change 4: Deduplicate token discipline

- **What:** Remove token discipline section from root CLAUDE.md (already in rules file)
- **Where:** `CLAUDE.md` lines 77-86
- **Why:** Duplicate of `.claude/rules/token-discipline.md`. The rules file has `paths: ["**/*"]` which matches every file, so it loads on the first file read of every session. After removing the CLAUDE.md copy, token discipline still enforces via the rules file. Two copies = wasted tokens AND potential drift if one gets updated without the other.
- **Exact change:** Delete lines 77-86 from root CLAUDE.md
- **Scope:** Skeleton

### Change 5: Deterministic token audit script + pre-commit hook

- **What:** Create a script that measures total always-on instruction payload and fails if it exceeds 300 lines. Must correctly identify `paths: ["**/*"]` as functionally always-on. Wire as pre-commit hook.
- **Where:** `q-system/.q-system/scripts/instruction-budget-audit.py`
- **Why:** The docs say <200 lines for CLAUDE.md. Docs also say "Rules without paths frontmatter are loaded at launch with the same priority as .claude/CLAUDE.md," making always-on rules effectively part of CLAUDE.md from a token perspective. Rules with `paths: ["**/*"]` are functionally identical to no `paths:` at all. Without a deterministic check, we'll drift back. LLM instruction ("keep CLAUDE.md short") is not a fix. A script that counts lines and exits non-zero IS. Docs say: "Use hooks for actions that must happen every time with zero exceptions."
- **Exact change:**
  ```python
  #!/usr/bin/env python3
  """Audit always-on instruction token budget.
  
  Single budget: CLAUDE.md (with imports) + effectively-always-on rules < 300 lines.
  
  IMPORTANT: Rules with paths: ["**/*"] are functionally always-on because **/*
  matches every file Claude will ever read. The script must count these as always-on,
  not conditional. A naive has_paths_frontmatter() check would misclassify them.
  
  Exits non-zero if budget exceeded.
  """
  import os, sys, re, yaml

  QROOT = os.path.join(os.path.dirname(__file__), "..", "..")
  PROJECT_ROOT = os.path.join(QROOT, "..")

  # Anthropic docs say <200 for CLAUDE.md (stated 3x).
  # Docs also say: "Rules without paths frontmatter are loaded at launch
  # with the same priority as .claude/CLAUDE.md."
  # Rules with paths: ["**/*"] match everything = same as no paths.
  # Single budget: CLAUDE.md + effectively-always-on rules combined.
  BUDGET_CLAUDE_MD = 200
  BUDGET_TOTAL_ALWAYS_ON = 300

  # Glob patterns that match everything (functionally always-on)
  CATCH_ALL_PATTERNS = {"**/*", "**/**", "**"}

  def count_lines(path):
      if not os.path.exists(path):
          return 0
      with open(path) as f:
          return sum(1 for line in f if line.strip())

  def is_effectively_always_on(path):
      """Return True if the rule has no paths: or paths: contains a catch-all glob."""
      with open(path) as f:
          content = f.read()
      
      # No frontmatter at all = always-on
      if not content.startswith("---"):
          return True
      
      # Parse YAML frontmatter
      end = content.find("---", 3)
      if end == -1:
          return True
      
      try:
          frontmatter = yaml.safe_load(content[3:end])
      except Exception:
          return True
      
      if not frontmatter or "paths" not in frontmatter:
          return True
      
      paths = frontmatter["paths"]
      if not isinstance(paths, list):
          return True
      
      # If ANY pattern is a catch-all, the rule is effectively always-on
      for p in paths:
          if p.strip().strip('"').strip("'") in CATCH_ALL_PATTERNS:
              return True
      
      return False

  def resolve_imports(path):
      """Count lines including @import targets."""
      total = count_lines(path)
      if not os.path.exists(path):
          return total
      with open(path) as f:
          for line in f:
              match = re.match(r'^@(.+)$', line.strip())
              if match:
                  import_path = os.path.join(os.path.dirname(path), match.group(1))
                  total += count_lines(import_path)
      return total

  def main():
      claude_md = os.path.join(PROJECT_ROOT, "CLAUDE.md")
      rules_dir = os.path.join(PROJECT_ROOT, ".claude", "rules")

      claude_md_lines = resolve_imports(claude_md)
      
      always_on_rules = 0
      always_on_files = []
      conditional_files = []
      for f in sorted(os.listdir(rules_dir)):
          if not f.endswith(".md"):
              continue
          fpath = os.path.join(rules_dir, f)
          lines = count_lines(fpath)
          if is_effectively_always_on(fpath):
              always_on_rules += lines
              always_on_files.append((f, lines))
          else:
              conditional_files.append((f, lines))

      total = claude_md_lines + always_on_rules
      
      print(f"CLAUDE.md (with imports): {claude_md_lines} / {BUDGET_CLAUDE_MD}")
      print(f"Always-on rules ({len(always_on_files)} files):")
      for name, lines in always_on_files:
          print(f"  {name}: {lines}")
      print(f"Conditional rules ({len(conditional_files)} files):")
      for name, lines in conditional_files:
          print(f"  {name}: {lines}")
      print(f"Total always-on (CLAUDE.md + rules): {total} / {BUDGET_TOTAL_ALWAYS_ON}")
      
      failed = False
      if claude_md_lines > BUDGET_CLAUDE_MD:
          print(f"\nFAIL: CLAUDE.md exceeds {BUDGET_CLAUDE_MD}-line budget by {claude_md_lines - BUDGET_CLAUDE_MD} lines")
          failed = True
      if total > BUDGET_TOTAL_ALWAYS_ON:
          print(f"\nFAIL: Total always-on exceeds {BUDGET_TOTAL_ALWAYS_ON}-line budget by {total - BUDGET_TOTAL_ALWAYS_ON} lines")
          failed = True
      
      if not failed:
          print("\nPASS: All budgets within limits")
      
      sys.exit(1 if failed else 0)

  if __name__ == "__main__":
      main()
  ```
- **Scope:** Skeleton

## 4. Change Interaction Matrix

| Change A | Change B | Interaction | Resolution |
|----------|----------|-------------|------------|
| C1 (slim root CLAUDE.md) | C2 (slim q-system/CLAUDE.md) | Both reduce the same imported chain | C1 runs first (outer file), C2 runs second (imported file). Combined total feeds into single 300-line budget. |
| C1 (slim root CLAUDE.md) | C4 (dedup token discipline) | C4 is a subset of C1 | C4 is implemented as part of C1. Listed separately for traceability. |
| C3 (path-scope rules + trim) | C2 (slim q-system/CLAUDE.md) | C2 removes content that references rules. C3 scopes those rules. | No conflict. C2 removes redundant references, C3 makes the referenced rules load conditionally. |
| C4 (dedup token discipline) | C5 (audit script) | After C4 removes the CLAUDE.md copy, the script must still count `token-discipline.md` as always-on via its `paths: ["**/*"]` | C5's `is_effectively_always_on()` correctly classifies `**/*` as always-on. No gap. |
| C5 (audit script) | C1+C2+C3+C4 | C5 validates the result of C1-C4 | C5 runs after all other changes. It's the acceptance test. |

## 5. Files Modified

| File | Change Type | Lines Added | Lines Removed |
|------|------------|-------------|---------------|
| `CLAUDE.md` | Edit | +0 | -50 |
| `q-system/CLAUDE.md` | Edit | +0 | -100 |
| `.claude/rules/folder-structure.md` | Edit | +8 | +0 |
| `.claude/rules/design-auto-invoke.md` | Edit | +7 | +0 |
| `.claude/rules/social-reaction-gate.md` | Edit | +0 | -15 |
| `.claude/rules/memory-freshness.md` | Edit | +5 | +0 |
| `q-system/.q-system/scripts/instruction-budget-audit.py` | Add | +95 | +0 |

## 6. Test Cases

### [Change 1+2] CLAUDE.md Size Tests

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 1.1 | DET | Total always-on budget | `python3 q-system/.q-system/scripts/instruction-budget-audit.py` | Total < 300 | Script exits 0, prints PASS |
| 1.2 | DET | No content loss for kept sections | `grep -c "Build and Test\|Commands\|Conventions" CLAUDE.md` | 3 matches | All three section headers present |
| 1.3 | BEH | Claude still follows conventions | Start new session, ask "what are the project conventions?" | Claude cites conventions from CLAUDE.md | Verified over 3 sessions |
| 1.4 | BEH | Claude still knows commands | Start new session, type `/q-morning` | Morning pipeline runs | Verified over 2 sessions |
| 1.5 | DET (negative) | Removed sections don't reappear | `grep -c "Tech Stack\|Tool Preferences\|Hooks" CLAUDE.md` | 0 matches | No hits for removed sections |

### [Change 3] Path-Scoping + Trim Tests

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 3.1 | DET | folder-structure.md has paths: | `head -5 .claude/rules/folder-structure.md` | YAML frontmatter with `paths:` | `paths:` key present |
| 3.2 | BEH | folder-structure loads when editing rules | Edit a file in `.claude/rules/`, check if folder conventions apply | Claude follows folder placement rules | Verified over 2 sessions |
| 3.3 | BEH (negative) | folder-structure does NOT load for engagement tasks | Ask Claude to draft a LinkedIn comment | Claude does not reference folder-structure | No folder-structure content in context |
| 3.4 | DET | auto-detection.md stays always-on | `head -5 .claude/rules/auto-detection.md` | No `paths:` frontmatter | File starts with `#` not `---` |
| 3.5 | DET | social-reaction-gate.md stays always-on, trimmed | `wc -l .claude/rules/social-reaction-gate.md` | ~22 lines, no `paths:` frontmatter | Line count <= 25 AND no `paths:` in frontmatter |
| 3.6 | BEH | social-reaction-gate still fires on pasted posts | Share a screenshot of someone's LinkedIn post | Claude extracts claims before drafting reaction | Gate steps followed |

### [Change 4] Deduplication Tests

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 4.1 | DET | Token discipline exists in exactly one place | `grep -rl "50K+ tokens" CLAUDE.md .claude/rules/` | Only `.claude/rules/token-discipline.md` | Single file match |
| 4.2 | BEH | Token discipline still enforced | Spawn 5+ agents in rapid succession | Token guard blocks or warns | Block message appears |
| 4.3 | DET | token-discipline.md is classified as always-on by audit script | Run audit script, check output | `token-discipline.md` listed under "Always-on rules" | File appears in always-on list, not conditional list |

### [Change 5] Audit Script Tests

| # | Type | Scenario | Input | Expected | Pass Criteria |
|---|------|----------|-------|----------|---------------|
| 5.1 | DET | Script passes after diet | `python3 q-system/.q-system/scripts/instruction-budget-audit.py` | Total < 300 | Exit code 0 |
| 5.2 | DET | Script catches bloat | Temporarily add 300 lines to CLAUDE.md, run script | FAIL message | Exit code 1, FAIL printed |
| 5.3 | DET | Script counts imports | Script resolves `@q-system/CLAUDE.md` | Import lines included in count | Import target lines counted |
| 5.4 | DET | Script treats `paths: ["**/*"]` as always-on | `token-discipline.md` and `security.md` both have `paths: ["**/*"]` | Both listed as always-on, not conditional | Both files in always-on output section |
| 5.5 | DET (negative) | Script treats narrow paths as conditional | `anti-misclassification.md` has `paths: ["q-system/canonical/**"]` | Listed as conditional | File in conditional output section |

## 7. Regression Tests

| # | What to Verify | How to Verify | Pass Criteria |
|---|----------------|---------------|---------------|
| R-1 | `/q-morning` still runs full pipeline | Run `/q-morning` in new session | All 9 phases complete, morning-log written |
| R-2 | `/q-debrief` still works with auto-detection | Paste a conversation transcript | Debrief fires automatically without `/q-debrief` command |
| R-3 | Voice enforcement still active for content | Ask Claude to draft a LinkedIn post | Founder voice skill invoked, anti-AI patterns applied |
| R-4 | AUDHD rules still apply to actionable output | Ask Claude to create a task list | Energy modes, time estimates, copy-paste format |
| R-5 | Anti-misclassification still blocks bad framing | Reference the product with a misclassification term | Claude catches and reframes |
| R-6 | `kipi update` propagates changes | Run `kipi update --dry` on a child instance | Diff shows the slimmed files |
| R-7 | PostCompact hook re-injects correctly | Run `/compact` mid-session | Mode, loops, voice reminders re-injected |
| R-8 | Session start hook still injects context | Start new session | Date, handoff, energy injected |
| R-9 | Memory freshness still enforced on fast-decay | Read a `decay: fast` memory and act on it | Verification step occurs before action |
| R-10 | Token discipline enforced after CLAUDE.md dedup | Start session, trigger token guard | Token guard fires from rules file, not CLAUDE.md | 

## 8. Rollback Plan

| Change | Rollback Steps | Risk |
|--------|---------------|------|
| C1-C4 (file edits) | `git revert <commit>` then `kipi update` to all instances | Low. All changes are in version control. |
| C5 (new script + hook) | Delete `instruction-budget-audit.py`, remove pre-commit hook entry. No other cleanup needed. | None. Script has no side effects. |

## 9. Change Review Checklist

| Check | Status | Notes |
|-------|--------|-------|
| Changes are additive (no breaking removals) | Pending | Content moves to skills/rules, not deleted from system |
| No conflicts with existing enforced rules | Pending | Code audit section below |
| No hardcoded secrets | Pending | No secrets involved |
| Propagation path verified (kipi update) | Pending | All changed files are skeleton files |
| Exit codes preserved (hooks exit 0) | Pending | No hook changes |
| AUDHD-friendly (no pressure/shame language added) | Pending | No new language, only removals |
| Test coverage for every change | Pending | 18 test cases + 10 regression tests |

## 10. Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| Total always-on lines (CLAUDE.md + imports + effectively-always-on rules) | 766 | <300 | `instruction-budget-audit.py` |
| CLAUDE.md lines (with imports) | 236 | <200 | `instruction-budget-audit.py` |
| Estimated always-on tokens | ~11,000 | <4,200 | Lines * ~14 tokens/line (average for markdown) |
| Daily token savings (10 sessions) | 0 | ~68,000 | (current - target) * 10 |
| Instruction adherence | Unmeasured | No regressions | Regression tests R-1 through R-10 |

## 11. Implementation Order

1. **Create `instruction-budget-audit.py`** (C5) - Run it first to establish baseline. No dependencies. Verify it correctly classifies `**/*` as always-on.
2. **Add `paths:` frontmatter to 3 rules + trim social-reaction-gate** (C3) - Safe, additive change. Rules still work, they just load conditionally.
3. **Slim `q-system/CLAUDE.md`** (C2) - Remove reference material, verify skills cover it.
4. **Slim root `CLAUDE.md` + dedup** (C1+C4) - Depends on C2 being done (import chain).
5. **Run audit script** (C5 again) - Verify budget passes.
6. **Wire audit script as pre-commit hook** - Deterministic enforcement. Docs say: "hooks are deterministic and guarantee the action happens."
7. **Run regression tests** (R-1 through R-10) - Full behavioral verification. Pay special attention to R-10 (token discipline after dedup).
8. **`kipi update --dry`** - Preview propagation to instances.
9. **`kipi update`** - Push to all instances (after founder approval).

## 12. Open Questions

All questions resolved. Resolutions documented below for traceability.

| Question | Owner | Deadline | Resolution |
|----------|-------|----------|------------|
| Should `social-reaction-gate.md` get `paths:` or stay always-on? | Assaf | 2026-04-14 | **RESOLVED: Stay always-on, trim to ~22 lines.** Docs say "Path-scoped rules trigger when Claude reads files matching the pattern, not on every tool use." Social reactions fire on pasted content with no file read. `paths:` would make the rule never load when needed. Trim instead. |
| Should `audhd-interaction.md` (22 lines) get `paths:` scoping? | Assaf | 2026-04-14 | **RESOLVED: Keep always-on.** Docs say "Keep it to facts Claude should hold in every session." AUDHD rules apply to every response. 22 lines (~320 tokens) is under the noise floor. No file pattern captures "all output." |
| Should the audit script run as a pre-commit hook? | Assaf | 2026-04-19 | **RESOLVED: Yes.** Docs say "Use hooks for actions that must happen every time with zero exceptions" and "Unlike CLAUDE.md instructions which are advisory, hooks are deterministic and guarantee the action happens." Budget enforcement is exactly this. 0.3s cost is trivial vs discovering bloat months later. |
| Target budget numbers (200/300/450) - are these right? | Assaf | 2026-04-14 | **RESOLVED: Single budget of 300 lines total always-on.** Docs say <200 for CLAUDE.md (stated 3 times). Docs also say "Rules without paths frontmatter are loaded at launch with the same priority as .claude/CLAUDE.md" making always-on rules effectively part of CLAUDE.md from a token perspective. Rules with `paths: ["**/*"]` are functionally identical and must be counted. One number: CLAUDE.md (with imports) + all effectively-always-on rules < 300 lines. |

---

## User Stories

### US-1: Session startup token savings
**As** the founder running 10+ Claude Code sessions per day,
**I want** the total always-on instruction payload to be under 300 lines,
**so that** I save ~68K tokens/day and Claude has more context for actual work instead of re-reading instructions it ignores.

**Acceptance:** `instruction-budget-audit.py` exits 0. Single budget < 300.

### US-2: Instruction adherence
**As** the founder relying on CLAUDE.md rules,
**I want** fewer, more specific instructions that Claude actually follows,
**so that** I stop seeing Claude ignore rules that got lost in 700+ lines of context.

**Acceptance:** Regression tests R-1 through R-10 pass. No new "Claude ignored X" incidents in the 2 weeks after rollout.

### US-3: Contextual rule loading
**As** a user drafting a LinkedIn comment,
**I want** folder-structure rules (255 lines) to NOT load,
**so that** my engagement task has 255 more lines of context for the actual work.

**Acceptance:** Test 3.3 passes. `folder-structure.md` has `paths:` frontmatter.

### US-4: No instruction drift
**As** the founder maintaining rules across CLAUDE.md and `.claude/rules/`,
**I want** zero duplicated instructions,
**so that** I update one place, not two, and avoid silent drift between copies.

**Acceptance:** Test 4.1 passes. Token discipline exists in exactly one file.

### US-5: Deterministic budget enforcement
**As** a token zealot,
**I want** a pre-commit hook that fails if someone pushes the always-on payload past 300 lines,
**so that** bloat is caught by code, not by noticing Claude ignoring rules 6 months later.

**Acceptance:** Test 5.2 passes. Script exits non-zero when budget exceeded. Script correctly classifies `paths: ["**/*"]` as always-on (test 5.4). Pre-commit hook wired.

### US-6: Safe rollout to all instances
**As** the founder running multiple kipi instances,
**I want** changes to propagate via `kipi update` with a dry-run preview,
**so that** I see exactly what changes before they hit production instances.

**Acceptance:** `kipi update --dry` shows diff. `kipi update` applies cleanly. Regression test R-6.

---

## Code Audit

### Duplication Audit

| Content | Location 1 | Location 2 | Action |
|---------|-----------|-----------|--------|
| Token discipline (7 rules) | `CLAUDE.md` lines 77-86 | `.claude/rules/token-discipline.md` (has `paths: ["**/*"]`, functionally always-on) | Remove from CLAUDE.md (C4). Rules file covers it on every file read. |
| "Never produce fluff" | `CLAUDE.md` line 40 | `q-system/CLAUDE.md` "Core Behavioral Rules" | Keep in CLAUDE.md only |
| Output format rules | `q-system/CLAUDE.md` "Output Format Rules" | `.claude/rules/audhd-interaction.md` | Remove from q-system/CLAUDE.md (C2) |
| Language rules | `q-system/CLAUDE.md` "Language Rules" | `.claude/rules/anti-misclassification.md` | Remove from q-system/CLAUDE.md (C2) |
| File authority | `q-system/CLAUDE.md` "File Authority" | `.claude/rules/folder-structure.md` | Remove from q-system/CLAUDE.md (C2) |
| Skills listing | `q-system/CLAUDE.md` "Skills and Plugins" | Auto-discovered at startup by Claude Code | Remove from q-system/CLAUDE.md (C2) |
| Review gates | `q-system/CLAUDE.md` "Inter-Skill Review Gates" | `.claude/rules/anti-misclassification.md` | Remove from q-system/CLAUDE.md (C2) |

### Contradiction Audit

| Rule A | Rule B | Conflict? | Resolution |
|--------|--------|-----------|------------|
| `voice-enforcement.md`: "Do NOT apply voice rules to conversational responses" | `audhd-interaction.md`: applies to all output | No conflict. Voice = published content. AUDHD = interaction style. Different scopes. | None needed |
| `auto-detection.md`: "No command needed, auto-detect transcripts" | `social-reaction-gate.md`: "Extract claims before drafting" | No conflict. Auto-detection triggers debrief. Social-reaction-gate triggers on *reactions to posts*. Different inputs. | None needed |
| `content-output.md`: "All written content must go through founder voice skill" | `voice-enforcement.md`: "Apply ONLY when generating content for others" | Potential overlap. Both say "voice skill for content." | `content-output.md` is the trigger, `voice-enforcement.md` defines scope. Keep both, they reinforce. |
| `folder-structure.md`: lists all canonical paths | `q-system/CLAUDE.md` "File Authority": lists key files | Redundant, not contradictory. | Remove File Authority from q-system/CLAUDE.md (C2) |

### Scoping Correctness Audit

Rules files with `paths: ["**/*"]` are a scoping anomaly. They have frontmatter that suggests conditional loading, but the glob matches everything. This PRD does not change their frontmatter (out of scope), but the audit script must handle them correctly.

| File | `paths:` value | Effectively always-on? | Script classification |
|------|---------------|----------------------|----------------------|
| `token-discipline.md` | `["**/*"]` | Yes (matches every file) | Always-on (correct) |
| `security.md` | `["**/*"]` | Yes (matches every file) | Always-on (correct) |
| `coding-audhd.md` | `["**/*.py", "**/*.js", ...]` | No (only code files) | Conditional (correct) |
| `anti-misclassification.md` | `["q-system/canonical/**", ...]` | No (only canonical/marketing) | Conditional (correct) |

### Orphan Check

After removals, verify nothing references removed content:

| Removed Section | What might reference it | Verification |
|-----------------|------------------------|--------------|
| "Tech Stack" from CLAUDE.md | Nothing. Informational only. | `grep -r "Tech Stack" .claude/ q-system/` |
| "Operating Modes" from q-system/CLAUDE.md | Skills reference modes by name | Modes table still exists in `q-system/methodology/modes.md` |
| "First-Run Setup" from q-system/CLAUDE.md | `q-setup` skill | Skill has its own copy in `setup-flow.md` |
| "Hooks" from CLAUDE.md | Nothing. Hooks are in settings.json. | N/A |

---

## Token Audit

### Current State (measured 2026-04-12)

| Component | Lines | Bytes | Est. Tokens | Loads When |
|-----------|-------|-------|-------------|------------|
| `CLAUDE.md` (root, no imports) | 90 | 5,643 | ~1,500 | Every session |
| `q-system/CLAUDE.md` (imported) | 146 | 7,679 | ~2,000 | Every session (via @import) |
| **CLAUDE.md total** | **236** | **13,322** | **~3,500** | **Every session** |
| `audhd-interaction.md` | 22 | 1,216 | ~320 | Always (no paths:) |
| `auto-detection.md` | 33 | 2,232 | ~590 | Always (no paths:) |
| `design-auto-invoke.md` | 27 | 1,229 | ~320 | Always (no paths:) |
| `folder-structure.md` | 255 | 14,053 | ~3,700 | Always (no paths:) |
| `memory-freshness.md` | 73 | 3,977 | ~1,050 | Always (no paths:) |
| `social-reaction-gate.md` | 37 | 2,068 | ~540 | Always (no paths:) |
| `voice-enforcement.md` | 22 | 925 | ~240 | Always (no paths:) |
| `token-discipline.md` | 46 | 2,833 | ~740 | Always (paths: ["**/*"] = matches everything) |
| `security.md` | 15 | 581 | ~150 | Always (paths: ["**/*"] = matches everything) |
| **Always-on rules total** | **530** | **29,114** | **~7,650** | **Every session** |
| **GRAND TOTAL (always-on)** | **766** | **42,436** | **~11,150** | **Every session** |

Note: `token-discipline.md` content also appears in `CLAUDE.md` lines 77-86 (duplicate), adding ~140 extra tokens. Total with duplication: ~11,290 tokens.

### Target State (after changes)

| Component | Lines | Est. Tokens | Loads When |
|-----------|-------|-------------|------------|
| `CLAUDE.md` (root, slimmed) | ~45 | ~600 | Every session |
| `q-system/CLAUDE.md` (slimmed) | ~40 | ~530 | Every session (via @import) |
| **CLAUDE.md total** | **~85** | **~1,130** | **Every session** |
| `audhd-interaction.md` | 22 | ~320 | Always (stays, 22 lines is fine) |
| `auto-detection.md` | 33 | ~590 | Always (stays, fires on pasted content) |
| `voice-enforcement.md` | 22 | ~240 | Always (stays, 22 lines is fine) |
| `social-reaction-gate.md` | ~22 | ~370 | Always (trimmed from 37, stays always-on) |
| `token-discipline.md` | 46 | ~740 | Always (paths: ["**/*"], sole copy after C4 dedup) |
| `security.md` | 15 | ~150 | Always (paths: ["**/*"], unchanged) |
| **Always-on rules total** | **~160** | **~2,410** | **Every session** |
| **GRAND TOTAL (always-on)** | **~245** | **~3,540** | **Every session** |

Budget check: 245 < 300. CLAUDE.md alone: 85 < 200. Both pass.

### Savings

| Metric | Before | After | Saved |
|--------|--------|-------|-------|
| Always-on lines | 766 | ~245 | **521 lines (68%)** |
| Always-on tokens | ~11,150 | ~3,540 | **~7,610 tokens/session** |
| Daily savings (10 sessions) | - | - | **~76,100 tokens/day** |
| Monthly savings (300 sessions) | - | - | **~2.3M tokens/month** |

### What moves to on-demand (path-scoped)

| Component | Lines | Est. Tokens | Now loads when |
|-----------|-------|-------------|----------------|
| `folder-structure.md` | 255 | ~3,700 | Files in `.claude/`, `plugins/`, `q-system/`, or scripts edited |
| `design-auto-invoke.md` | 27 | ~320 | HTML/CSS/TSX/JSX files edited |
| `memory-freshness.md` | 73 | ~1,050 | Memory files read/written |

These 355 lines (~5,070 tokens) still exist and still enforce. They just don't burn context when you're writing a DM.

---

## 13. Wiring Checklist (MANDATORY)

| Check | Status | Notes |
|-------|--------|-------|
| PRD file saved to `q-system/output/prd-claude-md-diet-2026-04-12.md` | Done | This file |
| All code/config changes implemented and tested | Pending | |
| New files listed in folder-structure rule (if any created) | Pending | `instruction-budget-audit.py` needs entry |
| New conventions referenced in root CLAUDE.md (if any added) | N/A | No new conventions, only removals |
| New rules referenced in folder-structure rules list (if any created) | N/A | No new rules |
| Memory entry saved for decisions/patterns worth recalling | Pending | Save: single 300-line budget, `**/*` = always-on, deterministic pre-commit enforcement |
| `kipi update --dry` confirms propagation diff (if skeleton files changed) | Pending | |
| `kipi update` run to push to all instances (if skeleton files changed) | Pending | |
| PRD Status field updated to "Done" | Pending | |
