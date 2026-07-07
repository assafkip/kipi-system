# GTM Plan: safe-autonomous-learning (OSS)

**Repo:** https://github.com/assafkip/safe-autonomous-learning (public, MIT, live 2026-06-30)
**One-line title:** Turn a public OSS toolkit into credibility + warm leads for "safe autonomous AI on confidential data."

---

## What / why (read first)

The repo is not the product. It is a **credibility wedge**. The three tools prove you solved a problem
every serious buyer of AI automation in a regulated/confidential field has: *how do you let AI improve
across projects without leaking one client's data into another?* GTM here = get the repo SEEN by those
people, and convert the attention into KTLYST positioning + conversations. Effort is tracked (posts
shipped, threads engaged), not outcomes (stars).

**Before any external post:** align the wedge language with strategy/canonical talk-tracks (anti-drift).
Check `~/.ktlyst/bridge/canonical-digest.json` isn't contradicted.

---

## Positioning

- **Wedge (the thing that's yours):** the fail-closed **client-data-gate** — publishing across projects
  is deterministic code, not a model being asked to be careful.
- **Category story:** governance-as-code for autonomous AI. Ties to the AI Index governance thesis.
- **ICP (who feels this pain):** teams running LLM automation on data they can't leak — threat-intel /
  security, legal, consulting, healthcare, anyone multi-tenant under NDA.
- **The line:** "Let your AI systems learn from every project without leaking any client's data."
- **Proof, not claim:** you run this on a real fleet; it was extracted, not theorized.

---

## Asset checklist (produce once, reuse everywhere)

- [ ] **Repo polish** (Quick Win, 30 min): add GitHub topics (`llm`, `ai-agents`, `security`,
      `governance`, `claude`), a one-line description (done), and a short demo (asciinema or a 60-90s
      screen gif: kill a job → watchdog ping; run distill → clean lesson publishes; a tainted lesson →
      HELD). A visual sells the gate better than prose.
- [ ] **Announcement post** (Deep Focus, 45 min): the scar story. Six days silent → the fleet heals +
      learns → the one rule I refused to let the model break. LinkedIn + X versions. Founder voice
      (personal scar, no stats, no rule-of-three, link the repo, no pitch).
- [ ] **Show HN post** (Quick Win, 20 min): "Show HN: Fail-closed tools so AI agents can share learnings
      without leaking client data." Technical, humble, link + one-paragraph why.
- [ ] **Reddit variants** (Deep Focus, 30 min): reframe per subreddit (below). Not copy-paste.
- [ ] **Technical deep-dive** (Deep Focus, 60-90 min, optional/later): "Why the publish decision has to
      be deterministic" — dev.to or Medium. The `wait(2)` decoder + the fail-closed argument. This is
      the piece that earns respect from engineers.

---

## Channel plan (where the ICP actually is)

| Channel | Angle | Energy / Time |
|---------|-------|---------------|
| **LinkedIn** (your audience) | The scar + the wedge; credibility with buyers/partners | People, 20 min |
| **X/Twitter** | Same, thread form; agent-builder + AI-safety crowd | People, 15 min |
| **Hacker News (Show HN)** | Technical, no hype; "here's the gate, here's why fail-closed" | Admin, 20 min |
| **r/LocalLLaMA, r/MachineLearning** | Agent builders; the auto-learn loop + gate | Deep Focus, per-sub |
| **r/netsec / r/cybersecurity** | The confidentiality angle; safe AI on sensitive data | Deep Focus, per-sub |
| **Claude Code / agent-dev communities** | It defaults to `claude -p`; drop-in for their agents | People, 15 min |

Post cadence: one channel per day, not a blast. Respond to every comment same-day (that's where the
warm leads surface). Async-first. No "launch day" pressure.

---

## Launch sequence (do in order, at your pace — no deadlines)

1. **Polish** the repo (topics + demo gif). One Quick Win session.
2. **LinkedIn + X** announcement (your home turf first — friendly audience, work out the framing).
3. **Show HN** (once the post framing is proven). Best Tue-Thu morning ET.
4. **Reddit** (1-2 subs), reframed per community.
5. **Deep-dive article** if momentum warrants; link back to repo.
6. **Engage the tail:** answer issues/comments fast, merge a PR if one comes, note who engages.

---

## Conversion mechanic (OSS attention → KTLYST)

The repo does the reaching; the conversation does the converting. When someone from a
confidential-data team comments/DMs/opens an issue:

- **Do not pitch in the OSS post.** Reactions are about the idea (engagement-playbook rule).
- The talk track when asked "what do you do": *"I run a fleet of AI systems for my own work; a few are
  client-confidential, so I had to build the gate. KTLYST builds this kind of safe autonomous AI for
  teams that can't leak. Happy to compare notes."* Share expertise, not a favor (RSD-safe).
- Warm lead = anyone who engages from security/legal/consulting/health. Log them (debrief flow →
  follow-up Action). The repo is the warm-intro generator.

---

## Metrics (effort first, signals second)

- **Effort (what you control):** posts shipped, comments answered, PRs reviewed. Target: 4-6 posts
  across channels, all comments answered same-day.
- **Signals (watch, don't chase):** stars, HN points, save/share ratio, and — the real one — inbound
  from ICP-shaped accounts.
- **The only outcome that matters:** 1-2 real conversations with confidential-data teams. That's the
  conversion, not the star count.

---

## Risks / anti-patterns

- **Over-claiming.** The gate is deterministic on KNOWN signals + an LLM net; it is not magic. Say so.
  A novel client name the LLM misses is the residual risk — name it honestly (credibility > hype).
- **Pitching in the OSS post.** Kills it. The repo is the pitch; the post is the story.
- **Standalone-repo vs contribute-upstream tension.** Your OSS mission favors contributing to existing
  projects. This is a standalone (justified — it's a novel primitive). If a natural host emerges (a
  Claude Code plugin registry, an agent framework), offering the gate there is the upstream move.
- **Letting it rot.** An OSS repo with an ignored issue reads worse than no repo. Only scale posting to
  the engagement you can service.

---

## Resume note

On return: repo is live + tested. Next unchecked action = **repo polish (topics + demo gif)**, then the
LinkedIn/X announcement. The announcement draft was offered but not yet written — ask for it when ready
("draft the announcement post"). Everything above is the durable checkpoint.
