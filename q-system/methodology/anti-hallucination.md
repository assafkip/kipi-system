# Anti-Hallucination Architecture

## Thesis

Kipi assumes the LLM is unreliable on complex content. Every architectural choice in this repo follows from that assumption. The system doesn't try to make the model accurate. It makes the model's mistakes findable.

Trust moves from the model to the trail.

## The loop

1. **Input arrives.** A content draft, a debrief transcript, a decision to record, a client question.

2. **Pre-LLM hooks fire.** Deterministic checks that don't need a model. Banned words, known-bad patterns, schema validation. Anything regex can catch runs before the LLM sees it.

3. **LLM produces work, not answers.** The prompt forces structure. Not "what's true?" but "produce X, cite the source for each claim, mark `{{UNVALIDATED}}` on anything you can't ground." The model is constrained to traceable artifacts.

4. **Post-LLM hooks fire.** voice-lint, format-lint, headline-lint, audhd-lint, linkedin-format-lint, batch-uniformity-lint, decision-origin-tag-lint. Each catches one kind of deterministic violation.

5. **Verifier runs when relevant.** The sycophancy-harness checks debriefs for rubber-stamping. A second model independently produces output on contested claims. Disagreement routes to founder review.

6. **Audit trail writes.** Every step logged. Decisions get origin tags. Canonical changes write a ripple entry. Graph triples append with timestamps. Auto-commit captures the diff.

7. **Canonical updates.** Validated knowledge writes to canonical files. The next session reads those files first. Memory is structural, not "the model remembers."

## What ships vs what doesn't

| Naive pattern | Kipi pattern |
|---|---|
| LLM produces an answer | LLM produces a candidate with citations and confidence |
| Output is "what the model said" | Output is what survived the stations |
| Model uncertainty is hidden | Model declares uncertainty as a field |
| Wrong answers are silent failures | Wrong answers leave a trail you can find |
| Trust the model | Trust the trail |

## Source-of-truth hierarchy

When two files disagree, the more-rigorous file wins. Higher-rigor files get cited; lower-rigor files get corrected to match.

Order, most rigorous first:

1. **`memory/graph.jsonl`** (instance-specific path) — entity-relationship triples with timestamps and provenance. Append-only.
2. **`canonical/decisions.md`** — dated decisions with origin tags (`[USER-DIRECTED]` / `[CLAUDE-RECOMMENDED]` / `[COUNCIL-DEBATED]` / `[SYSTEM-INFERRED]`).
3. **`canonical/insights.md`** — validated cross-project patterns.
4. **`canonical/discovery.md`** — open questions tracked with `DQ-###` IDs.
5. **`dashboard.md`** — cross-project rollup. Derives from above.
6. **`projects/<engagement>/progress.md`** — narrative summaries. Can drift.
7. **Drafts in `output/drafts/`** — work in progress.

## What's automated vs structural

**Automated (hooks fire on every write):**

- `voice-lint` catches voice violations
- `format-lint`, `headline-lint` catch structural and stylistic drift
- `audhd-lint` enforces actionability rules
- `linkedin-format-lint` enforces channel constraints
- `batch-uniformity-lint` catches pattern repetition
- `decision-origin-tag-lint` enforces origin tags on decisions
- `memory-freshness-check` flags stale handoffs at session start
- `token-guard` prevents runaway loops
- `sycophancy-harness` checks debriefs for rubber-stamping
- `auto-commit` logs every change

**Structural (architecture forces surface-on-read):**

- Multi-file state means contradictions become visible when state is loaded
- Provenance citations let any claim trace back to source (message ID, file, date, person)
- Source-of-truth hierarchy resolves disagreements without ambiguity
- `DQ-###` prevents loss of open questions
- `{{UNVALIDATED}}` markers force ungrounded claims to wear a label

**Manual still required:**

- Noticing contradictions when state loads (no auto cross-file consistency hook yet)
- Tracing to the more-rigorous source
- Logging the correction in dashboard so the next session knows it was caught

## Worked example: catching a contradiction

From the Pure Spectrum instance dashboard, 2026-05-11:

> "Canonical corrections logged: JA3 send-status — `progress.md` was falsely claiming 'memo sent 2026-05-05' when `graph.jsonl` correctly held 'on hold pending send decision'; corrected today."

Steps:

1. Session loaded multiple state files including `progress.md` and `graph.jsonl`
2. Contradiction surfaced during read: progress said sent, graph said on hold
3. Hierarchy resolved it: `graph.jsonl` beats `progress.md`
4. The lower-rigor file was corrected to match the higher-rigor one
5. The correction was logged in dashboard so future sessions know this was caught

No model got smarter. The architecture made the lie visible.

## Known gap

No live hook performs automated cross-file consistency detection. Catches currently happen via read-time surface — when something (the founder or Claude) loads state and notices files disagree. Worth building if catch-rate becomes a constraint.

## Files referenced in this doc

- Hook scripts: `q-system/.q-system/scripts/`
- Verifier: `q-system/.q-system/sycophancy-harness.py`
- Canonical: `q-system/canonical/`
- Memory: instance-specific (e.g. `q-pure/memory/`, `q-investigate/memory/`)
- Settings: `.claude/settings.json`

## See also

- `ARCHITECTURE.md` — Design Thesis section
- `plugins/kipi-core/skills/research-mode/SKILL.md` — runtime enforcement of anti-hallucination behavior during research
- `q-system/methodology/debrief-template.md` — debrief workflow that exercises the loop end-to-end
- `.claude/rules/wiring-check.md` — end-to-end connection enforcement
