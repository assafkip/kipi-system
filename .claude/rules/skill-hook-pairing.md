# Skill-Hook Pairing (ENFORCED)

Skills generate. Hooks validate. Every skill with DETERMINISTIC rules must ship a paired hook that enforces them. A skill without its hook is an aspiration.

## Decision rule

For each rule in a skill, ask: can it be caught by regex, string match, char count, or file inspection?

- **Yes** → it MUST have a hook; skill enforcement alone is insufficient. (Deterministic = banned words/chars, length caps, required structure, file-path constraints, citation/regex patterns.)
- **No** (needs judgment: tone, scar-anchoring, mode, specificity) → it lives in the skill. No hook.
- **Partial** → split it: hook the deterministic part, leave interpretation in the skill.

## Pairing contract

- A deterministic skill is not shippable without its hook (wiring-check enforces this).
- Hook lives at `q-system/.q-system/scripts/<skill>-lint.py` (per folder-structure), wired in `.claude/settings.json` PostToolUse — or the plugin's `hooks.json`.
- **Scope must match the skill.** Self-scope inside the script by `tool_input.file_path` and fast-exit on out-of-scope/code edits — never run logic on every Edit (token discipline).
- **Exit-code contract:** exit 2 = block (stderr fed to Claude), exit 0 = pass. The `test -f X && python3 X` guard makes a missing script a no-op; add `|| true` only to make a hook advisory rather than blocking.
- The script's header comment names the skill it pairs with.

## Override

Hooks block by default. Bypass per-file with an explicit marker (one per hook, no stacking): `<!-- voice-lint-skip -->`, `# headline-lint-skip`, etc.

## Wired pairings (status)

founder-voice → voice-lint (+ voice-substance) · headline-engineering → headline-lint · audhd-executive-function → audhd-lint · linkedin-brand → linkedin-format-lint · rca → rca-lint (plugin hooks.json) · fable-discipline → fable-discipline-lint (plugin hooks.json; enforces test-isolation, the deterministic slice of "verify against a copy"). · lessons corpus → lessons-validator (allowlist frontmatter guard for q-system/lessons/). Correctly interpretive (no hook): research-mode, learn-from-correction, deck-ai, council, kipi-design (brand/design/ui-ux-pro-max).

## Does NOT apply

Reference-only skills (no output); skills that emit code or visual artifacts (use type/lint/schema checks instead); one-shot internal-only outputs.

## Cross-references

`wiring-check.md` (broader wiring) · `token-discipline.md` (budget) · `q-system/.q-system/sycophancy-harness.py` (LLM-agent + deterministic-verifier exemplar).
