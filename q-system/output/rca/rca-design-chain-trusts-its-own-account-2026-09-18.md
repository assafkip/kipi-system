# RCA: the design chain seals rounds its own readers rejected, and the same failure classes VoiceLoop already paid for are in its code

**Date:** 2026-09-18
**Trigger:** founder, after four drift incidents in one session (bdfc96a7) and six code gaps found reading `design-chain-gate.py`: "do a deeper RCA to see if all of these issues are related to each other in a different way", then cross-check every VoiceLoop RCA finding against the design chain.
**Surface-fix commit:** pending
**Structural-fix commit:** pending

## What happened

The design chain produced rounds the founder rejected while every gate was green. On
2026-09-17/18 it sealed three directions against 51 negative reader verdicts and 1
positive across 23 runs (source: `consulting/design-chain.json` `vision._why` and commit
`c268cc6a`). Ten separate gaps were found today. Read one at a time they look like ten
bugs. Read together they are two defects, and both were already diagnosed, fixed and
written into a lesson by VoiceLoop before the design chain was built.

## Surface symptom

Negative controls, run 2026-09-18 against the live gate on throwaway rounds
(`scratchpad/negctl/run.py`, floor tier: no `craft` or `vision` block in that config):

```
A seal: (0, 'sealed 1 page(s) in .../roundA')
C (control, no standard.json) seal: 2 (2 = refused)
B status-page (only a hand-written receipt): (0, 'COMPLETE')
```

Round A's `gate/icp-round.md` says all three readers would LEAVE and call him "a data
fixer". Its `checks/tripwire.txt` says `FAIL: 4 AI-default tells found`. Its
`checks/bio_gate.txt` says `BLOCKED`. Its `proof.md` is one character. Its critique is
27 lines of `N. yes`. It sealed. Control C proves the gate is alive: remove the one
file the gate actually reads and it refuses. Round B is a page with nothing but a
`receipts.json` typed by hand, and the passive gate (what the Stop hook and
`SendUserFile` call) reports it COMPLETE.

## Surface root cause

The ten gaps, each with where it lives:

| # | Gap | Where |
|---|-----|-------|
| S1 | Founder-named defects never tracked to closure (hero defect 2 of RULE-2026-09-18-C skipped) | no reader of decisions.md rulings or chat findings; `WEAK[tag]` only sees author-marked findings, `design-chain-gate.py:232-288` |
| S2 | A technique imitated from a copied file instead of loading the skill that makes it | `craft_problems` regex-matches the page, `:371`; nothing records that the named skill ran |
| S3 | A citation to a file never opened ("generalized from Sketch.astro's seam function") | reference check is a substring of NARRATIVE.md, `:422-426` |
| S4 | Briefs built from constraints with no statement of what the page is FOR | fixed by `c268cc6a` (vision stage), with the same presence-only scope, `:905-911` |
| C1 | Reader-gate verdicts never read | `gate/` only has to be non-empty, `:1029-1032` |
| C2 | bio_gate, voice-lint, tripwire results never read | `checks/` only has to be non-empty, `:1029-1032` |
| C3 | impeccable report only has to be non-empty | `:463-470` |
| C4 | `proof.md` never validated | existence only, `:1026-1028` |
| C5 | Critique counts numbered lines, not answers | `:1060-1067` |
| C6 | Copied brief caught only on a byte-identical copy | `:205-229` |

Found while proving them, and not on the list before today:

| # | Gap | Where |
|---|-----|-------|
| C7 | `receipts.json`, `standard.json` and `gap.json` are trusted by whoever wrote them | `sealed_and_unedited` `:474-488`, standard check `:1069-1082`; round B above |
| C8 | A malformed `exemplars.json` silently turns the whole-set check off | `except ValueError: named = []`, `:400-404` |
| C9 | The repo where the site is built runs no design-chain hook | `consulting/.claude/settings.json` references `design-chain-gate` 0 times; commit `39745a0f` says the hooks invoke it |
| C10 | Two copies of `/design-chain`; the plugin copy has no vision stage | `plugins/kipi-core/commands/design-chain.md`: 0 mentions of VISION; the kipi marketplace clone has no copy |

## Structural root cause

### Root cause #1: the gate verifies the builder's account of the work, not the work

`type: implicit-contract`

This is the relation between the ten. Sort every check by WHO produced the thing it
reads:

| The gate computes it itself, at check time | The gate reads a file and trusts its author |
|---|---|
| brief quotes each owner anchor, read LIVE from the owner file | `standard.json` pass flag |
| technique fingerprint present in the page bytes | `gap.json` below-floor list |
| page sha matches the sha in a receipt | `receipts.json` (round B) |
| brief quotes a VISION.md line | `checks/*`, `gate/*`, `impeccable.txt` (non-empty only) |
| | `proof.md`, critique answers, `WEAK` dispositions, `REVIEWED BY FOUNDER`, `Founder, <date>:` markers, `reference` strings |

The left column holds. Every incident today sits in the right column. S1, S2, S3, S4,
C4, C5 and C6 read something the same agent wrote about its own work. C1, C2, C3 and C7
read a file that SHOULD come from an outside producer (a script, a model reader) and
never check that it did or what it said.

The gate's docstring states the contract it depends on: "`seal` runs the ENTIRE chain
before it writes a receipt, so a fresh receipt is the evidence that the chain ran."
Nothing makes a receipt only writable by `seal`. The contract is true only while the
agent it constrains chooses to keep it.

### Root cause #2: the only outside judges are collected and filed, never read

`type: missing-test`

Three things in the chain are not the builder: the lint scripts in `checks/`, the model
readers in `gate/`, and the founder's rulings in `decisions.md`. The gate requires all
three to EXIST and reads none of their verdicts. The reader gate is the one instrument
that measured what the founder later said (51 negatives against 1), and the seal
ignored it. The test suite encodes this as correct behaviour: 10 lines in
`test_design_chain_gate.py` write `"ok\n"`, `"answers\n"` or `"ran\n"` into those
files, so the suite's passing chain is built on hand-typed verdicts.

### Root cause #3: the judge of "is this good" sits after the seal

`type: process`

The Sep 15 bland RCA named it (root cause #5): the founder's eye is the bar and it
arrives after a full round. Today's vision stage moved the founder's words to the
FRONT of the chain. Nothing moved his verdict, or the readers' verdict, INTO the seal.
So the loop is still one rejection per sealed round.

### Root cause #4: the lesson existed, was loaded, and was not applied at build time

`type: process`

`q-system/lessons/bind-a-check-to-the-property-not-the-nearest-proxy.md` is dated
2026-09-14, distilled from VoiceLoop's `rca-checks-bound-to-a-proxy-not-the-property-2026-09-09.md`.
The design-chain gate was built 2026-09-15 and contains all three of that lesson's
causes: proxy checks (C1-C7), hand-typed producer output in tests (root cause #2), and
no floor on partial input (one exemplar cited satisfies the directions check, `:1057`).
The config itself cites `a-defect-absence-gate-is-a-floor-not-a-finish-line.md` and the
fix it chose, a self-authored craft manifest, fell back into the same class. Lesson
retrieval now exists (`lessons-inject`). Retrieval is not application.

### Root cause #5: RCA action items have no closure, so a diagnosed class stays open

`type: process`

`rca-design-chain-passes-bland-2026-09-15.md`: 9 open, 0 closed. At least two of those
shipped (`require_gap_check`; `standard` derived by `design-standard-from-exemplars.py`),
so the boxes are wrong in both directions. Still unbuilt: measurements injected at build
time, fingerprints that carry a count, the tenth critique question (`NINE_QUESTIONS = 9`).
`rca-design-chain-gate-blocks-its-own-steps-2026-09-15.md`: 3 open, 2 closed; one open
item is fleet propagation, and C9 is that item, still open.

### Root cause #6: enforcement lives where the work is not

`type: config`

The gate runs when a session starts in kipi-system and scans instance roots. A session
started in consulting, where `site/design/` lives, has no hook calling it (C9). The
scripts were copied into consulting by hand today and the commit says the next sync is
expected to overwrite them. The command exists in two copies and only the project copy
has the vision stage (C10).

## VoiceLoop findings that exist in the design chain

Every VoiceLoop RCA in `consulting/q-system/output/rca/` that mentions voice (11,
counted by `grep -li voice | wc -l`) plus kipi-system's `rca-verify-only-ran-the-sync-2026-09-06.md`.

| VoiceLoop finding (RCA, cause) | In the design chain? | Evidence |
|---|---|---|
| Executable bound to a proxy, the property lives only in prose (09-09 RC1) | YES, the core of it | C1-C7; negative-control round A |
| No test reaches a real producer; every answer is hand-typed (09-09 RC2) | YES | 10 hand-typed `checks`/`gate` lines in `test_design_chain_gate.py` |
| An identifier written in prose never checked against its ledger (09-09 RC4) | YES | S3 (cited file never opened); `proof.md` cites INDEX records nothing checks |
| Partial failure has no floor (09-09 RC3) | PARTLY | one exemplar of N cited passes `:1057`; any one VISION line passes `:961` |
| Receipt cannot say "not checked" (08-31 RC4) | YES | craft and vision return `[]` when not adopted; `receipts.json` records sha and time only; round A's receipt is indistinguishable from a full-bar round |
| The real fix assigned to "process, every caller" (08-31 RC5) | YES | command: "Two things the gate cannot see and this command makes you do anyway"; step 9 "Read them... fix" |
| Broad except turns a defect into a silent skip (08-11 RC2) | YES | C8, `:400-404` |
| Warn-mode ships (08-11 RC4) | YES, documented | impeccable browser engine missing exits 0 (command step 8) |
| Fix landed in a copy the runtime does not load / a sync reverts it (08-11 RC1, 08-06) | YES | C10; consulting's scripts are a hand copy the next sync owns |
| The sanctioned lane is reachable only one way; the path he uses is least checked (08-19 RC2, 08-26) | YES | C9: consulting sessions are ungated |
| RCA action items have no closure mechanism (08-19 RC5) | YES | root cause #5 |
| The job is specified nowhere; defect gates certify absence (08-12 RC1, RC4) | YES, recurred a month later | vision stage `c268cc6a` is the 08-12 job-spec fix, re-derived for design |
| "Done" measured on the pipe, not the surface he sees (09-06 RC1) | YES | seal covers round pages; the deploy ships a different build (17f: the phone drawing sealed in the round never reached the page, `site/DEPLOY.md`) |
| Lessons exist but nothing applies them at build time (08-27 RC1, RC2) | PARTLY | retrieval fixed by `lessons-inject`; application not (root cause #4) |
| A gate refuses the corpus it encodes (08-26 RC1, RC2) | NO, handled | `standard._derived.notes` keeps `min_body_px` above most exemplars on purpose, with a written reason |
| A "skip" written as a zero loop bound; a script carrying the bypass (09-06 verify-only) | NO | not found in the gate |
| Whole-run refusal on output shape (09-11) | NO | not found |

## Verification

Ran `python3 scratchpad/negctl/run.py`, got the three lines under Surface symptom:
round A sealed (exit 0), control C refused (exit 2), round B COMPLETE. That verifies the
DIAGNOSIS of C1, C2, C4, C5 and C7 at the floor tier. C3 and the `gap.json` half of C7
come from reading `:438-470`, not from a run; the craft tier was not exercised.

Ran `grep -c "design-chain" consulting/.claude/settings.json`, got `0` (C9). Ran
`grep -c VISION plugins/kipi-core/commands/design-chain.md`, got `0` (C10). Ran
`grep -c '^- \[ \]'` / `'^- \[x\]'` on both Sep 15 RCAs, got 9/0 and 3/2 (root cause #5).

No fix is verified. Nothing has shipped.

## Contributing factors

- VoiceLoop's standing warning applies here and cuts the other way: "the reflex after a
  miss is to add a gate" (08-19). Every item below re-binds or deletes an existing
  check; none adds a sixteenth.
- The honest-boundary docstrings are accurate and did not help. `vision_problems` says
  it "cannot see whether the vision is any good". Stating a hole is not closing it, the
  same finding as 08-26's corrected RCA.
- The gate has grown by adding a new file-presence check per incident. A new check that
  reads a self-authored file is one more instance of root cause #1.

## Fixes shipped

- Surface fix: none.
- Structural fix: none.

## Action items

- [ ] `seal` stops reading verdict files and produces them: it runs `design-standard-check.py`, `design-gap-check.py` and `design-impeccable-check.py` itself and records their exit codes, so `standard.json`, `gap.json` and `impeccable.txt` stop being trusted inputs (C3, C7) — owner: sana — type: code
- [ ] `seal` parses the reader-gate `.jsonl` and refuses while any reader would leave or names him narrowly, unless a founder disposition answers that reader by id (C1) — owner: sana — type: gate
- [ ] `seal` reads the exit status of bio_gate, voice-lint and tripwire from a runner it invokes, not from text files (C2) — owner: sana — type: code
- [ ] A citation in `craft-manifest.json` or `proof.md` that names a repo file must have been opened this session; port `code_claim_grounding_guard.py`'s check-one, which already does this for chat claims (S3, C4) — owner: sana — type: code
- [ ] Decide whether receipts must be unforgeable or only non-accidental, and encode the answer; today round B passes on a typed file (C7) — owner: sana — type: code
- [ ] `receipts.json` records which stages ran (craft, vision, gap, readers), so a floor-only seal is distinguishable from a full-bar seal (08-31 RC4) — owner: sana — type: code
- [ ] `exemplars.json` that does not parse is a refusal, not an empty roster (C8) — owner: sana — type: code
- [ ] Replace the 10 hand-typed verdict lines in `test_design_chain_gate.py` with captured real outputs carrying provenance, plus round A as a permanent negative control that must never seal (09-09 RC2) — owner: sana — type: test
- [ ] Wire the gate into `consulting/.claude/settings.json` through the sync, not a hand copy, and prove it with a session started in consulting (C9) — owner: sana — type: gate
- [ ] One source for `/design-chain`: delete the stale copy or sync it, with a check that the two cannot drift (C10) — owner: sana — type: code
- [ ] Close or void every box in both Sep 15 RCAs against the code as it is today (root cause #5) — owner: sana — type: process
- [ ] Delete checks that can only ever read self-authored text (critique line count C5, byte-copy brief C6) OR re-bind them to something the builder did not write; do not keep them as green decoration — owner: sana — type: code

## Lessons

- A gate that reads a file its subject wrote is a gate its subject passes. Sort checks by
  who produced the input; only checks the gate computes itself hold.
- Collecting an outside verdict and not reading it is worse than not collecting it: it
  looks like coverage. The reader gate saw the 51 negatives and the seal did not ask.
- VoiceLoop paid for these classes between 08-06 and 09-11 and wrote the lesson on 09-14.
  The design chain was built 09-15 and re-paid for all of them. The next gate built in
  this fleet runs the VoiceLoop table above against itself before it ships.
