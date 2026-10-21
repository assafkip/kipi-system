---
description: Run one design round through the design chain: vision, owners, brief with verbatim anchors, three directions, craft manifest, build, measure, critique, proof, checks, readers, seal. Nothing is shown before the seal.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Skill, SendUserFile
---

Run one design round. Usage: `/design-chain [project] [round]`.

`project` is a NAME, never a path: the `project` field of a `design-chain.json` under a root in
`instance-registry.json` (today: `askconsulting`). `round` defaults to today's date, with a letter
suffix if that folder exists (`2026-09-19b`). The founder does not remember round numbers.

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
print("NO project given. Known: %s" % ", ".join(sorted(found)))
EOF
```

UNKNOWN or NO: stop and say so.

## What holds each step

Every step below names the executable that checks it. `design-chain-gate.py seal <round>` runs the
producers itself and then the whole chain; nothing here is enforced by this document. Where a step
says a gate function, that function is in `design-chain-gate.py` and has its own test under
`q-system/.q-system/scripts/test/`.

## Step 0: the vision comes before the brief

Say what the page is trying to BE, in the founder's own words, before any constraint. Held by
`vision_problems()`: with a `vision` block in the config, `VISION.md` exists, carries the founder's
quoted lines, `brief.md` quotes one of them verbatim, and a declared component has a spec marked
reviewed. Scar: three sealed directions, all wrong, every one assembled from constraints.

## Step 1: read the owners, in full, this session

Read every owner file the config names, whole. Held by `brief_read_problems()`: when the config asks
for a fresh brief, the hook writes `brief-reads.json` from this session's transcript, and the seal
refuses a brief whose owners were not read in full, or a record copied from another round.

## Step 2: brief.md

Quote the owner anchors verbatim. Held by `chain_problems()`, whose anchor check reads the owner
files live and refuses a paraphrase.

## Step 3: directions.md

Three directions, or one when the round BUILDS a pick (`implements` in `craft-manifest.json`, which
must name a sealed round with three). Cite the exemplars: `chain_problems()` requires the configured
floor, all of them up to three.

## Step 3b: craft-manifest.json

The bar, not the floor. Techniques with their references; an `engine` credit needs a recorded run
(`engine_problems()`, fed by `design-engine-door.py`). Every repo file a technique cites must have
been opened this session (`citation_problems()`). `lane` is optional and must agree with the rounds
folder the instance config maps (`round_lane()`); the lane decides which web-only stages apply.

## Step 4: build, once per candidate stack

Build the page. Design skills are ENGINES: call them through this round and the door records each
run in `engines.jsonl`. Called outside a round, `design-engine-door.py` refuses and names this
command.

## Step 5: measure

`design-standard-check.py` measures the page against the standard, `design-gap-check.py` against the
exemplar captures, `design-impeccable-check.py` for anti-patterns. Do not write their verdicts by
hand: `seal` runs all three itself, writes `standard.json` and records the `standard`, `gap` and
`impeccable` stages with their exit codes (`receipt_problems()` reads them back). A non-site lane records them not applicable instead.

## Step 6: critique.md

The nine DNA questions per direction, answered. Mark every weakness `WEAK[tag]` and answer each with
a disposition line; a founder finding is `FOUNDER-FINDING[tag]` and needs one too
(`disposition_problems()`, `founder_finding_problems()`).

## Step 7: proof.md

One block per artifact, each naming a proof kind from the closed list and a record the proof index
holds (`proof_problems()`).

## Step 8: checks/

The declared checks run at seal, per page, from the config's `checks` list (`check:tripwire` today,
`declared_checks()`). A check that skipped is not a pass. `gap.json` and `impeccable.txt` are written
by the seal, not by hand.

## Step 9: gate/

The readers. `design-reader-gate.py` runs the ICP personas against the served page and appends rows
to `gate/reader-runs.jsonl`; `reader_problems()` refuses a LEAVE verdict, a re-roll over the cap, or
a floor not met, unless a founder disposition answers that reader by id.

## Step 10: seal, then show

`design-chain-gate.py seal <round>`. It holds a snapshot, runs the producers against it, checks the
whole chain, and writes `receipts.json` with what ran. Nothing is shown to the founder before the
seal: the gate blocks a preview of an unsealed page.

## What this command does not do

It does not decide whether the design is good. The gate measures floors and records what ran; the
founder's eye and real buyer conversations are the bar. A green seal means the chain ran, not that
the page works.
