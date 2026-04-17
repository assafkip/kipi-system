---
description: Review the active PRD with Codex and stream normalized findings to JSONL
allowed-tools: Bash
---

Review the active PRD against `templates/review-rubric.md`. The rubric defines
five dimensions (problem clarity, scope discipline, atomic decomposition, risk
surface, dependencies) and the severity scale (blocker | major | minor | nit).

Do not hand-edit the findings JSONL. Do not pass raw Codex output to the writer
verbatim. The writer accepts ONLY `{severity, body}` objects; extra keys are
rejected. This is the deterministic normalization layer — its whole purpose is
to refuse drifted Codex output shape.

Steps:

1. Resolve the active PRD:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prd_runner.py" status
```

Capture the `prd_id` and `spec_path` from the JSON output. If no PRD is active, stop and tell the author to run `/prd-start` first.

2. Read the PRD body and `templates/review-rubric.md`. Run Codex against them. Codex may return prose, markdown, or malformed JSON. That is expected.

3. Translate Codex's findings into the writer's input shape: a JSON array where every element is EXACTLY `{"severity": "blocker|major|minor|nit", "body": "one concrete concern"}`. One concern per element. No extra keys, no nesting. If Codex flagged the same concern twice, deduplicate.

4. Record the review.

   - If the array has at least one item, append via the writer. The writer assigns sequential ids, stamps `created_at`, sets `disposition: pending`, validates every field, AND stamps the PRD frontmatter with `codex_reviewed_at` as a side effect. That stamp is the approval gate's proof that Codex actually ran:

   ```bash
   echo '<JSON_ARRAY>' | \
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/findings_writer.py" \
     add "<prd-id>" --source codex-review
   ```

   - If Codex found nothing (clean pass), do NOT fabricate findings. Stamp the PRD with `record-review` so the approval gate can still fire:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/findings_writer.py" \
     record-review "<prd-id>" --source codex-review
   ```

   Source must be `codex-review` for a standard pass or `codex-adversarial` for an adversarial one. Without the stamp, `/prd-approve` will refuse to advance the PRD — that is the intended behavior. Do not try to work around it.

5. Advance the PRD to `in-review` so the findings gate will block approval:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prd_runner.py" advance in-review
```

6. Tell the author to triage with `/prd-triage`. Show the count of new findings and the severity breakdown (or "0 findings, clean pass recorded" if the review was clean).
