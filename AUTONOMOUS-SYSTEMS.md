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
| `com.kipi.launchd-health` | 09:30, 21:30 | **watchdog** — alert on any silent job death (families in 2.3) |
| `com.kipi.lessons-daily` | Mon 06:00 (weekly, despite the name) | **auto-learn** — distill → publish → propagate → Slack |
| `com.kipi.spillover-linear-check` | 08:10 (installed and loaded on the Mac 2026-09-30) | retry the Linear issue for new spillover rows (kipi-system, consulting, chief); one summary alert to Sana if any stay unlinked (ASK-1552) |

Every job whose plist is INSTALLED in `~/Library/LaunchAgents` under a watched prefix is
auto-monitored by the watchdog (2.3), except the watchdog's own label (`com.kipi.launchd-health`,
`SELF_LABEL` in `launchd-health-check.py`), which it skips. That label is covered instead by
`detect_dark_jobs` in `fleet-health-daily.py` (run by `com.kipi.fleet-health`), which reports it if its
plist is on disk and not loaded. A committed plist that was never installed is invisible to the
watchdog, which discovers installed plists, but it IS reported: `never_installed_findings` in
`fleet-health-daily.py` (detector `launchd-never-installed`) walks every `com.kipi.*.plist` that
`git ls-files` tracks, in any directory, and files one issue per template with no installed copy
(ASK-2277; before that it globbed `q-system/.q-system/scripts/` only and missed `automation/`). The
ones we own are rebuildable from a committed installer, so the layer survives a lost
`~/Library/LaunchAgents`.

Corrected 2026-09-28 (ASK-2193), from the source files rather than the 2026-06-30 list:
- `com.kipi.lessons-daily` is WEEKLY: its plist sets `StartCalendarInterval` Weekday 1, Hour 6
  (`q-system/.q-system/scripts/com.kipi.lessons-daily.plist:39`); the old row said "06:00" daily.
- `com.kipi.fractional-cxo.opp-scan` and `com.kipi.fractional-cxo.bolt-on-discovery` are RETIRED,
  not running: `launchd-intent-verify.py` (comment at :277-285) records that the 2026-08-01 jobs
  audit retired both by renaming their plists. Their rows are removed above. Exact retirement date
  beyond "by the 2026-08-01 audit": UNKNOWN.
- Chief-bot jobs (`com.<bot>.*`) are not covered by `launchd-health`; that coverage moves to the
  daily cloud health check (ASK-2191).

### 1.1 Where each scheduled job runs (2026-09-30, ASK-2176 Phase 8)

The automation cleanup (ASK-2176) moved scheduled work off the Mac where a fresh clone can do it.
Mac rows below are read from `launchctl list` and each plist's `StartCalendarInterval` /
`StartInterval` on 2026-09-30; Mac times are the machine's local time (PT). Cloud rows come from
the routine prompts in the chief repo's `cloud/` directory and the ASK-2176 record; the routine
list itself was not re-read from the routines API for this change.

**Cloud routines (claude.ai)**

| Routine | When (PT) | Prompt | Replaced |
|---------|-----------|--------|----------|
| fleet health check | daily 09:25 | chief `cloud/health-check.md` | adds cloud coverage of the chief-bot jobs (ASK-2191) |
| client status | weekdays 07:25 | chief `cloud/client-status.md`; publishes to chief `kipi/status` | new (ASK-2192) |
| Linear worker | Mon-Fri 09:40, 12:40, 15:40 | chief `cloud/linear-worker.md` | `com.kipi.dispatch`, retired 2026-09-30 |
| Triage | weekdays 09:05 | chief `cloud/triage.md` | `com.triage.brief` / `.act` / `.respond`, retired 2026-09-30 |
| LGTM | weekdays 08:35 | chief `cloud/lgtm.md`; reads GitHub through MCP (chief #47) | `com.lgtm.brief` / `.act` / `.respond` / `.week`, retired 2026-09-30 |
| meeting loop | daily 20:00 | instance-side prompt | an instance's meeting-loop launchd job, retired 2026-09-30 |

**GitHub Actions**

| Workflow | When | What |
|----------|------|------|
| `.github/workflows/gates.yml` (Nightly gates) | 02:15 PDT (cron `15 9 * * *` UTC, so 01:15 PST) | every gate a fresh clone can run; no model call, no secret |

**Still on the Mac, planned to move**

| Job | When | Cloud prompt | Waiting on |
|-----|------|--------------|------------|
| `com.kipi.lessons-daily` | Mon 06:00 (weekly) | chief `cloud/lessons-weekly.md` (distill + publish half only) | `notes-publish` reaching the fleet (ASK-2190) |

**Staying on the Mac** (they read the Mac)

| Job | When | Why it stays |
|-----|------|--------------|
| `com.gates.brief` | daily 02:15 | the Mac-only suites `gates.yml` cannot run: `kipi check` remote coverage, validate-separation phases 2-4, the untracked spillover census |
| `com.gates.respond` | every 10 min | answers the gates channel on the Mac |
| `com.kipi.launchd-health` | 09:30, 21:30 | reads the Mac's launchd state (2.3) |

**Other jobs loaded on the Mac, not part of the move**

| Job | When |
|-----|------|
| `com.kipi.audit-rotate` | 23:55 |
| `com.kipi.openloops-heartbeat` | 08:40, 20:40 |
| `com.kipi.fleet-health` | 08:15 |
| `com.kipi.linear-triage-health` | 09:00 |
| `com.kipi.fleet-full-suite-scan` | 08:20 (alerts on a state change only; RULE-2026-10-01-A) |
| `com.kipi.fleet-model-gate-scan` | 08:25 (model call sites not behind the model gate; alerts on a state change only; ASK-2395) |
| `com.kipi.linear-dor` | 03:00 |
| `com.kipi.disk-janitor` | 04:30 |
| `com.kipi.voice-refresh` | day 1 of the month, 09:00 |
| `com.kipi.browser-session-health`, `com.kipi.browser-session-deadman` | every 30 min |

`com.kipi.spillover-linear-check` was installed and loaded on 2026-09-30 and is listed in section 1.

`com.kipi.ticket-watch` is loaded on the Mac (`launchctl list`, 2026-10-01).

Not loaded on 2026-09-30, although a committed plist names it:
`com.cole.fleet-env-health` (plist present, not loaded).
Retired plists (`*.retired-<date>`) are not listed.

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
`launchd-health-check.py` auto-discovers every `~/Library/LaunchAgents/<prefix>*.plist` for the
prefixes in `WATCHED_PREFIXES` (`launchd-health-check.py:59-65`): `com.kipi.`, `com.cole.`,
`com.claudedaddy.`, `com.ask.`, `com.assaf.`, plus any line in
`~/.config/kipi/launchd-watch-prefixes.txt`. That file is how an instance adds its own job family:
a family listed there IS reported, one that is not listed and matches no base prefix is not. What
a given machine's file holds is machine state, not repo state; read the file, not this doc. Labels in `~/.config/kipi/launchd-paused.txt`
or `cole-pause.state` are printed, not alerted. It reads each job's `LastExitStatus` and
alerts (deduped, 6h TTL) on any non-zero. It always exits 0 so it never becomes the failing job it
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

### 3.3 The pipeline (`lessons-daily.sh`, launchd Mon 06:00, weekly)
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

## 5b. BREAK GLASS — main is frozen and nothing can merge

**Symptom:** every PR sits `BLOCKED`. `kipi/reviewer-approved` is missing or red on
every head, and re-running the reviewer does not post a status.

**Why it can happen:** `main` requires `validate` **and** `kipi/reviewer-approved`,
and since ASK-798 `enforce_admins: true` — so admins are subject to those checks
too. `kipi/reviewer-approved` is posted by a LOCAL script (`pr-review-agent.sh`),
not a GitHub Action. If that script's path is down, the required context is never
posted and **nobody can merge, including the person landing the fix for it.**

**The hatch (one command, reversible, logged, Slack-announced):**

```bash
# 1. confirm the freeze is what you think it is
bash q-system/.q-system/scripts/break-glass-main-protection.sh status

# 2. open the hatch (a reason is REQUIRED and goes in the ledger)
bash q-system/.q-system/scripts/break-glass-main-protection.sh off \
  "reviewer posting path down, landing the fix for it"

# 3. merge only what unblocks the situation

# 4. CLOSE IT AGAIN. Immediately.
bash q-system/.q-system/scripts/break-glass-main-protection.sh on
```

Who can run it: anyone with admin on the repo (today: `assafkip`). It needs `gh`
authenticated, nothing else.

Ledger: `~/.claude/audit/break-glass-main-protection.jsonl` (one row per action,
with the reason). Slack fires on `off` and on `on`.

**If `off` exits 2, it did nothing on purpose.** The audit row is written BEFORE
protection is touched, so an unwritable ledger REFUSES the override rather than
being discovered once the hatch is already open. Fix the ledger path (or point
`BREAK_GLASS_LEDGER` at a writable file) and re-run. **Exit 3 means the state DID
change but an audit signal failed** — read the warnings and announce it by hand,
because nobody has been told. Closing is never refused for a bookkeeping failure:
refusing to close would strand protection in the OFF state, which is worse than an
incomplete log.

**Why a switch instead of the old escape.** Before ASK-798 the escape was
`gh pr merge --admin`: silent, always available, indistinguishable from a normal
merge. The capability has not been removed, it has been made *visible* — the same
override now leaves a ledger row and a Slack message. If you find the hatch open
and nobody remembers opening it, that is exactly the signal the old design could
never produce.

**Leaving it open is the failure mode.** An always-open hatch is identical to no
gate at all, which is the thing ASK-798 existed to fix.

---

## 6. Operate / verify

```bash
# is the merge gate armed, and is the break-glass hatch closed?
bash q-system/.q-system/scripts/break-glass-main-protection.sh status

# see every kipi job's health
python3 q-system/.q-system/scripts/launchd-health-check.py --dry

# run the auto-learn loop once (heavy first run: backfills ~43 RCAs via claude)
kipi lessons-run
# preview without writing
python3 q-system/.q-system/scripts/lessons-distill.py --dry

# (re)install the jobs from committed installers. The lessons job is weekly (Mon 06:00),
# and its installer refuses (exit 2) unless run from the skeleton checkout itself.
bash q-system/.q-system/scripts/install-lessons-daily.sh
bash <instance>/automation/install-launchd.sh
# every committed kipi plist (or one: pass its label instead of --all).
# --all refuses (exit 2) from a git worktree, so it cannot repoint live jobs at one.
# Outside the skeleton it skips templates marked `kipi-scope: skeleton-only`.
bash q-system/.q-system/scripts/install-plist.sh --all

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
