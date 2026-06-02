# Code RCA System — Research Resource Map

Date: 2026-06-02
Purpose: Resources for building a "code RCA system." Focus: FAANG processes, postmortem culture, academic research.

## The fork that decides everything

"Code RCA" splits into two different problems with two separate research bodies. Pick one, or build both as distinct modes:

1. **Fault localization** — given a failing test or bug, find the faulty line/commit. Academic SE lineage (SBFL, delta debugging, bisection). Deterministic, code-level.
2. **Incident RCA** — given a production outage, reconstruct the causal chain and write the postmortem. SRE / Amazon COE lineage + recent LLM-RCA. Narrative, systemic, multi-signal.

They share almost no methodology. Most "code RCA" asks mean #2 with #1 bolted on as the "which commit" step.

---

## Bucket 1 — FAANG / hyperscaler processes

- **Google SRE, Ch. 15 "Postmortem Culture"** + template — https://sre.google/sre-book/postmortem-culture/
- **Google SRE example postmortem** (full worked example) — https://sre.google/sre-book/example-postmortem/
- **SRE Workbook, postmortem practices** — https://sre.google/workbook/postmortem-culture/ and https://sre.google/workbook/postmortem-analysis/
- **Amazon Correction of Errors (COE)** — no official public template; closest sources are AWS Builder's Library "Operational Excellence" articles + re:Invent COE talks. Structure: issue summary -> customer impact -> timeline -> what went wrong (5 Whys) -> detection -> mitigation -> corrective actions as *mechanisms*.
- **Microsoft Azure** — public RCA reports (minute-by-minute timelines) + Well-Architected Reliability pillar on post-incident review.
- **PagerDuty postmortem docs** (open, copyable, closest thing to a free reference implementation) — https://postmortems.pagerduty.com/culture/blameless/

## Bucket 2 — Postmortem culture / human-factors lineage

The "why" layer. Skipping it produces blame-shaped RCAs nobody files honestly.

- **John Allspaw, "Blameless PostMortems and a Just Culture"** (Etsy, 2012 — the origin) — https://www.etsy.com/codeascraft/blameless-postmortems
- **Richard Cook, "How Complex Systems Fail"** — foundational 18-point paper behind all of it (free PDF).
- **Sidney Dekker, "Just Culture" / "Field Guide to Understanding Human Error"** — academic spine Allspaw cites.
- **Allspaw, "Getting the messy details is critical"** — https://medium.com/code-for-america/john-allspaw-getting-the-messy-details-is-critical-59e641aa0a77
- Design tension to resolve: Allspaw treats **action items as a non-goal** of the learning review; Google makes them **mandatory**. Decide where your system lands.

## Bucket 3 — Academic research

### 3a. Fault localization (code-level lineage)
- **Wong et al., "A Survey on Software Fault Localization"** (IEEE TSE) — canonical survey, start here.
- **Spectrum-Based Fault Localization (SBFL) survey** — https://www.researchgate.net/publication/305389027
- **Zeller, Delta Debugging / ddmin** — "Yesterday, my program worked. Today, it does not. Why?" — failure-inducing-input minimization classic.
- **Combining SBFL + statistical debugging** (ASE 2019) — https://dl.acm.org/doi/10.1109/ASE.2019.00054
- Practical cousin: `git bisect` as deployed delta debugging.

### 3b. Incident / causal RCA + LLM-RCA (recent, fast-moving)
- **"Automatic Root Cause Analysis via LLMs for Cloud Incidents"** (Microsoft) — https://arxiv.org/abs/2305.15778
- **"Recommending Root-Cause and Mitigation Steps using LLMs"** (Microsoft, ICSE; 40,000+ incidents) — https://arxiv.org/pdf/2301.03797
- **RCACopilot** (EuroSys '24, in production at Microsoft, ~0.77 RCA accuracy) — search "RCACopilot EuroSys 2024".
- **Causal inference for RCA over distributed traces** (SCMs, Granger causality, Bayesian nets; "TraceCausalNet") — https://arxiv.org/pdf/2502.18240

---

## What the sources agree the system needs

- Enforced template: metadata, summary, impact (w/ SLO), **root cause vs trigger vs contributing factors** (multi-cause, never single), auto-seeded timeline, detection/response, action items as first-class objects.
- Timeline auto-built from: deploys, version control, monitoring/alerts, incident chat. Human annotates.
- Causes typed: code bug / config / design / process / monitoring / capacity / org.
