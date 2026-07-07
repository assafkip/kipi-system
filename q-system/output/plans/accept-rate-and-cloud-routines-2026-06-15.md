# Plan: steal the two loop-engineering bits worth stealing

Date: 2026-06-15
Source: the "Loop engineering: 14-step roadmap" article (Osmani / Anthropic docs /
Huntley Ralph Wiggum). Verdict on the article: it describes the system kipi already
runs. Only two pieces are net-new for this fleet. This plan pulls both.

## Track 1 — accepted-change rate (the metric that actually bites here)

### What / why
The article's KPI is "cost per accepted change." For this fleet that denominator is
wrong: tokens are effectively unmetered, so cost is not the constraint. The real
constraint the article itself names is review capacity. The honest adaptation:
**measure how often the gate's objections get fixed vs waved.** If Codex raises a
major finding and it gets deferred/optional instead of fixed, the gate is decorating,
not blocking. That rate is the comprehension-debt early warning, in our own receipts.

### Approach (three options, pick marked)
- **(A) Cost per accepted change** — tokens / accepted change. Rejected: `metrics.db`
  has no token/cost column (confirmed: only content_performance, outreach_log,
  copy_edits, behavioral_signals, daily_metrics, ab_tests). Needs new token
  instrumentation across every loop. Heaviest, lowest payoff for an unmetered plan.
- **(B) Disposition rate from prd-os/dsse receipts** ← PICK. Reads existing
  `.prd-os/findings/*.jsonl` + `.prd-os/receipts.jsonl`. Computes, per PRD and rolled
  up: accept-rate (accepted / total), deferred-major rate, rejected rate, resolution
  latency, findings-per-issue density. Zero new instrumentation, deterministic, fits
  the anti-hallucination "trust the trail" architecture.
- **(C) Both, layered** — add token cost later if a metered instance appears. Defer.

Pick: **B.** It uses data that already exists, measures the constraint that actually
binds (review burden, not spend), and is pure-deterministic so it pairs with a hook
like the sycophancy harness does.

### The signal, concretely (grounded in real data today)
`prd-build-craft-2026-06-15-findings.jsonl` has 3 findings: 2 accepted (fixed), 1
deferred with severity `major`. So that PRD scores: accept-rate 2/3, deferred-major
rate 1/3. A deferred MAJOR is the line worth watching: a real objection the gate
raised that shipped unfixed with a written rationale. One is fine (it had a
rationale). A pattern of them is the gate going soft.

### Files to touch
- **New:** `q-system/.q-system/scripts/accept-rate.py` — reads `.prd-os/findings/*.jsonl`
  + `.prd-os/receipts.jsonl`, prints per-PRD + rolled-up disposition table and flags
  any PRD whose deferred-major rate is over threshold. QROOT resolves two levels up
  per folder-structure.md (`scripts/*.py` -> `q-system/`); the prd-os data lives at
  repo root `.prd-os/`, so resolve repo root separately (parent of `q-system/`).
- **Wire (one of):** add a `kipi_accept_rate` MCP tool in
  `plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py`, OR call the script from `/q-wrap`
  so the rate surfaces at end-of-day next to effort. Minimum viable: the script alone,
  run by hand. Decide wiring after the script reads real numbers.
- **Threshold:** start with deferred-major-rate alert at a third, marked tunable in a
  header comment. Not a magic number; the first week of real output calibrates it.

### Acceptance criteria (reproducer-first)
- [ ] `python3 q-system/.q-system/scripts/accept-rate.py` runs against the live
      `.prd-os/` and exits 0
- [ ] For `prd-build-craft-2026-06-15` it reports accept-rate 2/3 and deferred-major
      rate 1/3 (hand-verified above — this is the test)
- [ ] Rolled-up line across all 4 PRDs in `.prd-os/findings/` prints without crashing
      on a PRD that has zero findings
- [ ] A PRD with a fabricated extra deferred-major finding trips the alert (negative
      self-test: prove the flag can fire, per fable-discipline)
- [ ] Wiring decision made and the chosen surface shows the number

### Patterns to follow (this repo's own)
- `q-system/.q-system/sycophancy-harness.py` — the deterministic-verifier-that-flags
  shape. accept-rate.py is the same shape: read trail, compute ratio, raise an alert.
- `skill-hook-pairing.md` — the rate is deterministic, so a threshold check belongs in
  a hook/harness, not a prompt.
- folder-structure.md QROOT rules for script depth.

## Track 2 — one cloud routine, laptop-off

### What / why
Fleet loops currently run session-scoped or on local cron, so they stop when the
laptop sleeps. Cloud routines (the `/schedule` skill) run laptop-off. The article's
own discipline applies: build the smallest one that works, prove it, then expand.

### Approach (three options, pick marked)
- **(A) Move /q-morning to a cloud routine** — highest value, highest risk. The morning
  pipeline leans on local files + interactively-authenticated MCP (Notion, Gmail,
  Apify). Headless/cron runs can lose interactive-auth MCP servers. Don't start here.
- **(B) One cloud-safe, no-interactive-auth loop first** ← PICK. Candidate: the fleet
  dirty/ahead audit (the SessionStart git fleet status) or a nightly
  `prd_runner.py gates run` re-proof. Both are self-contained, need no MCP login, and
  produce a short artifact worth waking up to.
- **(C) Park it** — keep local cron. Legitimate if laptop-off runs aren't a real need.

Pick: **B.** Smallest cloud-safe loop, dodges the headless-MCP caveat, proves the
routine path end-to-end before trusting it with the morning pipeline.

### Files to touch
- Mostly a `/schedule` invocation, not code. If a wrapper is needed: a small script in
  `q-system/.q-system/scripts/` that runs the audit and writes a dated artifact to
  `q-system/output/`.
- Confirm the routine has no dependency on an interactively-authenticated MCP server
  before scheduling (the documented headless gap).

### Acceptance criteria
- [ ] One routine scheduled via `/schedule`, cloud, laptop closed
- [ ] It runs overnight and leaves a readable artifact (fleet audit or gates re-proof)
      the founder sees next morning
- [ ] The run touches no interactive-auth MCP (verified, not assumed)
- [ ] Decision logged: expand to /q-morning or stay on the small loop

## Order
Track 1 first (it reads existing data, ships in one script + one reproducer). Track 2
second (adoption, depends on picking the cloud-safe loop). Both independent; either can
be parked without blocking the other.
