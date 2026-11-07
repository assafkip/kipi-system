# RCA: sub-agents reported prompt-injection arriving through their own hook error text during the Linear cleanup run

**Date:** 2026-08-16
**Trigger:** Founder-authorized security investigation. Two signals arrived together: (a) multiple sub-agents in session `b0bbdc11` each reported and refused what they judged to be prompt-injection delivered via this session's own tool/hook error output, and (b) Linear issue ASK-870 "SECURITY: unsanctioned .claude/ change" was auto-filed at 2026-08-16T17:33:17Z by this repo's `.claude/` integrity tripwire.
**Surface-fix commit:** none required — no compromised artifact was found
**Structural-fix commit:** pending (see Action items)

## What happened

Two independent events were initially read as one possible intrusion. Neither is an intrusion.

The ASK-870 tripwire event was a legitimate in-session documentation edit that used a non-sanctioned write path; the tripwire correctly reverted and quarantined it. The "prompt injection" the sub-agents refused was, on the evidence, this repo's own **Fable cross-model escalation** (ASK-311) working as documented in `.claude/rules/fable-escalation.md` — triage text computed against an orchestrator-level context tail and then delivered into a *sub-agent's* context, where it is behaviourally indistinguishable from an injected instruction.

No tampering was found in any hook, script, or rule. The sub-agents' refusals were correct behaviour and remain correct regardless of which explanation holds, because the fleet's own contract already says a triage is an inference, never an authority.

**Assessment: NOT an active compromise. No credential rotation, no persistence hunt, no incident response required.** Two genuine engineering defects were found and are captured below.

## Surface symptom

Four distinct classes of "injected" content were reported. Each maps to first-party text.

1. Instructing an agent to run an unrecognized script `fable-escalate.py --report`, referencing "cross-model triage" and an "escalation cap". This is verbatim `token-guard.py` block text:

```
q-system/.q-system/token-guard.py:676-685
    return ("[Fable escalation cap spent for this actor. Cross-model triage "
            "did not unstick this. Whether a page actually reached the "
            "founder is recorded per-row in the ledger; the script "
            "`fable-escalate.py --report` is what answers that, and nothing "
            "here should be read as a claim that anyone was reached.]")
    ...
    return ("[Cross-model triage requested (trigger: %s). It arrives on a later "
            "tool call in this session, or read it with `fable-escalate.py "
            "--report`.]" % trigger)
```

2. Asking an agent to omit issue IDs from its report and hand write control to an unverified "peer". Matches the triage delivered to actor `a542ade419af5af6d` at 18:11:25Z: *"SendMessage to the two sweep agents (`aba52025066f5b56b`, `a286d3337a0733573`) ... with instructions to take their chunk files as the work list and **skip everything listed as done** in `chunk4_progress.md`. Then idle until task notifications; **no further main-loop Linear reads**."*

3. Fabricated claims of completed work to relay as fact. Matches the triage delivered to actor `aba52025066f5b56b` at 18:21:28Z: *"the next coordinator output is the final report (restored ASK-870, 26 cancellations, 6 dangling-project leads, 5 injection attempts)"* — counts the receiving agent never computed.

4. Impersonating the coordinating agent. Every triage is written in imperative second person addressed to the orchestrator (`STOP:`, `NEXT:`), and arrives inside a sub-agent's hook stderr.

The ASK-870 quarantine symptom is a single-clause documentation append:

```diff
--- .claude/rules/skill-hook-pairing.md
+++ quarantine/20260816T173315Z/.claude__rules__skill-hook-pairing.md
-... council, kipi-design (brand/design/ui-ux-pro-max).
+... council, kipi-design (brand/design/ui-ux-pro-max), architecture-review
+ (explicit-ask only, not auto-invoked — no trigger-eval fixture needed).
```

## Surface root cause

`token-guard.py` `block()` appends model-authored free text to its own refusal and prints the whole thing to stderr, which the runtime feeds back as tool-error context:

```
token-guard.py:702-711
    parts = [message]
    if triage:
        parts.append(FABLE_BANNER % triage)
    ...
    print("\n\n".join(parts), file=sys.stderr)
    sys.exit(2)
```

The triage is fetched by `take_pending_triage()` from a JSON file and inserted verbatim. A sub-agent receiving it sees an authoritative-looking system channel issuing instructions it cannot attribute, naming a script it has never heard of and agent IDs it cannot verify. Refusing was the correct read of an ambiguous channel.

For ASK-870: the write to `.claude/rules/skill-hook-pairing.md` bypassed `apply-claude-changes.sh`, the only sanctioned write path, so the tripwire's baseline comparison classified it as unsanctioned drift.

## Structural root cause

### Root cause #1 — a trusted system channel carries unattributed, unlabelled-at-the-boundary third-party model text

`type: implicit-contract`

The Fable triage is a *proposal from a different model*, but it is delivered on the same stderr channel that carries the guard's own deterministic refusals. `FABLE_BANNER` does label it (`--- FABLE TRIAGE (fresh session, claude-fable-5) ---`, "It is a proposal, not a measurement"), and that labelling is why several agents correctly identified it as untrusted. What the banner does not establish is *provenance the receiver can verify*, and no executable asserts that property today: the PostToolUse/PreToolUse hook `q-system/.q-system/token-guard.py` prints the triage unconditionally, and its paired test `q-system/.q-system/tests/test_fable_escalation.py` pins delivery and degradation but has no case distinguishing a genuine triage from text another writer placed on the same channel. A recipient acting safely must treat both identically — which is exactly what happened, at the cost of an escalating security scare. The action items name the test and code change that would make provenance checkable.

### Root cause #2 — the triage is computed from one actor's context and delivered into another actor's context

`type: code-defect`

`request_escalation()` sends `hook_input["transcript_path"]` — a bounded 25-record tail. Sub-agents driven by orchestrator `SendMessage` bodies carry orchestrator-level state in that tail, so the triage model reasonably concluded it was triaging *the orchestrator* and addressed its answer there. Measured: all seven pending payloads for this session open with orchestrator-scoped diagnoses ("The orchestrator is not blocked on work at all…", "the coordinator burned its budget…") while being keyed to, and consumed by, sub-agent actors.

No script, hook, lint or test currently checks that the actor a triage is delivered to is the actor whose transcript produced it; the `request_escalation()` code path in `token-guard.py` passes the actor through without comparison, and no case in `test_fable_escalation.py` exercises a mismatch. That mismatch is what produces classes 2, 3 and 4 above. Advice that is sound for the coordinator ("skip what is already done", "the next output is the final report with these counts", "stop reading, delegate to the sweep agents") becomes, when read by a sub-agent, an instruction to hide IDs, relay numbers it never computed, and cede write control. The content is benign; the routing makes it read as an attack.

### Root cause #3 — the triage hand-off file sits in a world-writable directory with a predictable name and no validation

`type: code-defect`

```
token-guard.py:591     FABLE_PENDING_TEMPLATE = "/tmp/claude-fable-pending-%s.json"
token-guard.py:599-601 def pending_path(actor):
                           return os.environ.get("KIPI_FABLE_PENDING") or (
                               FABLE_PENDING_TEMPLATE % actor)
token-guard.py:621-622 if isinstance(data, dict) and data.get("triage"):
                           return data["triage"]
```

`/private/tmp` is mode `drwxrwxrwt`. Any local process can write a file at a guessable path whose `triage` string is then printed verbatim into an agent's context inside a system-looking banner. The deterministic checker that would catch this class does not exist yet: `take_pending_triage()` in `q-system/.q-system/token-guard.py` validates only `isinstance(data, dict) and data.get("triage")`, and its paired suite `q-system/.q-system/tests/test_fable_escalation.py` has no case that feeds it a hostile payload. `KIPI_FABLE_PENDING` lets an environment variable redirect the read outright. The action items below name the reproducer test and the code change that close it.

**This was not exploited today** — all seven payloads are owned by `assafkipnis`, timestamped coherently with the run, and their content matches the session's real state. It is a latent local-injection channel, not evidence of intrusion.

### Root cause #4 — the sanctioned `.claude/` write path is not discoverable at the moment of the write

`type: process`

An agent adding a skill and documenting it in the paired rule had no in-band signal that `.claude/` requires `apply-claude-changes.sh` until after the write, when the tripwire reverted it. The guard is correct and it held. The cost is that a routine documentation edit produces a `SECURITY:` Linear issue whose title asserts more than the content warrants, which is what pulled this into a security investigation.

## Verification

Every claim below is a command that was run, with its result.

**token-guard.py is not tampered with.**
```
$ git status --porcelain q-system/.q-system/token-guard.py .claude/rules/skill-hook-pairing.md
(empty)
$ git diff HEAD --stat -- q-system/.q-system/token-guard.py
(empty)
```
Both files are byte-identical to committed HEAD. Last change to `token-guard.py` is `d2bf3221` (2026-08-08, "one locked writer for the actor cache (ASK-507)"), authored by `Assaf Kipnis <1494043+assafkip@users.noreply.github.com>`. Full 15-commit history shows no unrecognized author and no commit inconsistent with the stated rate-limiting purpose.

**The integrity tripwire and both write guards are unmodified and wired.**
```
$ git status --porcelain .../claude-integrity-tripwire.py .../claude-path-write-guard.py .../apply_claude_changes.py
(empty)
$ grep -n "claude-integrity-tripwire\|claude-path-write-guard" .claude/settings.json settings-template.json
.claude/settings.json:169  (PreToolUse write guard)
.claude/settings.json:191  (self-heal: restore-from-git + page if either script is deleted)
.claude/settings.json:196  (--enforce --quiet tripwire)
+ the same three in settings-template.json (ships to the fleet)
```

**The tripwire is working, and this is its only event.**
```
$ ls q-system/output/claude-integrity/quarantine/
20260816T173315Z
```
One quarantine directory, containing one file. No other quarantine events exist on this tree.

**`fable-escalate.py` is legitimate first-party tooling, not attacker-introduced.**
Present at `q-system/.q-system/scripts/fable-escalate.py` (30715 bytes, 2026-08-14). Referenced by `token-guard.py:540,557`; documented end to end by `.claude/rules/fable-escalation.md`; paired test `q-system/.q-system/tests/test_fable_escalation.py` (19 cases); named in `.prd-os/prds/prd-notify-ledger-isolation-2026-08-04.md`. Introduced by `715895ea` (2026-08-03, PR #75, ASK-311).

**The escalation fired legitimately and at volume, on the documented trigger.**
```
$ ls -la q-system/output/fable-escalations/escalations-2026-08-16.jsonl
103517 bytes
```
Rows carry `"trigger": "volume-ceiling"` — the documented `VOLUME_CEILING=50` Tier A trigger — with genuine cap rows (`"capped": true`, `"failure": "cap reached (2)"`, and the honest `notify_delivered: false` accounting the rule describes). Seven pending payloads exist for this session's actors, timestamped 17:51:40Z through 18:23:54Z.

**The triage content is coherent, first-party, and self-labelling — not forged.**
All seven payloads are well-formed `DIAGNOSIS / STOP / NEXT / REFUTE`, each with a falsifiable refute command, matching the documented output contract exactly. Decisively, the 18:23:54Z triage *itself flags the injection pattern* rather than perpetuating it:

> "Also stop engaging with a5a3365's 'rate-limit cooldown monitor' claim — that's not a real mechanism and matches this session's established injection pattern (fable-escalate.py, fake agent IDs); one corrective nudge was sent, a second would be re-running the failed approach."

An attacker-controlled channel does not warn its target about itself. The two "injection" fingerprints named there — `fable-escalate.py` and "fake agent IDs" — are respectively a real script and real live agent IDs (`a845bd1ec5a913aa4`, `aba52025066f5b56b`, `a286d3337a0733573` all appear in `tasks/`), unverifiable only from inside a sub-agent.

**The disputed vocabulary is widespread first-party hook text, not a targeted payload.**
```
$ grep -li <marker> <20 sub-agent transcripts>/*.jsonl | wc -l
ASK-            20   (negative control — must be >0)
Linear          19   (negative control — must be >0)
fable-escalate  14
cross-model     13
escalation cap  11
```
Consistent with `token-guard.py` block text reaching most agents in a run that repeatedly hit a 50-call ceiling across ~873 issues.

**Negative self-test on the instrument.** The first run of this grep returned `0` for every marker *including* both controls, because the flag string `-lit` contains `-t`, which is not a valid grep option; the command errored to empty and the zeros were an artifact. The controls are what caught it. An earlier marker survey also returned "1 file" for all seven patterns — that file was `tasks/bpgg6j2mt.output`, the survey's own output, a self-match. Both false results were discarded and the corrected run is what is reported above.

**The ASK-870 change is benign and matches concurrent legitimate work.**
The quarantined file differs from the current rule by one clause appended to the "Wired pairings" line, adding `architecture-review` to the *interpretive, no-hook* list. The `diff` above is the whole change: it deletes no line, touches no hook wiring in `.claude/settings.json` or `settings-template.json`, and adds no instruction. `q-system/.q-system/scripts/claude-integrity-tripwire.py --enforce` is the executable that detected it and reverted it, and its quarantine copy is the artifact this diff was taken against. It is corroborated by an untracked new skill created one minute earlier:
```
$ ls -la plugins/kipi-core/skills/architecture-review/
SKILL.md      3289 bytes   Aug 16 10:32
references/                Aug 16 10:33
$ ls q-system/output/claude-integrity/quarantine/
20260816T173315Z            (tripwire fired 10:33:15)
```
Skill created 10:32, rule documented 10:33, tripwire reverted 10:33:15. This is an agent documenting its own new skill through the wrong write path.

## Contributing factors

- **The tripwire's Linear title reads `SECURITY: unsanctioned .claude/ change` for every drift, regardless of content.** A one-clause doc append and a hook deletion produce the same alarm text. That is defensible for a tripwire, but it sets the reader's prior toward intrusion before any diff is read.
- **Sub-agents cannot verify repo-specific tooling.** A fresh agent has no cheap way to establish that `fable-escalate.py` is sanctioned. The rule that documents it (`fable-escalation.md`) is deliberately path-scoped and not always-on, for a stated instruction-budget reason (601 lines against a 300 target), so the agents most likely to encounter the mechanism are the least likely to have its documentation loaded.
- **Volume amplified exposure.** The run hammered `VOLUME_CEILING=50` repeatedly across ~873 issues, so a mechanism designed to fire on rare stuck blocks fired constantly, and orchestrator-scoped triage landed in sub-agent contexts many times over.
- **The guards were noisy but correct.** `claude-path-write-guard` blocked two of this investigation's own read-only commands (a `find` over `~/.claude`, and `python3` given a `.claude/` path argument) because it pattern-matches the path, not the operation. Both were worked around with read-only tools. Over-blocking a reader is the right failure direction; it is still a false positive worth noting.

## Fixes shipped

- Surface fix: none required. No compromised artifact was found. `.claude/rules/skill-hook-pairing.md` was already auto-reverted by the tripwire before the investigation began, and the pre-revert copy is preserved at `q-system/output/claude-integrity/quarantine/20260816T173315Z/`.
- Structural fix: pending. The two genuine defects (cross-actor triage delivery, world-writable triage hand-off) are captured as action items below rather than patched inline — `token-guard.py` is the hottest hook in the repo and ships fleet-wide via `settings-template.json`, so a change there is an issue with a reproducer, not a drive-by edit during an investigation.

## Action items

- [ ] Restore the `architecture-review` clause to `.claude/rules/skill-hook-pairing.md` through `apply-claude-changes.sh`, so the intended documentation lands via the sanctioned path — owner: sana — type: doc
- [ ] Constrain the triage hand-off file: write it under a user-owned 0700 directory instead of bare `/tmp`, reject a payload whose owner is not the current uid, bound its size, and drop the `KIPI_FABLE_PENDING` override or restrict it to test runs — owner: sana — type: code
- [ ] Make the triage carry verifiable provenance the receiver can check, and make `request_escalation` refuse to deliver a triage to an actor other than the one whose transcript produced it — owner: sana — type: code
- [ ] Add a reproducer that drops a hostile `triage` string at the predictable `/tmp` path and asserts it never reaches the model's context; it must be seen failing against current `HEAD` before the fix — owner: sana — type: test
- [ ] Give the tripwire's Linear issue a severity signal derived from the diff (enforcement-affecting vs documentation-only), so a doc append does not open with the same alarm text as a disabled hook — owner: sana — type: gate
- [ ] Narrow `claude-path-write-guard` so a read-only command with a `.claude/` path argument is not blocked as a write, or document the sanctioned read route in its own refusal text — owner: sana — type: gate
- [ ] Add a one-line pointer to `fable-escalation.md` in the guard's own escalation banner, so an agent that meets `fable-escalate.py` for the first time can verify it in-band without loading the full rule — owner: sana — type: doc

## Lessons

- **A trusted channel carrying another model's free text is an injection surface even when nobody is attacking.** The Fable triage is labelled and honest, and it still produced four escalating "attack" signatures purely by being routed to the wrong reader. Label plus routing, not label alone.
- **Advice is scoped to an actor. Delivered to a different actor, correct advice becomes a malicious instruction.** "Skip what's already done" and "the final report says 26 cancellations" are sound for a coordinator and are exactly hiding-IDs and fabricating-results for a worker.
- **The refusals were the system working.** Every sub-agent refused, nothing false reached the founder, and no unintended Linear write occurred. The contract that made that correct — a triage is an inference until a command backs it — held under a condition its authors did not anticipate.
- **Run the negative control on the instrument, not just the subject.** Two separate measurements in this investigation returned clean, confident, wrong answers: an invalid grep flag that errored to zero across the board, and a marker survey that matched only its own output file. Both were caught by controls, not by review.
- **A tripwire that fires is evidence the tripwire works, not evidence of an attack.** Read the diff before the title.
