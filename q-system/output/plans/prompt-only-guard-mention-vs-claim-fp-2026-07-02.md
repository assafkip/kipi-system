<!-- prompt-only-enforcement-skip: this plan documents the guard's own
     mention-vs-claim FP; the guard blocked this very file on first write
     (live repro). The enforcement described here is executable:
     test-prompt-only-enforcement-guard-stderr.sh -->

# prompt-only-enforcement-guard: mention-vs-claim false positive (sp-edf9395d)

**What/why:** Verified live 2026-07-02: the guard flagged 11 lines of PRD
prd-prompt-only-guard-stderr-2026-07-02, including pure frontmatter
(`id:`/`title:`/`status:`), even though the doc names its executable blocker
(a hook plus a regression test) throughout. Root cause: the trigger regexes
and the suppressors both read the same +/-2-line window, so a blocker named
3+ lines from the trigger line is invisible to the suppressor. Frontmatter
metadata also matches the subject+action regexes ("Prompt Only Guard" =
subject "prompt" + action "guard") despite being a description, not a claim.
While writing this plan the guard blocked THIS file on the same FP - a live
second reproduction.

**Approach (the two mitigations named in the spillover entry, both minimal):**
1. Exempt leading YAML frontmatter lines (block delimited by `---` starting
   at line 0). Metadata is not an enforcement claim.
2. Split the windows: triggers and negation keep the +/-2 window; the
   deterministic-blocker suppressors (guard filename + DETERMINISTIC_RE)
   read a wider +/-6 window. Negation stays narrow on purpose - widening it
   would let a "must not" six lines away mask a real claim.
No changes to the regexes, target extensions, skip marker, or exit contract.

**Files to touch**
- `q-system/.q-system/scripts/prompt-only-enforcement-guard.py` - frontmatter
  skip + dual-window `_is_violation`
- `q-system/.q-system/scripts/test/test-prompt-only-enforcement-guard-stderr.sh`
  - new sections pinning: frontmatter-only FP passes; blocker named 4 lines
  away suppresses; blocker 8+ lines away still blocks; bare claim still blocks

**Acceptance criteria**
- [ ] New test sections shown FAILING against the unfixed script
- [ ] Frontmatter-metadata fixture (modeled on the archived PRD) exits 0
- [ ] Claim with blocker named within 6 lines exits 0
- [ ] Claim with blocker named 8+ lines away still exits 2 (window is wider,
      not document-wide)
- [ ] Original violation fixture still exits 2; stderr contract sections
      still pass
- [ ] Resolve path: sp-edf9395d stays open until this ships through the
      gated issue flow; this branch is the fix + reproducer

**Patterns to follow:** black-box fixture tests in the existing stderr test
(mktemp fixture dir, exit-code asserts); negative self-test before fix
(fable-discipline); scar-anchored why-comments citing sp-edf9395d.
