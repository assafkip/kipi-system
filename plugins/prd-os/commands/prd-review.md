---
description: Review the active PRD with Codex and stream normalized findings to JSONL
allowed-tools: Bash
---

Review the active PRD against `templates/review-rubric.md`. The rubric defines
six dimensions (problem clarity, scope discipline, atomic decomposition, risk
surface, dependencies, recurring gap classes) and the severity scale
(blocker | major | minor | nit). Dimension 6 points at `templates/gap-classes.md`,
the catalog of defect shapes that repeatedly ship past review.

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

2. Read the PRD body, `templates/review-rubric.md`, and `templates/gap-classes.md`. Run Codex against all three (the gap-classes catalog is what dimension 6 evaluates against). Codex may return prose, markdown, or malformed JSON. That is expected.

3. Translate Codex's findings into the writer's input shape: a JSON array where every element is EXACTLY `{"severity": "blocker|major|minor|nit", "body": "one concrete concern"}`. One concern per element. No extra keys, no nesting. If Codex flagged the same concern twice, deduplicate.

4. Record the review.

   - If the array has at least one item, append via the writer. The writer assigns sequential ids, stamps `created_at`, sets `disposition: pending`, validates every field, AND stamps the PRD frontmatter with the review proof (`codex_reviewed_at` plus `reviewed_by: <source>`) as a side effect. That stamp is the approval gate's proof that a real reviewer ran:

   ```bash
   echo '<JSON_ARRAY>' | \
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/findings_writer.py" \
     add "<prd-id>" --source <SOURCE>
   ```

   - If the reviewer found nothing (clean pass), do NOT fabricate findings. Stamp the PRD with `record-review` so the approval gate can still fire:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/findings_writer.py" \
     record-review "<prd-id>" --source <SOURCE>
   ```

   **`<SOURCE>` names the reviewer that actually ran. Never substitute one for another.**

   | Reviewer that ran | Standard pass | Adversarial pass |
   |---|---|---|
   | Codex | `codex-review` | `codex-adversarial` |
   | Claude senior-staff-engineer subagent | `claude-review` | `claude-adversarial` |

   Pick the row for the reviewer that ACTUALLY ran. Stamping `codex-*` for a pass Codex did not run puts a false provenance record in the findings ledger — worse than being blocked, in a repo whose whole thesis is receipts. Do NOT hardcode an outage into this file: a stale availability note outlives the outage and sends every later session to the wrong reviewer. `manual` and `plan` are the author's own words and the writer refuses them here by design.

   **When a reviewer is unavailable (no credits, missing auth), the ORDER is not yours to choose.** It lives in `q-system/.q-system/scripts/reviewer-resolve.sh`, the one chain every review call site in this fleet reads (ASK-3831). Walk it top to bottom:

   ```bash
   RR="$(git rev-parse --show-toplevel)/q-system/.q-system/scripts/reviewer-resolve.sh"
   bash -c ". \"$RR\" && reviewer_candidates review"
   ```

   It prints `<engine>  <account>  <stamp>`, one rung per line: Codex on the primary account, Codex on the other account when one is configured, then Opus. The stamp on the rung you land on is the stamp you write — you do not compose it yourself. Resolve `$RR` from the repo you are reviewing in, not from `${CLAUDE_PLUGIN_ROOT}`: plugins run from the marketplace clone, so a plugin-relative path reads a different copy than the one this repo's tests pin.

   **Record the outage there, not here.** Before moving down a rung:

   ```bash
   EFL="$(git rev-parse --show-toplevel)/q-system/.q-system/scripts/env-failure-lib.sh"
   bash -c ". \"$EFL\" && . \"$RR\" && reviewer_note_codex_outage <account> \"$(codex_env_marker \"$CODEX_OUT\" \"$CODEX_RC\")\""
   ```

   That writes at most ONE event per account per UTC day, which `fleet-health-daily.py` turns into one line for Sana. The reason this is a function call and not a note in your own output: Codex ran out of credits on 2026-09-16 and every call site recorded it privately, per PR — 24 cap tickets, every "Codex" round for seven weeks a degraded Opus stand-in, and no single line anywhere saying the fleet was down to one reviewer.

   **Never pass Codex's own refusal line, or any prose of yours, as that second argument.** What you pass lands in a PERMANENT Linear issue body, and a finding carries a reference, never untrusted text (ASK-204; ASK-3988 settled the same question for the worker's Codex branch). `codex_env_marker` is the fleet's closed vocabulary for this and is the only thing you hand over; the resolver coerces whatever arrives to one of `REVIEWER_OUTAGE_CODES` anyway, so free text does not reach the issue — it just arrives as `unclassified` and the operator loses the one grain of detail the marker would have carried. Codex's full output belongs in the review artifact on disk, which is where you already keep it.

   Without the stamp, `/prd-approve` will refuse to advance the PRD — that is the intended behavior. Do not try to work around it.

5. Advance the PRD to `in-review` so the findings gate will block approval:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prd_runner.py" advance in-review
```

6. Tell the author to triage with `/prd-triage`. Show the count of new findings and the severity breakdown (or "0 findings, clean pass recorded" if the review was clean).
