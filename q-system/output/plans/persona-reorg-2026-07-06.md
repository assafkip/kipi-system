# Plan: reorganize the fleet under top-level personas

**What/why:** Today ~48 projects sit flat in `~/projects/` (+ a `ktlyst-hub/` cluster). Founder wants top-level PERSONAS (a "partner" per type of work) with projects cascading under each. `Cole-GTM` is the anchor: Cole is the GTM partner; his projects nest under `Cole-GTM/`. Goal: one home per line of work, not a flat pile.

**Status:** PROPOSAL. Nothing moves until the persona taxonomy is agreed. This doc is the checkpoint.

---

## Confirmed anchor (founder-specified)

`Cole-GTM/` owns: notebooklm-daily-podcast, reddit-build-radar, vc-signals, event_coordinator, website, personal-brand.

Note: `com.cole.daily-podcast.plist` already exists in launchd — "Cole" is already a namespace for the podcast. The model is half-built.

---

## Proposed persona set (5 work personas + 1 personal)

Names after Cole are PLACEHOLDERS — rename freely. Role is the anchor.

### 1. `Cole-GTM/` — demand gen, market presence
- notebooklm-daily-podcast, reddit-build-radar, vc-signals, event_coordinator, website, personal-brand *(founder-specified)*
- **Nominate to add:** founder-signal-engine, signal-desk, competitive-analysis *(all market-signal → content/outreach)*
- **Core:** the `gtm/` pipeline currently inside `random-stuff-ideas` (ICP, positioning, campaigns, deals) — this IS Cole's brain and should become `Cole-GTM/`'s core, not a nested project.

### 2. `<Name>-Intel/` — threat intel, investigations, OSINT
- The KTLYST product: ktlyst-hub/product, product-baseline
- Client/deployment: 4_points_consulting, Alice, kipi-investigations, ktlyst-extract
- Tooling: facebook-ads-library-search, huntkit, ktlyst-review-panel
- *Decision below: product (the thing you sell) vs deployments (client work) may want a sub-split.*

### 3. `<Name>-Advisory/` — fractional consulting, client engagements
- ASK_AI_consultant, Pure_spectrum_Q, fractional-cxo

### 4. `<Name>-Products/` — the shipped micro-SaaS portfolio
- cheapcheck, briefonce, authorvoice, feedbackpin, runreceipts, shipgate
- Interview-coach family (5 copies → consolidation target): interview-coach, interview-coach-public, freshlist, warmreach, slimcli
- tokentrim

### 5. `<Name>-Platform/` — the OS + dev tooling everything runs on
- kipi-system (the factory — see decision 3), claude-focus, fable-discipline, kipi-rca, founder-voice-kit

### Personal (NOT a work persona — a plain bucket)
- travel-agent, negotiator, school-negotiator, school-idf, AUDHD_KIDS

### Dissolves
- `ktlyst-hub/` disappears. Its instances redistribute: product/product-baseline → Intel, website/personal-brand/event_coordinator → Cole-GTM, strategy → Cole-GTM or Advisory, accountant/lawyer → Ops (decision 4), deliverables → Intel or Platform.

---

## Open decisions (need founder call before any move)

1. **Persona count.** 5 work + personal as above, or fewer/bigger? (e.g. fold Advisory into Intel; fold Products into Platform.)
2. **Products persona, yes/no?** Or does Cole (who markets them) also own the product repos, and Platform owns only dev-tooling?
3. **kipi-system placement.** It's the factory that builds every instance. Keep it TOP-LEVEL/meta (my rec), or nest under Platform? Nesting it under a persona is odd since all personas depend on it.
4. **accountant + lawyer.** Own `Ops` persona, or nest under Advisory? They serve the whole business, not one line.
5. **Intel sub-split.** Product-you-sell vs client-deployments under one persona, or two?
6. **Physical layout.** Real nested dirs (`~/projects/Cole-GTM/website/`) vs a symlink/registry view. My rec: real dirs, migrated by script (see below) — matches the "cascade" you asked for and the deterministic-script preference.

---

## The migration mechanics (the part that earns the plan)

Naive `mv` breaks automation silently. Confirmed breakage surface:
- **instance-registry.json** — absolute path per kipi instance. Moving breaks `kipi update / list / check`.
- **17 launchd plists** reference `/projects/` paths — incl. `com.cole.daily-podcast`, `com.kipi.fractional-cxo.*` (the scanners that broke 6 days before), heartbeats, lessons-daily.
- **~/.ktlyst/bridge/** cross-instance state (readers/writers by path).
- **ktlyst-cluster.md** rule hardcodes `~/projects/ktlyst-hub/<instance>` for `--add-dir`.
- **Absolute `~/projects/...` refs** inside scripts (QROOT is relative, but cross-project refs may be absolute).

### Approach: one deterministic migration script, phased, reversible
Build `scripts/persona-reorg.py` that takes a persona-map JSON `{persona: [projects]}` and, per project:
1. `git mv` / move the dir into the persona folder.
2. Rewrite `instance-registry.json` paths.
3. Rewrite + `launchctl` reload every plist that referenced the old path.
4. Rewrite ktlyst bridge refs + `ktlyst-cluster.md` `--add-dir` paths.
5. Rewrite absolute `~/projects/<old>` refs found by a two-pass grep.
- `--dry` prints every planned move + every path rewrite, changes nothing.
- Runs **per-persona**, not big-bang. Rollback = reverse the persona-map.

### Move-risk tiers (do low-risk first to prove the script)
- **Tier 0 (no automation deps):** the Next.js SaaS + python tools + personal projects. Just repos. Safe first movers.
- **Tier 1 (registry only):** kipi instances (ASK, Pure_spectrum, 4_points, strategy...). Registry rewrite + `kipi check`.
- **Tier 2 (launchd + registry):** podcast, fractional-cxo, signal jobs, heartbeats. Highest risk — move last, verify each job fires after reload.

### Order
Cole-GTM first (founder's anchor AND it contains Tier-2 risk items — the podcast + signal jobs). Doing it first is the proving run; if the script handles Cole cleanly, the rest follows.

---

## Acceptance criteria (per persona batch)

- [ ] `--dry` output reviewed and approved before the real run
- [ ] After move: `kipi check` and `kipi list` green (paths resolve)
- [ ] Every rewritten launchd job reloaded and confirmed firing (`launchctl list` + a triggered run)
- [ ] Moved project's own smoke/test passes from its new path
- [ ] `~/.ktlyst/bridge/` reads/writes still resolve
- [ ] Rollback dry-run proven to reverse the batch
- [ ] launchd-health watchdog quiet (no silent job death)

## Patterns to follow (this repo's own)
- Deterministic script over instructions (founder rule + `.claude/rules/` throughout).
- Instance automation lives at repo root, not synced subtrees (memory: launchd-autonomous-layer scar).
- Two-pass grep on every rename (token-discipline "Cleanup / Migration Rule").
- Phased + reversible + verified-firing, per self-healing-retry contract.
