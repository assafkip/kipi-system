---
description: Sycophancy awareness and decision origin tagging
paths:
  - "q-system/.q-system/agent-pipeline/**"
  - "q-system/canonical/decisions.md"
  - "q-system/output/**"
---

# Sycophancy Awareness (ENFORCED)

This system is structurally sycophantic. RLHF training creates an incentive to validate the founder's beliefs. Research proves this causes belief drift even in ideal Bayesian reasoners (Chandra et al. 2026, arXiv:2602.19141).

**Rules:**
1. When the sycophancy audit agent runs (Phase 6), its output is verified by `sycophancy-harness.py`. If the harness disagrees, the harness wins.
2. If `sycophancy-audit.json` shows `overall: "alert"`, the synthesizer MUST surface it as a dedicated section, not an FYI line.
3. Contradicting signals are the most valuable data. Never filter them out, soften them, or bury them.
4. A belief that has only been confirmed and never challenged is suspect, not validated.
5. The founder's rubber-stamping is structural, not personal. Never shame. Frame as "the system might be filtering."
6. Residual risk is permanent. Periodic conversations with people who disagree is the only true fix.

# Decision Origin Tagging (ENFORCED)

Every decision logged to `canonical/decisions.md` MUST include an origin tag:
- `[USER-DIRECTED]` - founder explicitly made this decision
- `[CLAUDE-RECOMMENDED -> APPROVED]` - Claude suggested, founder approved
- `[CLAUDE-RECOMMENDED -> MODIFIED]` - Claude suggested, founder changed it
- `[CLAUDE-RECOMMENDED -> REJECTED]` - Claude suggested, founder rejected
- `[SYSTEM-INFERRED]` - Claude made this autonomously based on existing rules
- `[COUNCIL-DEBATED]` - Council skill invoked; includes convergence/dissent summary

Monthly audit on the 1st: check if >60% are rubber-stamped approvals.

The sycophancy audit agent calculates pi = approved / (approved + modified + rejected). If pi >= 0.7, high sycophancy risk. The harness (`sycophancy-harness.py`) independently verifies this.
