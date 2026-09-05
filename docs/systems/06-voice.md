# 06. Voice

Anything another person will read leaves in the founder's voice. Three scripts decide
that on every write and every turn: `voice-lint.py`, `voice-substance-lint.py` and
`voice-stop-gate.py`. The subsystem has two halves. The vocabulary half is that set of
lints on banned words, banned shapes and missing substance. The method half, called
voiceloop, measures style bands from the founder's own writing, selects real exemplars per
channel and length, and scores a candidate for echo and fingerprint. A loader injects the
corpus on a writing request; the Stop gate reads the chat output itself.

## Components

```mermaid
flowchart TB
    CORP[(voice corpus: exemplars.jsonl, scars.md, built.md, lexicon.json)]
    subgraph inject [Before writing]
        VDL[voice-dna-loader.py, UserPromptSubmit]
        VREF[voice_ref.py --channel --words]
        SEL[selector.py: which 3-5 real pieces ride in this prompt]
        ASM[assemble.py: the voice section of a prompt]
    end
    subgraph lint [After writing, PostToolUse]
        VL[voice-lint.py: banned words, em-dashes, rule of three, comma triplets, stats]
        VSL[voice-substance-lint.py: a scar, a named thing, evidence, or it reads as AI]
        BUL[voiceloop-band-lint.py: bands, templated shapes, corpus echo]
        LFL[linkedin-format-lint.py] & HL[headline-lint.py] & BL[batch-uniformity-lint.py] & FL[format-lint.py] & AL[audhd-lint.py]
    end
    subgraph method [voiceloop package]
        CO[corpus.py: read a voice/ dir, degrade never die]
        FP[fingerprint.py: measurable style from a corpus, scored on a candidate]
        EC[echo.py: the candidate must not parrot its own prompt]
        VAL[validate.py: the loud corpus contract, suites and CLIs only]
    end
    subgraph stop [At the end]
        VSG[voice-stop-gate.py, Stop: final check on chat output; drift counter -> alert]
    end
    subgraph refresh [Growing the corpus]
        VR[/voice-refresh -> granola-voice-harvest.py -> granola-voice-synthesize.py -> granola-voice-fingerprint.py]
        GC[granola_candidates.py: correction candidates, never edits]
        SRE[stat-registry-extract.py: the numbers voice may cite]
    end
    CORP --> VDL --> VREF --> SEL --> ASM
    CORP --> CO --> FP & EC
    VAL -. checks .-> CORP
    FP & EC --> BUL
    VR --> CORP
```

The corpus is a directory of the founder's real writing plus two substance files (scars
and things built) and a lexicon. Before writing, the loader detects a writing request and
runs the selector, which picks the three to five real pieces that match the channel and
the target length, and the assembler renders them into the prompt. After a file is written,
the vocabulary lints and the band lint run on it; the band lint scores fingerprint and
echo through the method package. At the end of the turn the Stop gate reads the chat
output itself. The corpus grows through the refresh command, a three-stage pipeline from
meeting transcripts that emits candidates a person accepts, never direct edits.

## Flow: one draft

```mermaid
sequenceDiagram
    participant F as Founder
    participant VDL as voice-dna-loader.py
    participant M as Model
    participant L as PostToolUse lints
    participant G as voice-stop-gate.py
    F->>VDL: "draft a LinkedIn post about ..."
    VDL->>VDL: writing-intent regex matches
    VDL-->>M: who is writing, the four moves, corrections that override older rules, a few real rows, the selector command to run
    M->>M: runs voice_ref.py --channel linkedin --words N, reads scars.md and built.md
    M->>M: writes the draft file
    M->>L: Write
    L->>L: voice-lint (exit 2 on a banned pattern), voice-substance-lint (exit 2 with no anchor), voiceloop-band-lint (reports; advisory, measured 61% of the fleet's drafts would trip it)
    L-->>M: findings
    M->>M: revises
    M->>G: Stop
    G->>G: the chat output itself: banned patterns, corpus-similarity drift counter
    G-->>M: exit 2 with the pattern, or pass
```

The loader fires only on a writing request and injects the register, the corrections that
override older rules, a few anchor rows, and the exact selector command for this channel
and length, because length is a real axis: a long piece written against short rows comes
out formal. The lints run on the written file: two block, one reports. The Stop gate is the
last word on what the model says in chat, and its drift counter files an engineering alert
on state change rather than paging anyone.

## Every piece

Corpus and method
- Corpus directory (per founder, outside the skeleton): `exemplars.jsonl` (verbatim pieces, provenance founder-supplied-verbatim), `scars.md`, `built.md`, `lexicon.json`.
- `plugins/kipi-core/voiceloop/`: `corpus.py`, `selector.py`, `assemble.py`, `fingerprint.py`, `echo.py`, `validate.py`, `voice_ref.py`. Founder-agnostic; the public mirror is exported by `automation/export_voice_loop.py` and a pre-commit hook in the consulting instance refuses an engine change that the mirror did not follow.
- `founder-voice` skill: the instruction half (voice DNA, writing samples, anti-AI patterns) that the loader points at.

Injection
- `voice-dna-loader.py` (UserPromptSubmit): `WRITING_TRIGGER_PATTERNS`; reads only the corpus directory; refuses a 40 KB fixed dump by design (measured to make output worse).

Lints (PostToolUse, each self-scoped to published paths)
- `voice-lint.py` (blocks): the vocabulary, em-dashes and double hyphens, rule-of-three and comma-triplet shapes, statistical citations, slash-command references in published text. `voice-banned-list-duplication-check.py` fails when a skill file restates its banned list.
- `voice-substance-lint.py` (blocks): a draft needs a scar, a named thing, a test or evidence; the OR-of-three anchor rule.
- `voiceloop-band-lint.py` (reports, in the template): bands, templated shapes, echo; imports `is_published_path` from voice-lint so both halves agree on what a draft is.
- `linkedin-format-lint.py`, `headline-lint.py`, `batch-uniformity-lint.py`, `format-lint.py`, `audhd-lint.py`: channel format, headline patterns, uniform openers across a batch, DM and email format, and the AUDHD actionability rules on founder-facing output.
- `scan-draft.py`, `copy-diff.py`, `compliance-check.py`: the bus-era draft scanner (also the `kipi_scan_draft` MCP tool), the copy-edit analyser, and the compliance check for generated content.
- `fix-voice-style.py`: a one-off that applied two fixes to the founder output style and committed them.

Stop
- `voice-stop-gate.py` (Stop, and `--drain-only` at SessionStart): final check on the assistant's chat output; honors no marker; its `authorship_page` drift counter emits through `slack-notify.sh`.

Refresh and evaluation
- `/voice-refresh` (kipi-core command): pulls new meetings and runs `granola-voice-harvest.py` (deterministic harvest), `granola-voice-synthesize.py` (LLM synthesis), `granola-voice-fingerprint.py` (deterministic fingerprint); `granola_candidates.py` in the consulting instance turns findings into correction candidates for `exemplars.jsonl` only.
- `stat-registry-extract.py`: audits and regenerates the canonical statistics the voice may cite.
- `audhd-output-eval.py`: the paired, blind A/B harness that measures whether the AUDHD output style improves output without regressing correctness; on demand, real model cost.
- `skill-trigger-eval.py`: measures whether founder-voice and the other interpretive skills fire on their fixture prompts; advisory, on demand.
- `founder-judge-calibration.py`: a blinded founder-versus-judge calibration set for the voice judge.
- Skills: `founder-voice`, `linkedin-brand`, `headline-engineering`, `audhd-executive-function` (page 12 covers content shaping).

## Scars

- The 40 KB dump: a fixed injection of the whole voice file made output worse, measured.
  Result: select against channel and length, never dump.
- 2026-08-05: pairing the founder's years with building AI at those employers, a claim the
  years alone do not make. Result: the bio gate on stated durations.
- 2026-08-29: the style half of the engine ran nowhere on drafts, so a clean vocabulary
  lint read as a full pass. Result: `voiceloop-band-lint.py`, shipped advisory because it
  would have blocked 61 percent of the fleet's drafts on day one.

## Retired

- `voice-dna.md` as a loaded artifact: the loader's own banner says it is retired; the
  three Granola scripts now aim at `exemplars.jsonl`, the file the drafter reads.
