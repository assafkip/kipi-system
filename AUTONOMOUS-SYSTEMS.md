# Autonomous Systems

How the kipi fleet keeps itself running and keeps itself learning — with no human in the loop on the
happy path, and a hard human-safe stop on the dangerous path. Built 2026-06-30. This is the canonical
reference; the code is the source of truth, this explains the why.

There are two systems here. **Self-healing** keeps the machinery alive. **Auto-learning** makes the
fleet smarter every night. They share one design spine: *prevention + detection + durability, with the
one irreversible action gated by hard code, not model judgment.*

---

## 1. The autonomous layer (what runs on its own)

The fleet's "things happen without me" layer is **launchd jobs** (`~/Library/LaunchAgents/com.kipi.*.plist`)
plus cloud routines (Claude Code Remote triggers). There is no user crontab. As of 2026-06-30 the
launchd jobs are:

| Job | When | What |
|-----|------|------|
| `com.kipi.audit-rotate` | 23:55 | rotate audit logs |
| `com.kipi.openloops-heartbeat` | 08:40, 20:40 | wake per-instance agents to advance open loops |
| `com.kipi.fractional-cxo.opp-scan` | 08:00 | daily income/opportunity scan |
| `com.kipi.fractional-cxo.bolt-on-discovery` | 07:00 | daily consulting-lead discovery |
| `com.kipi.launchd-health` | 09:30, 21:30 | **watchdog** — Slack-ping on any silent job death |
| `com.kipi.lessons-daily` | 06:00 | **auto-learn** — distill → publish → propagate → Slack |

Every job is auto-monitored by the watchdog and (for the ones we own) rebuildable from a committed
installer, so the layer survives a lost `~/Library/LaunchAgents`.

---

## 2. Self-healing

### 2.1 The scar that forced it
2026-06-24: a `kipi update` ran, and its `rsync --delete` deleted the fractional-cxo income-scanner
scripts because they lived *inside* the synced `q-system/` tree at a path the skeleton doesn't manage.
The two launchd jobs then exited **127 (command-not-found) every morning for 6 days** — and nothing
told anyone. The income scanners silently stopped hunting income. That single incident is the origin
of everything in this section.

### 2.2 Prevention — the updater can't silently eat instance files
`kipi-update.sh` snapshots + restores before its destructive `rsync --delete`. It originally protected
only *untracked* files; a *committed* instance script had no protection. The fix
(`kipi-update-preserve-scan.py`) flags **tracked instance-only** files the delete would remove — scoped
by a precise discriminator: **only files the skeleton git NEVER tracked** (genuinely instance-added, so
skeleton-intended deletions still propagate). Those get added to the snapshot/restore set and the
founder is warned. Policy: **warn + preserve** (founder-chosen). Fail-open: a missing helper is a no-op.
Tests: `test-kipi-update-preserve-scan.sh`, `test-kipi-update-preserve-integration.sh` (RED→GREEN).

### 2.3 Detection — silent job death becomes a phone ping
`launchd-health-check.py` auto-discovers every `com.kipi.*` job, reads its `LastExitStatus`, and
Slack-pings (deduped, 6h TTL) on any non-zero. It always exits 0 so it never becomes the failing job it
reports. `LastExitStatus` arrives as a raw `wait(2)` status (exit 3 → 768); `normalize_exit` decodes it
so the ping reads "exit 3". Runs 09:30 + 21:30. This is the deterministic backstop the philosophy
demands — a prompt can't watch launchd; a job can. Test: `test_launchd_health_check.py` (11 cases).

### 2.4 Durability — instance automation lives OUTSIDE the synced tree
The root cause was scripts *inside* `q-system/`. The durable fix: instance-specific automation lives at
the repo **root** (e.g. `fractional-cxo/automation/`), which `kipi update` never touches (it only fans
`q-system/`, `.claude/`, `plugins/`). Repo-root stays git-tracked (recoverable) AND clobber-proof.
Each such bundle ships a committed installer (`install-launchd.sh`) so `clone → run → jobs back`.

---

## 3. Autonomous cross-instance learning

### 3.1 The problem
kipi learns inside each instance (RCAs, memories, debriefs) and the lessons never crossed the ~18
instances. The corpus (`q-system/lessons/`) had the sharing *rail* but no *engine*, so it held one
lesson. claudesidian (the inspiration) fills its single-vault brain via **capture → synthesize →
write-back into the same store**; that loop is what compounds. kipi had the rail, not the loop.

### 3.2 The model (founder redesign, 2026-06-30 — inverts the prior PRD)
- **Every learning is shareable to every instance.** Dropped the earlier "only share a pattern that
  recurred in 2+ unrelated instances" rule — it missed most of the value.
- **De-identify by SCRUBBING client data, not by requiring recurrence.** A real HOW-only lesson has no
  client data; if any slips in, strip it.
- **Fully autonomous** — no candidate queue, no human promotion on the happy path.
- **Daily heartbeat + Slack on change.**

### 3.3 The pipeline (`lessons-daily.sh`, launchd 06:00)
```
read every instance's new RCAs (source-hash ledger => each processed once)
  → DISTILL each into a HOW-only lesson via `claude -p` (drop all WHAT/specifics)
  → GATE (see 3.4)
  → PUBLISH clean lessons to q-system/lessons/<id>.md
  → kipi update fans them read-only to all instances
  → Slack a one-line summary (silent when nothing new)
```

### 3.4 The gate — the one place autonomy is dangerous, so it's hard code
A cross-client data leak is irreversible for a threat-intel shop. So publishing is **fail-closed** in
`lessons_scrub.py` — deterministic, not model trust:

- `is_clean(text)` passes ONLY when there are **zero** client-data signals: static tokens
  (`KTLYST|CISO|Assaf|re-breach`), absolute paths, emails, URLs, and the registry's instance
  **codenames** (distinctive names only — generic role words like "accountant" are ignored to avoid
  over-holding).
- A lesson publishes only if the scrubbed text is **deterministically clean AND** a second `claude -p`
  semantic pass confirms no residual real entity.
- Anything the gate can't clear is **HELD** — written to `lesson-candidates/`, named in the Slack,
  **never published**. Over-holding is a safe false positive; leaking is not. This module holds.

Tests: `test-lessons-scrub.sh` (11), `test-lessons-distill.sh` (7). Real-path verified: a live RCA
distilled to *"Serialize shared exclusive resources and make silent no-ops observable"* and cleared the
gate.

---

## 4. Design decisions (and why)

| Decision | Why | Origin |
|----------|-----|--------|
| Instance automation lives at repo root, not in `q-system/` | The synced tree is a `rsync --delete` target; repo-root is not. Durable + git-tracked. | scar 2026-06-24 |
| Updater policy = **warn + preserve** (not abort/warn-only) | No silent data loss; the update still proceeds. | founder-chosen |
| Watchdog + committed installers for every owned job | Silent death and lost LaunchAgents were the two failure modes; cover both. | scar 2026-06-24 |
| Auto-learn shares **every** learning (not 2+ recurrence) | Recurrence-gating missed most of the value. | founder-directed |
| De-identify by **scrub**, not recurrence | A HOW-only lesson has no client data; scrub is the backstop. | founder-directed |
| Publish gate is **fail-closed hard code** | A cross-client leak is irreversible; can't rest on model judgment. | Claude-recommended → approved |
| Held lessons surface, never leak | The safe side of the trade for a threat-intel shop. | design invariant |

---

## 5. How it was built

Reproducer-first, throughout. Every deterministic guarantee has a test that first shows the failure,
then shows it fixed:
- The updater guard: a fixture where a raw `rsync --delete` deletes a tracked instance-only script
  (RED), then the snapshot→scan→restore sequence preserves it (GREEN).
- The watchdog: a deliberately-failing launchd job proves detection before the real job is trusted.
- The scrub gate: every client-data class asserted HELD; a clean HOW-only lesson asserted published.

The order was: fix the live fire (recover the income scanners) → prevent recurrence (updater guard) →
detect the class (watchdog) → make it durable (repo-root + installers) → then build the learning engine
on top of a now-trustworthy autonomous layer. Nothing was declared done on "I think it works"; each
step is "ran X, got Y".

---

## 6. Operate / verify

```bash
# see every kipi job's health
python3 q-system/.q-system/scripts/launchd-health-check.py --dry

# run the auto-learn loop once (heavy first run: backfills ~43 RCAs via claude)
kipi lessons-run
# preview without writing
python3 q-system/.q-system/scripts/lessons-distill.py --dry

# (re)install the daily jobs from committed installers
bash q-system/.q-system/scripts/install-lessons-daily.sh
bash <instance>/automation/install-launchd.sh

# run the test suite for these systems
bash q-system/.q-system/scripts/test/test-lessons-scrub.sh
bash q-system/.q-system/scripts/test/test-lessons-distill.sh
bash test-kipi-update-preserve-scan.sh
bash test-kipi-update-preserve-integration.sh
python3 q-system/.q-system/scripts/test_launchd_health_check.py
```

Key files: `q-system/.q-system/scripts/{launchd-health-check,lessons_scrub,lessons-distill}.py`,
`q-system/.q-system/scripts/lessons-daily.sh`, `kipi-update{,‑preserve-scan}.{sh,py}`,
`lesson-candidates/` (held queue + ledger, skeleton-only, never fanned).
