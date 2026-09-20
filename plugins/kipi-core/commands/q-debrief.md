---
description: Post-conversation extraction. Runs the canonical debrief template end to end and routes every insight to its canonical file.
argument-hint: [person or company]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

Run a full conversation debrief. DEBRIEF is the highest-priority workflow in this
system (`q-system/CLAUDE.md`), and this command is its manual trigger. A pasted
transcript fires the same workflow automatically without the command
(`.claude/rules/auto-detection.md`) — no need to type it twice.

`$ARGUMENTS` is the person or company. If it is empty, ask once who the
conversation was with, then proceed.

## Process

1. Locate the instance root and the canonical template. This command ships in the
   kipi-core plugin, but the template and every routing target live in the
   instance, so resolve them from the working tree, not from the plugin:

```bash
QROOT="q-system"; [ -d "$QROOT" ] || QROOT="."; echo "QROOT: $QROOT"; ls "$QROOT/methodology/debrief-template.md" "$QROOT/canonical" "$QROOT/memory" 2>&1
```

2. Read `$QROOT/methodology/debrief-template.md` in full and follow it exactly.
   It is the canonical structure; this file does not restate it, so it cannot
   drift from it. In order, the template covers:
   - Raw source archival to `sources/YYYY-MM-DD-person-name.md` (immutable) BEFORE
     any extraction.
   - The predict-first step: predictions written before the founder describes what
     happened, then scored against reality into `memory/working/predictions.jsonl`.
   - The debrief template proper, then the signal quality check and its routing.
   - All 12 strategic implications lenses, each ending in a concrete action or an
     explicit "no change needed".
   - The Design Partner Conversion section. MANDATORY for practitioner, CISO, or
     buyer conversations; skip only for pure VC conversations.
   - The 11 processing instructions that route insights to canonical files,
     including step 6: entity-relationship triples appended to
     `$QROOT/memory/graph.jsonl`. That file is what `knowledge-inject` reads back
     into later sessions, and this workflow is its only documented writer — a
     debrief that skips step 6 is the reason a later session cannot recall the
     conversation.
   - The quality checklist at the end. Work it as a checklist, not as prose.

3. Before writing changes to a canonical file that alter positioning, strategy, or
   messaging, apply the council auto-trigger rule in
   `.claude/rules/auto-detection.md`: conflicting signals get a Quick Council
   ("new signal or noise?"), and a result is logged to `canonical/decisions.md`
   with the `[COUNCIL-DEBATED]` origin tag. Every decision written to that log
   carries an origin tag (`.claude/rules/sycophancy-core.md`).

4. Close the loops the debrief opens. Every outbound action gets a tracked loop:

```bash
python3 "$QROOT/.q-system/loop-tracker.py" open debrief_next_step "<person>" "<what we are waiting for>"
```

5. Verify the ripple. Log each canonical edit, then run the verifier:

```bash
python3 "$QROOT/.q-system/scripts/ripple-verify.py" "$QROOT/canonical/changelog.md" "$(date +%F)"
```

Exit 0 is done. Exit 1 is a soft gate: address the missing targets or log a skip
reason in the changelog. It does not block debrief completion.

## Done means

Every checkbox in the template's Quality Checklist is ticked or explicitly marked
N/A with a reason. An unfilled section says "N/A - not discussed", never nothing.
