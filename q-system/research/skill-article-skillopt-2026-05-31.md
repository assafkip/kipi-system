# Skill Article: SkillOpt — train the skill, not the model

**Saved:** 2026-05-31. Parked for later thinking.
**Source:** arXiv:2605.23904 — "SkillOpt: Executive Strategy for Self-Evolving Agent Skills"
Microsoft + SJTU/Tongji/Fudan, May 2026. Code: https://aka.ms/SkillOpt
Local PDF copy of full text was at /tmp/a.pdf during the read session (re-fetch from arXiv if gone).

---

## One-line thesis

Stop hand-writing or one-shot-generating agent skills. Treat the skill `.md` as the
**trainable external state of a frozen model** and optimize it with deep-learning
discipline in text space. Model weights never change. Deploy cost = zero extra calls
(just a longer prompt).

## Results (why it's worth attention)

- Best-or-tied on all 52 (model, benchmark, harness) cells.
- GPT-5.5: +23.5 pts direct chat, +24.8 Codex, +19.1 Claude Code over no-skill.
- Final skills stay compact: 300–2,000 tokens after only 1–4 accepted edits.
- Skills transfer across model scales, across Codex↔Claude Code, and to nearby benchmarks.

## The analogy (Figure 1, verbatim)

| Deep learning | SkillOpt |
|---|---|
| parameter | skill document |
| gradient direction | trajectory-derived edit direction |
| learning rate | edit budget (max edits per step) |
| validation check | held-out selection gate |
| batch / schedule | rollout batch / minibatch / gate |

## The loop

Run skill on tasks → score rollouts → a **separate optimizer model** reads scored
traces → proposes bounded add/delete/replace edits → keep an edit **only if** a
held-out validation score strictly improves → rejected edits go to a buffer so they
aren't re-proposed. Epoch boundary: a slow/meta update writes a protected
longitudinal-guidance block (still gated).

## The 5 mechanisms that drove the gains (ablation-proven, Table 3)

1. **Held-out validation gate.** Accept only if it strictly beats current score on an
   unseen split. Biggest lever. Stops plausible-but-wrong edits accumulating.
2. **Bounded edits (textual learning rate).** Cap edits/step. Removing it: Spreadsheet
   77.5 → 71.8. Unbounded rewrites erase good rules + overfit to one failure.
3. **Rejected-edit buffer.** Failed edits become negative feedback. Removing it: 77.5 → 72.9.
4. **Separate optimizer from executor.** The model doing the task never edits its own
   skill. Prevents self-delusion. Optimizer-side memory is never shipped.
5. **Compact + procedural, not instance-specific.** Edits ranked by: systematic impact
   > fills a gap > general principle beats entity-specific > concrete over vague.

## Their edit-ranking criteria (Appendix C.2.6, verbatim order)

1. Systematic impact (fixes recurring failures, not edge cases)
2. Complementarity (fills gaps, doesn't duplicate)
3. Generality (general principle > tied to specific entity/question type)
4. Actionability (concrete guidance > vague advice)

## Their 5 design principles (Appendix C.4, verbatim)

1. Task-execution model is fixed; only the text skill changes.
2. Every candidate skill evaluated on a selection split before acceptance.
3. Minibatch analyses merged hierarchically → edits represent recurring evidence, not single examples.
4. Edit budget = learning-rate analogue: larger early changes, smaller late refinements.
5. Deployed skill stays lightweight + inspectable; optimizer-side meta skill stays separate.

## Qualitative: what optimized skills actually became

- **ALFWorld:** generic "search-transform-place" → finite-state policy with object-identity
  matching, visited-location memory, progress locks, loop breakers. 49.3 → 74.6.
- **SpreadsheetBench:** generic automation → workbook-forensics policy (inspect real
  workbook not previews, normalize keys/types, write evaluated static values even when
  prompt says formulas). 40.4 → 78.9.
- Pattern: edits ADD compact procedural constraints around observed failure modes. They
  don't replace the skill with an unrelated prompt.

## Default hyperparameters (for reference if we ever build the loop)

4 epochs, rollout batch 40, reflection minibatch 8 (16 parallel analysts), textual LR
Lt=4 cosine decay (floor 2), strict-greater validation gate (ties rejected), slow update
20 sampled tasks/epoch, patch edit mode, medium reasoning effort both sides.

---

## How this maps onto kipi (the actual "come back to this" part)

**We already have 2 of 4 layers. Missing the loop that connects them.**

Have:
- **Validator layer** — `skill-hook-pairing.md` ("skills generate, hooks validate") +
  voice-lint / headline-lint / audhd-lint. = the deterministic scorer SkillOpt needs.
- **One-shot edit proposer** — `learn-from-correction` skill proposes a principle edit
  from an (agent_output, human_output) pair, outputs a proposal for human review.

Missing (the SkillOpt core):
- **No held-out eval set per skill.** Hooks check the current draft; no fixed bank of
  "prompt → graded-good output" to score a skill *change* against. We edit on vibes.
- **No accept-only-if-score-improves gate.** `learn-from-correction` proposes, human
  eyeballs, done. No before/after number.
- **No rejected-edit memory.** Same weak guidance can be re-suggested across sessions.
- **Editor = executor.** Same Claude session writes content AND edits its own voice
  skill. Exactly the self-delusion the paper warns against.

Aligns with standing founder rules: "prefer deterministic script-based solutions,"
"fix exactly what was flagged, no scope expansion" (= bounded edits), skill-hook-pairing
thesis (= optimizer + verifier). SkillOpt is the missing middle: the gate.

## Options when we come back

- **Option 1 (Deep Focus, ~half day):** Eval bank + gate for ONE skill (assaf-voice).
  Build 15–25 held-out cases (prompt → ideal output, hand-graded). Score current skill
  with existing lints + rubric. Future edits must beat baseline or rejected.
- **Option 2 (Deep Focus, ~1–2 days, needs 1 first):** Upgrade `learn-from-correction`
  into a gated loop — propose bounded edit (1–2 ops) → re-run on eval bank → accept only
  if strictly improves → log rejects to a buffer the proposer reads next time.
- **Option 3 (Quick Win, ~20 min):** Just adopt the cheap discipline now — add to
  skill-creator / skill-hook-pairing: (a) edits bounded to 1–2 changes no wholesale
  rewrite, (b) prefer general principles over entity-specific rules, (c) keep skills
  300–2,000 tokens.

**Prior call:** Option 1 first (the eval bank is what we structurally lack and what makes
everything else measurable), Option 3 immediately, Option 2 only if the gate earns it.

## Open questions to think about later

- Is a held-out eval bank maintainable for a voice skill where "good" is subjective?
  (The gate needs a stable scorer. Lints are deterministic; voice quality isn't fully.)
- Could the "separate optimizer" be a different model/session (e.g. Codex) to get true
  executor/optimizer separation cheaply?
- Does this generalize past voice — e.g. the prd-os / dsse skills where success IS
  deterministic (receipts, gates)? Those might be the better first target than voice.
