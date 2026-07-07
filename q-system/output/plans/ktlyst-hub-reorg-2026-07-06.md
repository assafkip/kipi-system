# Plan: dissolve ktlyst-hub — the final persona-reorg batch (Tier-2)

**What/why:** ktlyst-hub is the last cluster in the fleet persona-reorg. Its 6
instances scatter into existing personas; the `ktlyst-hub/` cluster dissolves.
This is Tier-2 (registry + bridge + cluster-rule + git worktrees) — the highest
blast radius of the whole reorg, which is why it was gated on a founder taxonomy
call and left for last.

**Status:** SPEC'D. Engineering PRD written (founder-delegated the calls):
`q-system/output/prd-ktlyst-hub-dissolution-2026-07-06.md`. Both open decisions
RESOLVED there — product bucket = **B (`ktlyst-saas/`)**; worktree handling =
**A (git-correct `git worktree repair <newpaths>`)**. Nothing moves until the
dry run is reviewed.

**Worktree wrinkle — RESOLVED (investigation + salvage-check 2026-07-06):**
`product-baseline` is a *linked worktree* of `product` (branch `feat/v5-canonical-port`),
not an independent repo. Founder-corrected intent: **baseline is the SUCCESSOR** (the v5
canonical port), `product` is the deprecated old line kept alive only by automated
skeleton syncs. So the good product's git metadata is trapped inside the repo we want to
retire. Salvage-check verified nothing stranded on old product: all 8 gate/packaging
files it added exist on baseline at equal-or-greater size (the 3 real-looking merges —
ATT&CK technique-fit, fabricated-IOC rejector, source-fidelity gates — were forward-ported
into baseline and extended). `/Users/assafkip`→`/Users/assafkipnis` is a two-Mac migration
symlink the linkage currently rides on.

Fix (PRD Change 2, `detach_worktree_to_standalone`): commit baseline's pending work →
`git clone --single-branch` it into a standalone repo at `ktlyst-saas/projects/product`
→ rename branch to `main` → **verify independence** (clone survives old product removal)
→ `git worktree remove` the redundant baseline → **archive** old `product` to `_archive/`
(reversible, never `rm`). Registry `ktlyst` → new standalone path. A fresh clone drops the
symlink dependency for free.

---

## Where the reorg stands (2026-07-06)

- **DONE (6 moves):** cole-gtm, consulting, micro-saas, intel, dev-tools personas
  migrated; interview-coach-public re-homed dev-tools -> micro-saas (RULE-F).
- **DONE:** the stale-ref remediation PRD (`prd-reorg-stale-ref-remediation-2026-07-06`,
  archived) — hardened `persona-reorg.py`'s rewriter (all 4 path forms + .mjs/.cjs),
  added the `--remediate` cross-project sweep, hardened the audit gate
  (`scripts/reorg-stale-ref-audit.py`, exit 0 = clean). **The tool is now battle-ready
  for Tier-2.** Pre-existing wrong-user refs -> spillover sp-01ae37c2.
- **REMAINING:** ktlyst-hub (this plan).

## Founder taxonomy decisions (captured)

| ktlyst-hub instance | Destination | Status |
|---|---|---|
| `accountant` (registry `accountant`) | `consulting/projects/accountant` | FIRM |
| `lawyer` (registry `ktlyst_lawyer`) | `consulting/projects/lawyer` | FIRM |
| `strategy` (registry `KTLYST_strategy`) | `cole-gtm/projects/strategy` | FIRM |
| `deliverables` (nogit) | `intel/projects/deliverables` | FIRM |
| `product` (registry `ktlyst`) | ktlyst SaaS bucket (see OPEN) | OPEN |
| `product-baseline` (nogit, worktrees?) | same bucket as product | OPEN |

**OPEN decision — product bucket (A or B):** founder said the product is "another
one of the ktlyst list of SaaS products, subdomain later."
- **A:** `micro-saas/projects/product` — with the existing SaaS. Simplest; odd name
  for the flagship.
- **B:** new `ktlyst-saas/projects/` bucket — dedicated KTLYST-branded SaaS home
  (product + product-baseline; room to grow). Agent recommendation.

## Tier-2 dependency surface (from recon)

- **Registry (4 rewrites):** `ktlyst`->product, `KTLYST_strategy`->strategy,
  `ktlyst_lawyer`->lawyer, `accountant`->accountant.
- **launchd:** only `com.ktlyst.q-morning.plist.disabled` (rewrite-only, no reload).
- **`~/.ktlyst/bridge/` cluster state:** product writes `product_state.json`;
  strategy writes `canonical-digest.json` + `market_signal.json`; lawyer writes
  `legal-flags.json`. The bridge DIR does not move, but writer self-ref paths do,
  and `bridge-sync.py` / `inject-bridge.sh` / `scripts/` may hardcode instance paths.
- **`~/.claude/rules/ktlyst-cluster.md`:** hardcodes `~/projects/ktlyst-hub/<instance>`
  for strategy, lawyer, accountant, product (the `--add-dir` + canonical-authority
  table). Must be rewritten to the new paths. This is a GLOBAL rule (HELD class —
  founder-confirm before edit, per the tool's Phase D).
- **git worktrees to repair (tool does this):** product (4), strategy (2),
  product-baseline (4 — see wrinkle).

## Tier-2 wrinkle to resolve FIRST

`product-baseline` reports **4 worktrees on a nogit dir** (no `.git` directory).
Abnormal — worktrees need a `.git`. Likely a linked worktree of `product`, or a
detached `.git` file. Moving it blind could orphan the worktrees. **Step 1 is to
investigate this before any move.**

## The tool extension needed (finding: current model can't express this)

Every prior persona moved into ONE parent bucket. ktlyst-hub scatters into 4
destinations. `persona-reorg.py`'s `PERSONAS` schema assumes one parent + a flat
projects list all landing under `parent.dst/projects/`. This batch needs a
**per-project destination override** (each project names its own target bucket).

Deterministic path (matches the founder "fix the tool" preference):
- Add an optional `dst_bucket` (or `dst_persona`) field per project entry; when
  present, the project moves under that bucket's `projects/` instead of the
  persona parent's. cole-gtm/consulting/intel/micro-saas are already migrated, so
  this batch is a DISTRIBUTION into existing buckets (no new parent for FIRM
  items; a new `ktlyst-saas` parent only if product-bucket = B).
- Unit-test the distribution mapping (like `test_persona_reorg.py`).
- Reuse everything already hardened: worktree repair, all-form self-ref rewrite,
  `.remediation.bak` namespace, the audit gate.

## Proposed sequence (execute on OK, dry-run gated)

1. **Investigate** product / product-baseline worktrees (the wrinkle). Resolve
   before any move.
2. **Extend** `persona-reorg.py` for per-project destinations + unit test.
3. **Add** the ktlyst-hub distribution to `PERSONAS` (or a distribution map),
   with the FIRM destinations + the chosen product bucket.
4. **Cluster teardown:** rewrite `ktlyst-cluster.md` (HELD — founder confirm),
   repoint the 4 registry entries, the disabled plist, the bridge writer refs.
5. **Dry-run** -> review -> **apply** -> `git worktree repair` -> `--remediate`
   sweep -> `scripts/reorg-stale-ref-audit.py` exit 0 -> `kipi check` FAIL<=2.
6. **Track canonical:** fleet-map.md + decisions.md (RULE-2026-07-06-G) as we go.
7. Decide ktlyst-hub cluster-rule fate: dissolved entirely, or a thinner cluster
   rule survives if any instance stays.

## Acceptance criteria

- [ ] product/product-baseline worktree situation understood + safe-move plan
- [ ] tool supports per-project destinations, unit test green
- [ ] `--dry` reviewed before apply
- [ ] all 6 instances at new paths; `ktlyst-hub/` empty/gone
- [ ] `kipi check` FAIL<=2 (baseline), `kipi list` resolves
- [ ] 4 registry entries repointed
- [ ] `ktlyst-cluster.md` rewritten (founder-confirmed) or the cluster formally retired
- [ ] bridge reads/writes still resolve (`product_state.json` etc.)
- [ ] `reorg-stale-ref-audit.py` exit 0 after the move
- [ ] fleet-map.md + decisions.md updated
- [ ] rollback proven (manifest + `.bak`)

## Patterns to follow (this repo's own)

- The hardened `persona-reorg.py` (all-form rewriter, worktree repair, bak
  namespace) — do NOT reintroduce the gaps the remediation PRD just closed.
- `scripts/reorg-stale-ref-audit.py` exit 0 is the deterministic done-gate.
- Canonical tracked per structural move, not batched ([[feedback_canonical_tracks_reorg]]).
- Instance automation stays repo-root, never synced subtrees ([[launchd-autonomous-layer]]).
- Cross-instance preflight for the ktlyst-cluster.md edit (echo path, confirm).
