---
id: mint-approval-tokens-one-at-a-time-just-in-time
kind: pattern
title: Mint Approval Tokens One At A Time, Just In Time
date: 2026-10-31
---

## Problem

Short-lived, one-shot authorization tokens (approvals, elevated-privilege grants, signed capability tokens) are often minted in a batch: a human approves several upcoming steps at once, and the automation holds a handful of tokens to spend as it goes.

This breaks whenever the first step runs longer than the token lifetime. The later tokens expire while still unspent, the later steps are refused, and a human has to be interrupted to re-approve. The failure is silent until the moment of use, and it gets worse exactly when steps are slow — loops over many items, retries, large batches — which is when an interruption costs the most.

## Pattern

Keep at most one live token in existence, and mint it only once the step that will consume it is about to run.

Enforce it on both sides:

**In the token store (authoritative):** reject a mint request while an unexpired, unspent token exists. The store is the only thing that can guarantee the invariant, because it is the only component that sees all requesters. Return a distinct non-success status so callers can tell "already live" apart from "denied" and from "transport failure."

**In the requesting process (cooperative):** request the next token only after the previous privileged command has exited. Never pre-fetch. The request becomes part of the step's own setup rather than part of a planning phase that ran arbitrarily long ago.

With both in place, a token's lifetime only has to cover one step's startup, not the whole remaining plan. The timeout can therefore be short, which is what makes it useful as a security control.

## How to implement

1. Give the store a single-slot model: a live token is either present or absent. Clear the slot on spend, on expiry, and on explicit revoke.
2. Make mint a check-and-set under a lock or a conditional write, so two concurrent requesters cannot both observe an empty slot. Without this, the invariant holds in testing and fails under concurrency.
3. Make spend atomic and single-use: the same operation that validates the token consumes it. Validate-then-use leaves a replay window.
4. Decide the policy for a mint request that arrives while a token is live. Refusing is the safest default and surfaces the bug in the caller. Returning the existing token quietly re-introduces batching through the back door.
5. Always free the slot when a step ends, including on crash, non-zero exit, and cancellation. Use a cleanup handler, or let expiry be the backstop so a crashed step cannot wedge the system until someone intervenes.
6. Size the lifetime to one step's startup latency plus margin — not to the duration of the whole run.
7. Log every mint, spend, refusal, and expiry with a correlation id for the step. Expiries in the log are the signal that step granularity is still too coarse.

## Tests

- Mint once, then mint again while the first is live: second mint returns non-success, and the store still holds exactly one token.
- Spend the token, then mint: succeeds.
- Let a token expire, then mint: succeeds, and the stale token is gone.
- Spend the same token twice: second attempt is refused.
- Two concurrent mint attempts against an empty slot: exactly one succeeds.
- Kill a step mid-flight without spending: the slot becomes free via cleanup or expiry, with no manual action.
- Run a multi-step sequence where one step takes longer than the token lifetime: all later steps still succeed, because each minted its own token at the point of use.

## When this applies

Any short-lived single-use grant handed to automation: human approval gates, step-up authorization, temporary credentials, break-glass access, signed one-time capability tokens. The general rule is that a time-boxed grant must be acquired as late as possible relative to its use, and the issuer — not the caller — must be what enforces how many are outstanding.

## Trade-off

Just-in-time minting means more approval round trips when a human is in the loop. Address that with scope rather than with batching: let one token cover a whole bounded loop as a single step, or pre-authorize a class of operations by policy so routine steps need no token at all. Do not address it by handing out tokens for work that has not started.
