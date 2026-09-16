# RCA: a round passed every gate in the design chain and the founder's first word for it was "bland"

**Date:** 2026-09-15
**Trigger:** Founder, on the sealed round 2026-09-15f: "It is not doing it for me. It's very bland and I'm not seeing how it's similar at all to any of the examples."
**Surface-fix commit:** pending
**Structural-fix commit:** pending

## What happened

Round 2026-09-15f was built, measured, critiqued, proofed, read by twelve fresh model
readers and sealed. Every gate the design chain owns returned clean: 8 of 8 pages passed
`design-standard-check.py`, the impeccable browser detector found 0 anti-patterns while its
known-slop control found 6, `check_technique_parity.py` found 0 gaps against 9 declared
techniques, the kipi-design tripwire found 0 tells while its control fired 4, `bio_gate`
flagged 0 lines with 4 negative controls firing, `voice-lint` had 0 blocking violations,
and `canon-audit.py` reported 0 failing clause-page pairs out of 88.

The founder then looked at it and said it is bland and does not resemble the six exemplars
he supplied. He is right, and it is measurable: on 7 of 13 axes the round sits below a
quarter of the exemplar median. This is the seventh round in a row to drift the same way.

## Surface symptom

`site/design/2026-09-15f/gap-to-exemplars.py`, running the identical probe that captured
the exemplars, against the same 1440x900 fold:

```
axis                              their median    their range               mine
distinct background colours                  6         3 to 6                  0
buttons in the fold                         10       7 to 127                  1
transitioned elements                       41      18 to 211                  2
svg elements in the fold                    11        5 to 64             1 to 2
images in the fold                           4        0 to 20                  0
distinct radii                               5         2 to 5                  1
shadows                                      2         0 to 4                  0
```

Zero background colours is the single most explanatory number. Every exemplar builds its
fold out of coloured fields; the round is one flat grey rectangle with text in the middle
of it. One button against their median of ten is the second: the round has no navigation,
no logo and no footer, so it is a slide rather than a page.

## Surface root cause

`references/NARRATIVE.md` section 3 says, in the build's own words: "The group is
essentially flat. **Depth comes from colour fields and layering**, not from drop shadows."

The build read the first half of that sentence and implemented "flat" as "no colour", and
never implemented the second half. Zero colour fields were built. The sentence that named
the defect was written by the same process, three steps earlier, and no executable compared
the built page to it.

## Structural root cause

### Root cause #1: every mechanical gate in the chain is a defect-ABSENCE check, and a bland page has no defects

`type: missing-test`

A defect-absence detector returns clean for a page with nothing wrong and nothing right.
This was already the corpus lesson `a-defect-absence-gate-is-a-floor-not-a-finish-line.md`,
and the craft manifest was the fix for it. The fix did not hold, because the manifest is
authored by the same process it constrains: I choose which techniques to declare, so the
bar is set by the thing being measured.

Proven rather than argued. A deliberately bland control page was built with no artifact, no
SVG, no colour, no motion and four lines of text, and run through the chain's three
independent mechanical gates:

```
design-standard-check.py   bland-control.html: PASS
dogfood_gate.py tripwire   exit=0
impeccable (browser)       (no output)   control fired: True; browser engine: True
```

All three pass it. The impeccable run's own control fired in the same execution, so this is
not a dead engine reporting silence. **Three of the four mechanical gates in the chain
cannot distinguish a deliberately bland page from a crafted one, and the fourth is
self-authored.**

### Root cause #2: the exemplar measurements existed and no executable compared anything to them

`type: missing-test`

`references/MEASUREMENTS.md` and five per-site JSON captures hold real numbers at
1440x900 for exactly the axes the round is off on. The chain's grounding check
(`craft.require_grounding`) reads them not at all. What it actually asserts is that a
technique's `reference` string appears as a SUBSTRING somewhere in `NARRATIVE.md`, and that
every exemplar URL appears in the narrative.

That is provenance, not proximity. A technique may cite `stripe.com`, pass the grounding
check, and be realized at 2% of stripe.com's measured value on the axis it claims. That is
what happened nine times in one manifest.

The comparison that catches this is 60 lines of Python and was written AFTER the founder's
reaction, not before it.

### Root cause #3: the coded standard and the measured exemplars contradict each other, and the coded one wins every time

`type: config`

`design-chain.json` `standard` is a blocking gate. `NARRATIVE.md` is prose. Where they
disagree, the hook wins and the prose loses, silently, every round:

```
                        standard (coded, blocks)     exemplar median (prose, advisory)
type sizes in the fold  3 max                        6
large elements          2 max                        (not capped; notion runs 96px display)
elements on the signal  2 max                        6 distinct background colours
words in the fold       80 max                       (not capped)
```

A page cannot satisfy both. Passing the coded floor **guarantees** the page is sparser than
every exemplar in the set, on the exact axes the founder reacted to. The gate written to
prevent slop is actively enforcing blandness, and it has done so for seven rounds.

This is the most actionable cause: the numbers in `standard` were hand-written from
`site-design.md` section 6 (NN/g's "no more than 3 type sizes and 2 large elements in a
view") before the exemplars were ever captured, and were never reconciled when the
measurements arrived.

### Root cause #4: the canon is read at step 1 and the visual decisions are made at step 4, with nothing re-injecting it in between

`type: process`

The chain reads five owner files and a narrative in step 1, then writes a brief, then three
directions, then builds. By the time a colour or a radius is chosen, the measurements are
forty-plus tool calls back in the context. The brief quotes the canon's SENTENCES because a
check requires it; nothing puts the canon's NUMBERS in front of the build at the moment a
number is chosen.

This exact class is already solved elsewhere in this repo. `knowledge-inject.py` puts the
instance's own facts, with path, line and a FULL/PARTIAL coverage verdict, in front of the
model before it reasons, precisely because "retrieval quality as a property of the transient
session is the thesis violation the whole repo is built against." The design chain has no
equivalent and relies on the transient session.

### Root cause #5: the only instrument for "is this good" arrives after the whole round is sealed

`type: process`

`design-chain.json` says so in its own words: "Nothing in this block certifies a page is
good. Green here means 'not a wireframe'. The founder's eye and five real buyer
conversations are the bar." The chain then requires a complete round, ten steps, four
directions, eight pages and twelve model readers before that bar is applied once.

The feedback loop is therefore one founder reaction per full round. That is what
"unmanageable" names, and it is a structural property of the chain's ordering, not a
failure of effort. Seven rounds have each cost a full build to learn one thing.

### Root cause #6: "first screen" was never defined as a page

`type: implicit-contract`

Every exemplar capture includes that site's navigation in the fold. The round's pages have
no header, no logo, no nav and no footer, because "first screen" was read as "the hero
block". No check requires a page to be a page, so eight pages with no identity on them
passed everything. The one-button-against-ten number is mostly this.

## Verification

The bland-control experiment is the verification that the diagnosis is real, run before any
fix:

```
$ python3 design-standard-check.py bland-control.html --url http://127.0.0.1:8794/bland-control.html
bland-control.html: PASS

$ printf '{"tool_name":"Write","tool_input":{"file_path":".../bland-control.html"}}' | python3 dogfood_gate.py
exit=0

$ python3 design-impeccable-check.py . --url-base http://127.0.0.1:8794
--- bland-control.html
    engine: browser (URL, computed styles resolved)
    (no output)
control fired: True; browser engine: True
```

The gap measurement is the verification that the founder's reaction is a number and not a
mood:

```
$ python3 site/design/2026-09-15f/gap-to-exemplars.py
AXES WHERE MINE IS UNDER A QUARTER OF THEIR MEDIAN:
  svg elements in the fold: they 11, mine 2
  images in the fold: they 4, mine 0
  transitioned elements: they 41, mine 2
  distinct background colours: they 6, mine 0
  shadows: they 2, mine 0
  distinct radii: they 5, mine 1
  buttons in the fold: they 10, mine 1
```

No structural fix is verified yet. Every action item below is open.

## Contributing factors

- **The craft manifest's fingerprints are presence checks, not magnitude checks.** A
  declared technique passes on one matching regex. `border-radius:6px` appearing once
  satisfies "controls at 4 to 8px, the group has two tiers"; the group has five distinct
  radii and the page has one.
- **The narrative is regenerated by hand and the measurements by script, and only the
  script's output is trustworthy.** `NARRATIVE.md`'s section 3 sentence was correct and
  ignored. Prose that no executable reads is a suggestion.
- **`canon-audit.py`, written this session, is itself all absence checks.** It reports 0
  failing pairs on the bland round. It is a real improvement on nothing and it does not
  close this class.
- **The nine critique questions are answered by the author.** Question 5 ("what here is
  decoration") is not the question that would have caught this; the question that would
  have caught it is "what is on their page that is not on mine", and it is not asked.
- **Every round's evidence of craft is the artifact, and the artifact is always a
  measurement drawing.** Two grey rectangles and a blue one is the maximum craft that shape
  permits, which is why more effort produced no more richness.

## Fixes shipped

- Surface fix: none yet. The round stands as sealed and measured, with
  `gap-to-exemplars.py` committed beside it so the numbers are reproducible.
- Structural fix: pending, per the action items below.

## Action items

- [ ] Add `gap-to-exemplars.py` to the chain as a BLOCKING step between build and seal, with per-axis floors derived from the captured exemplars rather than hand-written — owner: Sana — type: gate
- [ ] Regenerate `design-chain.json` `standard` FROM `MEASUREMENTS.md` with a script, so the floor cannot contradict the group; keep any hand override but make it carry a written reason — owner: Sana — type: code
- [ ] Add the bland-control page to the chain's test corpus as a permanent negative control: if it ever seals, the chain has stopped being able to see craft — owner: Sana — type: test
- [ ] Port `knowledge-inject.py`'s shape to the build step: a hook that, on a Write to a round page, injects the measured exemplar values for the axes that page touches, with file and line — owner: Sana — type: gate
- [ ] Port `miyo-research-gate.py`'s shape: block a build Write when the session has not read `MEASUREMENTS.md`, fail-open, with a kill switch — owner: Sana — type: gate
- [ ] Require a page to be a page: header, nav, footer, or an explicit round-local declaration that this is a fold-only mock with a reason — owner: Sana — type: gate
- [ ] Change the chain's ordering so the founder sees ONE richly built direction before three more are built, replacing four-thin-then-seal with one-rich-then-compare — owner: founder decision — type: process
- [ ] Make craft-manifest fingerprints carry a COUNT or a range, not just presence, so "two radius tiers" cannot be satisfied by one radius — owner: Sana — type: code
- [ ] Add "what is on their page that is not on mine" as a tenth critique question, answered against the gap table rather than from memory — owner: Sana — type: doc

## Lessons

- A gate that can only detect defects will pass a page that has no defects and no qualities.
  Adding more absence-detectors, which is what six rounds of this chain did, cannot close
  that gap; the missing instrument is a DISTANCE to a target, and the target has to be
  measured numbers rather than cited prose.
- When a coded gate and a prose canon disagree, the coded gate wins silently and forever.
  `standard` capped type sizes at 3 while the measured group runs 6, for seven rounds, and
  no one noticed because the contradiction lived across two files and only one of them
  executes.
- Grounding that checks a citation is provenance. Grounding that checks a number is
  proximity. This chain had the first and called it the second.
- The canon read at step 1 is not in the room at step 4. `knowledge-inject.py` exists in
  this repo because that is a known failure mode, and the design chain was built without it.
- The cheapest diagnostic for "can this gate see quality" is to build the blandest thing
  that passes it. It took ten minutes and it settled a question six rounds of argument did
  not.
