---
description: Run one design round through the design chain: read the canon, brief with verbatim anchors, three directions, build once per candidate stack, measure against the standard, critique, proof, checks, ICP gate, seal. Nothing is shown to the founder before the seal.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, SendUserFile
---

Run one design round through the design chain.

Usage: `/design-chain [project] [round]`

- `project`: the site being designed, by NAME (`askconsulting`), never by path.
  Resolved from the `project` field of a `design-chain.json` under any root in
  `instance-registry.json`. With no argument: the nearest `design-chain.json`
  above the current directory; if none, list the known project names and stop.
- `round`: optional. Default is today's date (`2026-09-16`, then `2026-09-16b`).
  The founder never has to remember round names.

## Why this command exists

Founder, 2026-09-15: "When I try to create web design, you continuously find ways
to go back to your generic stuff. If it's not reading the prose, ignoring the
prose, or going around it." The design-chain gate
(`q-system/.q-system/scripts/design-chain-gate.py`) blocks screenshots, sends,
publishes and the end of the turn until a page's chain is complete. This command
is the path THROUGH the gate, in order. Skipping a step does not save time; the
gate returns you to it.

Two things the gate cannot see and this command makes you do anyway: think from
the reader and the one idea (design-dna.md sections 2 to 4), and produce three
genuinely different directions before touching HTML (design-dna.md section 8).

## Step 0: locate the round

```bash
python3 - "$ARGUMENTS" <<'EOF'
import json, os, pathlib, sys
want = (sys.argv[1].split() + [""])[0].lower()
reg = pathlib.Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")) / "instance-registry.json"
roots = [pathlib.Path(i["path"]) for i in json.load(open(reg))["instances"]] if reg.is_file() else []
found = {}
for r in roots:
    c = r / "design-chain.json"
    if c.is_file():
        try: found[json.load(open(c)).get("project", r.name).lower()] = r
        except ValueError: pass
if want and want in found: print(found[want]); sys.exit()
if want: print("UNKNOWN project %r. Known: %s" % (want, ", ".join(sorted(found)) or "none")); sys.exit(2)
d = pathlib.Path.cwd()
while d != d.parent and not (d / "design-chain.json").is_file(): d = d.parent
print(d if (d / "design-chain.json").is_file() else "NO project given and none above cwd. Known: %s" % ", ".join(sorted(found)))
EOF
```

The round lives at `<root>/site/design/<round-name>/`, where `<round-name>` is
the second argument if given, else today's date with a letter suffix if the date is
taken. The printed path is `<root>`; if it starts with UNKNOWN or NO, stop and say so.
Create the round directory. Every page,
receipt and screenshot of this round goes in there and nowhere else.

## Step 1: read the owners, in full, this session

Read, with the Read tool, every file listed under `owners` in
`<root>/design-chain.json`, plus `design-dna.md` and `site-design.md` in full.
Then read the previous round's `critique.md` and `standard.json` if a previous
round exists, and every file in `<root>/site/design/exemplars/`.

Do not summarize them into context from memory. The brief in step 2 has to quote
them, and the gate compares the quotes against the live files.

## Step 2: brief.md

Write `<round>/brief.md` with:

1. **The reader** (three lines: who, what went wrong in their week, what they
   need to feel in the first screen), derived from design-dna.md section 2.
2. **The pain family this round leads with**, in the buyer's own words from
   `config/segment-pain-model.json` or the site brief, with the source named.
3. **The one thing this screen says**, one line.
4. **The anchors, verbatim.** Every anchor line the config names, copied exactly
   from the live owner file. Run `python3 <kipi-system>/q-system/.q-system/scripts/design-chain-gate.py status <round>`
   after writing; it lists any anchor the brief does not quote.

## Step 3: directions.md

Three directions, each under its own heading, each argued from the one idea
(design-dna.md section 4: what the idea generates for layout, type, colour,
imagery, motion, copy). For each: the composition in two lines, the artifact it
shows and which proof kind it is (section 4b), what it would look like on a
phone. If `exemplars/` holds files, cite the one each direction builds on or
departs from, by filename, and say what changes.

A direction that could belong to another consultant's page is not a direction.

## Step 3b: craft-manifest.json (the BAR; everything else here is a FLOOR)

Every other check in this command is defect-ABSENCE: missing files, unquoted anchors,
word counts, type sizes, AI-default tells. None of them can see craft. On 2026-09-15 a
round cleared all of them and shipped three wireframes, measured at 0 image assets, 0
background images and 0 animated elements. That failure was already written down:
`q-system/lessons/a-defect-absence-gate-is-a-floor-not-a-finish-line.md`, distilled from
`cole-gtm/q-system/output/rca/rca-design-room-skipped-premium-tools-2026-06-25.md`. Its
four causes: a floor-detector became the definition of done; grounding enforced
provenance, not ambition; the direction was resolved at concept level with no execution
tier, so the premium and the cheap realization were equally compliant; effort-economy ran
downhill to the cheapest passing artifact.

Before building, write `<round>/craft-manifest.json`. Shape is cole-gtm's
`steal-manifest.json`, one entry per technique:

```json
{"techniques": [{"id": "mismatch-reveal",
  "technique": "what it is and which reference it comes from",
  "role": "the mismatch", "reference": "...",
  "pages": ["Clock-html-laptop.html"],
  "import": ["gsap"], "applied": ["ScrollTrigger"]}]}
```

`import` and `applied` are case-SENSITIVE regexes checked against the built page with HTML
and block comments stripped, so a fingerprint surviving only in commented-out code does
not count. The gate BLOCKS when a declared technique is absent. A manifest that declares
nothing is itself a gap: declaring nothing must not be the cheapest way to comply.
`pages` is optional and scopes a technique to the pages that should carry it.

The tier comes from `design-chain.json` `craft.tier`. `craft` is the default and is
required for anything the founder compares or that reaches a visitor. `wireframe` is
legitimate only for a copy test and must be DECLARED; an undeclared tier is the required
one, so silence is never the cheap path.

This check never certifies a page. Green means "not a wireframe". The founder's eye and
five real buyer conversations are the bar (`site-design.md` section 8).

## Step 4: build, once per candidate stack

`site-design.md` section 10: the stack is not chosen; the agreed design is built
once per candidate stack and the founder compares working versions. Build each
direction as plain HTML first (fast to compare), then the picked direction in
Astro and Next.js when the founder has picked. Pages go in the round directory,
named `<direction>-<stack>-<viewport>.html`. Real artifacts only: a run log with
its clock, a findings folder, a measured before and after. Sample data is
labelled sample. No stock imagery, no generated scenes standing in for work.

Word budget and type sizes come from `design-chain.json` `standard`, not from
memory. Read them before writing the first tag.

## Step 5: measure

Serve the round directory and run the standard check on every page:

```bash
(python3 -m http.server 8793 --directory <round> >/dev/null 2>&1 &)
python3 <kipi-system>/q-system/.q-system/scripts/design-standard-check.py <round>/<page>.html --url http://127.0.0.1:8793/<page>.html
```

A FAIL is a design fault, not a threshold to argue with. Fix the page and rerun
until every page passes. The check writes `standard.json` with the page hash.

## Step 6: critique.md

The nine questions from design-dna.md section 7, answered per direction, numbered
1 to 9 under each direction's heading. Question 9 ("what did I choose because it
was the default") names at least three concrete choices per direction. Say which
answers are weak. Revise the page if an answer is weak, then rerun step 5.

## Step 7: proof.md

For every artifact on every page: the proof kind (problem, capability,
reliability, outcome, pedigree) and the record it comes from
(`q-consult/output/proof-audit/INDEX.md` or the compression audit), with the
confidence label the record carries.

## Step 8: checks/

Run and save into `<round>/checks/`:
- `bio_gate` on every line of copy that mentions an employer (consulting:
  `python3 -c` against `q-consult/pipeline/bio_gate.py`), output to `bio_gate.txt`.
- voice-lint on the copy, output to `voice-lint.txt`.
- The kipi-design tripwire (`plugins/kipi-design/hooks/dogfood_gate.py`) on each
  page, output to `tripwire.txt`.

Run the impeccable step with the script, not by hand. It is required by the gate
(`craft.require_impeccable`) and it writes `checks/impeccable.txt` itself:

```bash
python3 <kipi-system>/q-system/.q-system/scripts/design-impeccable-check.py <round>
```

It runs a known-slop control in the same invocation, because a clean report whose control
never fired is decoration, and it records WHICH ENGINE ran. impeccable has two: a static
HTML parse, and a real browser via URL that resolves computed styles. The browser engine
needs puppeteer, which is installed nowhere in this fleet as of 2026-09-15, and the
detector exits 0 when it is missing rather than failing, so that gap is invisible to a
caller reading exit codes. The receipt prints it under "WHAT THIS RUN COULD NOT SEE".


Run and save into `<round>/checks/`:
- `bio_gate` on every line of copy that mentions an employer (consulting:
  `python3 -c` against `q-consult/pipeline/bio_gate.py`), output to `bio_gate.txt`.
- voice-lint on the copy, output to `voice-lint.txt`.
- The kipi-design tripwire (`plugins/kipi-design/hooks/dogfood_gate.py`) on each
  page, output to `tripwire.txt`.

## Step 9: gate/

Screenshot each page (the round's own shoot script, or `shoot.py` in the previous
round adapted), then run the ICP-persona comprehension gate:

```bash
python3 <root>/q-consult/output/comprehension/gate_icp.py <round> <page>.png ... --n 3
```

Move its `.md` and `.jsonl` outputs into `<round>/gate/`. Read them. Any reader
who would leave, or who calls him something narrow (a repair shop, a data
fixer), is a copy finding; fix, rerun from step 5.

## Step 10: seal, then show

```bash
python3 <kipi-system>/q-system/.q-system/scripts/design-chain-gate.py seal <round>
```

Only after `sealed N page(s)` may a screenshot be sent with SendUserFile. Send
the laptop screens, one caption each: direction, pain family, artifact, and the
two or three gate findings that survived. Then stop and let the founder pick.
The founder's pick, with his reason, goes into `site-design.md`'s Decision log
and the picked screen into `exemplars/` under a dated name.

## What this command does not do

It does not choose for the founder, does not skip a step because the round is
"small", and does not send anything before the seal. If the gate blocks a step,
the block message names what is missing; do that, do not route around it.
