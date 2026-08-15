---
description: AUDHD-adapted coding rules - structure, communication, emotional scaffolding
paths:
  - "**/*.py"
  - "**/*.js"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.sh"
  - "**/*.html"
  - "**/*.css"
---

# AUDHD Coding Rules (ENFORCED)

## Enforcement pairing (read before trusting the word ENFORCED above)

| Piece | Path |
|---|---|
| Detector | `q-system/.q-system/scripts/wiring-check.py` |
| Wiring | PostToolUse on Edit/Write, `.claude/settings.json` + `settings-template.json` |
| Test | `q-system/.q-system/scripts/test_wiring_check.py` |

**ADVISORY DETECTION, not prevention.** `wiring-check.py` inspects the written
file and reports max nesting, max function length, debug leftovers
(`print`/`console.log`/`debugger`/`breakpoint`/TODO), bare `except`, unused
imports, orphaned function defs, and hardcoded URLs/ports. It **exits 0 on every
path**, violations included. Findings arrive as feedback to Claude and the write
still lands. ENFORCED here means detected-and-surfaced. It does not mean blocked
and it does not mean prevented.

Flipping it to exit 2 is a founder decision made in the open, never a silent one:
the hook ships via `settings-template.json`, so a hard block would land on every
code Edit/Write across every instance (ASK-132).

**What no detector covers:** Presentation, Error Communication, Session
Structure, and the banned-language list below are model behaviour, not
file-inspectable. They stay interpretive, per `skill-hook-pairing.md`'s decision
rule: a judgment rule lives in the instruction, not in a hook. Nothing checks
them mechanically, so if the model drifts there, no gate will say so.

## Code Structure (Working Memory)

*Detected by `wiring-check.py`, advisory only: the 2-level nesting cap and the
30-line function cap. The other three bullets below are read by you, not by any
script.*

- Functions do one thing. If the description has "and," split it.
- Max nesting: 2 levels. Extract inner blocks into named functions.
- Early returns over nested else chains. Happy path reads top to bottom.
- Explicit over clever. 3 clear lines beat 1 cryptic comprehension.
- No function longer than 30 lines. Task separation applies to code.

## Naming (External Memory)
- Names carry full meaning. `user_email_validated` not `checked`. `retry_count` not `n`.
- Booleans: `is_`, `has_`, `can_`. Functions: verb-first (`validate_token`, `send_email`).
- No abbreviations except universal (`url`, `id`, `db`).

## Completion Standard (Wiring)
- Code is not done when written. Done = runs end-to-end, no orphaned pieces.
- Every new function is called somewhere. Every route is registered. Every component is rendered.
- Every import is installed. Every config value is read. Every event has a listener.
- Report completion as full chain: "Added X to Y. Called from Z on line N. Tests passing."
- If wiring can't be verified, say so: "Can't verify without running. Want to test?"
- Never say "done" after writing a function. Writing is not done.

## Presentation (One Thing at a Time)
- One file per message. One concept per edit.
- Show the change first, explain why second. Action layer on top.
- No "as mentioned above" or "recall that we." Repeat context inline.
- One approach. Not "you could use X or Y." Override if you want.

## Error Communication (Factual, No Shame)
- State what, where, why. Never "something went wrong."
- After 3 failures: checkpoint. "Here's where we are. [summary]. Good place to pause if you want."
- Never retry same approach. Shrink scope. Micro-action ladder.
- Never say "this should be simple" or "easy fix." If it were, it'd be done.

## Banned Language in Code Contexts
Never: "obviously," "simply," "just," "as you know," "this should work," "real quick," "no worries," "we're almost done," "sorry about that," "easy fix."
Use: "Here's what changed." "That works. Next." "Two approaches ruled out." "Good stopping point." "Committed and passing."

## Session Structure
- Start with easiest fix. Build momentum.
- After hard debugging: next item is a quick win. Recovery buffer.
- After 3+ complex changes without checkpoint: commit, test, or demo.
- Never end on a broken state. Find a clean stopping point.
