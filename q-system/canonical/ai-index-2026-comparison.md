# AI Index 2026 vs the Work I've Built

**Status:** living doc — started 2026-06-26. Refine as each instance is analyzed.
**Purpose:** track how the work (kipi-system core + every instance) responds to,
alleviates, or differs from the concerns in Stanford HAI's *AI Index Report 2026*
(425 pages, hai.stanford.edu/assets/files/ai_index_report_2026.pdf).
**Extraction:** corpus built via `q-system/.q-system/scripts/pdf-extract.py`
(per-chapter markdown + `figures.jsonl`), so we can re-mine any chapter cheaply.

---

## The thesis (one line)

The report describes the **AI capability/governance gap at civilizational scale.**
The kipi-system is a working instance of **closing that gap at n=1 — governance
as code, not policy.** Control can be fast and automatic when it's baked into
hooks and receipts instead of written as rules nobody enforces.

---

## The report's core concerns (its own 15 Top Takeaways, condensed)

1. Capability is accelerating, not plateauing — 88% org adoption, agents leaping.
2. The U.S.–China model-performance gap has effectively closed.
3. Compute + supply chain are dangerously concentrated (TSMC, U.S. data centers).
4. **Jagged frontier** — IMO gold medal but can't read a clock; agents still fail
   ~1 in 3 real tasks.
5. Robots fail most household tasks (12% success) despite lab excellence.
6. **Responsible AI is not keeping pace** — safety benchmarks lag, incidents rose
   233 → 362, and improving one RAI dimension (safety) can degrade another (accuracy).
7. U.S. leads investment ($285.9B) but its ability to attract talent is declining (−89% since 2017).
8. Adoption is historically fast (53% in 3 years); consumers derive large free value.
9. Productivity gains concentrate in the same fields where entry-level jobs are declining.
10. Environmental footprint is expanding (CO2, water, 29.6 GW of data-center power).
11. Science models: smaller models can outperform much larger ones.
12. Clinical AI adoption is up, but the rigorous evidence base is thin.
13. Formal education lags AI; policy is missing.
14. AI sovereignty is rising; open source is redistributing who participates.
15. Experts vs public hold a 50-point trust gap; institutional trust is fragmented.

**The spine across all of it:** what AI *can do* is outrunning our ability to *manage* it.

---

## How the kipi-system core OS responds

### Direct hit 1 — Responsible AI not keeping pace (Takeaway #6)
The report's central worry, solved at operator scale:
- prd-os receipts + closeout gate (refuses to archive with an open finding)
- capability-token (an agent cannot mint its own grant)
- destructive-op-deny hook (hook-level, not prompt-level)
- skill→hook pairing doctrine (deterministic rules get a paired enforcing hook)
- sycophancy harness + anti-drift
- no-orphan-findings / spillover ledger; wiring-check; token-guard

The doctrine itself — *hook-level enforcement beats prompt-level rules* — is the
report's "governance must keep pace" claim, implemented.

### Direct hit 2 — Jagged frontier / agents fail 1-in-3 (Takeaway #4)
- fable-discipline: verify against a copy, single-writer chokepoints, scar comments
- Codex adversarial review; reproducer-first verification loops; self-healing pipeline
- The "receipts not prompts" thesis assumes model unreliability and checks the work.

### Context, not counter-idea — Economy (#9), R&D (#11)
- You run solo on an agent fleet → you *are* the productivity-gain data point.
- Model allocation by task (Haiku/Sonnet/Opus) already lives the "route to the
  cheapest sufficient model / smaller can win" finding.

---

## Per-instance analysis (deep dive — 19 registered instances, 2026-06-26)

Read-only agent pass over every registered instance's own positioning/identity
files. Strength = how directly it answers a report concern.

| Instance | Strength | How it answers the report (one line) |
|---|---|---|
| **KTLYST_strategy** | **Strong** | Governance as a design primitive: 27+ deterministic gates + character-level provenance + honest BLOCKED verdicts. Governs capability *at generation time*. |
| **ktlyst-website** | **Strong** | Public positioning *is* the governance layer: "Deterministic, Not Probabilistic," full audit trail, mandatory human approval before production. |
| **4_points_consulting** | **Strong** | 18 IC structured-analytic techniques (ACH, deception detection, premortem) + A–F confidence + citation enforcement. Assumes AI is unreliable, plans for it. |
| **ktlyst_lawyer** | **Strong** | Compliance/liability infrastructure cited to statute; turns regulatory obligation into contractual + audit procedure. Governance after capability. |
| **ASK_AI_consultant** | **Strong** | Sells the fix: hardens orgs' unreliable AI into governed systems (Pure Spectrum proof, $600K+ avoidance). Closes the gap at the org level. |
| **ktlyst (product)** | **Medium** | Zero-inference extraction + source citations + 5 validation gates + DSSE audit logs. Trades capability for verifiability. |
| **Pure_spectrum_Q** | **Medium** | Provenance after a real hallucination incident (DQ-055); agents as discovery tools, not decision-makers; reversible/auditable controls. |
| **kipi-investigations** | **Medium** | Every node/edge traced to the `tool_use_id` that produced it; analyst-approval gates on every edge; `{{UNVALIDATED}}` marks. |
| **accountant** | **Medium** | Fail-closed egress filter (Rust): the LLM *cannot* see raw financial PII regardless of prompt. Constrain the model, don't trust it. |
| **personal-brand** | **Medium-Strong** | A credible threat-intel expert publicly modeling responsible AI use — bridges the exact expert↔public trust gap (#15) the report measures. |
| **AUDHD_KIDS** | **Medium** | Evidence-tiered (1–5), citation-enforced parent research for neurodivergent kids — fills a population the report never measures. |
| **travel-agent** | **Medium** | Even a consumer tool carries the signature: prices cited live, "founder decides," never auto-books. The discipline is reflexive. |
| **fractional-cxo** | Tangential | Income finder; routes an AI-security expert toward governance roles, but doesn't itself close any gap. |
| **gtm-partner** | Tangential | Agentic GTM with proof-gating discipline, but operates *within* the gap, doesn't close it. |
| **school-negotiator** | Tangential | Consumer value from AI (#8) — negotiation coach. No governance angle. |
| q-education / event_coordinator / school-idf / car-research | None | Placeholder, placeholder, non-AI activity, not on disk. |

### The convergence finding (the actual headline)

The same architecture appears in **every serious instance, independently, across
unrelated domains** (threat intel, fraud, legal, accounting, OSINT, parenting
research, travel). The shared pattern:

1. **Deterministic/zero-inference extraction first; the LLM is advisory only.**
2. **Provenance on every claim** — page/offset, source span, `tool_use_id`, statute cite.
3. **Human approval gate before anything ships** — "NOT FOR DEPLOYMENT," analyst
   gates, "founder decides," fail-closed egress.
4. **Explicit uncertainty** — `{{UNVALIDATED}}`, A–F confidence, evidence tiers 1–5.

This is the *same doctrine* as the core OS (hooks → receipts → gates), rediscovered
per domain. It even shows up where there's no compliance reason for it (travel
booking). That makes it a genuine signature, not a feature bolted on for security
buyers.

**So the comparison is not "kipi has governance features." It is:** the report
describes the capability/governance gap as the defining unsolved problem of the
field; this body of work is *the same answer, re-derived 12 times in 12 domains.*
What the report says the industry is failing to do — govern capability at the point
of generation — is the involuntary default of everything here.

---

## Code-level proof pass (2026-06-26)

The per-instance pass above read positioning docs. This pass found the *enforcing
code* (scripts, hooks, validators, schemas) with file:line, and marked "DOC ONLY"
where a claim has no code behind it. Score = how many of the 4 pattern elements
(deterministic-first / provenance / human-gate / uncertainty-marking) are enforced
in code, not prose.

| Instance | In-code | Built | Strongest code citation |
|---|---|---|---|
| **kipi-system core OS** | **4/4** | core | `prd_runner.py:471` gate engine; receipts `:660-769`; 11 blocking hooks in `settings.json` |
| **ktlyst (product)** | **4/4** | independent | `v007.py:198` source_span must match PDF **verbatim**; `verdicts.py:69` `NOT_FOR_DEPLOYMENT` is the only legal value |
| **accountant** | **4/4** | independent | `agent.rs:167` fail-closed egress before `reqwest.post`; `safe.rs` `SafeValue` enum has no String variant |
| **Pure_spectrum_Q** | **4/4*** | independent | `validators/allowlist.py` fail-closed loader; `phase3_agent.py:128` agent can't fabricate `supporting_query_ids` |
| **ktlyst_lawyer** | **3/4** | independent | `stat-verify.py:196` citation validator; `decision-origin-tag-lint.py:42` human-decision tag enforcer |
| **kipi-investigations** | **3/4** | independent | `investigator.py:879` `tool_use_id` provenance; `:1760` `{{UNVALIDATED}}` enforced |
| KTLYST_strategy | 4/4 | **inherited** (prd-os) | `findings.schema.json` *"schema does not trust raw Codex output"* — shared core, not domain-built |
| 4_points_consulting | 2/4 | independent | `findings-verify-hook.py:71` blocks a CONFIRMED finding whose identifier is still UNVERIFIED |
| AUDHD_KIDS | 1/4 | independent | `compliance-check.py:147` auto-fails overclaims missing `{{UNVALIDATED}}` |
| travel-agent | 0/4 | — | all DOC; "never auto-book" enforced by *absence of a booking API*, not gate code |

\* Pure Spectrum: the gate + anti-fabrication are shipped code; some uncertainty
marking lives in `decisions.md` (doc).

### What the code pass changed about the claim (calibration)

- **The airtight core is ~6 instances, not 12.** Genuinely independent,
  code-enforced governance — across **three stacks** (Python threat-intel, **Rust**
  finance, Python fraud/OSINT/legal) — exists in: ktlyst product (4/4), accountant
  (4/4), Pure Spectrum (4/4), lawyer (3/4), investigations (3/4), plus the core OS
  (4/4). That spread across unrelated domains and languages is the real, defensible
  convergence finding.
- **The docs pass over-rated 4_points** (Strong → 2/4 in code): its CHALLENGE/
  premortem human gates and A–F confidence scale are procedural, not hooked.
- **Honest negatives** (these strengthen the claim by bounding it): investigations'
  human gate is post-facto auto-approve, not a hard pre-ship block; AUDHD_KIDS is
  doc-enforced except for the `{{UNVALIDATED}}` check; travel-agent has zero
  enforcing code.
- **A real pattern the code surfaced:** travel-agent governs by *capability absence*
  — there's no booking API to misuse. "Can't do harm because the tool doesn't exist"
  is a legitimate fourth governance mode alongside gate/provenance/marking.

### The defensible one-line version (for a public piece)

Across six independently built systems in three languages, the same governance
doctrine is enforced in code — the LLM is advisory, every claim is traced to a
verbatim source, and output is blocked before it ships. That is the thing the AI
Index says the field is failing to do, implemented six times by one operator.

## What kipi has that the report never measures

- **Neurodivergent-aware operation** (AUDHD executive-function layer). The report
  measures adoption and education but has nothing on cognitive-style accessibility.
- **Governance at n=1.** The report frames governance only institutionally/nationally;
  kipi proves the same mechanisms work for one person.
- **File-based persistent memory** as an operating substrate.

## What the report flags that kipi doesn't address

- **Environmental footprint** (#10). token-discipline optimizes cost, not carbon.
- **Rigorous multi-objective measurement** (#6 safety-vs-accuracy). The tension is
  acknowledged (sycophancy vs helpfulness) but not measured the way the report demands.

---

## The publishable angle

"AI governance as code, at the smallest possible scale." The report keeps saying
governance is losing the race because it's slow, manual, and institutional. The
kipi-system is a counter-proof: governance can be fast and automatic if it's
encoded as hooks and receipts. Worth a piece once the per-instance evidence lands.

---

## Going public: the credibility playbook (researched 2026-06-26)

Deep-research pass (106 agents, 24/25 claims survived 3-vote adversarial check).
Scope: reach AI researchers/academics, win = durable credibility. Citations are
verified primary sources unless flagged.

### The core finding (built for this situation)
The biggest credibility lever for an outsider is the thing already in hand:
**receipts.** Soderberg, Errington & Nosek 2020 (*Royal Society Open Science*
7(10):201520, survey of 3,759 researchers) found researchers rate openness /
reproducibility cues (links to code/data, evidence of computational
reproducibility) as MORE important to a preprint's credibility than author
identity or peer-review signals. Cue type explained 10-19% of credibility
variance; rater identity ~1%. The file-level receipts across six systems outweigh
the absent PhD. This is the empirical backbone, not opinion.

### The wall (structural, real)
- **Recognition is rank-gated** — Merton 1968 (*Science* 159.3810), the "Matthew
  effect": eminent names get disproportionate credit and visibility; unknowns are
  under-credited for equivalent work.
- **Can't network in** — Bourdieu-vs-Latour (*Social Epistemology* 30(3), 2016,
  medium confidence, contested theory): credibility is field-specific; an outsider
  must satisfy the field's internal criteria, not just know people.

### The playbook (ranked, evidence-backed)
1. **Write it up; put it on arXiv.** Preprint release ~+20.2% citations, the
   largest open-science effect (arXiv:2404.16171, ~122k papers). arXiv-first is the
   entry ticket.
2. **Release the reproducible artifact (code + receipts).** ~+34% citations after
   confound control across 2,439 systems papers (PMC9044204). This is the moat per
   the Nosek finding.
3. **Target NeurIPS 2026 Evaluations & Datasets Track.** Renamed; now explicitly
   accepts reproducibility audits, benchmark-limitation analyses, and negative
   results as standalone contributions ("need not introduce a new model"), mandates
   code release, requires Responsible-AI metadata (NeurIPS 2026 CFP + official
   blog). The governance-enforcement code + an audit framing fits exactly. Most
   actionable venue found.
4. **Embed in institutional design.** Raji, Xu, Honigsberg & Ho, "Outsider
   Oversight" (AIES 2022, arXiv:2206.04737): "audits alone are unlikely to achieve
   actual accountability; sustained focus on institutional design will be required."
   Connect to a lab / collaborator / program for access + legitimacy.

### Don't mistake reach for credibility
- Social-media promotion buys attention, not citations: a Twitter/X RCT
  (#TweetTheJournal) found no significant 1-year citation effect but a real
  Altmetric bump. (Broader RCT literature is mixed.) Use X to distribute the arXiv
  link; standing comes from artifact + venue.
- An altmetric spike is not standing: 2025 systematic review (125 studies) found
  Altmetric-citation R~0.16-0.19 vs Mendeley-readership-citation R~0.89.

### Failure mode (from the literature)
Most industry write-ups get ignored because they read as product marketing, not a
falsifiable contribution with released, verifiable artifacts. Fix: frame as an
audit/evaluation, lead with the receipts, stop selling.

### Honest gaps in this pass
Thin/silent on FAccT/AIES/HAI/GovAI/CSET specifics (only NeurIPS evidenced), the
historical lab-memo tradition (Bell Labs/PARC/DEC SRC surfaced in search but no
claim survived verification), and the named diffusion frameworks (Crane, Rogers,
Granovetter — no verified claim). NeurIPS 2026 specifics are cycle-specific; verify
the live CFP. A gap-fill pass is queued if a venue gets chosen.

## Going to revenue: the consulting-leverage playbook (2026-06-26)

Deep-research pass (108 agents, 25/25 claims verified on the completed re-run).
Scope: buyers = AI-builder companies + security teams shipping unreliable AI; win
= inbound consulting revenue.

### The load-bearing insight (and the trap)
There is a real tension in the evidence, and resolving it is the whole game:
- Edelman-LinkedIn says PUBLISH expertise (it drives RFP access, premium, demand).
- Gartner says DISPLAYING expertise BACKFIRES: buyers are overwhelmed by
  high-quality info (89%), hit a "crisis of confidence," and are 153% more likely
  to settle for a smaller, safer purchase. Suppliers "unwittingly exacerbate this
  by focusing on thought leadership and high levels of expertise."
- Resolution: SENSE-MAKING. Sellers who help buyers reconcile conflicting info and
  decide with confidence closed high-quality, low-regret deals ~80% of the time.

The move: frame the six-system receipts + AI-Index comparison as a DIAGNOSTIC that
reduces the buyer's confusion ("here's how to tell if your AI is actually
governed"), NOT as an expertise flex. Same asset, opposite framing.

### Verified findings (with evidence tier)
1. **Verifiable content is the rare winner** [vendor: Edelman-LinkedIn]. 55% of
   buyers prioritize content "grounded in verifiable facts"; only 15% of thought
   leadership is rated "very good." The receipts are exactly that rare, checkable
   content almost no competitor produces. Most actionable finding.
2. **Thought leadership drives demand — as stated intent** [vendor: Edelman-LinkedIn].
   86% would invite a consistent producer to an RFP; 60% pay a premium; 75%
   researched something new because of a piece. CAVEAT: self-reported intent; the
   report's own actual-purchase number is 23%.
3. **Expertise-display backfires; sense-making wins** [vendor: Gartner]. The
   load-bearing insight above.
4. **Credibility genuinely persuades** [PEER-REVIEWED: Pornpitakpan 2004, J. Applied
   Social Psych]. High-credibility sources are more persuasive (effect comparable to
   argument quality) — but delivery must be sense-making, not a flex.
5. **Referrals are a myth; engineer distribution** [PEER-REVIEWED: Grierson & Brennan
   2017]. Providers overestimate referral influence; clients say they weren't
   influenced to refer. Do NOT rely on good work spreading itself. Failure mode.
6. **Productize into fixed-scope, fixed-price premium** [practitioner case: Dunford].
   Live proof a solo expert charges $50K-$100K FLAT per engagement (not hourly).
7. **Sell from authority via a "probative conversation"** [practitioner: Enns / Win
   Without Pitching]. Arrive as the guide, not the pitch. Consistent with sense-making.
8. **Don't invent a category; anchor to the emerging problem** [practitioner: Dunford,
   vs Play Bigger]. Category creation needs "double persuasion." Ride the
   already-emerging "shipping ungoverned AI" problem instead.

### The ranked playbook (highest evidence first)
1. Reframe the receipts as a DIAGNOSTIC that cuts buyer confusion (#1 + #3).
2. Productize it into a named, fixed-price engagement, not hourly (#6).
3. Engineer distribution deliberately — publish, talk, community; don't wait for
   referrals (#5).
4. Sell from authority: arrive already-the-expert via the asset (#4 + #7).
5. Anchor to "ungoverned AI" as an existing problem; don't evangelize a new
   category (#8).

### Evidence honesty (3 tiers — do not conflate)
- PEER-REVIEWED (rigorous anchors): source credibility persuades (Pornpitakpan
  2004); referrals are a myth (Grierson & Brennan 2017).
- VENDOR-SPONSORED (high-quality but self-interested, self-reported intent): all
  Edelman-LinkedIn and Gartner figures. Edelman sells TL consulting; Gartner sells
  the framework.
- PRACTITIONER OPINION (useful, not evidence): Dunford, Enns, Baker.

### Gaps the research could NOT fill (real holes in the plan)
- NO evidence on the proof-asset / free-audit as a lead magnet in security buying —
  how much to give away vs gate is unanswered.
- NO channel-specific evidence for reaching AI-builder / security buyers (community,
  analyst relations, talks, dark social).
- NO evidence that a signature named framework lifts pricing beyond general credibility.
These are the next research targets if this becomes the plan.

## Refinement log

- 2026-06-26 — doc created; core-OS mapping done.
- 2026-06-26 — per-instance deep dive complete (19 registered instances, read-only
  agent pass). Convergence finding added: one governance-at-generation-time pattern
  re-derived across 12 domains. 5 Strong, 6 Medium(+), 3 Tangential, rest None/empty.
- 2026-06-26 — code-level proof pass complete (file:line citations, code-vs-doc).
  Result: airtight core is ~6 independently-built, code-enforced instances across 3
  stacks (Python/Rust); 4_points downgraded Strong→2/4; honest negatives recorded.
  "12 domains" recalibrated to "~6 in real code." See Code-level proof pass section.
- Open threads to refine next:
  - Decide the artifact: essay ("governance as code at n=1"), conference talk, or
    a KTLYST positioning asset. Ties to the OSS-contribution mission.
  - Environmental footprint (#10) is a real blind spot — only KTLYST_strategy's
    $5/run cap touches it. Worth a deliberate position or an explicit "out of scope."
  - Optional: lift the 6 strongest file:line citations into a standalone evidence
    appendix if this becomes a public claim (so reviewers can verify each).
