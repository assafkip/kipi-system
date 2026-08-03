---
description: When a stuck-loop detector refuses, a different model triages in a fresh session. Tier A is automatic; Tier B/C are commands you run.
paths:
  - "**/scripts/**"
  - "**/hooks/**"
  - "**/tests/**"
  - "**/*.py"
  - "**/*.sh"
---

# Fable Escalation: when Opus is stuck, a different model triages (ASK-311)

PATHS-SCOPED ON PURPOSE. Tier A needs no prompt budget at all: the PreToolUse
hook `token-guard.py` staples the triage to its own refusal, so that half of
the mechanism runs as a script whether or
not this file is loaded. Only the Tier B/C commands below need a reader, and
those fire while you are in code. The always-on instruction budget is already
601 lines against a target of 300 (`instruction-budget-audit.py`, the
pre-commit ratchet), and a rule that does not have to be always-on must not be.

Opus keeps the work. Fable is the triage lens, in a fresh session, and it never
implements. The executable is
`q-system/.q-system/scripts/fable-escalate.py` — the only caller of
`claude -p --model claude-fable-5` in this fleet and the only writer of the
escalation ledger. Its paired test is
`q-system/.q-system/tests/test_fable_escalation.py` (19 cases, 7/7 mutants
killed).

## Why a different model and not "try harder"

Same-model retries re-run the same reasoning distribution, so a pattern that
deadlocks Opus deadlocks it again on the next attempt. Cross-model escalation
breaks cycles same-model retries cannot, because the two failure distributions
are complementary ([Act or Escalate, arXiv:2604.08588]).

`q-system/.q-system/token-guard.py` is already the outside-the-model progress
detector this needs, and every one of its checks terminated in "give up and tell
the founder". The escalation is a missing branch on that existing script, not a
new gate: one call site tag, one subprocess, one test file.

## Tier A — automatic (no action required from you)

`token-guard.py` calls the script above on three stuck refusals and staples the
triage to the exit-2 message. You will simply see a `FABLE TRIAGE` section.

| Trigger id | Detector |
|---|---|
| `exact-retry` | `check_exact_retry`, `RETRY_LIMIT=3` |
| `edit-spiral` | `check_edit_spiral`, `EDIT_FAIL_LIMIT=3` |
| `volume-ceiling` | `check_volume`, `VOLUME_CEILING=50` (incl. gate-grace spent) |

Deliberately excluded, tagged per call site rather than sniffed from the text:

- Warn-tier detectors (read spiral, grep drift, time stall, agent-no-output). A
  warn means "you may be drifting"; most runs recover unaided, and the time-stall
  detector fires on any legitimate read-only audit stretch.
- Sensitive-file refusals. Policy, not a stuck state.
- MCP rate limits. `environmental-trigger` class per `self-healing-retry.md`
  rule 5 — stop on attempt 1; cross-model triage cannot fix an API.

## Tier B and C — you run the command

These are judgment calls, so they are advisory by design: an automatic call here
would add latency while a human is waiting for a reply. Run:

```bash
python3 q-system/.q-system/scripts/fable-escalate.py \
  --trigger <id> --reason "<one line: what is looping>"
```

| Trigger id | Fires when |
|---|---|
| `founder-repeat` | the founder has asked the same substantive thing 2+ times, or said "why did you stop" / "I already told you" / "that's wrong" twice on one artifact |
| `state-vs-spec` | you are about to report that something IS happening or HAS failed, based on a file artifact rather than an observation (`rca-specification-reported-as-state-2026-08-02.md`: 9 false claims in one session) |
| `derivation-split` | two sides derive one logical value from different sources and every test is green |
| `copy-drift` | you edited a file and cannot prove the running system loads that copy |
| `invented-fixture` | a test passes but its fixture was invented rather than produced |
| `no-evidence-fork` | 2+ plausible approaches and no evidence to choose (`quick-plan.md` name-options) |

Whether these FIRE is a model decision, which no deterministic checker can
observe. Measured instead, advisory and periodic, by
`q-system/.q-system/scripts/skill-trigger-eval.py` against the fixture set
`q-system/.q-system/skill-evals/fable-escalation.json`. That is the same posture
`skill-hook-pairing.md` already gives founder-voice, rca and fable-discipline.
It is a signal, never a pass/fail gate.

## What comes back

Four sections: `DIAGNOSIS` (one falsifiable claim), `STOP` (the looping
approach, named), `NEXT` (one action with the command that proves it), `REFUTE`
(the command that would show the diagnosis is wrong).

Per `evidence-ledger.md`, a triage is an INFERENCE until a command backs it. Run
its `REFUTE` line before acting on it. The ledger row stores it labelled, never
as a measurement.

Every call leaves one JSONL row in `q-system/output/fable-escalations/`
(trigger, packet hash, packet size, duration, whether the model answered, the
diagnosis). Read them back with:

```bash
python3 q-system/.q-system/scripts/fable-escalate.py --report
```

## Limits, all coded

| Limit | Where |
|---|---|
| 2 escalations per actor per session, then `slack-notify.sh` pages once | `FABLE_CAP`, `notify_cap()` |
| 45s cap on the call, plus a wider outer cap in `token-guard.py` | `FABLE_TIMEOUT`, nested `maybe_escalate` |
| Any failure degrades to the plain refusal, byte for byte | `test_broken_fable_degrades_to_plain_block` |
| A suite can never spend a real call | `PYTEST_CURRENT_TEST` chokepoint in `call_fable` |
| Off switch | `KIPI_FABLE_ESCALATION=0` |

Cross-model is a step before the human, never instead of one. At the cap the
script hands off: no further calls, and one page to the founder. The test
`test_escalations_stop_at_the_cap_and_page_once` pins both halves.

## Honest boundary

`fable-escalate.py` sends a bounded tail of the transcript (25 records) and
nothing else. It cannot see what you were thinking, and it cannot read the repo:
the child runs outside the project directory on purpose, so its answer is a read
of the packet, not of the codebase. A thin packet yields a thin triage; say so
rather than treating the reply as authoritative.

## Cross-references

`loop-exits.md` (this is exit 5, no progress, with a new terminal branch) ·
`self-healing-retry.md` (the cause taxonomy that excludes MCP rate limits) ·
`evidence-ledger.md` (why a triage is stored labelled) ·
`skill-hook-pairing.md` (why Tier C gets fixtures and not a lint) ·
`founder-notifications.md` (the one ping channel).
