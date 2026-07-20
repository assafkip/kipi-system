---
id: put-correctness-rules-in-code-judgment-in-the-prompt
kind: pattern
title: Put correctness rules in code, judgment in the prompt
date: 2026-07-20
---

When you build automation that mixes an LLM with deterministic logic, split responsibilities by what each tool is actually good at, and enforce the split.

An LLM is the right engine for TASTE, JUDGMENT, and TEXT: curating, drafting, classifying ambiguous input, summarizing. It is the wrong engine for CORRECTNESS RULES: caps and quotas, deduplication, cadence and spacing, idempotency, scheduling, what-counts-as-done bookkeeping, and any publish/cancel reconciliation. A correctness rule stated in a prompt is a rule the model MAY or may not honor on any given run; the same rule in code is one it cannot bypass.

The failure mode to hunt for: a rule that must always hold has been written as an instruction to a model instead of as executable logic. It passes review because the prompt text reads correctly, and it fails intermittently in production because generation is nondeterministic. Symptoms are same-shape repeat incidents (a limit exceeded, a duplicate emitted, a step skipped) that no single code change seems to prevent, because the logic that should own the invariant does not exist in code at all.

How to apply:

1. For every rule in a system, ask: 'Is this a matter of judgment, or an invariant that must always hold?' Judgment stays with the model. Invariants move to code the model calls, not code the model is asked to imitate.

2. Build the deterministic modules AND wire them into the live path. A tested module that the production entry point never calls is worse than none: it creates false confidence. Confirm the running path executes the code, not just that the code exists.

3. Audit existing automation the same way. Enumerate every job that an LLM drives, and for each one list what the model does versus where the correctness rules live. Any job whose caps, dedup, or scheduling live 'in the prompt' is a latent repeat-incident. Run the greps, record the verdict per job, and treat 'rules in the prompt' as a defect to migrate, not a style choice.

4. When an incident traces back to a model not following an instruction, the fix is code that makes the instruction unnecessary, not a stronger instruction. 'Tell the model to be more careful' is not a fix; a check it cannot skip is.

Rule of thumb: if a wrong outcome would be a bug rather than a matter of taste, the logic that prevents it belongs in code.
