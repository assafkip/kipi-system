---
description: A rule or README line that says something is watched, or will alert, notify or page anyone, names the executable that does it. Held by capability-claim-lint.py.
paths:
  - ".claude/rules/**"
  - "**/README*.md"
---

# Named emitter (ENFORCED)

`q-system/.q-system/scripts/capability-claim-lint.py` holds this: any line in a
rule or README that says something is watched, or that something will alert,
notify or page anyone, names the executable that does it within two lines.
The test is one question: "what runs that?". A claim with no script behind it
is a promise, and a promise read as a capability makes the reader stop
watching for the thing.

The reference shape, with the emitter on the claim's own line:

- A failed job pages Sana through `q-system/.q-system/scripts/slack-notify.sh`.

If nothing runs it, write that ("nothing alerts on this").

## An uncaptured commitment is an orphan too

A promise about the future ("I will report back if it breaks", "I'll keep
checking the next few runs") is a finding with no owner. The agent does not
persist between sessions, so a promise that lives only in chat is dropped when
the session ends. The next action is a detector that runs, named by its script
and channel, or a finding captured per `no-orphan-findings.md`. Never the
sentence alone.

## Scar (ASK-562)

Four times in one day a capability was reported by reading the design instead
of observing the behaviour: "I'll tell you either way" with nothing computing
it, and a job described as running every 4 hours that had never run once.

## Honest boundary

The lint sees FILES, never chat, so the commitment half is a model decision no
hook observes. It checks that an emitter is NAMED near the claim, never that
the named script exists, is wired, or fires. It matches a fixed phrase set.
Bypass one file with `capability-claim-lint-skip`.

<!-- enforcement -->
```json
[
  {
    "clause": "Named emitter",
    "status": "ENFORCED",
    "exec": "q-system/.q-system/scripts/capability-claim-lint.py",
    "config": ".claude/settings.json",
    "test": "q-system/.q-system/scripts/test_capability_claim_lint.py",
    "note": "ENFORCED covers the file half only: an alerting phrase in .claude/rules/*.md or a README with no executable path within two lines blocks the write (PostToolUse, exit 2). The uncaptured-commitment half is chat and no hook observes it."
  }
]
```
