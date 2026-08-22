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

founder-voice → voice-lint (+ voice-substance) · headline-engineering → headline-lint · audhd-executive-function → audhd-lint · linkedin-brand → linkedin-format-lint · rca → rca-lint (plugin hooks.json) · fable-discipline → fable-discipline-lint (prd-os plugin hooks.json — the skill is prd-os's execution-discipline layer, merged 2026-07-04; enforces test-isolation, the deterministic slice of "verify against a copy"). · lessons corpus → lessons-validator (allowlist frontmatter guard for q-system/lessons/). · memory-freshness (rule) → memory-freshness-check (SessionStart: surfaces decay:fast memories for verification). · memory-confidence (rule) → memory-confidence-validator (PostToolUse: blocks out-of-range confidence / unknown provenance on auto-memory writes) + memory-confidence-surface (SessionStart: surfaces low-trust memories at recall). · settings-template sync → settings-template-sync-check (PostToolUse on settings edits + `kipi update` preflight: blocks/aborts when an enforcement hook is wired in .claude/settings.json but missing from settings-template.json, which would ship its script to the fleet with the switch dead). · RULE-2026-06-30-A (instance automation lives at repo root) → instance-automation-guard (PostToolUse: blocks a script written into an INSTANCE's q-system/ subtree, which kipi update's rsync --delete would clobber; skeleton self-detects via instance-registry.json and no-ops; fleet-only, wired in settings-template.json + FLEET_ONLY). dev-skills-auto-invoke (rule) → dev-skills-lint (`kipi check` Gate 1.1c: every skill its trigger table names resolves to a readable SKILL.md; a dangling `~/.claude/skills` symlink passes, since no instance can repair the founder's machine, and a PASSING run costs one line -- the stale-link count folds into it and `--verbose` lists them, because six repeated non-actionable warnings per run train you to skim the gate). Correctly interpretive (no hook): research-mode, learn-from-correction, deck-ai, council, kipi-design (brand/design/ui-ux-pro-max).

## Trigger-eval pairings (advisory, not a blocking hook)

Interpretive auto-invoked skills (founder-voice, audhd-executive-function, rca, fable-discipline, social-reaction-gate) -- and the dev-skills-auto-invoke reflex -- cannot be gated by a deterministic hook -- whether they FIRE is a model decision. They instead get a TRIGGER-EVAL fixture set in `q-system/.q-system/skill-evals/<skill>.json` (should_trigger prompts), run ON-DEMAND by `q-system/.q-system/scripts/skill-trigger-eval.py` (it shells `claude -p`). This is ADVISORY and PERIODIC -- never a blocking exit-2 hook (it costs real Opus calls and the rate is noisy). It measures the one thing the lint layer structurally cannot see: whether the skill actually triggers.
A second advisory layer exists for the AUDHD output style: `q-system/.q-system/scripts/audhd-output-eval.py` (H2) measures whether the style IMPROVES output without regressing correctness or safety -- paired baseline/candidate responses, a blind A/B judge, a weighted rubric and a release gate (methodology adopted from ayghri/i-have-adhd, MIT). Cases in `q-system/.q-system/skill-evals/audhd-output-cases.json`, test `test-audhd-output-eval.py`. Same posture as trigger-eval: ON-DEMAND, ADVISORY, real model cost, never a blocking hook.

## Does NOT apply

Reference-only skills (no output); skills that emit code or visual artifacts (use type/lint/schema checks instead); one-shot internal-only outputs.

## Cross-references

`wiring-check.md` (broader wiring) · `token-discipline.md` (budget) · `q-system/.q-system/sycophancy-harness.py` (LLM-agent + deterministic-verifier exemplar).
