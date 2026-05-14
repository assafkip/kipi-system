---
description: Run the Skeptic persona session against the active draft PRD
allowed-tools: Bash, Read, Edit
---

Run the planning-personas Skeptic session against the active PRD. Refuses if the PRD is not in `draft` state, and writes the result as a `## Persona Review` section in the PRD spec.

## Phase 0 runtime gate (ENFORCED)

The command refuses to run unless `q-system/memory/working/prd-personas-baseline.md` contains the literal line `phase_0_kill_criterion: failed`. Until Phase 0 has been measured and failed the 50% reduction target, this command is dead code. Use the commented-out Persona Review template in `plugins/prd-os/templates/prd.md` instead.

The check is the first thing the command does:

```bash
grep -q '^phase_0_kill_criterion: failed$' q-system/memory/working/prd-personas-baseline.md || { echo "refused: Phase 0 gate not cleared. Use the template scaffold instead." >&2; exit 2; }
```

This is enforcement, not a prose warning.

## Steps

1. Resolve the active PRD:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prd_runner.py" status
```

Capture the `prd_id`, `spec_path`, and `status` from the JSON. If no PRD is active, stop and tell the author to run `/prd-start` first. If the status is not `draft`, refuse with the current state and a hint to run `/prd-revise` if the PRD needs to come back to draft.

2. Read the PRD body. Read `${CLAUDE_PLUGIN_ROOT}/personas/skeptic.md` to load the pinned questions and anti-patterns. Do not paraphrase the questions; they are asked verbatim.

3. Run the Skeptic session in conversation with the founder:
   - Ask each of the three pinned questions in order.
   - Wait for an answer to each before moving on.
   - A brief answer is acceptable. A dismissive answer ("nothing important") fires the anti-pattern warning from `skeptic.md`; surface the warning and re-ask the question once. After one re-ask, accept whatever the founder writes.
   - **Skip** is allowed: if the founder types only `skip` (case-insensitive, optionally with trailing punctuation), the Q-A pair records the answer literally as `skipped` rather than as the founder's prose. This preserves the question in the durable section while honoring the founder's choice not to engage with that specific question.
   - The founder may type `abort` or `cancel` at any time. In that case do NOTHING to the PRD spec; partial answers are discarded.
   - Interruption (session ends before all three questions answered) is treated the same as abort: nothing is written.
   - **Answer sanitization (ENFORCED):** before writing answers to the PRD spec, reject any answer that contains a level-2 markdown heading (`^## ` at the start of any line) OR a fenced code block (\`\`\`). These would corrupt `prd_split.py`'s extraction logic, which anchors on `## Issues` and the first fence after it. If a founder answer contains either, refuse and re-ask the question with a hint to remove level-2 headings and fenced code blocks. The Q-A pair is only persisted after the sanitization check passes.

4. After all three questions are answered, write the result to the PRD per the rerun rules below.

5. Update the PRD frontmatter `updated_at` to the current ISO timestamp via direct Edit on the spec file. Do not advance the PRD state; the persona session does not change `status`.

## Rerun, dup-section, and abort handling

- **First run on this PRD** (no `## Persona Review` heading exists in the spec): append a new section at the position immediately before the `## Issues` heading. The section starts with a `## Persona Review` heading and contains a single `### Skeptic` subsection with the three Q-A pairs.

- **Rerun on the same PRD** (a `## Persona Review` heading already exists): do NOT add a second `## Persona Review` heading. Append a new timestamped subsection `### Skeptic (rerun YYYY-MM-DDTHH:MM:SSZ)` under the existing `## Persona Review` section. Earlier subsections are preserved unchanged; the new run is additive.

- **Verify before writing**: count `## Persona Review` occurrences in the spec, IGNORING occurrences inside HTML comment blocks (`<!-- ... -->`). The Phase 0 template scaffold contains a commented-out `## Persona Review` placeholder; this must not be confused with a real section. If the post-strip count after the proposed edit would be greater than 1, refuse and surface a hint to the founder. The command strips HTML comments with a regex pass before counting headings.

- **Section placement**: the `## Persona Review` heading must appear after `## Open questions` and before `## Issues`. This placement is required so that `prd_split.py` (which anchors on `## Issues`) is unaffected and so that Codex review sees the section as context for the substantive PRD content.

- **Abort or interruption**: if the founder types "abort" or "cancel" at any prompt, OR if the session ends before all three questions are answered, write nothing. Do not save partial answers. The next invocation starts fresh.

## What this command does NOT do

- Does not advance the PRD state. The PRD remains in `draft` after the session.
- Does not modify the review-rubric.md. Codex still scores the PRD against the same rubric, unaware of whether personas ran.
- Does not nudge `/prd-review` to ask about personas. `/prd-review` is unchanged.
- Does not block `/prd-review`. Skipping `/prd-personas` is allowed and has no enforcement.

## Codex review note

This command file is itself reviewed by Codex when the issue executes. The review checks: scope adherence (no edits outside allowed_files), correctness of the rerun rules, abort handling, and consistency with the parent PRD's documented behavior.
