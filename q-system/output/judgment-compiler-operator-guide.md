# Judgment Compiler — operator guide

One page. What it does: every finding triage now leaves an immutable,
hash-chained receipt of the decision AND the workflow state it was made in.
Those receipts are the calibration dataset the v1 benchmark proved we were
missing. (Energy: Quick Win per command, under 1 min each.)

## Where it lives

- Ledger: `.prd-os/judgments.jsonl` (main checkout, shared by all worktrees)
- Policy proposals: `.prd-os/judgment-policy-candidates.jsonl`
- Engine: `plugins/prd-os/scripts/judgment_compiler.py`
- PRD: `q-system/output/prd-judgment-compiler-2026-08-04.md` (ASK-363)

## Daily use (inside /prd-triage — nothing new to remember)

Triage works exactly as before. One upgrade: pass a reason code + evidence and
the decision becomes machine-learnable:

```bash
python3 plugins/prd-os/scripts/findings_writer.py \
  set-disposition <prd-id> finding-3 rejected \
  --rationale "same defect as finding-1" \
  --reason-code duplicate --evidence finding:<prd-id>/finding-1
```

- `duplicate`, `already-remediated`, `owned-by-other-prd`, `scope-removed`,
  `out-of-scope`, `superseded` are REFUSED without `--evidence` (that is the
  point: unsupported dispositions stop passing as facts).
- No `--reason-code`? Still works, records an honest null.
- Emergency off switch: `KIPI_JUDGMENT_CAPTURE=0` (exact legacy behavior).

## Commands (from any instance repo)

```bash
kipi judgment verify              # re-prove the whole receipt chain
kipi judgment evaluate            # calibration metrics + release-gate status
kipi judgment assemble --prd <id> --finding <id>   # see decision-time context
kipi judgment sample-check --basis <sha256>        # reproduce a 5% sample verdict
kipi judgment policy-candidates   # repeated overrides -> reviewed proposals
kipi judgment selftest            # in-memory contract proof (read-only safe)
```

## Calibration status (2026-08-04)

- Prospective context-complete decisions: **0 of 50 required**. They accrue
  automatically as you triage; no separate data-entry task exists.
- Release gates (all must pass before the judge auto-decides anything):
  ≥88% exact agreement, kappa ≥0.80, ≥80% per-class recall, ≥50 cases,
  zero evidence-gate bypasses. Check any time: `kipi judgment evaluate`.
- Until then the judge only recommends. v1 evidence for why: 40% agreement,
  92% confidence, worse than accept-all.

## Policy candidates

`kipi judgment policy-candidates` writes proposals only (`status: proposed`,
counterexample search recorded). Promotion to a real gate = normal PRD/issue
flow + `gate_register`. The tool has no code path to install anything — a
grep test enforces that.
