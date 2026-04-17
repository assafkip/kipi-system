---
description: Start a new PRD from an idea (creates spec, blocks on active issue)
argument-hint: <slug> [owner]
allowed-tools: Bash
---

Create a new PRD from the template. The slug becomes part of the PRD id
(`prd-<slug>-YYYY-MM-DD`). Slug must be kebab-case.

The runner enforces two invariants:
- No other PRD is active and non-archived.
- No issue is active (cross-runner concurrency guard).

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prd_runner.py" new "$1" --owner "${2:-${USER:-unknown}}"
```

If the command exits non-zero, surface stderr verbatim. Do not retry. Common rejections:
- slug format (not kebab-case)
- active PRD (advise `/prd-archive` or clear)
- active issue (advise closing the issue first)

After success, read the new PRD spec file to the author and ask them to fill in:
- Problem (concrete, observed, measurable)
- Goals and non-goals
- Proposed approach
- Risks and rollback
- Open questions

Do not auto-draft PRD content. The PRD is the author's contract. Auto-drafting creates sycophantic PRDs that pass review because Claude agreed with itself.
