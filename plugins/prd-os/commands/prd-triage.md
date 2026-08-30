---
description: Triage pending findings on the active PRD
argument-hint: [finding-id disposition [rationale]]
allowed-tools: Bash
---

Set dispositions on the active PRD's findings. `/prd-approve` is blocked by the
runner's findings gate until every finding has a non-pending disposition.

Dispositions:
- `accepted` — will be fixed in this PRD. No rationale needed.
- `rejected` — will NOT be addressed. `--rationale` REQUIRED (why not).
- `deferred` — tracked but out of scope for this PRD. `--rationale` REQUIRED (where).
- `pending` — initial state; can be used to revert a premature disposition.

Do not edit the JSONL file by hand. The writer enforces the rationale rule and
stamps `resolved_at` atomically with the disposition change.

Steps:

1. Resolve the active PRD id:

```bash
PRD_ID=$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/prd_runner.py" status | \
  python3 -c "import sys,json; s=json.load(sys.stdin); print(s.get('prd_id') or '')")
```

If `PRD_ID` is empty, tell the author no PRD is active and stop.

2. Print the cross-PRD advisory. This surfaces prior findings from sibling PRDs
   that were already `rejected` or `deferred` and closely match a pending
   finding here, so the author triages with the prior rationale in view:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/findings_writer.py" advisory "$PRD_ID"
```

   The advisory is deterministic (token-shingle similarity, no LLM) and printed
   by the runner, not assembled here. It is informational only: it never blocks,
   never auto-dispositions, and any xref failure is swallowed so triage proceeds.
   Empty output means no sibling PRD settled anything similar.

3. List pending findings:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/findings_writer.py" list "$PRD_ID" --only-pending
```

Show them to the author. For each, ask what disposition they want. Do NOT guess the author's intent; pending findings are theirs to resolve.

4. **Run the blind judge BEFORE the author decides**, once per finding. This is
   what makes a triage a calibration case: `evaluate` scores a receipt only when
   it carries BOTH a judge prediction and a human decision.

```bash
JUDGE_RUN="$(mktemp -t judge-run-XXXXXX).json"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/judgment_compiler.py" \
  judge --prd "$PRD_ID" --finding <finding-id> --output "$JUDGE_RUN"
```

   The judge runs with tools OFF and sees only the frozen context packet, which
   carries no disposition or rationale. **Do NOT show its prediction to the
   author before their disposition is set.** An author who sees the prediction
   and agrees inflates measured agreement, and the calibration set stops
   measuring anything. Report it afterwards, or not at all.

   If the judge call fails, say so and continue WITHOUT `--judge-run`. A model
   outage must not wedge triage; it costs one calibration case, and a receipt
   with an honest missing judge is worth more than a blocked author.

5. Apply each disposition. Pass the structured reason code and its evidence so
   the judgment receipt captures a machine-checkable decision, not prose:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/findings_writer.py" \
  set-disposition "$PRD_ID" <finding-id> <accepted|rejected|deferred> \
  [--rationale "<text>"] \
  [--reason-code <valid-fix-now|already-remediated|duplicate|owned-by-other-prd|scope-removed|out-of-scope|superseded|defer-dependency|defer-ordering|invalid-finding|insufficient-context|needs-human>] \
  [--evidence <finding:prd/id | issue:id | prd:id | receipt:id | commit:sha | test:path | scope:path#section | judgment:receipt-id | spillover:id>]...
  [--judge-run "$JUDGE_RUN"]
```

   Every adjudication appends an immutable receipt to `.prd-os/judgments.jsonl`
   (the Judgment Compiler ledger — `judgment_compiler.py`, enforced in code,
   not here). Evidence-requiring codes (`duplicate`, `already-remediated`,
   `owned-by-other-prd`, `scope-removed`, `out-of-scope`, `superseded`) are
   REFUSED by the writer without a stable `--evidence` reference; the findings
   file stays untouched on refusal. Omitting `--reason-code` still works and
   records an honest `null` — prefer passing it: receipts with codes are what
   the calibration evaluator and policy-candidate detector can learn from.

6. When all findings are dispositioned, remind the author to run `/prd-approve`.
   `kipi judgment verify` re-proves the receipt chain any time.
