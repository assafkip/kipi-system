# Session of Record — Autonomous Systems (2026-06-30)

Canonical record of the work and the discussion that produced the fleet's self-healing and
self-learning layers. The technical reference is `AUTONOMOUS-SYSTEMS.md` (root); the decisions are
`RULE-2026-06-30-A..E` in `decisions.md`; this file captures the *thread* — how the understanding
evolved and why the design landed where it did. Skeleton-only (canonical/ is not fanned).

---

## The discussion arc (how we got here)

**1. "Do we have self-healing?"** → Inventory found ~13 mechanisms, mostly git-hygiene hooks. Honest
read: narrow, not comprehensive.

**2. "Is it relevant — build on it or leave it?"** → The wired healers earn their keep; the one
unwired PRD (self-healing pipeline) was speculative. Recommendation: don't build on spec.

**3. "Are you guessing, or did you read the code?"** → Caught relaying a subagent's read as my own.
Corrected by reading `kipi-update.sh`, `git-health-check.sh`, and the PRD firsthand. Discipline
reset: verify, don't infer. This set the tone for the rest of the session (reproducer-first, "ran X
got Y", not "I think it works").

**4. "I want things happening autonomously, not a routine I start."** → Found the real autonomous
layer (launchd + cloud routines), and that **two income-scanner jobs had exited 127 silently for 6
days** (2026-06-24..30) after a kipi update deleted their scripts. The abstract "self-healing"
question had a concrete, money-losing answer sitting in it.

**5. "Continue autonomously as senior staff."** → Recovered the scanners, relocated them out of the
clobber zone, built the watchdog, hardened the updater, wrote docs — chaining, not stopping.

**6. "So all repos are self-healing and cross-learning now?"** → No — an overclaim. Self-healing was
narrow and not yet fanned; "cross-learning" didn't really exist. Pushed back rather than nod.

**7. "We added something for cross-brain learning — find it."** → The lessons corpus. It was wired
and reaching instances, BUT: one-way broadcast (skeleton-authored, instances read-only, push-guard
blocks upward), and the corpus held **exactly one lesson**. The rail was real; the engine was missing.

**8. "Read claudesidian; I modeled it on that."** → claudesidian is a *single vault* whose brain
compounds via **capture → synthesize → write-back into the same store** (daily-review, weekly-
synthesis distill patterns back into the vault). Key realization: the founder modeled a *cross-
instance* system on a *single-instance* design. claudesidian's magic isn't cross-brain sharing (it
has none) — it's the write-back loop. The corpus copied the sharing rail but not the loop.

**9. First build attempt (harvest + human queue).** Built an engine that clustered patterns across
2+ unrelated instances and queued candidates for the founder to promote. Founder rejected the shape:

**10. "This isn't how we build. Do everything autonomously. Every learning, not just repeats.
Scrub client data instead of requiring two instances. Daily heartbeat. Slack me the changes."** →
The model inversion. Rebuilt: fully autonomous distill → scrub → publish → propagate → Slack.

**11. "How does it hand me the draft, exactly?"** → Exposed that "hands me" was a passive file in a
folder — a silent drop by the founder's own rule. Reframed delivery to Slack + surface.

**12. "Save it to canonical / document how we built it."** → AUTONOMOUS-SYSTEMS.md + decisions log +
ARCHITECTURE link.

**13. "The docs don't reach instances — fix it, but deterministic, not prose."** → Built
`instance-automation-guard` (a hook that blocks the mistake at write-time and fans to every
instance), because a `.claude/rules` prose file is a suggestion and the repo bans prompt-only
enforcement.

---

## What we built (artifacts + commits)

| Work | Where | Commit |
|------|-------|--------|
| Recover + relocate income scanners to durable `automation/` | fractional-cxo | `2b881fb` |
| Committed installer (rebuild jobs from git) | fractional-cxo | `95f5f9a` |
| launchd watchdog (silent-death → Slack) + test | kipi-system | `50638bd` |
| Updater guard: warn+preserve tracked instance-only files + tests | kipi-system | `4f3a62b` |
| Autonomous auto-learn: distill → fail-closed scrub → publish → propagate → Slack + tests | kipi-system | `a4bb77d` |
| Canonical docs + decision log + ARCHITECTURE link | kipi-system | `2f837d3` |
| Deterministic automation-placement guard (fleet-wide hook) + test | kipi-system | `d862636` |

All kipi-system commits pushed to `origin/main`. fractional-cxo is local-only (no remote).

Test coverage (all green, reproducer-first): updater guard (scan + RED→GREEN integration), watchdog
(11 logic + live fake-fail), scrub gate (11), distiller (7), automation guard (6).

---

## Key decisions (full records in decisions.md)

- **RULE-A** instance automation lives at repo root, never in `q-system/` (the rsync --delete zone).
- **RULE-B** kipi update = warn + preserve tracked instance-only files (never silent-delete).
- **RULE-C** every kipi launchd job is watched + rebuildable.
- **RULE-D** cross-instance learning shares EVERY learning; de-identify by scrub, not recurrence.
- **RULE-E** a lesson publishes only through a fail-closed client-data gate.

---

## Honest gaps surfaced (not hidden)

- The autonomous layer's plists live only in `~/Library/LaunchAgents`; audit-rotate + openloops still
  lack committed installers.
- Root docs + canonical/ are skeleton-only (not fanned). The automation *guard* fans; the *docs* don't.
- New skeleton changes (guard, auto-learn) reach the 18 instances only on the next `kipi update`.
- Spillover `sp-10cf4f76` (the updater root cause) left RED by founder call — fix shipped, no formal
  PRD receipt.
- First auto-learn run backfills ~43 RCAs (real `claude -p` spend).

---

## Scars reinforced this session

- A silent 127 is worse than a loud crash — 6 days of lost income scanning with no signal. Detection
  is not optional (RULE-C).
- "I think it works" is not done; verify firsthand, reproducer-first (turn 3).
- A file in a folder the founder must remember to open is a silent drop (turn 11).
- Prose is a suggestion; enforcement is a hook (turn 13).
- Model the loop, not just the rail (turn 8): a sharing pipe with no engine stays empty.
