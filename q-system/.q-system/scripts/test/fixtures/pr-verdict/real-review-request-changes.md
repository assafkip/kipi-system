Reading additional input from stdin...
2026-08-03T01:52:56.526145Z ERROR codex_core::session::session: failed to load skill /Users/founder/.agents/skills/audhd-executive-function/SKILL.md: missing YAML frontmatter delimited by ---
OpenAI Codex v0.146.0
--------
workdir: /Users/founder/.config/kipi/review-trees/pr-74
model: gpt-5.6-sol
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019fc552-ef78-7042-b537-564700d059ef
--------
user
You are a SENIOR STAFF ENGINEER at Meta. You have NEVER seen this codebase before.
You were asked to review pull request #74 in /Users/founder/.config/kipi/review-trees/pr-74, and you are ADVERSARIAL by default:
your job is to find what is wrong, not to be agreeable.

## THIS IS REVIEW ROUND 2 OF THIS PR

Earlier rounds are in the PR comments (`gh pr view 74 --comments`). Read them
AFTER you have formed your own read of the code, never before -- your value is
that you did not inherit anyone's frame.

Then apply this rule, which is binding:

- A finding raised in an earlier round may be raised AGAIN only if your own
  reproducer shows it is STILL LIVE. Paste that repro. 'They did not fix it
  properly' without an executed repro is re-litigation, and it is dropped.
- A finding the author ANSWERED with a code citation is settled unless you can
  falsify the citation. Say which citation you falsified and how.
- Do not escalate severity across rounds on the same underlying issue. If it was
  a minor in round 1, it is a minor now, unless new evidence shows a
  consequence nobody had seen. Name that new consequence explicitly.
- By round 3+, a PR that keeps producing NEW blockers on UNCHANGED code means the
  earlier rounds were miscalibrated. Say so in your review if you see it. That is
  a finding about the review process, and it is worth more than another nit.

## Read the change

  gh pr view 74
  gh pr diff 74

## What your fresh eyes are FOR

You have no memory of why anything here is the way it is. That is the point. Do NOT
accept a comment, a commit message, or a doc as evidence — those are the author's
claims about the code, written by the same mind that wrote the bug. Read what the
code DOES. Where a comment and the code disagree, the code is the truth and the
comment is a finding.

Be specifically suspicious of:
- **Test fixtures the author invented.** A fixture built from the same mental model
  as the code tests nothing. Check that every fixture's SHAPE matches what the real
  producer actually emits. This fleet has already shipped a mutex whose remote half
  never fired because its fixture used a key no producer emits, while the suite was green.
- **Tests that could not fail.** For each new test ask: what would break to make this
  red? If nothing plausible would, it is decoration.
- **Claims of enforcement.** 'This ensures X' in a comment is not enforcement. Find
  the code path that refuses, or call it a finding.
- **Error paths, retries, partial failure.** What is left behind when this dies
  halfway? What does the operator see?

## The operational bar (this is the Meta staff part)

This fleet runs UNATTENDED agents on a schedule, against Linear objects that CANNOT
BE DELETED, in a PUBLIC repo. So judge it that way:
- What happens at 3am when this fires and nobody is watching?
- What is the blast radius of it being wrong? What is permanent and unrecoverable?
- What pages a human, and is that signal or noise? A checker that cries wolf trains
  the operator to ignore it, which costs the real alert later.
- Can this be rolled back? If not, say so loudly.
- Concurrency: two of these running at once. What breaks?

## WHAT EACH SEVERITY MEANS — use these anchors, not your feel for it

Severity is BLAST RADIUS and RECOVERABILITY. It is not how clever the finding is,
how long it took you to find, or how much the code annoyed you. Every one of these
anchors is a real event on this fleet, so calibrate against them directly:

- **blocker** — permanent or unrecoverable if it merges. Publishes a credential to
  a Linear object that cannot be deleted. Destroys or overwrites founder work.
  Silently disables the very detector the change adds, forever. If the honest
  answer to 'can we undo this after it fires?' is no, it is a blocker.
- **major** — wrong behavior unattended that a human must clean up, but CAN clean
  up. Files duplicate permanent issues. Cries wolf on every run (a checker the
  operator learns to ignore costs the real alert later, which is why false alarms
  rank here and not below). Reports success for work that did not happen.
- **minor** — real, reproducible, and bounded. Log or help text that misstates
  what the code does. A narrow false negative on an input shape nobody hits yet.
  A docstring that contradicts the code. It should be fixed; it does not gate.
- **nit** — style, naming, formatting, preference. Never gates anything.

Two calibration checks before you assign a severity:
1. If you cannot name what a human has to DO about it at 3am, it is not a blocker
   or a major.
2. If your reproducer only fails under inputs you had to construct and no producer
   in this repo emits, drop the severity a level and say so.

Inflating a minor to a major to make a review feel substantial is itself a defect:
it wedges a PR that should have shipped, and it burns the author's next round on
work that did not need doing.

## THE STANDING RULE — non-negotiable

EVERY finding MUST ship a RUNNABLE REPRODUCER that you ACTUALLY RAN, with its real
output pasted. A finding with no executed repro is an opinion and will be rejected.
Write repros to $TMPDIR and run them. If you cannot make it fail, DROP the finding
and say you tried. Dropping a finding you could not reproduce is a SUCCESS of this
process, not a failure of it.

Never modify the repo. Read-only review. Do not commit, do not push.

## Output

For each finding: SEVERITY (blocker|major|minor|nit), a one-sentence claim, the exact
file:line, the reproducer command, and its REAL output.

Then:
- **What is sound** — attacks you tried that the code survived. Name them. A review
  that only lists faults is not calibrated and cannot be trusted on the faults.
- **VERDICT:** decided by THIS RULE, not by feel:
    - any blocker or major finding      => REQUEST CHANGES (BLOCK only if merging
      as-is would cause permanent or unrecoverable damage)
    - only minor/nit findings           => APPROVE WITH NITS
    - no finding survived reproduction  => APPROVE
  A bar this high ALWAYS finds something; that is what APPROVE WITH NITS is for.
  On APPROVE WITH NITS the pipeline captures every minor as a tracked follow-up,
  so approving with nits does NOT lose them. Using REQUEST CHANGES to log minors
  wedges the PR forever and is itself a review defect.
  State the verdict and the single most important thing to fix first.
- **Last, a machine-readable findings block**, EXACTLY this shape, one line per
  finding, empty block if none. The pipeline parses it; keep prose out of it:

FINDINGS:
severity|one-sentence claim|file:line
END FINDINGS
warning: Skill descriptions were shortened to fit the 2% skills context budget. Codex can still see every skill, but some descriptions are shorter. Disable unused skills or plugins to leave more room for the rest.
hook: SessionStart
hook: SessionStart
hook: SessionStart Completed
hook: SessionStart Completed
hook: UserPromptSubmit
hook: UserPromptSubmit
hook: UserPromptSubmit Completed
hook: UserPromptSubmit Completed
codex
I’m using the GitHub review skill for the PR workflow and the Assaf voice skill for the final review format.

Plan, matching your required order:

- Read the applicable repo instructions, inspect PR metadata/diff and surrounding producers/tests, then form an independent review before reading earlier comments.
- Build and run every candidate reproducer from `$TMPDIR`, compare surviving findings against round 1, and return the calibrated verdict plus the exact findings block.

Your review brief already authorizes this exact read-only plan, so I’m proceeding without modifying the repo.
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "sed -n '1,240p' /Users/founder/.codex/plugins/cache/openai-curated-remote/github/0.1.9-alpha.0-5f2a107-2841cf9749ae/skills/github/SKILL.md && sed -n '1,260p' /Users/founder/.agents/skills/assaf-voice/SKILL.md && sed -n '1,260p' q-system/AGENTS.md" in /Users/founder/.config/kipi/review-trees/pr-74
 exited 1 in 0ms:
---
name: github
description: Inspect GitHub repositories, PRs, issues, reviews, and CI; publish authorized changes.
---

# GitHub

- Scope PR reads and review threads to their canonical base repository.
- For review fixes or writes, follow `../gh-address-comments/SKILL.md`.
- If Actions logs are unavailable, use
  `scripts/inspect_pr_checks.py --repo <matching-checkout> --pr <full-pr-url>`;
  report external checks and URLs for provider follow-up.

## Publish GitHub Changes

- Stage, commit, push, and PR creation each require explicit authorization;
  requesting one action never authorizes the others.
- Inspect staged and unstaged status/diffs; for mixed worktrees, ask which
  files belong. Stage only confirmed paths with `git add -- <paths>`; never
  stage unrelated changes. Never use `git add -A`, `git add .`, or
  `git add --all`.
- If on the default branch, create a feature branch before committing;
  otherwise preserve the requested or current branch. Push only when requested
  and only after confirming the staged scope.
- Resolve the exact base/head repositories and branches; reuse an existing
  matching PR instead of creating another.
- Create at most one PR. If creation is uncertain, verify read-only; never
  blindly retry.
- Set `draft: true`, unless explicitly requested `draft: false`.
- Supply exactly one `base`/`head` or `base_branch`/`head_branch` pair.
- Cross-repository heads, including same-organization `head_repo`, must use
  `<head-owner>:<branch>`.
---
name: assaf-voice
description: ALWAYS USE THIS SKILL for ANY written output - LinkedIn posts, Medium articles, emails, DMs, talk tracks, outreach messages, slide copy, Notion content, investor updates, comments, replies, or any other text that will be read by another human. This includes both ad-hoc requests ("write me a reply to X") and planned/scheduled content (morning routine posts, marketing pipeline, engagement hitlist comments). This skill is NOT optional - it is the default voice layer for all written output in this system.
metadata:
  version: 1.0.0
---

<!-- FIXTURE TRIM: the reviewer echoed the founder's private voice/AUDHD SKILL.md
     bodies into this transcript. The skeleton ships to every instance via kipi
     update, so that content cannot live here (CLAUDE.md separation + the Phase 1
     purity sweep). The tests parse the verdict line and the FINDINGS block, never
     this region, so it is replaced rather than reproduced. -->
[skill bodies elided from fixture]
hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
codex
The checkout does not contain the referenced `q-system/AGENTS.md`, so I cannot load that nested instruction file here. I’m completing the required voice references, then I’ll inspect the PR without reading prior comments.
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "wc -l /Users/founder/.agents/skills/assaf-voice/SKILL.md && sed -n '261,620p' /Users/founder/.agents/skills/assaf-voice/SKILL.md && sed -n '1,240p' /Users/founder/.agents/skills/assaf-voice/references/layers/core-voice.md && sed -n '1,240p' /Users/founder/.agents/skills/assaf-voice/references/layers/vocabulary.md && sed -n '1,240p' /Users/founder/.agents/skills/assaf-voice/references/layers/gotchas.md && pwd && rg --files -g 'AGENTS.md' -g '"'!node_modules'"' -g '"'!vendor'"'" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
     350 /Users/founder/.agents/skills/assaf-voice/SKILL.md

4. **Mechanical "man"/"dude" insertion.** These words are natural in Assaf's voice but AI sprinkles them as casual-signaling. Max 1-2 per batch of messages. Never in back-to-back drafts. Never as the only casual marker.

5. **The mirror-then-pivot.** Never quote their words -> restate the problem -> pivot to "I'm building against this." Once per batch, max. If every message follows quote -> empathy -> pitch, it's a template, not a conversation.

6. **Uniform comment structure.** When writing multiple LinkedIn/X comments in one batch, vary the structure. Not every comment should be: [quote them] -> [restate] -> [add one layer]. Some should be a question. Some should be a short disagreement. Some should just be two sentences.

7. **The "Name," greeting.** Assaf starts messages with "I" as the subject. Not "Name, [verb]..." See First Person Usage rules.

8. **Wrong content for format.** Match the text to the delivery mechanism. A LinkedIn connection request (300 char limit) is not a comment. Keep it short and direct: "I saw your post on X. I'm building for that problem. would be good to connect." A comment can be longer and more substantive. A DM is conversational. An email has structure. Never write comment-length text for a connection request or vice versa.

### Structural Anti-Patterns (NEVER do these)

1. **Uniform sentence length.** AI sentences cluster around 12-18 words. Mix 4-word sentences with 25-word sentences. Never let three consecutive sentences be similar length.

2. **Uniform paragraph length.** AI paragraphs are suspiciously similar in size. Vary them. Some paragraphs should be one sentence. Others can be longer.

3. **Transition-word paragraph openers.** AI opens every paragraph with "Furthermore," "Moreover," "In contrast." Start with the actual content instead.

4. **Bold-title bullet restatement.** Where a bolded phrase is immediately restated in the following sentence. Wikipedia flagged this as "virtually nonexistent" in human writing but ubiquitous in AI output.

5. **The three-point default.** AI groups everything in threes. Use two examples, or four, or one. Break the pattern.

6. **Compulsive balance.** AI presents both sides even when unnecessary. If the point is "X is broken," don't add "but some people disagree" unless genuinely relevant. Take a side.

7. **The "X, doing Y" participial phrase.** "The company released its report, highlighting key trends." AI defaults to this structure repeatedly. Restructure.

8. **Formulaic closings.** No summary paragraph that restates what was just said. No "In conclusion." End with a sharp thought, not a recap.

9. **Colon overuse.** "The answer is simple: [explanation]." AI reaches for colons far more than humans do.

### Tonal Anti-Patterns (NEVER do these)

1. **The statistical average voice.** AI sounds like no one in particular. Every output must sound like Assaf specifically - with his scars, his directness, his Israeli bluntness.

2. **Hedging everything.** "Might," "could," "perhaps," "generally," "somewhat," "often," "in many cases." AI avoids absolute statements. Assaf says "X is broken." Not "X might have some challenges."

3. **Overly formal default.** No contractions, no informal asides, grammatically perfect but emotionally dead. Use contractions. Use fragments. Start sentences with "And" or "But."

4. **Upbeat abstractions.** "Absolutely brilliant," "truly groundbreaking," "incredibly insightful" - never paired with specific evidence. Every positive claim needs a specific example or it gets cut.

5. **No personal texture.** No anecdotes, no frustration, no humor, no surprise. AI writing lacks lived experience. Assaf's writing IS lived experience. If a paragraph could have been written by someone who never worked in security, rewrite it.

6. **Suspiciously consistent style.** AI maintains the same register throughout. Humans drift, get sharper, soften, go on tangents. Let the voice breathe.

### What Human Writing Has That AI Doesn't

- Sentence fragments used for emphasis
- Starting sentences with "And" or "But"
- Parenthetical asides that feel like the writer thinking out loud
- Occasional imperfect grammar that sounds natural
- Strong opinions stated without qualification
- Specific names, numbers, tools, dates instead of generic references
- Frustration, impatience, dry humor - real emotional texture
- Varying levels of formality within the same piece
- Deliberate repetition for rhetorical effect (not accidental)

### The Detection Test

Before outputting, mentally run these checks:
- **Perplexity:** Am I always picking the most predictable next word? Surprise the reader occasionally.
- **Burstiness:** Are my sentences varying enough in length? Mix short punches with longer developing sentences.
- **Lexical diversity:** Am I repeating the same structures? Vary the sentence construction.
- **The "who wrote this" test:** If you removed the byline, would a reader guess this was written by a specific person with specific experiences? Or could it have been generated by any LLM? If the latter, rewrite.

---

## Quality Check (ALL MUST PASS)

Before outputting any content, verify:

**Voice checks:**
1. **Scar test:** Does at least one paragraph anchor in real operational experience?
2. **Contrast test:** Is there at least one sharp "X isn't Y. It's Z." pattern?
3. **Specificity test:** Does it sound like a specific person with specific experiences, or could any content marketer have written this?
4. **Theater test:** Does every sentence carry information or enable action? No filler paragraphs?

**Mechanical checks:**
5. **Filler test:** Zero words from the banned AI words list? Zero hedging language?
6. **Emdash test:** Zero emdashes anywhere? (Use commas, periods, or hyphens.)
7. **Sentence test:** Does sentence length VARY? Mix of short (5 words) and longer (20+ words)? No three consecutive sentences of similar length?
8. **Paragraph test:** Does paragraph length vary? At least one single-sentence paragraph?

**Anti-AI checks:**
9. **Transition test:** Does any paragraph open with "Furthermore," "Moreover," "Additionally," "That said"? Remove them.
10. **Hedge test:** Count instances of "might," "could," "perhaps," "generally." More than one per 500 words = rewrite.
11. **Structure test:** Are all bullet lists exactly 3 items? Break the pattern. Are all sections the same length? Vary them.
12. **Personality test:** Remove the byline. Can you tell a human wrote this? Can you tell WHICH human? If not, rewrite.

If any check fails, rewrite before outputting.
# Layer 1: Core Voice

Assaf Kipnis. 12+ years threat intelligence (LinkedIn, Google, Meta, ElevenLabs). Israeli. AUDHD. English as second language.

## The Core Voice: Frustrated Practitioner Who Became a Builder

Every piece of writing comes from: "I saw this break repeatedly. Here's why it keeps breaking. Here's what should exist instead."

NOT a vendor marketing voice. NOT a news commentator. NOT academic. NOT motivational.

IS: a person who has been in the room when things broke. Direct because clarity matters more than politeness. Thinks in systems, not features. Gets genuinely irritated by theater and waste.

## 5 Archetypes (use at least one per piece)

1. **The Witness** - "At Google, I watched four teams fight the same scam operation. None of them knew." Authority from being present.
2. **The Namer** - Gives names to dysfunction: "whac-a-mole metric," "compliance theater," "shelfware," "safety debt," "translation tax." Makes vague frustration concrete.
3. **The Systems Thinker** - Proposes systems, not tools. Moves from "what's broken" to "the structural fix."
4. **The Attacker-Aware Defender** - Frames through the adversary's advantage. "Defenders reset after every incident. Attackers build on every success."
5. **The Tester** - Tests things himself, reports results. Engaged a scammer for weeks. Ran 3 AI models on same conversation.

## Emotional Register

Present: controlled frustration, conviction, intellectual honesty, dry humor, practical concern.
Absent: enthusiasm, excitement, fear-mongering, vulnerability signaling, motivational energy.

## The Wiring (not style choices)

- **Israeli:** Direct is default. No performative politeness. No "hope you're well." Short sentences from thinking in Hebrew.
- **ASD:** Pattern recognition, systems over social, low tolerance for theater, blunt delivery, classification instinct.
- **ADHD:** Hyperfocus depth, impatience with slow systems, cross-domain connections, short paragraphs.
- Do NOT add politeness layers. Do NOT smooth the directness. DO preserve taxonomy instinct and cross-domain connections.
# Layer 3: Vocabulary (also used by scan-draft.py)

## Words Assaf Uses
"Codify," "compound," "closed loop," "shelfware," "folklore" vs "record," "theater," "nervous system," "muscles," "reflexes," "institutional memory," "append-only," "translation tax"

## Words Assaf Never Uses
"Leverage," "innovative," "cutting-edge," "game-changing," "single pane of glass," "next-gen," "AI-powered" (without specifics), "circling back," "just checking in," "following up on my last message," "holistic," "robust," "seamless," "empower," "unlock," "excited," "thrilled," "humbled," "proud"

## Banned AI Words (Tier 1 - instant tells, NEVER use)

delve, comprehensive, crucial, vital, pivotal, robust, innovative, transformative, intricate, meticulous, nuanced, vibrant, enduring, unparalleled, unwavering, cutting-edge, groundbreaking, unprecedented, tapestry, synergy, landscape (metaphorical), realm, beacon, interplay, treasure trove, paradigm, cornerstone, catalyst, linchpin, testament

## Banned AI Verbs (NEVER use)

leverage, utilize, optimize, foster, underscore, embark, garner, bolster, showcase, enhance, empower, unlock, revolutionize, streamline, spearhead, navigate (metaphorical)

## Banned AI Adverbs (NEVER use)

meticulously, effectively, efficiently, strategically, consistently, seamlessly, furthermore, moreover, additionally, indeed

## Banned Phrases (NEVER use)

Openings: "In today's world/fast-paced/era," "Let's dive in/explore/unpack," "It's important/crucial/worth noting," "Generally speaking"

Transitions: "Furthermore," / "Moreover," / "Additionally," as paragraph openers. "In conclusion," / "To sum up," / "That said," / "With that in mind," / "This is where X comes in"

Hype: "Game-changer," "Unlock the potential," "Revolutionize the way," "A pivotal moment," "New era," "Let's face it"

Sycophantic: "Great question!" / "That's a really interesting point" / "Absolutely!" as opener / "I hope this helps!"

## Banned DM/Email Formulas (NEVER in CISO outreach)

1. Quote-mirror opener (quoting someone's words back, then reacting). Max 1 per batch.
   Instead: lead with your own experience or a question about their situation.
2. "Exactly" bridge ("That's exactly what I'm building"). Flattery formula.
3. "Name, [gratitude]" opener formula across multiple messages.
4. Mechanical "man"/"dude" insertion. Max 1-2 per batch.
5. Mirror-then-pivot (quote -> empathy -> pitch). Once per batch max.
   Instead: skip the mirror. State what you build. Or ask a question. Let them connect.
6. Uniform comment structure across a batch.
   Instead: 1 question opener, 1 short disagreement, 1 two-sentence take, then vary the rest.
7. "Name," greeting. Start with "I" as subject.
8. Wrong content for format. CR = 300 chars. Comment = longer. DM = conversational.
# Layer 5: Gotchas (Batch & Structural Enforcement)

> Loaded LAST. Highest recency weight. These override patterns in other layers.

## Batch Uniformity (ENFORCED when writing 3+ copy blocks)

- **Vary openers.** No more than 2 comments can share the same opening pattern. If one starts with "The X point..." the next cannot. Mix: lead with your own experience, ask a question, start with a short disagreement, open with a two-sentence take.
- **Vary arc.** Not every comment can follow validate -> expand -> connect. At least 1 must be a question. At least 1 must be under 2 sentences. At least 1 must disagree or add friction.
- **Vary length.** Some comments 2 sentences. Some 4-5. Never all the same length.

## Contractions (MANDATORY)

Use contractions: don't, isn't, doesn't, can't, won't, it's, you're, we're, they're, I'm.
The formal forms (do not, is not, does not, it is, you are) read as AI-generated. Every "do not" in a LinkedIn comment is a detection signal. The only exception: emphasis. "This is not a tools problem." works. But 5 "is not" in one batch does not.

## Banned DM/Email Formulas (with alternatives)

1. **Quote-mirror opener.** Don't open by quoting their words back. Instead: lead with your own experience or a question about their situation. Max 1 quote-reference per batch.
2. **"Exactly" bridge.** Never say "that's exactly what I'm building" or "exactly the kind of." Instead: describe what you build. Let them connect the dots.
3. **"Name, [gratitude]" opener.** Don't formula-greet across a batch. Instead: vary or skip. Get to the point.
4. **Mechanical "man"/"dude."** Max 1-2 per batch. Never in back-to-back drafts.
5. **Mirror-then-pivot.** Don't quote -> empathy -> pitch in every message. Instead: skip the mirror. State what you're building directly. Or ask a question. Once per batch max.
6. **Uniform comment structure.** Don't write 5 comments with the same arc. Instead: 1 question opener, 1 short disagreement, 1 two-sentence take, then vary.
7. **"Name," greeting.** Start DMs/emails with "I" as the subject. Not "Name, [verb]..."
8. **Wrong content for format.** CR = 300 chars max, direct. Comment = longer, substantive. DM = conversational. Email = structured. Don't write comment-length CRs.

## Detection Test (run before output)

1. **Perplexity:** Am I always picking the most predictable next word? Surprise the reader.
2. **Burstiness:** Are sentences varying in length? Mix 4-word punches with 20-word developing sentences.
3. **Lexical diversity:** Am I repeating the same structures across the batch?
4. **The "who wrote this" test:** Remove the byline. Can you tell a specific person wrote this? If it reads like any LLM, rewrite.

## Quality Check (ALL MUST PASS)

1. Scar test: at least one paragraph anchors in real operational experience?
2. Contrast test: at least one "X isn't Y. It's Z." pattern?
3. Specificity test: could any content marketer have written this? If yes, rewrite.
4. Theater test: every sentence carries information or enables action?
5. Filler test: zero banned AI words?
6. Emdash test: zero emdashes?
7. Sentence test: length varies? Short punches mixed with longer sentences?
8. Paragraph test: at least one single-sentence paragraph?
9. Transition test: no paragraph opens with "Furthermore," "Moreover," "Additionally"?
10. Hedge test: max 1 hedge word per 500 words?
11. Structure test: not everything grouped in threes? Sections vary in length?
12. Personality test: remove byline - can you tell WHICH human wrote this?

## Active Corrections (auto-populated by copy-diff agent)

(No corrections logged yet. This file grows as the founder edits generated copy.)
/Users/founder/.config/kipi/review-trees/pr-74
AGENTS.md

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "sed -n '1,320p' AGENTS.md && git status --short && git remote -v && gh pr view 74 --json number,title,body,author,baseRefName,headRefName,headRefOid,baseRefOid,url,files,commits,statusCheckRollup && gh pr diff 74" in /Users/founder/.config/kipi/review-trees/pr-74
 exited 1 in 38ms:
error connecting to api.github.com
check your internet connection or https://githubstatus.com

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
codex
GitHub is unreachable from this sandbox. The `gh pr view` call failed before returning PR data. I’m switching to the locally fetched PR branch and base refs, which preserves the code review. I’ll retry GitHub once before the round-comparison step because earlier comments are required for the final result.
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'git branch --show-current && git branch -avv && git show-ref --heads --tags && git log --oneline --decorate -20 && git status --porcelain=v1 && git diff --stat origin/main...HEAD && git diff --name-status origin/main...HEAD' in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 14ms:
 q-system/.q-system/capability-manifest.json        |   4 +
 q-system/.q-system/scripts/capability-map-gen.py   | 210 ++++++++++++++++++---
 .../scripts/test/test-capability-map-wiring.py     | 198 +++++++++++++++++++
 3 files changed, 386 insertions(+), 26 deletions(-)
M	q-system/.q-system/capability-manifest.json
M	q-system/.q-system/scripts/capability-map-gen.py
A	q-system/.q-system/scripts/test/test-capability-map-wiring.py

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'git diff --find-renames --find-copies --unified=80 origin/main...HEAD -- q-system/.q-system/capability-manifest.json q-system/.q-system/scripts/capability-map-gen.py q-system/.q-system/scripts/test/test-capability-map-wiring.py' in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
diff --git a/q-system/.q-system/capability-manifest.json b/q-system/.q-system/capability-manifest.json
index b0b47af..2561ae6 100644
--- a/q-system/.q-system/capability-manifest.json
+++ b/q-system/.q-system/capability-manifest.json
@@ -349,160 +349,164 @@
     },
     {
       "path": "q-system/.q-system/scripts/test_memory_autocapture.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_memory_confidence_surface.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_memory_confidence_validator.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_memory_confidence_wiring.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_memory_outcomes.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_memory_reflect.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_memory_scores_surface.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_plugin_version_bump_check.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_prompt_only_enforcement_guard.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_provenance_vocabulary.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_read_first_gate.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_session_recall.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_settings_template_sync_check.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_system_manifest.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_review_tier.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_token_guard_commit_forms.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_token_guard_observation.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/test_voice_lint_caps.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/scripts/tests/test-stat-verify.py",
       "runner": "python3"
     },
     {
       "path": "q-system/.q-system/test_token_guard_runtime.py",
       "runner": "python3"
+    },
+    {
+      "path": "q-system/.q-system/scripts/test/test-capability-map-wiring.py",
+      "runner": "python3"
     }
   ],
   "required_data": [],
   "skeleton_only": [
     "q-system/.q-system/scripts/test/test-auto-update-nudge.sh",
     "q-system/.q-system/scripts/test/test-instance-ownership-contract.py",
     "q-system/.q-system/scripts/test/test-kipi-rollback-matrix.sh",
     "q-system/.q-system/scripts/test/test-kipi-rollback.sh",
     "q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh",
     "q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh",
     "q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh",
     "q-system/.q-system/scripts/test/test-kipi-update-leak-preflight.sh",
     "q-system/.q-system/scripts/test/test-kipi-update-preservation-failure.sh",
     "q-system/.q-system/scripts/test/test-kipi-update-safety.sh",
     "q-system/.q-system/scripts/test/test-lessons-push-guard.sh",
     "q-system/.q-system/scripts/test/test-propagation-entrypoints.py",
     "q-system/.q-system/scripts/test/test-propagation-leak-baseline.py",
     "q-system/.q-system/scripts/test/test-propagation-leak-sources.py",
     "q-system/.q-system/scripts/test/test-token-guard-template-wiring.sh",
     "q-system/.q-system/scripts/test/test-updater-issue-sequence.py",
     "q-system/.q-system/scripts/test_autocapture_wiring.py"
   ],
   "declared_inert": [
     {
       "path": "q-system/.q-system/scripts/accept-rate.py",
       "reason": "sycophancy pi metric script with no caller on any wiring surface",
       "spillover_id": "sp-cc33bdb0"
     },
     {
       "path": "q-system/.q-system/scripts/granola-voice-synthesize.py",
       "reason": "ad-hoc founder tool, no wiring surface references; wire-or-delete is a founder decision",
       "spillover_id": "sp-cc33bdb0"
     },
     {
       "path": "q-system/.q-system/scripts/instance-diet.py",
       "reason": "one-off maintenance tool, no wiring surface references",
       "spillover_id": "sp-cc33bdb0"
     },
     {
       "path": "q-system/.q-system/scripts/instance-fact-inventory.py",
       "reason": "built for prd-skeleton-data-containment and never wired; its only references are that PRD's specs and its own test",
       "spillover_id": "sp-0f773063"
     },
     {
       "path": "q-system/.q-system/scripts/linear-collapse-jobmigration.py",
       "reason": "one-shot family collapse: it absorbed the 32-member job-migration family into ASK-151 on 2026-07-28 and has no second family to run on. ASK-226 generalises it; retire this one when that lands",
       "spillover_id": "sp-fb332466"
     },
     {
       "path": "q-system/.q-system/scripts/linear-triage.py",
       "reason": "built and tested (21 cases) but deliberately unwired: --apply writes permanent Linear comments and closes issues, so no trigger exists until the founder reviews the full dry-pass table. sp-0126e55b is the wiring destination -- triage must GATE the DoR drafter, which is loaded and currently drafting readiness ahead of it",
       "spillover_id": "sp-0126e55b"
     },
     {
       "path": "q-system/.q-system/scripts/memory_outcomes.py",
       "reason": "auto-capture referee merged (PR #7) but gated OFF fleet-wide; activates with the held kipi update",
       "spillover_id": "sp-cac8540c"
     },
     {
       "path": "q-system/.q-system/scripts/memory_reflect.py",
       "reason": "auto-capture referee merged but gated OFF fleet-wide",
       "spillover_id": "sp-cac8540c"
     },
     {
       "path": "q-system/.q-system/scripts/pdf-extract.py",
       "reason": "ad-hoc research tool (AI Index comparison), invoked manually",
       "spillover_id": "sp-cc33bdb0"
     },
     {
       "path": "q-system/.q-system/scripts/review-tier.py",
       "reason": "deterministic review-tier classifier: built, tested (55 checks incl. a mutation layer), and DELIBERATELY unwired. Not a hook, so .claude/settings.json is the wrong surface -- its contract is `review-tier.py ... || run_independent_review`, making the call site pr-review-agent.sh or linear-worker.sh. Picking between them changes behaviour (one saves a Codex call, the other a whole worker run) and is its own design decision. Held back on purpose: this classifier decides WHO GETS REVIEWED, so it must not arm itself in the same PR that has not yet been reviewed",
       "spillover_id": "sp-f0f0fc7e"
     },
     {
       "path": "q-system/.q-system/scripts/session_recall.py",
       "reason": "auto-capture referee merged but gated OFF fleet-wide",
       "spillover_id": "sp-cac8540c"
     },
     {
       "path": "q-system/.q-system/scripts/stat-registry-extract.py",
diff --git a/q-system/.q-system/scripts/capability-map-gen.py b/q-system/.q-system/scripts/capability-map-gen.py
index ad9dd37..e4c9203 100644
--- a/q-system/.q-system/scripts/capability-map-gen.py
+++ b/q-system/.q-system/scripts/capability-map-gen.py
@@ -249,202 +249,360 @@ def collect_hooks(root: Path) -> list:
     except json.JSONDecodeError:
         return [{
             "name": "hook wiring (settings.json)",
             "layer": L_ENFORCEMENT,
             "status": "BROKEN",
             "summary": "settings.json does not parse as JSON, so no hook in it can load.",
             "entry": rel(root, settings),
             "trigger": "session lifecycle",
             "evidence": f"{rel(root, settings)}: json.JSONDecodeError on parse.",
         }]
 
     for event, groups in (data.get("hooks") or {}).items():
         for group in groups if isinstance(groups, list) else []:
             for hook in (group.get("hooks") or []):
                 cmd = hook.get("command") or ""
                 scripts = re.findall(r"[\w\-./${}]+\.(?:py|sh)", cmd)
                 resolved, missing = [], []
                 for s in scripts:
                     clean = (s.replace("${CLAUDE_PROJECT_DIR}", "")
                               .replace("$CLAUDE_PROJECT_DIR", "").lstrip("/"))
                     if "${" in clean or "$" in clean:
                         continue
                     (resolved if (root / clean).is_file() else missing).append(clean)
                 if not scripts:
                     continue
                 label = os.path.basename(scripts[0])
                 # Matcher is part of the identity: one script can be wired to
                 # several events/matchers, and those are different capabilities.
                 # Without it, investigations' two PostToolUse run-lint.sh hooks
                 # produced the same name AND the same entry, so even the path-hash
                 # disambiguation collided (linear-sync exit 3, 2026-07-26).
                 matcher = str(group.get("matcher") or "all")
                 caps.append({
                     "name": f"hook {label} ({event}/{matcher})",
                     "layer": L_ENFORCEMENT,
                     "status": "BROKEN" if missing else "LIVE",
                     "summary": (f"{event} hook running {label}."
                                 + (" Its script is MISSING from disk."
                                    if missing else "")),
                     "entry": f".claude/settings.json -> {scripts[0]} [{event}/{matcher}]",
                     "trigger": f"{event} ({group.get('matcher', 'all')})",
                     "evidence": (
                         f"Wired in .claude/settings.json under {event}. "
                         + (f"MISSING on disk: {', '.join(missing)}. The switch is on "
                            f"and nothing is behind it."
                            if missing else
                            f"Script present: {', '.join(resolved) if resolved else label}.")
                     ),
                 })
     return caps
 
 
 def collect_agents(root: Path) -> list:
     caps = []
     for p in walk(root, ".claude", "agents", "*.md"):
         text = read_text(p)
         m = re.search(r"^model:\s*(\S+)", text, re.M)
         caps.append({
             "name": f"agent {p.stem}",
             "layer": L_AGENTS,
             "status": "LIVE" if m else "NEEDS_WORK",
             "summary": summarize(text, f"Agent {p.stem}."),
             "entry": rel(root, p),
             "trigger": "invoked by an orchestrator or the Agent tool",
             "evidence": (f"{rel(root, p)}: model pinned to {m.group(1)}."
                          if m else
                          f"{rel(root, p)}: NO model: frontmatter, so tier is unpinned."),
         })
     return caps
 
 
 def _docstring_line(text: str) -> str:
     """First line of a module docstring, or '' if there is not a well-formed one."""
     parts = text.split('"""')
     if len(parts) < 3:
         return ""
     lines = [ln.strip() for ln in parts[1].strip().splitlines() if ln.strip()]
     return lines[0][:180] if lines else ""
 
 
+# Files whose CONTENT can wire an engine. A mention anywhere in one of these is a
+# reference; markdown is handled separately below because prose is not wiring.
+SURFACE_CODE_EXT = {
+    ".py", ".sh", ".bash", ".zsh", ".yml", ".yaml", ".toml", ".json",
+    ".cfg", ".ini", ".mk", ".txt",
+}
+SURFACE_DOC_EXT = {".md"}
+# Extensionless wiring surfaces (the kipi CLI, Makefiles, lefthook's shell blocks).
+SURFACE_NAMES = {"Makefile", "makefile", "kipi", "Dockerfile", "Justfile", "justfile"}
+
+# GENERATED ARTIFACTS ARE NOT WIRING SURFACES (ASK-122, caught pre-merge).
+#
+# Widening the scan repo-wide swept in q-system/output/, which holds codex
+# transcripts, run logs, plans and RCAs. Those name scripts constantly and run
+# nothing. Measured on kipi-investigations: _sync_all.py flipped to LIVE on the
+# strength of `q-system/output/codex-sfactivity-prd-out.txt` line 738, a bare
+# `find`-style listing `./plugins/.../_sync_all.py`.
+#
+# The invocation filter cannot save this: that line starts with "./" and so
+# matches MD_INVOCATION_RE. A log of a command that ENUMERATED files is
+# indistinguishable, line by line, from a runbook that INVOKES one. The only
+# durable separator is provenance -- who wrote the file -- so the fix is to drop
+# generated trees from the surface rather than to write a cleverer regex.
+#
+# q-system/output/ is the OS's generated-artifacts directory by convention; it is
+# also in kipi-update.sh's INSTANCE_OWNED_SUBTREES, i.e. already understood
+# fleet-wide as an instance's own output rather than source.
+GENERATED_SURFACE_PREFIXES = ("q-system/output/",)
+
+
+def _witness_rank(p: Path):
+    """Sort key that prefers a REAL caller over a scratch/hidden copy of one.
+
+    Any path component starting with "." is a review tree, a worktree or a tool
+    cache, never the wiring a reader should be sent to look at.
+    """
+    parts = p.parts
+    hidden = any(part.startswith(".") for part in parts)
+    return (hidden, len(parts), str(p))
+
+
+def is_generated_surface(p: Path, root: Path) -> bool:
+    """True when p is a generated artifact, so its content must not count as wiring."""
+    try:
+        rel = p.relative_to(root).as_posix()
+    except ValueError:
+        return False
+    return rel.startswith(GENERATED_SURFACE_PREFIXES)
+
+# A markdown line only counts as wiring if it INVOKES something. A findings doc
+# saying "engine_x.py left the template unfilled" names a script without keeping it
+# alive; a runbook line `python3 engine_x.py` does. Without this split, widening the
+# scan repo-wide just trades false-dead for false-alive (ASK-122).
+MD_INVOCATION_RE = re.compile(r"(?:python3?\s|bash\s|\bsh\s|\./|source\s|-m\s)")
+
+# Module tokens an engine can be reached by WITHOUT its .py suffix. `import x`,
+# `from x import y`, `python -m x`, and importlib's spec_from_file_location("x", ...)
+# are all real callers that a filename-only scan reads as silence. Scar: ASK-230,
+# where provenance_vocabulary.py had two live importers and was reported inert
+# because both wrote `import provenance_vocabulary` with no extension.
+MODULE_REF_RE = re.compile(
+    r"^\s*from\s+([\w.]+)\s+import\b"
+    r"|^\s*import\s+([\w.]+)"
+    r"|spec_from_file_location\(\s*[\"']([\w.\-]+)[\"']"
+    r"|-m\s+([\w.]+)\b",
+    re.M,
+)
+
+
+# `fill_sheet.2026-07-28.py` beside `fill_sheet.py` is a dated SNAPSHOT of an
+# engine, not a second engine. Alice's run-sweep.sh writes one before every sweep
+# (`cp "$GEN/fill_sheet.py" "$DIR/backups/fill_sheet.$TODAY.py"`) and copies it back
+# on failure, so it is live DATA on a rollback path. No static scan can ever match
+# it -- the caller interpolates $TODAY -- so it would report UNWIRED forever and
+# the only way to "fix" it is to delete a rollback artifact (ASK-122).
+DATED_SNAPSHOT_RE = re.compile(r"\.\d{4}-\d{2}-\d{2}$")
+
+
+def _is_test_file(p: Path) -> bool:
+    return p.name.startswith(("test_", "test-")) or "test" in p.parts or "tests" in p.parts
+
+
+def _iter_surface_files(root: Path):
+    """Every file in the repo whose content can constitute wiring.
+
+    WHY REPO-WIDE (ASK-122): the previous list walked only .claude/, plugins/ and
+    q-system/, so an instance whose code lives anywhere else reported its own
+    runners as absent. Alice flagged 22 engines UNWIRED while `regenerate.sh` ran
+    four of them by path and `pipeline.py` imported two more. The scan has to
+    follow the repo, not a layout the skeleton happens to use.
+    """
+    for p in root.rglob("*"):
+        if not p.is_file() or is_vendored(p):
+            continue
+        if is_generated_surface(p, root):
+            continue
+        if p.suffix.lower() in SURFACE_CODE_EXT or p.suffix.lower() in SURFACE_DOC_EXT:
+            yield p
+        elif p.name in SURFACE_NAMES:
+            yield p
+
+
+def _build_reference_index(root: Path, engines: list) -> dict:
+    """Map each engine path -> the set of OTHER files that reference it.
+
+    Two ways to match: the file name (`foo.py`, seen in shell/CLI invocations and
+    config) and the bare module name, but the bare name ONLY inside an import or
+    loader construct. A generic stem like `pipeline` appears in ordinary prose all
+    over this fleet; counting bare-word hits would mark half the repo live.
+    """
+    by_filename = {}
+    by_module = {}
+    for p in engines:
+        by_filename.setdefault(p.name, []).append(p)
+        by_module.setdefault(p.stem, []).append(p)
+    if not by_filename:
+        return {}
+
+    # One alternation, one pass per file: a per-engine regex would be
+    # len(engines) x len(files) scans, which is minutes on a large instance.
+    # The lookbehind must NOT exclude "/": the common form is path-qualified
+    # (`python3 "$G/fill_sheet.py"`), and blocking it hid every shell caller.
+    filename_re = re.compile(
+        r"(?<![\w.\-])(" + "|".join(re.escape(n) for n in sorted(by_filename)) + r")(?![\w\-])"
+    )
+
+    refs: dict = {}
+    for src in _iter_surface_files(root):
+        text = read_text(src)
+        if not text:
+            continue
+        if src.suffix.lower() in SURFACE_DOC_EXT:
+            text = "\n".join(ln for ln in text.splitlines() if MD_INVOCATION_RE.search(ln))
+            if not text:
+                continue
+        for match in filename_re.finditer(text):
+            for engine in by_filename[match.group(1)]:
+                if engine != src:
+                    refs.setdefault(engine, set()).add(src)
+        for match in MODULE_REF_RE.finditer(text):
+            token = next((g for g in match.groups() if g), None)
+            if not token:
+                continue
+            for part in (token, token.rsplit(".", 1)[-1]):
+                for engine in by_module.get(part, ()):
+                    if engine != src:
+                        refs.setdefault(engine, set()).add(src)
+    return refs
+
+
 def collect_engines(root: Path) -> list:
     """Scripts that have a paired test, or that are referenced from a wiring
     surface. An engine with neither is reported UNWIRED rather than assumed fine."""
     caps = []
     tests = {p.name for p in root.rglob("test*") if p.is_file() and not is_vendored(p)}
 
-    # Wiring surfaces mirror capability-gate.py's WIRING_SURFACE_GLOBS. A narrower
-    # list reports UNWIRED for engines that are in fact called by another engine or
-    # by the kipi CLI: the first run of this generator flagged 60 UNWIRED in
-    # 4_points_consulting purely because python-calls-python was never read.
-    surfaces = ""
-    for pat in (".claude/settings.json", "settings-template.json", "lefthook.yml",
-                "Makefile", "*.sh", "kipi*", "validate-separation.py",
-                ".github/workflows/*.yml", "*/hooks/hooks.json", "*/*/hooks.json"):
-        for p in root.glob(pat):
-            if p.is_file() and not is_vendored(p):
-                surfaces += read_text(p)
-    for sub in (root / ".claude", root / "plugins", root / "q-system"):
-        if not sub.is_dir():
-            continue
-        for pattern in ("*.md", "*.py", "*.sh", "*.json"):
-            for p in sub.rglob(pattern):
-                if is_vendored(p) or p.name.startswith(("test_", "test-")):
-                    continue
-                surfaces += read_text(p)
-
+    engines = []
     for p in root.rglob("*.py"):
         if is_vendored(p):
             continue
         if p.name.startswith(("test_", "test-")) or "test" in p.parts:
             continue
-        text = read_text(p)
-        if len(text.splitlines()) < 40:
+        # A generated tree is not a wiring surface (see is_generated_surface), so
+        # it must not be an ENGINE source either. Excluding it from only one of
+        # the two makes its contents permanently dark: still collected, but with
+        # every file that could reference them now off-surface, so they report
+        # UNWIRED with no way to ever clear it (review finding, PR #74 major;
+        # would have compounded sp-3761d2d9). An artifact is not an engine, so
+        # the coherent move is to stop reporting it at all rather than to report
+        # it as dead. Measured: drops 12 phantom engines in kipi-investigations.
+        if is_generated_surface(p, root):
+            continue
+        if DATED_SNAPSHOT_RE.search(p.stem):
             continue
-        has_test = any(p.stem in t for t in tests)
-        referenced = p.name in surfaces
+        if len(read_text(p).splitlines()) < 40:
+            continue
+        engines.append(p)
+
+    refs = _build_reference_index(root, engines)
+
+    for p in engines:
+        text = read_text(p)
+        sources = refs.get(p, set())
+        # WITNESS ORDER IS NOT ALPHABETICAL (review finding, PR #74 minor).
+        # Plain sorted()[0] puts dot-prefixed paths first, so the evidence named
+        # a review scratch tree (.pr42rev/, .claude/worktrees/) instead of the
+        # real caller in 163 of 785 witnesses measured across five repos. The
+        # verdict was right and the citation was useless, which is worse than it
+        # sounds: the citation is the only part a human re-checks.
+        test_sources = sorted((s for s in sources if _is_test_file(s)), key=_witness_rank)
+        wiring_sources = sorted((s for s in sources if not _is_test_file(s)), key=_witness_rank)
+        has_test = any(p.stem in t for t in tests) or bool(test_sources)
+        referenced = bool(wiring_sources)
         status = "LIVE" if (has_test or referenced) else "UNWIRED"
         bits = []
         if has_test:
-            bits.append("has a paired test")
+            witness = rel(root, test_sources[0]) if test_sources else "name-matched test file"
+            bits.append(f"has a paired test ({witness})")
         if referenced:
-            bits.append("referenced on a wiring surface")
+            bits.append(f"referenced on a wiring surface ({rel(root, wiring_sources[0])})")
         if not bits:
             bits.append("NO test and NO wiring reference found")
         caps.append({
             "name": f"engine {p.stem}",
             "layer": L_ENGINES,
             "status": status,
             # A file can contain a single unpaired \"\"\" (inside a string, or a
             # truncated file), so index [1] is not safe and an empty docstring
             # has no [0] line. Fall back rather than lose the whole collector.
             "summary": _docstring_line(text) or f"Python engine {p.name}.",
             "entry": rel(root, p),
             "trigger": "called by a hook, a command, or another script",
             "evidence": f"{rel(root, p)}: {len(text.splitlines())} lines; " + ", ".join(bits) + ".",
         })
     return caps
 
 
 def collect_domains(root: Path) -> list:
     caps = []
     for p in sorted(root.glob("q-*")):
         if not p.is_dir() or p.name in ("q-system",):
             continue
         files = [f for f in p.rglob("*") if f.is_file() and not is_vendored(f)]
         caps.append({
             "name": f"domain {p.name}",
             "layer": L_DOMAIN,
             "status": "LIVE" if files else "NEEDS_WORK",
             "summary": f"Instance-specific domain directory {p.name}/.",
             "entry": p.name + "/",
             "trigger": "read by this instance's commands and skills",
             "evidence": f"{p.name}/: {len(files)} file(s) on disk.",
         })
     return caps
 
 
 def dedupe(caps: list) -> list:
     """Two capabilities that slugify to one key would collapse into one permanent
     Linear issue, so disambiguate here rather than letting linear-sync refuse.
 
     The suffix is a hash of the ENTRY PATH, not a counter. A counter collided for
     real: one registered instance has a file that legitimately produces "engine core 2",
     and a second "engine core" was being renamed to "engine core (2)", which
     slugifies to the same key. linear-sync's collision guard caught it (exit 3),
     which is the guard working, but the generator should not emit the collision in
     the first place. A path hash is unique by construction and stable across runs,
     so re-running does not reshuffle keys and orphan already-created issues.
     """
     slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
     seen, out = {}, []
     for cap in caps:
         base = cap["name"]
         k = slug(base)
         # Loop, do not single-shot. Hashing the entry alone is not enough when the
         # entries are themselves identical: kipi-investigations wires run-lint.sh
         # four times under the same event and matcher with different command
         # arguments, so all four hashed the same and stayed collided even after
         # renaming. Folding the ordinal into the hash terminates and is stable for
         # a given (entry, ordinal) pair.
         ordinal = 0
         while k in seen:
             ordinal += 1
             tag = hashlib.sha1(
                 f"{cap.get('entry') or base}#{ordinal}".encode()
             ).hexdigest()[:6]
             cap["name"] = f"{base} [{tag}]"
             k = slug(cap["name"])
         seen[k] = True
         out.append(cap)
     return out
 
 
 def tag_origin(caps: list, root: Path, skeleton: Path) -> list:
     """Mark each capability skeleton-propagated or instance-local.
 
     WHY THIS IS LOAD-BEARING (ASK-113): `kipi update` rsyncs .claude/rules/,
     .claude/agents/, q-system/ and plugins/ from the skeleton into all 24
     instances. Those capabilities are therefore THE SAME capability, present 24
     times. Filing an issue per instance for a skeleton rule would create ~24
     permanent duplicates of one problem and would itself be the fleet-homogeneity
     violation this whole exercise exists to find.
diff --git a/q-system/.q-system/scripts/test/test-capability-map-wiring.py b/q-system/.q-system/scripts/test/test-capability-map-wiring.py
new file mode 100644
index 0000000..be842ab
--- /dev/null
+++ b/q-system/.q-system/scripts/test/test-capability-map-wiring.py
@@ -0,0 +1,198 @@
+#!/usr/bin/env python3
+"""Wiring detection in capability-map-gen.py: what counts as "this engine is alive".
+
+WHY (ASK-122): the generator flagged 22 local engines in Alice as UNWIRED. Nearly
+all of them had a visible caller on disk -- `regenerate.sh` literally runs
+`python3 "$G/fill_sheet.py"`, `brightdata.sh` runs `mcp-client.py`, `pipeline.py`
+imports `geo_clues`. The scan simply never opened those files: it walked only
+.claude/, plugins/ and q-system/, and Alice's code lives in q-investigate/ and
+scripts/. A gate that reports dead-and-alive the same way is not a gate.
+
+Second blind spot, same issue, already scarred once (ASK-230, provenance_vocabulary):
+`has_test` compared FILENAMES only, so `tests/test_extract.py` importing `geo_clues`
+scored as no-test. An importer is the strongest liveness evidence there is.
+
+The five NEGATIVE cases below are the point of this file. Widening the scan makes
+false-LIVE the new failure mode, so a prose-only mention, a true orphan, a
+self-referencing docstring, a generated run log, and a dated snapshot must all
+still fail to count as wiring. A gate that cannot fail is a rubber stamp.
+
+The generated-log case was not written from imagination: it was found by diffing
+old-vs-new output across five real instances before merge, where it had already
+flipped a genuinely dead script to LIVE. A negative case earns its place by
+having caught something.
+
+Isolation: every fixture is built in a tempdir. Nothing here reads a real repo.
+"""
+
+import importlib.util
+import sys
+import tempfile
+import unittest
+from pathlib import Path
+
+GEN = Path(__file__).resolve().parent.parent / "capability-map-gen.py"
+
+
+def load_generator():
+    spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+    mod = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(mod)
+    # Populated per run in main(); an inherited value would mark fixture paths
+    # vendored and silently collect zero engines.
+    mod._NESTED_REPOS = set()
+    return mod
+
+
+def engine_body(name: str) -> str:
+    """A file long enough to clear the generator's 40-line engine floor."""
+    head = f'#!/usr/bin/env python3\n"""{name} -- fixture engine."""\n'
+    return head + "\n".join(f"# line {i}" for i in range(60))
+
+
+def build_fixture(root: Path) -> None:
+    (root / "q-investigate" / "tools").mkdir(parents=True)
+    (root / "q-investigate" / "lib").mkdir(parents=True)
+    (root / "q-investigate" / "tests").mkdir(parents=True)
+    (root / "docs").mkdir(parents=True)
+
+    # 1. LIVE: only caller is a shell script outside q-system/.
+    (root / "q-investigate/tools/engine_shell_called.py").write_text(
+        engine_body("engine_shell_called"))
+    (root / "q-investigate/tools/run.sh").write_text(
+        '#!/bin/bash\nset -euo pipefail\n'
+        'python3 "$(dirname "$0")/engine_shell_called.py" --once\n')
+
+    # 2. LIVE: only evidence is a test that IMPORTS it under a different filename.
+    (root / "q-investigate/lib/engine_import_tested.py").write_text(
+        engine_body("engine_import_tested"))
+    (root / "q-investigate/tests/test_unrelated_name.py").write_text(
+        "import sys\nsys.path.insert(0, '../lib')\n"
+        "import engine_import_tested\n\n"
+        "def test_it():\n    assert engine_import_tested\n")
+
+    # 3. LIVE: invoked from a fenced command inside a markdown command/runbook.
+    (root / "q-investigate/lib/engine_doc_invoked.py").write_text(
+        engine_body("engine_doc_invoked"))
+    (root / "docs/runbook.md").write_text(
+        "# Runbook\n\nRegenerate the deliverable:\n\n```bash\n"
+        "python3 q-investigate/lib/engine_doc_invoked.py\n```\n")
+
+    # 4. NEGATIVE: named in prose only. A findings doc saying a script is broken
+    #    is not a caller. This must stay UNWIRED or the widened scan has simply
+    #    traded false-dead for false-alive.
+    (root / "q-investigate/lib/engine_prose_only.py").write_text(
+        engine_body("engine_prose_only"))
+    (root / "docs/findings.md").write_text(
+        "# Findings\n\nDefect D1: engine_prose_only.py left the template unfilled.\n"
+        "Nobody has run engine_prose_only since the migration.\n")
+
+    # 5. NEGATIVE: nothing anywhere mentions it.
+    (root / "q-investigate/lib/engine_orphan.py").write_text(
+        engine_body("engine_orphan"))
+
+    # 6. NEGATIVE: self-reference in its own docstring is not a caller.
+    (root / "q-investigate/lib/engine_self_ref.py").write_text(
+        '#!/usr/bin/env python3\n'
+        '"""engine_self_ref.py -- run engine_self_ref.py nightly."""\n'
+        + "\n".join(f"# line {i}" for i in range(60)))
+
+    # 7. NEGATIVE: named only inside q-system/output/, the generated-artifacts
+    #    tree. A codex transcript or run log that ENUMERATES files reads exactly
+    #    like a runbook that INVOKES one, so the fixture is a `find`-style
+    #    listing -- the real shape that flipped _sync_all.py to LIVE in
+    #    kipi-investigations. Note both lines below satisfy MD_INVOCATION_RE
+    #    ("./" and "python3 "), which is the point: the invocation filter cannot
+    #    catch this, only dropping the generated tree can.
+    (root / "q-system" / "output").mkdir(parents=True)
+    (root / "q-investigate/lib/engine_logged_only.py").write_text(
+        engine_body("engine_logged_only"))
+    (root / "q-system/output/codex-run-out.txt").write_text(
+        "Files considered:\n"
+        "./q-investigate/lib/engine_logged_only.py\n"
+        "python3 q-investigate/lib/engine_logged_only.py  # transcript echo\n")
+
+    # 8. A dated snapshot of a live engine is not a second engine. Its writer
+    #    interpolates the date, so no static scan can ever match its literal name.
+    (root / "q-investigate/tools/backups").mkdir(parents=True)
+    (root / "q-investigate/tools/backups/engine_shell_called.2026-07-28.py").write_text(
+        engine_body("engine_shell_called snapshot"))
+
+
+class TestWiringDetection(unittest.TestCase):
+    @classmethod
+    def setUpClass(cls):
+        cls.mod = load_generator()
+        cls.tmp = tempfile.TemporaryDirectory()
+        cls.root = Path(cls.tmp.name)
+        build_fixture(cls.root)
+        cls.by_entry = {
+            c["entry"]: c for c in cls.mod.collect_engines(cls.root)
+        }
+
+    @classmethod
+    def tearDownClass(cls):
+        cls.tmp.cleanup()
+
+    def status(self, entry: str) -> str:
+        self.assertIn(entry, self.by_entry,
+                      f"{entry} was not collected at all; got {sorted(self.by_entry)}")
+        return self.by_entry[entry]["status"]
+
+    # --- positive: real wiring the old scan could not see -------------------
+
+    def test_shell_caller_outside_qsystem_counts(self):
+        self.assertEqual(
+            "LIVE", self.status("q-investigate/tools/engine_shell_called.py"),
+            "run.sh invokes it by path; that is wiring wherever run.sh lives")
+
+    def test_importing_test_counts_even_with_mismatched_filename(self):
+        self.assertEqual(
+            "LIVE", self.status("q-investigate/lib/engine_import_tested.py"),
+            "test_unrelated_name.py imports the module; filename match is not the test")
+
+    def test_fenced_invocation_in_markdown_counts(self):
+        self.assertEqual(
+            "LIVE", self.status("q-investigate/lib/engine_doc_invoked.py"),
+            "a runbook line that runs the script is a trigger")
+
+    # --- negative: the widened scan must still be able to say dead ----------
+
+    def test_prose_mention_is_not_wiring(self):
+        self.assertEqual(
+            "UNWIRED", self.status("q-investigate/lib/engine_prose_only.py"),
+            "a findings doc naming a script does not make it live")
+
+    def test_orphan_stays_unwired(self):
+        self.assertEqual(
+            "UNWIRED", self.status("q-investigate/lib/engine_orphan.py"),
+            "nothing references it; this is the case the gate exists for")
+
+    def test_self_reference_is_not_wiring(self):
+        self.assertEqual(
+            "UNWIRED", self.status("q-investigate/lib/engine_self_ref.py"),
+            "a script naming itself in its own docstring is not a caller")
+
+    def test_generated_output_is_not_wiring(self):
+        self.assertEqual(
+            "UNWIRED", self.status("q-investigate/lib/engine_logged_only.py"),
+            "q-system/output/ holds codex transcripts and run logs; a log that "
+            "lists a script did not run it, and its lines look like invocations")
+
+    def test_dated_snapshot_is_not_an_engine(self):
+        self.assertNotIn(
+            "q-investigate/tools/backups/engine_shell_called.2026-07-28.py",
+            self.by_entry,
+            "a dated snapshot is a rollback artifact; flagging it forever leaves "
+            "deleting the rollback copy as the only way to clear the gate")
+
+    # --- the evidence has to name the caller, not just assert a verdict -----
+
+    def test_evidence_names_the_referencing_file(self):
+        ev = self.by_entry["q-investigate/tools/engine_shell_called.py"]["evidence"]
+        self.assertIn("run.sh", ev,
+                      f"evidence must point at the caller so the map is auditable: {ev}")
+
+
+if __name__ == "__main__":
+    unittest.main(verbosity=2)

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
codex
The diff changes three files, but the behavior fans out across every source file in a repo. I’m checking the scanner’s real inputs now, especially hidden worktrees, generated directories, comments, relative imports, and evidence selection. These are the places a green fixture can still lie.
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "sed -n '1,260p' q-system/.q-system/scripts/capability-map-gen.py && sed -n '260,620p' q-system/.q-system/scripts/capability-map-gen.py && sed -n '620,980p' q-system/.q-system/scripts/capability-map-gen.py && rg -n \"capability-map-gen|collect_engines|capability-map\" --glob '"'!q-system/output/**'"' --glob '"'!*.md'"' . && rg -n \"spec_from_file_location|"'^'"\\s*from\\s+\\.|"'^'"\\s*import\\s+["'^#]*," --glob '"'*.py' --glob '"'!q-system/output/**'"' . | head -200" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
#!/usr/bin/env python3
"""Generate a CAPABILITY-MAP.json for a kipi instance repo by structural recon.

Pairs with linear-sync.py (which turns a map into a Linear plan) and the SDLC
standard at q-system/output/plans/linear-sdlc-standard-2026-07-26.md.

WHY A GENERATOR AND NOT 24 HAND-WRITTEN MAPS (ASK-113): a hand-written map is
accurate for one afternoon. It drifts the moment a command is added, and nothing
detects the drift. This walks the repo and reports what is ACTUALLY there, so
re-running it is how you notice a capability appeared or a hook went dead.

WHAT IT WILL NOT DO: it does not judge whether a capability is *good*, and it does
not invent evidence. Every `evidence` string it emits is a fact it read off disk
(a path, a line count, a wiring reference it found or failed to find). Status is
derived from wiring, not from claims in prose. The senior-engineer triage pass
adds judgment on top of this; it does not replace it.

THE VALUABLE DETECTION: a hook wired in settings.json whose script does not exist
on disk. That is a dead enforcement gate -- the switch is on and nothing is behind
it -- and it is invisible to every prose-level review.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

# Layers, in the order they appear in the emitted map.
L_GOVERNANCE = "L0 Governance and rules"
L_COMMANDS = "L1 Commands"
L_SKILLS = "L2 Skills"
L_ENFORCEMENT = "L3 Enforcement and automation"
L_AGENTS = "L4 Agents"
L_ENGINES = "L5 Engines and scripts"
L_DOMAIN = "L6 Domain data"

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache",
    "dist", "build", ".next", ".claude-plugin", "archives",
    "site-packages", "dist-packages", "vendor", ".mypy_cache", ".ruff_cache",
    ".tox", "eggs", ".eggs", "htmlcov", ".terraform",
}

# Substrings that mark a vendored tree wherever they appear in a path. Directory
# NAME matching alone was not enough: 4_points_consulting keeps a virtualenv under
# q-investigate/ whose inner dirs are named lib/ and python3.x/, so a name-only
# filter admitted 5450 site-packages files as "engines" (recon run 2026-07-26).
VENDOR_MARKERS = ("site-packages", "dist-packages", "/node_modules/", "/.git/")


# Roots of git repos nested INSIDE the repo being scanned. Populated per run.
#
# WHY (ASK-113): several instances contain other instances. ASK_AI_consultant is
# ~/projects/consulting, which holds 12 sibling instance repos under projects/;
# gtm-partner is ~/projects/cole-gtm, which holds 5. Without this, a parent's map
# swallows every child's capabilities and the fleet is counted several times over
# (first full run: 12430 capabilities, badly inflated). A nested git repo is a
# separate unit of propagation and gets its own map and its own Linear project.
_NESTED_REPOS: set = set()


def find_nested_repos(root: Path) -> set:
    """Directories under `root` that are their own git repo (or worktree)."""
    found = set()
    for git in root.rglob(".git"):
        parent = git.parent
        if parent.resolve() == root.resolve():
            continue
        if any(d in SKIP_DIRS for d in parent.parts):
            continue
        found.add(parent.resolve())
    return found


def is_vendored(p: Path) -> bool:
    if any(d in SKIP_DIRS for d in p.parts):
        return True
    if _NESTED_REPOS:
        try:
            rp = p.resolve()
        except OSError:
            rp = p
        for nested in _NESTED_REPOS:
            if nested in rp.parents:
                return True
    s = "/" + str(p).replace(os.sep, "/") + "/"
    if any(m in s for m in VENDOR_MARKERS):
        return True
    # A virtualenv identifies itself with pyvenv.cfg at its root; anything under
    # such a directory is a dependency, not a capability of this repo.
    for parent in p.parents:
        if (parent / "pyvenv.cfg").exists():
            return True
        if parent.name in ("bin", "lib") and (parent.parent / "pyvenv.cfg").exists():
            return True
    return False


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except OSError:
        return ""


def frontmatter_description(text: str) -> str:
    """Pull `description:` out of a markdown frontmatter block, if present."""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    for line in text[3:end].splitlines():
        if line.strip().startswith("description:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return ""


def first_prose_line(text: str) -> str:
    """First real sentence, skipping frontmatter, headings, and code fences."""
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            body = text[end + 4:]
    in_fence = False
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s or s.startswith(("#", "|", ">", "-", "*", "<!--")):
            continue
        return s[:200]
    return ""


def summarize(text: str, fallback: str) -> str:
    return frontmatter_description(text) or first_prose_line(text) or fallback


def walk(root: Path, *parts):
    """Glob helper that skips vendored and cache directories."""
    base = root.joinpath(*parts[:-1]) if len(parts) > 1 else root
    if not base.is_dir():
        return []
    out = []
    for p in base.rglob(parts[-1]):
        if is_vendored(p):
            continue
        if p.is_file():
            out.append(p)
    return sorted(out)


def rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


# --- collectors ---------------------------------------------------------------


def collect_commands(root: Path) -> list:
    caps = []
    seen = set()
    for base in (root / ".claude" / "commands", root / "plugins"):
        if not base.is_dir():
            continue
        for p in base.rglob("*.md"):
            if is_vendored(p):
                continue
            if base.name == "plugins" and "commands" not in p.parts:
                continue
            name = f"/{p.stem}"
            if name in seen:
                continue
            seen.add(name)
            text = read_text(p)
            caps.append({
                "name": f"command {name}",
                "layer": L_COMMANDS,
                "status": "LIVE" if len(text.strip()) > 120 else "NEEDS_WORK",
                "summary": summarize(text, f"Slash command {name}."),
                "entry": rel(root, p),
                "trigger": f"manual: {name}",
                "evidence": f"{rel(root, p)}: {len(text.splitlines())} lines on disk."
                            + ("" if len(text.strip()) > 120 else " Body is near-empty, so the command is a stub."),
            })
    return caps


def collect_skills(root: Path) -> list:
    caps = []
    for p in root.rglob("SKILL.md"):
        if is_vendored(p):
            continue
        text = read_text(p)
        name = p.parent.name
        caps.append({
            "name": f"skill {name}",
            "layer": L_SKILLS,
            "status": "LIVE",
            "summary": summarize(text, f"Skill {name}."),
            "entry": rel(root, p),
            "trigger": "model-invoked, or an auto-invoke rule",
            "evidence": f"{rel(root, p)}: {len(text.splitlines())} lines on disk.",
        })
    return caps


def collect_rules(root: Path) -> list:
    caps = []
    for p in walk(root, ".claude", "rules", "*.md"):
        text = read_text(p)
        enforced = "ENFORCED" in text
        named = re.findall(r"[\w\-/]+\.(?:py|sh)\b", text)
        caps.append({
            "name": f"rule {p.stem}",
            "layer": L_GOVERNANCE,
            "status": "LIVE" if (not enforced or named) else "NEEDS_WORK",
            "summary": summarize(text, f"Rule {p.stem}."),
            "entry": rel(root, p),
            "trigger": "always-on instruction context",
            "evidence": (
                f"{rel(root, p)}: {len(text.splitlines())} lines; "
                + (f"claims ENFORCED and names {len(set(named))} executable(s)."
                   if enforced and named else
                   "claims ENFORCED but names NO executable, so it is prompt-only."
                   if enforced else "advisory, no enforcement claim.")
            ),
        })
    return caps


def collect_hooks(root: Path) -> list:
    """The high-value pass: a hook wired in settings.json whose script is gone."""
    caps = []
    settings = root / ".claude" / "settings.json"
    if not settings.is_file():
        return caps
    try:
        data = json.loads(read_text(settings) or "{}")
    except json.JSONDecodeError:
        return [{
            "name": "hook wiring (settings.json)",
            "layer": L_ENFORCEMENT,
            "status": "BROKEN",
            "summary": "settings.json does not parse as JSON, so no hook in it can load.",
            "entry": rel(root, settings),
            "trigger": "session lifecycle",
            "evidence": f"{rel(root, settings)}: json.JSONDecodeError on parse.",
        }]

    for event, groups in (data.get("hooks") or {}).items():
    for event, groups in (data.get("hooks") or {}).items():
        for group in groups if isinstance(groups, list) else []:
            for hook in (group.get("hooks") or []):
                cmd = hook.get("command") or ""
                scripts = re.findall(r"[\w\-./${}]+\.(?:py|sh)", cmd)
                resolved, missing = [], []
                for s in scripts:
                    clean = (s.replace("${CLAUDE_PROJECT_DIR}", "")
                              .replace("$CLAUDE_PROJECT_DIR", "").lstrip("/"))
                    if "${" in clean or "$" in clean:
                        continue
                    (resolved if (root / clean).is_file() else missing).append(clean)
                if not scripts:
                    continue
                label = os.path.basename(scripts[0])
                # Matcher is part of the identity: one script can be wired to
                # several events/matchers, and those are different capabilities.
                # Without it, investigations' two PostToolUse run-lint.sh hooks
                # produced the same name AND the same entry, so even the path-hash
                # disambiguation collided (linear-sync exit 3, 2026-07-26).
                matcher = str(group.get("matcher") or "all")
                caps.append({
                    "name": f"hook {label} ({event}/{matcher})",
                    "layer": L_ENFORCEMENT,
                    "status": "BROKEN" if missing else "LIVE",
                    "summary": (f"{event} hook running {label}."
                                + (" Its script is MISSING from disk."
                                   if missing else "")),
                    "entry": f".claude/settings.json -> {scripts[0]} [{event}/{matcher}]",
                    "trigger": f"{event} ({group.get('matcher', 'all')})",
                    "evidence": (
                        f"Wired in .claude/settings.json under {event}. "
                        + (f"MISSING on disk: {', '.join(missing)}. The switch is on "
                           f"and nothing is behind it."
                           if missing else
                           f"Script present: {', '.join(resolved) if resolved else label}.")
                    ),
                })
    return caps


def collect_agents(root: Path) -> list:
    caps = []
    for p in walk(root, ".claude", "agents", "*.md"):
        text = read_text(p)
        m = re.search(r"^model:\s*(\S+)", text, re.M)
        caps.append({
            "name": f"agent {p.stem}",
            "layer": L_AGENTS,
            "status": "LIVE" if m else "NEEDS_WORK",
            "summary": summarize(text, f"Agent {p.stem}."),
            "entry": rel(root, p),
            "trigger": "invoked by an orchestrator or the Agent tool",
            "evidence": (f"{rel(root, p)}: model pinned to {m.group(1)}."
                         if m else
                         f"{rel(root, p)}: NO model: frontmatter, so tier is unpinned."),
        })
    return caps


def _docstring_line(text: str) -> str:
    """First line of a module docstring, or '' if there is not a well-formed one."""
    parts = text.split('"""')
    if len(parts) < 3:
        return ""
    lines = [ln.strip() for ln in parts[1].strip().splitlines() if ln.strip()]
    return lines[0][:180] if lines else ""


# Files whose CONTENT can wire an engine. A mention anywhere in one of these is a
# reference; markdown is handled separately below because prose is not wiring.
SURFACE_CODE_EXT = {
    ".py", ".sh", ".bash", ".zsh", ".yml", ".yaml", ".toml", ".json",
    ".cfg", ".ini", ".mk", ".txt",
}
SURFACE_DOC_EXT = {".md"}
# Extensionless wiring surfaces (the kipi CLI, Makefiles, lefthook's shell blocks).
SURFACE_NAMES = {"Makefile", "makefile", "kipi", "Dockerfile", "Justfile", "justfile"}

# GENERATED ARTIFACTS ARE NOT WIRING SURFACES (ASK-122, caught pre-merge).
#
# Widening the scan repo-wide swept in q-system/output/, which holds codex
# transcripts, run logs, plans and RCAs. Those name scripts constantly and run
# nothing. Measured on kipi-investigations: _sync_all.py flipped to LIVE on the
# strength of `q-system/output/codex-sfactivity-prd-out.txt` line 738, a bare
# `find`-style listing `./plugins/.../_sync_all.py`.
#
# The invocation filter cannot save this: that line starts with "./" and so
# matches MD_INVOCATION_RE. A log of a command that ENUMERATED files is
# indistinguishable, line by line, from a runbook that INVOKES one. The only
# durable separator is provenance -- who wrote the file -- so the fix is to drop
# generated trees from the surface rather than to write a cleverer regex.
#
# q-system/output/ is the OS's generated-artifacts directory by convention; it is
# also in kipi-update.sh's INSTANCE_OWNED_SUBTREES, i.e. already understood
# fleet-wide as an instance's own output rather than source.
GENERATED_SURFACE_PREFIXES = ("q-system/output/",)


def _witness_rank(p: Path):
    """Sort key that prefers a REAL caller over a scratch/hidden copy of one.

    Any path component starting with "." is a review tree, a worktree or a tool
    cache, never the wiring a reader should be sent to look at.
    """
    parts = p.parts
    hidden = any(part.startswith(".") for part in parts)
    return (hidden, len(parts), str(p))


def is_generated_surface(p: Path, root: Path) -> bool:
    """True when p is a generated artifact, so its content must not count as wiring."""
    try:
        rel = p.relative_to(root).as_posix()
    except ValueError:
        return False
    return rel.startswith(GENERATED_SURFACE_PREFIXES)

# A markdown line only counts as wiring if it INVOKES something. A findings doc
# saying "engine_x.py left the template unfilled" names a script without keeping it
# alive; a runbook line `python3 engine_x.py` does. Without this split, widening the
# scan repo-wide just trades false-dead for false-alive (ASK-122).
MD_INVOCATION_RE = re.compile(r"(?:python3?\s|bash\s|\bsh\s|\./|source\s|-m\s)")

# Module tokens an engine can be reached by WITHOUT its .py suffix. `import x`,
# `from x import y`, `python -m x`, and importlib's spec_from_file_location("x", ...)
# are all real callers that a filename-only scan reads as silence. Scar: ASK-230,
# where provenance_vocabulary.py had two live importers and was reported inert
# because both wrote `import provenance_vocabulary` with no extension.
MODULE_REF_RE = re.compile(
    r"^\s*from\s+([\w.]+)\s+import\b"
    r"|^\s*import\s+([\w.]+)"
    r"|spec_from_file_location\(\s*[\"']([\w.\-]+)[\"']"
    r"|-m\s+([\w.]+)\b",
    re.M,
)


# `fill_sheet.2026-07-28.py` beside `fill_sheet.py` is a dated SNAPSHOT of an
# engine, not a second engine. Alice's run-sweep.sh writes one before every sweep
# (`cp "$GEN/fill_sheet.py" "$DIR/backups/fill_sheet.$TODAY.py"`) and copies it back
# on failure, so it is live DATA on a rollback path. No static scan can ever match
# it -- the caller interpolates $TODAY -- so it would report UNWIRED forever and
# the only way to "fix" it is to delete a rollback artifact (ASK-122).
DATED_SNAPSHOT_RE = re.compile(r"\.\d{4}-\d{2}-\d{2}$")


def _is_test_file(p: Path) -> bool:
    return p.name.startswith(("test_", "test-")) or "test" in p.parts or "tests" in p.parts


def _iter_surface_files(root: Path):
    """Every file in the repo whose content can constitute wiring.

    WHY REPO-WIDE (ASK-122): the previous list walked only .claude/, plugins/ and
    q-system/, so an instance whose code lives anywhere else reported its own
    runners as absent. Alice flagged 22 engines UNWIRED while `regenerate.sh` ran
    four of them by path and `pipeline.py` imported two more. The scan has to
    follow the repo, not a layout the skeleton happens to use.
    """
    for p in root.rglob("*"):
        if not p.is_file() or is_vendored(p):
            continue
        if is_generated_surface(p, root):
            continue
        if p.suffix.lower() in SURFACE_CODE_EXT or p.suffix.lower() in SURFACE_DOC_EXT:
            yield p
        elif p.name in SURFACE_NAMES:
            yield p


def _build_reference_index(root: Path, engines: list) -> dict:
    """Map each engine path -> the set of OTHER files that reference it.

    Two ways to match: the file name (`foo.py`, seen in shell/CLI invocations and
    config) and the bare module name, but the bare name ONLY inside an import or
    loader construct. A generic stem like `pipeline` appears in ordinary prose all
    over this fleet; counting bare-word hits would mark half the repo live.
    """
    by_filename = {}
    by_module = {}
    for p in engines:
        by_filename.setdefault(p.name, []).append(p)
        by_module.setdefault(p.stem, []).append(p)
    if not by_filename:
        return {}

    # One alternation, one pass per file: a per-engine regex would be
    # len(engines) x len(files) scans, which is minutes on a large instance.
    # The lookbehind must NOT exclude "/": the common form is path-qualified
    # (`python3 "$G/fill_sheet.py"`), and blocking it hid every shell caller.
    filename_re = re.compile(
        r"(?<![\w.\-])(" + "|".join(re.escape(n) for n in sorted(by_filename)) + r")(?![\w\-])"
    )

    refs: dict = {}
    for src in _iter_surface_files(root):
        text = read_text(src)
        if not text:
            continue
        if src.suffix.lower() in SURFACE_DOC_EXT:
            text = "\n".join(ln for ln in text.splitlines() if MD_INVOCATION_RE.search(ln))
            if not text:
                continue
        for match in filename_re.finditer(text):
            for engine in by_filename[match.group(1)]:
                if engine != src:
                    refs.setdefault(engine, set()).add(src)
        for match in MODULE_REF_RE.finditer(text):
            token = next((g for g in match.groups() if g), None)
            if not token:
                continue
            for part in (token, token.rsplit(".", 1)[-1]):
                for engine in by_module.get(part, ()):
                    if engine != src:
                        refs.setdefault(engine, set()).add(src)
    return refs


def collect_engines(root: Path) -> list:
    """Scripts that have a paired test, or that are referenced from a wiring
    surface. An engine with neither is reported UNWIRED rather than assumed fine."""
    caps = []
    tests = {p.name for p in root.rglob("test*") if p.is_file() and not is_vendored(p)}

    engines = []
    for p in root.rglob("*.py"):
        if is_vendored(p):
            continue
        if p.name.startswith(("test_", "test-")) or "test" in p.parts:
            continue
        # A generated tree is not a wiring surface (see is_generated_surface), so
        # it must not be an ENGINE source either. Excluding it from only one of
        # the two makes its contents permanently dark: still collected, but with
        # every file that could reference them now off-surface, so they report
        # UNWIRED with no way to ever clear it (review finding, PR #74 major;
        # would have compounded sp-3761d2d9). An artifact is not an engine, so
        # the coherent move is to stop reporting it at all rather than to report
        # it as dead. Measured: drops 12 phantom engines in kipi-investigations.
        if is_generated_surface(p, root):
            continue
        if DATED_SNAPSHOT_RE.search(p.stem):
            continue
        if len(read_text(p).splitlines()) < 40:
            continue
        engines.append(p)

    refs = _build_reference_index(root, engines)

    for p in engines:
        text = read_text(p)
        sources = refs.get(p, set())
        # WITNESS ORDER IS NOT ALPHABETICAL (review finding, PR #74 minor).
        # Plain sorted()[0] puts dot-prefixed paths first, so the evidence named
        # a review scratch tree (.pr42rev/, .claude/worktrees/) instead of the
        # real caller in 163 of 785 witnesses measured across five repos. The
        # verdict was right and the citation was useless, which is worse than it
        # sounds: the citation is the only part a human re-checks.
        test_sources = sorted((s for s in sources if _is_test_file(s)), key=_witness_rank)
        wiring_sources = sorted((s for s in sources if not _is_test_file(s)), key=_witness_rank)
        has_test = any(p.stem in t for t in tests) or bool(test_sources)
        referenced = bool(wiring_sources)
        status = "LIVE" if (has_test or referenced) else "UNWIRED"
        bits = []
        if has_test:
            witness = rel(root, test_sources[0]) if test_sources else "name-matched test file"
            bits.append(f"has a paired test ({witness})")
        if referenced:
            bits.append(f"referenced on a wiring surface ({rel(root, wiring_sources[0])})")
        if not bits:
            bits.append("NO test and NO wiring reference found")
        caps.append({
            "name": f"engine {p.stem}",
            "layer": L_ENGINES,
            "status": status,
            # A file can contain a single unpaired \"\"\" (inside a string, or a
            # truncated file), so index [1] is not safe and an empty docstring
            # has no [0] line. Fall back rather than lose the whole collector.
            "summary": _docstring_line(text) or f"Python engine {p.name}.",
            "entry": rel(root, p),
            "trigger": "called by a hook, a command, or another script",
            "evidence": f"{rel(root, p)}: {len(text.splitlines())} lines; " + ", ".join(bits) + ".",
        })
    return caps


def collect_domains(root: Path) -> list:
    caps = []
    for p in sorted(root.glob("q-*")):
        if not p.is_dir() or p.name in ("q-system",):
            continue
        files = [f for f in p.rglob("*") if f.is_file() and not is_vendored(f)]
        caps.append({
            "name": f"domain {p.name}",
            "layer": L_DOMAIN,
            "status": "LIVE" if files else "NEEDS_WORK",
            "summary": f"Instance-specific domain directory {p.name}/.",
            "entry": p.name + "/",
            "trigger": "read by this instance's commands and skills",
            "evidence": f"{p.name}/: {len(files)} file(s) on disk.",
        })
    return caps


def dedupe(caps: list) -> list:
    """Two capabilities that slugify to one key would collapse into one permanent
    Linear issue, so disambiguate here rather than letting linear-sync refuse.

    The suffix is a hash of the ENTRY PATH, not a counter. A counter collided for
    real: one registered instance has a file that legitimately produces "engine core 2",
    and a second "engine core" was being renamed to "engine core (2)", which
    slugifies to the same key. linear-sync's collision guard caught it (exit 3),
    which is the guard working, but the generator should not emit the collision in
    the first place. A path hash is unique by construction and stable across runs,
    so re-running does not reshuffle keys and orphan already-created issues.
    """
    slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    seen, out = {}, []
    for cap in caps:
        base = cap["name"]
        k = slug(base)
        # Loop, do not single-shot. Hashing the entry alone is not enough when the
        # entries are themselves identical: kipi-investigations wires run-lint.sh
        # four times under the same event and matcher with different command
        # arguments, so all four hashed the same and stayed collided even after
        # renaming. Folding the ordinal into the hash terminates and is stable for
        # a given (entry, ordinal) pair.
        ordinal = 0
        while k in seen:
            ordinal += 1
            tag = hashlib.sha1(
                f"{cap.get('entry') or base}#{ordinal}".encode()
            ).hexdigest()[:6]
            cap["name"] = f"{base} [{tag}]"
            k = slug(cap["name"])
        seen[k] = True
        out.append(cap)
    return out


def tag_origin(caps: list, root: Path, skeleton: Path) -> list:
    """Mark each capability skeleton-propagated or instance-local.

    WHY THIS IS LOAD-BEARING (ASK-113): `kipi update` rsyncs .claude/rules/,
    .claude/agents/, q-system/ and plugins/ from the skeleton into all 24
    instances. Those capabilities are therefore THE SAME capability, present 24
    times. Filing an issue per instance for a skeleton rule would create ~24
    permanent duplicates of one problem and would itself be the fleet-homogeneity
    violation this whole exercise exists to find.

    A shared capability is tracked ONCE, in the kipi-system project. Instance maps
    still RECORD it (the overlap pass needs to see it) but set track=false so it
    never becomes an issue in the instance's project.

    The test is path existence in the skeleton, which is exactly what rsync
    copies, so it cannot drift from the propagation it models.
    """
    for cap in caps:
        entry = (cap.get("entry") or "").split(" -> ")[0].strip()
        is_shared = False
        if entry and not entry.startswith("/"):
        if entry and not entry.startswith("/"):
            candidate = skeleton / entry
            is_shared = candidate.exists() and root.resolve() != skeleton.resolve()
        cap["origin"] = "skeleton" if is_shared else "local"
        # Track locally only what this repo actually owns.
        cap["track"] = not is_shared
    return caps


def build(root: Path, repo: str, skeleton: Path) -> dict:
    global _NESTED_REPOS
    _NESTED_REPOS = find_nested_repos(root)
    caps = []
    for fn in (collect_rules, collect_commands, collect_skills, collect_hooks,
               collect_agents, collect_engines, collect_domains):
        try:
            caps.extend(fn(root))
        except Exception as exc:  # one bad collector must not lose the rest
            print(f"WARN: {fn.__name__} failed on {repo}: {exc}", file=sys.stderr)
    caps = dedupe(caps)
    caps = tag_origin(caps, root, skeleton)

    counts, origins = {}, {}
    for cap in caps:
        counts[cap["status"]] = counts.get(cap["status"], 0) + 1
        origins[cap["origin"]] = origins.get(cap["origin"], 0) + 1
    trackable = [c for c in caps if c["track"] and c["status"] != "LIVE"]
    return {
        "_readme": (
            "Generated by q-system/.q-system/scripts/capability-map-gen.py from "
            "structural recon of this repo. Every 'evidence' string is a fact read "
            "off disk, not a claim. Status is derived from wiring: BROKEN means a "
            "hook is wired to a script that is not there; UNWIRED means an engine "
            "has neither a test nor a wiring reference. Re-run to detect drift."
        ),
        "repo": repo,
        "root": str(root),
        "summary": f"Capabilities of the {repo} repo: {len(caps)} detected.",
        "nested_repos_excluded": sorted(str(n) for n in _NESTED_REPOS),
        "status_counts": counts,
        "origin_counts": origins,
        "actionable_local": len(trackable),
        "capabilities": caps,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a CAPABILITY-MAP.json by recon.")
    ap.add_argument("--root", required=True, help="repo root to scan")
    ap.add_argument("--repo", required=True, help="repo/instance name")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skeleton", default=os.path.join(os.path.dirname(__file__), "..", "..", ".."),
                    help="skeleton repo root; capabilities that also exist there are "
                         "kipi update propagations and are tracked once, in kipi-system")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"BLOCK: {root} is not a directory", file=sys.stderr)
        return 1
    cmap = build(root, args.repo, Path(args.skeleton).resolve())
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(cmap, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    counts = ", ".join(f"{k}={v}" for k, v in sorted(cmap["status_counts"].items()))
    origins = ", ".join(f"{k}={v}" for k, v in sorted(cmap["origin_counts"].items()))
    print(f"{args.repo}: {len(cmap['capabilities'])} capabilities ({counts}) "
          f"[{origins}] -> {cmap['actionable_local']} actionable+local -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
./kipi:153:gen = os.path.join(home, "q-system/.q-system/scripts/capability-map-gen.py")
./kipi:154:outdir = os.path.join(home, "q-system/output/capability-maps")
./kipi:167:          --maps "$KIPI_HOME/q-system/output/capability-maps" \
./automation/test_voice_refresh.py:13:_spec = importlib.util.spec_from_file_location("voice_refresh", os.path.join(_HERE, "voice_refresh.py"))
./scripts/reorg-stale-ref-audit.py:26:import os, re, sys, subprocess
./scripts/reorg-stale-ref-audit.py:37:_spec = _ilu.spec_from_file_location("persona_reorg", _PR_PATH)
./scripts/test_persona_reorg_detach.py:25:_spec = ilu.spec_from_file_location("persona_reorg", _PR)
./scripts/test_persona_reorg.py:13:_spec = ilu.spec_from_file_location("persona_reorg", _PR)
./q-system/lib/kipi_ingest/readers/markdown.py:12:from ..contract import Block, Drop, ReadResult, make_block_id
./q-system/lib/kipi_ingest/__init__.py:14:from .contract import (
./q-system/lib/kipi_ingest/readers/xlsx_reader.py:15:from ..contract import Block, Drop, ReadResult, make_block_id
./q-system/lib/kipi_ingest/readers/csv_reader.py:13:from ..contract import Block, Drop, ReadResult, make_block_id
./validate-separation.py:538:    spec = importlib.util.spec_from_file_location(
./q-system/lib/kipi_ingest/readers/__init__.py:10:from .markdown import read_md
./q-system/lib/kipi_ingest/readers/__init__.py:11:from .csv_reader import read_csv
./q-system/lib/kipi_ingest/readers/__init__.py:12:from .xlsx_reader import read_xlsx  # openpyxl imported lazily inside read_xlsx
./plugins/prd-os/tests/test_prd_split_from_linear.py:149:    spec = importlib.util.spec_from_file_location("dsse_issue_runner", ISSUE_RUNNER)
./plugins/prd-os/tests/test_findings_xref.py:35:    spec = importlib.util.spec_from_file_location(name, path)
./plugins/prd-os/tests/test_gate_lifecycle.py:103:    spec = importlib.util.spec_from_file_location("prd_runner_lifecycle", PRD_RUNNER)
./plugins/prd-os/tests/test_findings_writer.py:725:    spec = importlib.util.spec_from_file_location(
./plugins/prd-os/tests/test_spillover.py:43:    spec = importlib.util.spec_from_file_location("prd_runner_under_test", PRD_RUNNER)
./plugins/prd-os/tests/conftest.py:32:    spec = importlib.util.spec_from_file_location(
./plugins/prd-os/tests/test_concurrency.py:25:    spec = importlib.util.spec_from_file_location(
./plugins/kipi-design/skills/ui-ux-pro-max/src/data/_sync_all.py:10:import csv, os, json
./plugins/prd-os/scripts/prd_split.py:644:    spec = importlib.util.spec_from_file_location("kipi_linear_sync", client_path)
./plugins/kipi-design/skills/ui-ux-pro-max/data/_sync_all.py:10:import csv, os, json
./plugins/kipi-core/kipi-mcp/tests/test_morning_init.py:243:        import os, time
./plugins/kipi-design/hooks/test_dogfood_gate.py:12:import sys, os
./plugins/kipi-design/hooks/dogfood_gate.py:29:import json, os, re, sys

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'python3 q-system/.q-system/scripts/test/test-capability-map-wiring.py && python3 q-system/.q-system/scripts/capability-map-gen.py --root . --repo pr-74-review --out "$TMPDIR/pr74-capability-map.json" --skeleton . && python3 - <<'"'PY'
import json, os
from collections import Counter, defaultdict
from pathlib import Path
p = Path(os.environ['TMPDIR']) / 'pr74-capability-map.json'
data = json.loads(p.read_text())
engines = [c for c in data['capabilities'] if c['layer'] == 'L5 Engines and scripts']
print('engines', len(engines), Counter(c['status'] for c in engines))
by_name = defaultdict(list)
for c in engines:
    by_name[Path(c['entry']).name].append(c)
for name, vals in sorted(by_name.items()):
    if len(vals) > 1:
        print('\\nDUP', name, len(vals))
        for c in vals:
            print(c['entry'], c['status'], c['evidence'])
PY" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 1715ms:
pr-74-review: 397 capabilities (LIVE=377, NEEDS_WORK=9, UNWIRED=11) [local=397] -> 20 actionable+local -> /var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T//pr74-capability-map.json
engines 284 Counter({'LIVE': 273, 'UNWIRED': 11})

DUP _sync_all.py 2
plugins/kipi-design/skills/ui-ux-pro-max/data/_sync_all.py LIVE plugins/kipi-design/skills/ui-ux-pro-max/data/_sync_all.py: 414 lines; has a paired test (q-system/.q-system/scripts/test/test-capability-map-wiring.py), referenced on a wiring surface (q-system/.q-system/scripts/capability-map-gen.py).
plugins/kipi-design/skills/ui-ux-pro-max/src/data/_sync_all.py LIVE plugins/kipi-design/skills/ui-ux-pro-max/src/data/_sync_all.py: 414 lines; has a paired test (q-system/.q-system/scripts/test/test-capability-map-wiring.py), referenced on a wiring surface (q-system/.q-system/scripts/capability-map-gen.py).

DUP accept-rate.py 2
q-system/.q-system/scripts/accept-rate.py LIVE q-system/.q-system/scripts/accept-rate.py: 300 lines; referenced on a wiring surface (.prd-os/issues/accept-rate-metric-script.md).
.pr25rev/mut/q-system/.q-system/scripts/accept-rate.py LIVE .pr25rev/mut/q-system/.q-system/scripts/accept-rate.py: 300 lines; referenced on a wiring surface (.prd-os/issues/accept-rate-metric-script.md).

DUP audhd-lint.py 2
q-system/.q-system/scripts/audhd-lint.py LIVE q-system/.q-system/scripts/audhd-lint.py: 283 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/audhd-lint.py LIVE .pr25rev/mut/q-system/.q-system/scripts/audhd-lint.py: 283 lines; referenced on a wiring surface (settings-template.json).

DUP batch-uniformity-lint.py 2
q-system/.q-system/scripts/batch-uniformity-lint.py LIVE q-system/.q-system/scripts/batch-uniformity-lint.py: 213 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/batch-uniformity-lint.py LIVE .pr25rev/mut/q-system/.q-system/scripts/batch-uniformity-lint.py: 213 lines; referenced on a wiring surface (settings-template.json).

DUP canonical-digest.py 2
q-system/.q-system/scripts/canonical-digest.py LIVE q-system/.q-system/scripts/canonical-digest.py: 264 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
.pr25rev/mut/q-system/.q-system/scripts/canonical-digest.py LIVE .pr25rev/mut/q-system/.q-system/scripts/canonical-digest.py: 264 lines; referenced on a wiring surface (q-system/.q-system/scripts/canonical-digest.py).

DUP capability-gate.py 2
q-system/.q-system/scripts/capability-gate.py LIVE q-system/.q-system/scripts/capability-gate.py: 571 lines; has a paired test (q-system/.q-system/scripts/test_capability_gate.py), referenced on a wiring surface (fleet-capability-verify.py).
.pr25rev/mut/q-system/.q-system/scripts/capability-gate.py LIVE .pr25rev/mut/q-system/.q-system/scripts/capability-gate.py: 571 lines; has a paired test (q-system/.q-system/scripts/test_capability_gate.py), referenced on a wiring surface (fleet-capability-verify.py).

DUP capability-map-gen.py 2
q-system/.q-system/scripts/capability-map-gen.py LIVE q-system/.q-system/scripts/capability-map-gen.py: 693 lines; has a paired test (q-system/.q-system/scripts/test/test-capability-map-wiring.py), referenced on a wiring surface (kipi).
.pr25rev/mut/q-system/.q-system/scripts/capability-map-gen.py LIVE .pr25rev/mut/q-system/.q-system/scripts/capability-map-gen.py: 535 lines; has a paired test (q-system/.q-system/scripts/test/test-capability-map-wiring.py), referenced on a wiring surface (kipi).

DUP capability-overlap.py 2
q-system/.q-system/scripts/capability-overlap.py LIVE q-system/.q-system/scripts/capability-overlap.py: 305 lines; referenced on a wiring surface (kipi).
.pr25rev/mut/q-system/.q-system/scripts/capability-overlap.py LIVE .pr25rev/mut/q-system/.q-system/scripts/capability-overlap.py: 305 lines; referenced on a wiring surface (kipi).

DUP changelog-write.py 2
q-system/.q-system/scripts/changelog-write.py LIVE q-system/.q-system/scripts/changelog-write.py: 86 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).
.pr25rev/mut/q-system/.q-system/scripts/changelog-write.py LIVE .pr25rev/mut/q-system/.q-system/scripts/changelog-write.py: 86 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).

DUP code_claim_grounding_guard.py 2
q-system/.q-system/scripts/code_claim_grounding_guard.py LIVE q-system/.q-system/scripts/code_claim_grounding_guard.py: 296 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/code_claim_grounding_guard.py LIVE .pr25rev/mut/q-system/.q-system/scripts/code_claim_grounding_guard.py: 194 lines; referenced on a wiring surface (settings-template.json).

DUP collection-gate.py 2
q-system/.q-system/scripts/collection-gate.py LIVE q-system/.q-system/scripts/collection-gate.py: 162 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
.pr25rev/mut/q-system/.q-system/scripts/collection-gate.py LIVE .pr25rev/mut/q-system/.q-system/scripts/collection-gate.py: 162 lines; referenced on a wiring surface (q-system/.q-system/scripts/collection-gate.py).

DUP compliance-check.py 2
q-system/.q-system/scripts/compliance-check.py LIVE q-system/.q-system/scripts/compliance-check.py: 354 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
.pr25rev/mut/q-system/.q-system/scripts/compliance-check.py LIVE .pr25rev/mut/q-system/.q-system/scripts/compliance-check.py: 354 lines; referenced on a wiring surface (q-system/.q-system/scripts/compliance-check.py).

DUP concurrency.py 2
plugins/kipi-dsse/scripts/concurrency.py LIVE plugins/kipi-dsse/scripts/concurrency.py: 86 lines; has a paired test (plugins/prd-os/tests/test_concurrency.py), referenced on a wiring surface (plugins/kipi-dsse/scripts/issue_runner.py).
plugins/prd-os/scripts/concurrency.py LIVE plugins/prd-os/scripts/concurrency.py: 86 lines; has a paired test (plugins/prd-os/tests/test_concurrency.py), referenced on a wiring surface (plugins/kipi-dsse/scripts/issue_runner.py).

DUP conftest.py 2
plugins/kipi-core/kipi-mcp/tests/conftest.py UNWIRED plugins/kipi-core/kipi-mcp/tests/conftest.py: 110 lines; NO test and NO wiring reference found.
plugins/prd-os/tests/conftest.py UNWIRED plugins/prd-os/tests/conftest.py: 175 lines; NO test and NO wiring reference found.

DUP containment-targets.py 2
q-system/.q-system/scripts/containment-targets.py LIVE q-system/.q-system/scripts/containment-targets.py: 225 lines; has a paired test (q-system/.q-system/scripts/test/test-containment-gitlink.py), referenced on a wiring surface (validate-separation.py).
.pr25rev/mut/q-system/.q-system/scripts/containment-targets.py LIVE .pr25rev/mut/q-system/.q-system/scripts/containment-targets.py: 204 lines; has a paired test (q-system/.q-system/scripts/test/test-containment-gitlink.py), referenced on a wiring surface (validate-separation.py).

DUP content-lint.py 2
q-system/.q-system/scripts/content-lint.py LIVE q-system/.q-system/scripts/content-lint.py: 164 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).
.pr25rev/mut/q-system/.q-system/scripts/content-lint.py LIVE .pr25rev/mut/q-system/.q-system/scripts/content-lint.py: 164 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).

DUP copy-diff.py 2
q-system/.q-system/scripts/copy-diff.py LIVE q-system/.q-system/scripts/copy-diff.py: 236 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
.pr25rev/mut/q-system/.q-system/scripts/copy-diff.py LIVE .pr25rev/mut/q-system/.q-system/scripts/copy-diff.py: 236 lines; referenced on a wiring surface (q-system/.q-system/scripts/copy-diff.py).

DUP core.py 4
plugins/kipi-design/skills/design/scripts/cip/core.py LIVE plugins/kipi-design/skills/design/scripts/cip/core.py: 215 lines; has a paired test (name-matched test file), referenced on a wiring surface (plugins/kipi-design/skills/ui-ux-pro-max/scripts/design_system.py).
plugins/kipi-design/skills/design/scripts/logo/core.py LIVE plugins/kipi-design/skills/design/scripts/logo/core.py: 175 lines; has a paired test (name-matched test file), referenced on a wiring surface (plugins/kipi-design/skills/ui-ux-pro-max/scripts/design_system.py).
plugins/kipi-design/skills/ui-ux-pro-max/scripts/core.py LIVE plugins/kipi-design/skills/ui-ux-pro-max/scripts/core.py: 262 lines; has a paired test (name-matched test file), referenced on a wiring surface (plugins/kipi-design/skills/ui-ux-pro-max/scripts/design_system.py).
plugins/kipi-design/skills/ui-ux-pro-max/src/scripts/core.py LIVE plugins/kipi-design/skills/ui-ux-pro-max/src/scripts/core.py: 262 lines; has a paired test (name-matched test file), referenced on a wiring surface (plugins/kipi-design/skills/ui-ux-pro-max/scripts/design_system.py).

DUP correction_outcome.py 2
q-system/.q-system/scripts/correction_outcome.py LIVE q-system/.q-system/scripts/correction_outcome.py: 84 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/scripts/memory_autocapture.py).
.pr25rev/mut/q-system/.q-system/scripts/correction_outcome.py LIVE .pr25rev/mut/q-system/.q-system/scripts/correction_outcome.py: 84 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/scripts/correction_outcome.py).

DUP decision-origin-tag-lint.py 2
q-system/.q-system/scripts/decision-origin-tag-lint.py LIVE q-system/.q-system/scripts/decision-origin-tag-lint.py: 182 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/decision-origin-tag-lint.py LIVE .pr25rev/mut/q-system/.q-system/scripts/decision-origin-tag-lint.py: 182 lines; referenced on a wiring surface (settings-template.json).

DUP design_system.py 2
plugins/kipi-design/skills/ui-ux-pro-max/scripts/design_system.py LIVE plugins/kipi-design/skills/ui-ux-pro-max/scripts/design_system.py: 1067 lines; referenced on a wiring surface (plugins/kipi-design/skills/ui-ux-pro-max/scripts/search.py).
plugins/kipi-design/skills/ui-ux-pro-max/src/scripts/design_system.py LIVE plugins/kipi-design/skills/ui-ux-pro-max/src/scripts/design_system.py: 1067 lines; referenced on a wiring surface (plugins/kipi-design/skills/ui-ux-pro-max/scripts/design_system.py).

DUP firecrawl-scrape.py 2
q-system/.q-system/scripts/firecrawl-scrape.py LIVE q-system/.q-system/scripts/firecrawl-scrape.py: 70 lines; has a paired test (q-system/.q-system/scripts/test/test-firecrawl-scrape.sh), referenced on a wiring surface (.prd-os/prds/prd-deterministic-reading-2026-07-28.md).
.pr25rev/mut/q-system/.q-system/scripts/firecrawl-scrape.py LIVE .pr25rev/mut/q-system/.q-system/scripts/firecrawl-scrape.py: 70 lines; has a paired test (q-system/.q-system/scripts/test/test-firecrawl-scrape.sh), referenced on a wiring surface (.prd-os/prds/prd-deterministic-reading-2026-07-28.md).

DUP fleet-board-refresh.py 2
q-system/.q-system/scripts/fleet-board-refresh.py LIVE q-system/.q-system/scripts/fleet-board-refresh.py: 101 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/fleet-board-refresh.py LIVE .pr25rev/mut/q-system/.q-system/scripts/fleet-board-refresh.py: 101 lines; referenced on a wiring surface (settings-template.json).

DUP fleet-health-daily.py 3
.review-tmp-pr11/scripts/fleet-health-daily.py LIVE .review-tmp-pr11/scripts/fleet-health-daily.py: 1020 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
q-system/.q-system/scripts/fleet-health-daily.py LIVE q-system/.q-system/scripts/fleet-health-daily.py: 1633 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
.pr25rev/mut/q-system/.q-system/scripts/fleet-health-daily.py LIVE .pr25rev/mut/q-system/.q-system/scripts/fleet-health-daily.py: 1633 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).

DUP fleet-loop-board.py 2
q-system/.q-system/scripts/fleet-loop-board.py LIVE q-system/.q-system/scripts/fleet-loop-board.py: 321 lines; referenced on a wiring surface (q-system/.q-system/scripts/fleet-board-refresh.py).
.pr25rev/mut/q-system/.q-system/scripts/fleet-loop-board.py LIVE .pr25rev/mut/q-system/.q-system/scripts/fleet-loop-board.py: 321 lines; referenced on a wiring surface (q-system/.q-system/scripts/fleet-board-refresh.py).

DUP format-lint.py 2
q-system/.q-system/scripts/format-lint.py LIVE q-system/.q-system/scripts/format-lint.py: 202 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/format-lint.py LIVE .pr25rev/mut/q-system/.q-system/scripts/format-lint.py: 202 lines; referenced on a wiring surface (settings-template.json).

DUP generate.py 3
plugins/kipi-design/skills/design/scripts/cip/generate.py LIVE plugins/kipi-design/skills/design/scripts/cip/generate.py: 484 lines; referenced on a wiring surface (plugins/kipi-core/skills/deck-ai/SKILL.md).
plugins/kipi-design/skills/design/scripts/logo/generate.py LIVE plugins/kipi-design/skills/design/scripts/logo/generate.py: 362 lines; referenced on a wiring surface (plugins/kipi-core/skills/deck-ai/SKILL.md).
plugins/kipi-design/skills/design/scripts/icon/generate.py LIVE plugins/kipi-design/skills/design/scripts/icon/generate.py: 487 lines; referenced on a wiring surface (plugins/kipi-core/skills/deck-ai/SKILL.md).

DUP granola-voice-fingerprint.py 2
q-system/.q-system/scripts/granola-voice-fingerprint.py LIVE q-system/.q-system/scripts/granola-voice-fingerprint.py: 95 lines; referenced on a wiring surface (automation/voice_refresh.py).
.pr25rev/mut/q-system/.q-system/scripts/granola-voice-fingerprint.py LIVE .pr25rev/mut/q-system/.q-system/scripts/granola-voice-fingerprint.py: 95 lines; referenced on a wiring surface (automation/voice_refresh.py).

DUP granola-voice-harvest.py 2
q-system/.q-system/scripts/granola-voice-harvest.py LIVE q-system/.q-system/scripts/granola-voice-harvest.py: 120 lines; has a paired test (automation/test_voice_refresh_command.py), referenced on a wiring surface (plugins/kipi-core/commands/voice-refresh.md).
.pr25rev/mut/q-system/.q-system/scripts/granola-voice-harvest.py LIVE .pr25rev/mut/q-system/.q-system/scripts/granola-voice-harvest.py: 120 lines; has a paired test (automation/test_voice_refresh_command.py), referenced on a wiring surface (plugins/kipi-core/commands/voice-refresh.md).

DUP granola-voice-synthesize.py 2
q-system/.q-system/scripts/granola-voice-synthesize.py LIVE q-system/.q-system/scripts/granola-voice-synthesize.py: 139 lines; referenced on a wiring surface (automation/voice_refresh.py).
.pr25rev/mut/q-system/.q-system/scripts/granola-voice-synthesize.py LIVE .pr25rev/mut/q-system/.q-system/scripts/granola-voice-synthesize.py: 139 lines; referenced on a wiring surface (automation/voice_refresh.py).

DUP headline-lint.py 2
q-system/.q-system/scripts/headline-lint.py LIVE q-system/.q-system/scripts/headline-lint.py: 314 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/headline-lint.py LIVE .pr25rev/mut/q-system/.q-system/scripts/headline-lint.py: 314 lines; referenced on a wiring surface (settings-template.json).

DUP instance-automation-guard.py 2
q-system/.q-system/scripts/instance-automation-guard.py LIVE q-system/.q-system/scripts/instance-automation-guard.py: 97 lines; has a paired test (q-system/.q-system/scripts/test/test-instance-automation-guard.sh), referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/instance-automation-guard.py LIVE .pr25rev/mut/q-system/.q-system/scripts/instance-automation-guard.py: 77 lines; has a paired test (q-system/.q-system/scripts/test/test-instance-automation-guard.sh), referenced on a wiring surface (settings-template.json).

DUP instance-diet.py 2
q-system/.q-system/scripts/instance-diet.py LIVE q-system/.q-system/scripts/instance-diet.py: 239 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
.pr25rev/mut/q-system/.q-system/scripts/instance-diet.py LIVE .pr25rev/mut/q-system/.q-system/scripts/instance-diet.py: 239 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).

DUP instance-fact-inventory.py 2
q-system/.q-system/scripts/instance-fact-inventory.py LIVE q-system/.q-system/scripts/instance-fact-inventory.py: 395 lines; has a paired test (q-system/.q-system/tests/separation/test_instance_fact_inventory.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
.pr25rev/mut/q-system/.q-system/scripts/instance-fact-inventory.py LIVE .pr25rev/mut/q-system/.q-system/scripts/instance-fact-inventory.py: 395 lines; has a paired test (q-system/.q-system/tests/separation/test_instance_fact_inventory.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).

DUP instruction-budget-audit.py 2
q-system/.q-system/scripts/instruction-budget-audit.py LIVE q-system/.q-system/scripts/instruction-budget-audit.py: 221 lines; referenced on a wiring surface (AGENTS.md).
.pr25rev/mut/q-system/.q-system/scripts/instruction-budget-audit.py LIVE .pr25rev/mut/q-system/.q-system/scripts/instruction-budget-audit.py: 221 lines; referenced on a wiring surface (AGENTS.md).

DUP launchd-health-check.py 2
q-system/.q-system/scripts/launchd-health-check.py LIVE q-system/.q-system/scripts/launchd-health-check.py: 484 lines; has a paired test (q-system/.q-system/scripts/test_launchd_health_check.py), referenced on a wiring surface (AUTONOMOUS-SYSTEMS.md).
.pr25rev/mut/q-system/.q-system/scripts/launchd-health-check.py LIVE .pr25rev/mut/q-system/.q-system/scripts/launchd-health-check.py: 484 lines; has a paired test (q-system/.q-system/scripts/test_launchd_health_check.py), referenced on a wiring surface (AUTONOMOUS-SYSTEMS.md).

DUP lessons-distill.py 2
q-system/.q-system/scripts/lessons-distill.py LIVE q-system/.q-system/scripts/lessons-distill.py: 243 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-daily-exit.sh), referenced on a wiring surface (AUTONOMOUS-SYSTEMS.md).
.pr25rev/mut/q-system/.q-system/scripts/lessons-distill.py LIVE .pr25rev/mut/q-system/.q-system/scripts/lessons-distill.py: 243 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-daily-exit.sh), referenced on a wiring surface (AUTONOMOUS-SYSTEMS.md).

DUP lessons-validator.py 2
q-system/.q-system/scripts/lessons-validator.py LIVE q-system/.q-system/scripts/lessons-validator.py: 85 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-validator.sh), referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/lessons-validator.py LIVE .pr25rev/mut/q-system/.q-system/scripts/lessons-validator.py: 85 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-validator.sh), referenced on a wiring surface (settings-template.json).

DUP lessons_scrub.py 2
q-system/.q-system/scripts/lessons_scrub.py LIVE q-system/.q-system/scripts/lessons_scrub.py: 89 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-scrub.sh), referenced on a wiring surface (q-system/.q-system/scripts/lessons-daily.sh).
.pr25rev/mut/q-system/.q-system/scripts/lessons_scrub.py LIVE .pr25rev/mut/q-system/.q-system/scripts/lessons_scrub.py: 89 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-scrub.sh), referenced on a wiring surface (q-system/.q-system/scripts/lessons-daily.sh).

DUP linear-claim.py 4
.review-scratch/repo/q-system/.q-system/scripts/linear-claim.py LIVE .review-scratch/repo/q-system/.q-system/scripts/linear-claim.py: 585 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
.pr28rev/root/q-system/.q-system/scripts/linear-claim.py LIVE .pr28rev/root/q-system/.q-system/scripts/linear-claim.py: 585 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
q-system/.q-system/scripts/linear-claim.py LIVE q-system/.q-system/scripts/linear-claim.py: 773 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
.pr25rev/mut/q-system/.q-system/scripts/linear-claim.py LIVE .pr25rev/mut/q-system/.q-system/scripts/linear-claim.py: 585 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).

DUP linear-dor-drafter.py 2
q-system/.q-system/scripts/linear-dor-drafter.py LIVE q-system/.q-system/scripts/linear-dor-drafter.py: 1261 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-dor-drafter-redrive.sh), referenced on a wiring surface (kipi).
.pr25rev/mut/q-system/.q-system/scripts/linear-dor-drafter.py LIVE .pr25rev/mut/q-system/.q-system/scripts/linear-dor-drafter.py: 560 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-dor-drafter-redrive.sh), referenced on a wiring surface (kipi).

DUP linear-issue-ref-check.py 2
q-system/.q-system/scripts/linear-issue-ref-check.py LIVE q-system/.q-system/scripts/linear-issue-ref-check.py: 153 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-issue-ref-check.sh), referenced on a wiring surface (kipi).
.pr25rev/mut/q-system/.q-system/scripts/linear-issue-ref-check.py LIVE .pr25rev/mut/q-system/.q-system/scripts/linear-issue-ref-check.py: 153 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-issue-ref-check.sh), referenced on a wiring surface (kipi).

DUP linear-job-migration.py 2
q-system/.q-system/scripts/linear-job-migration.py LIVE q-system/.q-system/scripts/linear-job-migration.py: 225 lines; referenced on a wiring surface (kipi).
.pr25rev/mut/q-system/.q-system/scripts/linear-job-migration.py LIVE .pr25rev/mut/q-system/.q-system/scripts/linear-job-migration.py: 225 lines; referenced on a wiring surface (kipi).

DUP linear-queue.py 2
q-system/.q-system/scripts/linear-queue.py LIVE q-system/.q-system/scripts/linear-queue.py: 225 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-queue.sh), referenced on a wiring surface (kipi).
.pr25rev/mut/q-system/.q-system/scripts/linear-queue.py LIVE .pr25rev/mut/q-system/.q-system/scripts/linear-queue.py: 225 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-queue.sh), referenced on a wiring surface (kipi).

DUP linear-sync.py 4
.review-scratch/repo/q-system/.q-system/scripts/linear-sync.py LIVE .review-scratch/repo/q-system/.q-system/scripts/linear-sync.py: 862 lines; has a paired test (.pr22rev/test-scratch-guard-push.sh), referenced on a wiring surface (kipi).
.review-tmp-pr11/scripts/linear-sync.py LIVE .review-tmp-pr11/scripts/linear-sync.py: 929 lines; has a paired test (.pr22rev/test-scratch-guard-push.sh), referenced on a wiring surface (kipi).
q-system/.q-system/scripts/linear-sync.py LIVE q-system/.q-system/scripts/linear-sync.py: 1203 lines; has a paired test (.pr22rev/test-scratch-guard-push.sh), referenced on a wiring surface (kipi).
.pr25rev/mut/q-system/.q-system/scripts/linear-sync.py LIVE .pr25rev/mut/q-system/.q-system/scripts/linear-sync.py: 989 lines; has a paired test (.pr22rev/test-scratch-guard-push.sh), referenced on a wiring surface (kipi).

DUP linkedin-format-lint.py 2
q-system/.q-system/scripts/linkedin-format-lint.py LIVE q-system/.q-system/scripts/linkedin-format-lint.py: 285 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/linkedin-format-lint.py LIVE .pr25rev/mut/q-system/.q-system/scripts/linkedin-format-lint.py: 285 lines; referenced on a wiring surface (settings-template.json).

DUP md-prune.py 2
q-system/.q-system/scripts/md-prune.py LIVE q-system/.q-system/scripts/md-prune.py: 229 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/md-prune.py LIVE .pr25rev/mut/q-system/.q-system/scripts/md-prune.py: 229 lines; referenced on a wiring surface (settings-template.json).

DUP memory-confidence-surface.py 2
q-system/.q-system/scripts/memory-confidence-surface.py LIVE q-system/.q-system/scripts/memory-confidence-surface.py: 115 lines; has a paired test (q-system/.q-system/scripts/test_memory_confidence_surface.py), referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/memory-confidence-surface.py LIVE .pr25rev/mut/q-system/.q-system/scripts/memory-confidence-surface.py: 115 lines; has a paired test (q-system/.q-system/scripts/test_memory_confidence_surface.py), referenced on a wiring surface (settings-template.json).

DUP memory-confidence-validator.py 2
q-system/.q-system/scripts/memory-confidence-validator.py LIVE q-system/.q-system/scripts/memory-confidence-validator.py: 131 lines; has a paired test (q-system/.q-system/scripts/test_memory_confidence_validator.py), referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/memory-confidence-validator.py LIVE .pr25rev/mut/q-system/.q-system/scripts/memory-confidence-validator.py: 116 lines; has a paired test (q-system/.q-system/scripts/test_memory_confidence_validator.py), referenced on a wiring surface (settings-template.json).

DUP memory-freshness-check.py 2
q-system/.q-system/scripts/memory-freshness-check.py LIVE q-system/.q-system/scripts/memory-freshness-check.py: 96 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/memory-freshness-check.py LIVE .pr25rev/mut/q-system/.q-system/scripts/memory-freshness-check.py: 96 lines; referenced on a wiring surface (settings-template.json).

DUP memory-scores-surface.py 2
q-system/.q-system/scripts/memory-scores-surface.py LIVE q-system/.q-system/scripts/memory-scores-surface.py: 178 lines; has a paired test (q-system/.q-system/scripts/test_memory_scores_surface.py), referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/memory-scores-surface.py LIVE .pr25rev/mut/q-system/.q-system/scripts/memory-scores-surface.py: 178 lines; has a paired test (q-system/.q-system/scripts/test_memory_scores_surface.py), referenced on a wiring surface (settings-template.json).

DUP memory_autocapture.py 2
q-system/.q-system/scripts/memory_autocapture.py LIVE q-system/.q-system/scripts/memory_autocapture.py: 196 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/memory_autocapture.py LIVE .pr25rev/mut/q-system/.q-system/scripts/memory_autocapture.py: 196 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (settings-template.json).

DUP memory_outcomes.py 2
q-system/.q-system/scripts/memory_outcomes.py LIVE q-system/.q-system/scripts/memory_outcomes.py: 226 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
.pr25rev/mut/q-system/.q-system/scripts/memory_outcomes.py LIVE .pr25rev/mut/q-system/.q-system/scripts/memory_outcomes.py: 226 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).

DUP memory_reflect.py 2
q-system/.q-system/scripts/memory_reflect.py LIVE q-system/.q-system/scripts/memory_reflect.py: 276 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
.pr25rev/mut/q-system/.q-system/scripts/memory_reflect.py LIVE .pr25rev/mut/q-system/.q-system/scripts/memory_reflect.py: 276 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).

DUP open-loops.py 2
q-system/.q-system/scripts/open-loops.py LIVE q-system/.q-system/scripts/open-loops.py: 150 lines; has a paired test (q-system/.q-system/scripts/test/test-open-loops-heartbeat-exit.sh), referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/open-loops.py LIVE .pr25rev/mut/q-system/.q-system/scripts/open-loops.py: 150 lines; has a paired test (q-system/.q-system/scripts/test/test-open-loops-heartbeat-exit.sh), referenced on a wiring surface (settings-template.json).

DUP pdf-extract.py 2
q-system/.q-system/scripts/pdf-extract.py LIVE q-system/.q-system/scripts/pdf-extract.py: 208 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
.pr25rev/mut/q-system/.q-system/scripts/pdf-extract.py LIVE .pr25rev/mut/q-system/.q-system/scripts/pdf-extract.py: 208 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).

DUP plugin-version-bump-check.py 2
q-system/.q-system/scripts/plugin-version-bump-check.py LIVE q-system/.q-system/scripts/plugin-version-bump-check.py: 125 lines; has a paired test (q-system/.q-system/scripts/test_plugin_version_bump_check.py), referenced on a wiring surface (lefthook.yml).
.pr25rev/mut/q-system/.q-system/scripts/plugin-version-bump-check.py LIVE .pr25rev/mut/q-system/.q-system/scripts/plugin-version-bump-check.py: 125 lines; has a paired test (q-system/.q-system/scripts/test_plugin_version_bump_check.py), referenced on a wiring surface (lefthook.yml).

DUP prompt-only-enforcement-guard.py 2
q-system/.q-system/scripts/prompt-only-enforcement-guard.py LIVE q-system/.q-system/scripts/prompt-only-enforcement-guard.py: 348 lines; has a paired test (q-system/.q-system/scripts/test_prompt_only_enforcement_guard.py), referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/prompt-only-enforcement-guard.py LIVE .pr25rev/mut/q-system/.q-system/scripts/prompt-only-enforcement-guard.py: 348 lines; has a paired test (q-system/.q-system/scripts/test_prompt_only_enforcement_guard.py), referenced on a wiring surface (settings-template.json).

DUP propagation-leak-gate.py 2
q-system/.q-system/scripts/propagation-leak-gate.py LIVE q-system/.q-system/scripts/propagation-leak-gate.py: 1255 lines; has a paired test (q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh), referenced on a wiring surface (build-template-repo.sh).
.pr25rev/mut/q-system/.q-system/scripts/propagation-leak-gate.py LIVE .pr25rev/mut/q-system/.q-system/scripts/propagation-leak-gate.py: 1255 lines; has a paired test (q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh), referenced on a wiring surface (build-template-repo.sh).

DUP publish-reconciliation.py 2
q-system/.q-system/scripts/publish-reconciliation.py LIVE q-system/.q-system/scripts/publish-reconciliation.py: 220 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
.pr25rev/mut/q-system/.q-system/scripts/publish-reconciliation.py LIVE .pr25rev/mut/q-system/.q-system/scripts/publish-reconciliation.py: 220 lines; referenced on a wiring surface (q-system/.q-system/scripts/publish-reconciliation.py).

DUP receipts-ledger-check.py 2
q-system/.q-system/scripts/receipts-ledger-check.py LIVE q-system/.q-system/scripts/receipts-ledger-check.py: 170 lines; has a paired test (q-system/.q-system/scripts/test/test-receipts-ledger-check.sh), referenced on a wiring surface (lefthook.yml).
.pr25rev/mut/q-system/.q-system/scripts/receipts-ledger-check.py LIVE .pr25rev/mut/q-system/.q-system/scripts/receipts-ledger-check.py: 170 lines; has a paired test (q-system/.q-system/scripts/test/test-receipts-ledger-check.sh), referenced on a wiring surface (lefthook.yml).

DUP ripple-verify.py 2
q-system/.q-system/scripts/ripple-verify.py LIVE q-system/.q-system/scripts/ripple-verify.py: 191 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).
.pr25rev/mut/q-system/.q-system/scripts/ripple-verify.py LIVE .pr25rev/mut/q-system/.q-system/scripts/ripple-verify.py: 191 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).

DUP route-overrides-to-learn.py 2
q-system/.q-system/scripts/route-overrides-to-learn.py LIVE q-system/.q-system/scripts/route-overrides-to-learn.py: 201 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/schemas/copy-diffs.schema.json).
.pr25rev/mut/q-system/.q-system/scripts/route-overrides-to-learn.py LIVE .pr25rev/mut/q-system/.q-system/scripts/route-overrides-to-learn.py: 201 lines; referenced on a wiring surface (q-system/.q-system/scripts/route-overrides-to-learn.py).

DUP run-step-audit.py 2
q-system/.q-system/scripts/run-step-audit.py LIVE q-system/.q-system/scripts/run-step-audit.py: 91 lines; has a paired test (q-system/.q-system/scripts/test/test-open-loops-heartbeat-exit.sh), referenced on a wiring surface (q-system/.q-system/scripts/open-loops-heartbeat.sh).
.pr25rev/mut/q-system/.q-system/scripts/run-step-audit.py LIVE .pr25rev/mut/q-system/.q-system/scripts/run-step-audit.py: 91 lines; has a paired test (q-system/.q-system/scripts/test/test-open-loops-heartbeat-exit.sh), referenced on a wiring surface (q-system/.q-system/scripts/open-loops-heartbeat.sh).

DUP scan-draft.py 2
q-system/.q-system/scripts/scan-draft.py LIVE q-system/.q-system/scripts/scan-draft.py: 208 lines; referenced on a wiring surface (validate-separation.py).
.pr25rev/mut/q-system/.q-system/scripts/scan-draft.py LIVE .pr25rev/mut/q-system/.q-system/scripts/scan-draft.py: 208 lines; referenced on a wiring surface (validate-separation.py).

DUP search.py 4
plugins/kipi-design/skills/design/scripts/cip/search.py LIVE plugins/kipi-design/skills/design/scripts/cip/search.py: 127 lines; referenced on a wiring surface (plugins/kipi-design/skills/design/SKILL.md).
plugins/kipi-design/skills/design/scripts/logo/search.py LIVE plugins/kipi-design/skills/design/scripts/logo/search.py: 114 lines; referenced on a wiring surface (plugins/kipi-design/skills/design/SKILL.md).
plugins/kipi-design/skills/ui-ux-pro-max/scripts/search.py LIVE plugins/kipi-design/skills/ui-ux-pro-max/scripts/search.py: 114 lines; referenced on a wiring surface (plugins/kipi-design/skills/design/SKILL.md).
plugins/kipi-design/skills/ui-ux-pro-max/src/scripts/search.py LIVE plugins/kipi-design/skills/ui-ux-pro-max/src/scripts/search.py: 114 lines; referenced on a wiring surface (plugins/kipi-design/skills/design/SKILL.md).

DUP session_recall.py 2
q-system/.q-system/scripts/session_recall.py LIVE q-system/.q-system/scripts/session_recall.py: 197 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
.pr25rev/mut/q-system/.q-system/scripts/session_recall.py LIVE .pr25rev/mut/q-system/.q-system/scripts/session_recall.py: 197 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).

DUP settings-template-sync-check.py 2
q-system/.q-system/scripts/settings-template-sync-check.py LIVE q-system/.q-system/scripts/settings-template-sync-check.py: 173 lines; has a paired test (q-system/.q-system/scripts/test_settings_template_sync_check.py), referenced on a wiring surface (kipi-update.sh).
.pr25rev/mut/q-system/.q-system/scripts/settings-template-sync-check.py LIVE .pr25rev/mut/q-system/.q-system/scripts/settings-template-sync-check.py: 146 lines; has a paired test (q-system/.q-system/scripts/test_settings_template_sync_check.py), referenced on a wiring surface (kipi-update.sh).

DUP skill-trigger-eval.py 2
q-system/.q-system/scripts/skill-trigger-eval.py LIVE q-system/.q-system/scripts/skill-trigger-eval.py: 86 lines; has a paired test (q-system/.q-system/scripts/test/test-skill-trigger-eval.sh), referenced on a wiring surface (.pr25rev/mut/q-system/.q-system/scripts/skill-trigger-eval.py).
.pr25rev/mut/q-system/.q-system/scripts/skill-trigger-eval.py LIVE .pr25rev/mut/q-system/.q-system/scripts/skill-trigger-eval.py: 86 lines; has a paired test (q-system/.q-system/scripts/test/test-skill-trigger-eval.sh), referenced on a wiring surface (q-system/.q-system/scripts/skill-trigger-eval.py).

DUP stat-registry-extract.py 2
q-system/.q-system/scripts/stat-registry-extract.py LIVE q-system/.q-system/scripts/stat-registry-extract.py: 245 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
.pr25rev/mut/q-system/.q-system/scripts/stat-registry-extract.py LIVE .pr25rev/mut/q-system/.q-system/scripts/stat-registry-extract.py: 245 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).

DUP stat-verify.py 2
q-system/.q-system/scripts/stat-verify.py LIVE q-system/.q-system/scripts/stat-verify.py: 802 lines; has a paired test (q-system/.q-system/scripts/tests/test-stat-verify.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
.pr25rev/mut/q-system/.q-system/scripts/stat-verify.py LIVE .pr25rev/mut/q-system/.q-system/scripts/stat-verify.py: 802 lines; has a paired test (q-system/.q-system/scripts/tests/test-stat-verify.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).

DUP sycophancy-monthly-check.py 2
q-system/.q-system/scripts/sycophancy-monthly-check.py LIVE q-system/.q-system/scripts/sycophancy-monthly-check.py: 65 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/sycophancy-monthly-check.py LIVE .pr25rev/mut/q-system/.q-system/scripts/sycophancy-monthly-check.py: 65 lines; referenced on a wiring surface (settings-template.json).

DUP synthesize-schedule.py 2
q-system/.q-system/scripts/synthesize-schedule.py LIVE q-system/.q-system/scripts/synthesize-schedule.py: 1148 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
.pr25rev/mut/q-system/.q-system/scripts/synthesize-schedule.py LIVE .pr25rev/mut/q-system/.q-system/scripts/synthesize-schedule.py: 1148 lines; referenced on a wiring surface (q-system/.q-system/scripts/synthesize-schedule.py).

DUP temperature-scoring.py 2
q-system/.q-system/scripts/temperature-scoring.py LIVE q-system/.q-system/scripts/temperature-scoring.py: 302 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
.pr25rev/mut/q-system/.q-system/scripts/temperature-scoring.py LIVE .pr25rev/mut/q-system/.q-system/scripts/temperature-scoring.py: 302 lines; referenced on a wiring surface (q-system/.q-system/scripts/temperature-scoring.py).

DUP token-guard.py 2
.pr27rev/token-guard.py LIVE .pr27rev/token-guard.py: 923 lines; has a paired test (.pr27rev/test-token-guard-hook-behavior.sh), referenced on a wiring surface (instance-registry.json).
q-system/.q-system/token-guard.py LIVE q-system/.q-system/token-guard.py: 1057 lines; has a paired test (.pr27rev/test-token-guard-hook-behavior.sh), referenced on a wiring surface (instance-registry.json).

DUP update-preservation-manifest.py 2
q-system/.q-system/scripts/update-preservation-manifest.py LIVE q-system/.q-system/scripts/update-preservation-manifest.py: 668 lines; has a paired test (q-system/.q-system/scripts/test/test-update-preservation-manifest.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
.pr25rev/mut/q-system/.q-system/scripts/update-preservation-manifest.py LIVE .pr25rev/mut/q-system/.q-system/scripts/update-preservation-manifest.py: 668 lines; has a paired test (q-system/.q-system/scripts/test/test-update-preservation-manifest.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).

DUP verify-containment-export.py 2
q-system/.q-system/scripts/verify-containment-export.py LIVE q-system/.q-system/scripts/verify-containment-export.py: 556 lines; has a paired test (q-system/.q-system/tests/separation/test_containment_export.py), referenced on a wiring surface (.prd-os/issues/sdc-owner-export.md).
.pr25rev/mut/q-system/.q-system/scripts/verify-containment-export.py LIVE .pr25rev/mut/q-system/.q-system/scripts/verify-containment-export.py: 556 lines; has a paired test (q-system/.q-system/tests/separation/test_containment_export.py), referenced on a wiring surface (.prd-os/issues/sdc-owner-export.md).

DUP voice-dna-loader.py 2
q-system/.q-system/scripts/voice-dna-loader.py LIVE q-system/.q-system/scripts/voice-dna-loader.py: 158 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/voice-dna-loader.py LIVE .pr25rev/mut/q-system/.q-system/scripts/voice-dna-loader.py: 158 lines; referenced on a wiring surface (settings-template.json).

DUP voice-lint.py 2
q-system/.q-system/scripts/voice-lint.py LIVE q-system/.q-system/scripts/voice-lint.py: 841 lines; has a paired test (q-system/.q-system/scripts/test_review_tier.py), referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/voice-lint.py LIVE .pr25rev/mut/q-system/.q-system/scripts/voice-lint.py: 678 lines; has a paired test (q-system/.q-system/scripts/test_review_tier.py), referenced on a wiring surface (settings-template.json).

DUP voice-stop-gate.py 2
q-system/.q-system/scripts/voice-stop-gate.py LIVE q-system/.q-system/scripts/voice-stop-gate.py: 168 lines; has a paired test (q-system/.q-system/scripts/test/test-voice-enforcement-rule-wired.sh), referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/voice-stop-gate.py LIVE .pr25rev/mut/q-system/.q-system/scripts/voice-stop-gate.py: 168 lines; has a paired test (q-system/.q-system/scripts/test/test-voice-enforcement-rule-wired.sh), referenced on a wiring surface (settings-template.json).

DUP voice-substance-lint.py 2
q-system/.q-system/scripts/voice-substance-lint.py LIVE q-system/.q-system/scripts/voice-substance-lint.py: 274 lines; has a paired test (q-system/.q-system/scripts/test/test-voice-enforcement-rule-wired.sh), referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/voice-substance-lint.py LIVE .pr25rev/mut/q-system/.q-system/scripts/voice-substance-lint.py: 274 lines; has a paired test (q-system/.q-system/scripts/test/test-voice-enforcement-rule-wired.sh), referenced on a wiring surface (settings-template.json).

DUP wiring-check.py 2
q-system/.q-system/scripts/wiring-check.py LIVE q-system/.q-system/scripts/wiring-check.py: 270 lines; referenced on a wiring surface (settings-template.json).
.pr25rev/mut/q-system/.q-system/scripts/wiring-check.py LIVE .pr25rev/mut/q-system/.q-system/scripts/wiring-check.py: 270 lines; referenced on a wiring surface (settings-template.json).

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "python3 - <<'PY'
import json, os
from pathlib import Path
p = Path(os.environ['TMPDIR']) / 'pr74-capability-map.json'
data = json.loads(p.read_text())
for c in data['capabilities']:
    if c['layer'] == 'L5 Engines and scripts' and (c['status'] "'!= '"'LIVE' or any(part.startswith('.') for part in Path(c['entry']).parts)):
        print(c['status'], c['track'], c['entry'], '::', c['evidence'])
PY
rg -n \""'^'"\\.pr25rev|"'^'"\\.review-tmp|"'^'"\\.pr2[0-9]rev\" .gitignore .git/info/exclude 2>/dev/null || true
git ls-files '.pr25rev/**' '.review-tmp-pr11/**' '.pr27rev/**' | sed -n '1,80p'
git ls-files '.pr25rev/**' '.review-tmp-pr11/**' '.pr27rev/**' | wc -l
nl -ba q-system/.q-system/scripts/capability-map-gen.py | sed -n '330,510p'" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
UNWIRED True .pr24rev/mutate.py :: .pr24rev/mutate.py: 76 lines; NO test and NO wiring reference found.
LIVE True .pr27rev/token-guard.py :: .pr27rev/token-guard.py: 923 lines; has a paired test (.pr27rev/test-token-guard-hook-behavior.sh), referenced on a wiring surface (instance-registry.json).
UNWIRED True .review-tmp-pr11/repro_B_update_path_crashes_run.py :: .review-tmp-pr11/repro_B_update_path_crashes_run.py: 104 lines; NO test and NO wiring reference found.
UNWIRED True .review-tmp-pr11/repro_C_ledger_only_key_all_clear.py :: .review-tmp-pr11/repro_C_ledger_only_key_all_clear.py: 81 lines; NO test and NO wiring reference found.
UNWIRED True .review-tmp-pr11/repro_A_linear_unreachable_silent.py :: .review-tmp-pr11/repro_A_linear_unreachable_silent.py: 47 lines; NO test and NO wiring reference found.
UNWIRED True .review-tmp-pr11/repro_D_matcher_corpus.py :: .review-tmp-pr11/repro_D_matcher_corpus.py: 63 lines; NO test and NO wiring reference found.
LIVE True .review-scratch/repo/q-system/.q-system/scripts/linear-sync.py :: .review-scratch/repo/q-system/.q-system/scripts/linear-sync.py: 862 lines; has a paired test (.pr22rev/test-scratch-guard-push.sh), referenced on a wiring surface (kipi).
LIVE True .review-scratch/repo/q-system/.q-system/scripts/linear-claim.py :: .review-scratch/repo/q-system/.q-system/scripts/linear-claim.py: 585 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
LIVE True .review-tmp-pr11/scripts/fleet-health-daily.py :: .review-tmp-pr11/scripts/fleet-health-daily.py: 1020 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
LIVE True .review-tmp-pr11/scripts/linear-sync.py :: .review-tmp-pr11/scripts/linear-sync.py: 929 lines; has a paired test (.pr22rev/test-scratch-guard-push.sh), referenced on a wiring surface (kipi).
LIVE True .pr28rev/root/q-system/.q-system/scripts/linear-claim.py :: .pr28rev/root/q-system/.q-system/scripts/linear-claim.py: 585 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
LIVE True q-system/.q-system/bus-to-log.py :: q-system/.q-system/bus-to-log.py: 126 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
LIVE True q-system/.q-system/loop-tracker.py :: q-system/.q-system/loop-tracker.py: 248 lines; referenced on a wiring surface (q-system/.q-system/preflight.md).
LIVE True q-system/.q-system/token-guard.py :: q-system/.q-system/token-guard.py: 1057 lines; has a paired test (.pr27rev/test-token-guard-hook-behavior.sh), referenced on a wiring surface (instance-registry.json).
LIVE True q-system/.q-system/verify-bus.py :: q-system/.q-system/verify-bus.py: 359 lines; referenced on a wiring surface (validate-separation.py).
LIVE True q-system/.q-system/audit-morning.py :: q-system/.q-system/audit-morning.py: 281 lines; referenced on a wiring surface (AGENTS.md).
LIVE True q-system/.q-system/sycophancy-harness.py :: q-system/.q-system/sycophancy-harness.py: 607 lines; referenced on a wiring surface (.claude/rules/morning-pipeline.md).
LIVE True q-system/.q-system/verify-orchestrator.py :: q-system/.q-system/verify-orchestrator.py: 170 lines; referenced on a wiring surface (validate-separation.py).
LIVE True q-system/.q-system/log-step.py :: q-system/.q-system/log-step.py: 210 lines; referenced on a wiring surface (q-system/.q-system/preflight.md).
LIVE True q-system/.q-system/verify-schedule.py :: q-system/.q-system/verify-schedule.py: 229 lines; referenced on a wiring surface (validate-separation.py).
LIVE True q-system/.q-system/scripts/memory-confidence-validator.py :: q-system/.q-system/scripts/memory-confidence-validator.py: 131 lines; has a paired test (q-system/.q-system/scripts/test_memory_confidence_validator.py), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/session_recall.py :: q-system/.q-system/scripts/session_recall.py: 197 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/voice-lint.py :: q-system/.q-system/scripts/voice-lint.py: 841 lines; has a paired test (q-system/.q-system/scripts/test_review_tier.py), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/voice-stop-gate.py :: q-system/.q-system/scripts/voice-stop-gate.py: 168 lines; has a paired test (q-system/.q-system/scripts/test/test-voice-enforcement-rule-wired.sh), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/voice-dna-loader.py :: q-system/.q-system/scripts/voice-dna-loader.py: 158 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/audhd-lint.py :: q-system/.q-system/scripts/audhd-lint.py: 283 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/fleet-health-daily.py :: q-system/.q-system/scripts/fleet-health-daily.py: 1633 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
LIVE True q-system/.q-system/scripts/canonical-digest.py :: q-system/.q-system/scripts/canonical-digest.py: 264 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
LIVE True q-system/.q-system/scripts/handoff-provenance-lint.py :: q-system/.q-system/scripts/handoff-provenance-lint.py: 188 lines; has a paired test (q-system/.q-system/scripts/test_handoff_provenance_lint.py), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/fleet-board-refresh.py :: q-system/.q-system/scripts/fleet-board-refresh.py: 101 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/granola-voice-synthesize.py :: q-system/.q-system/scripts/granola-voice-synthesize.py: 139 lines; referenced on a wiring surface (automation/voice_refresh.py).
LIVE True q-system/.q-system/scripts/launchd-health-check.py :: q-system/.q-system/scripts/launchd-health-check.py: 484 lines; has a paired test (q-system/.q-system/scripts/test_launchd_health_check.py), referenced on a wiring surface (AUTONOMOUS-SYSTEMS.md).
LIVE True q-system/.q-system/scripts/linear-collapse-jobmigration.py :: q-system/.q-system/scripts/linear-collapse-jobmigration.py: 221 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/capability-map-gen.py :: q-system/.q-system/scripts/capability-map-gen.py: 693 lines; has a paired test (q-system/.q-system/scripts/test/test-capability-map-wiring.py), referenced on a wiring surface (kipi).
LIVE True q-system/.q-system/scripts/memory_reflect.py :: q-system/.q-system/scripts/memory_reflect.py: 276 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/lessons-validator.py :: q-system/.q-system/scripts/lessons-validator.py: 85 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-validator.sh), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/stat-verify.py :: q-system/.q-system/scripts/stat-verify.py: 802 lines; has a paired test (q-system/.q-system/scripts/tests/test-stat-verify.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/memory-freshness-check.py :: q-system/.q-system/scripts/memory-freshness-check.py: 96 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/plugin-version-bump-check.py :: q-system/.q-system/scripts/plugin-version-bump-check.py: 125 lines; has a paired test (q-system/.q-system/scripts/test_plugin_version_bump_check.py), referenced on a wiring surface (lefthook.yml).
LIVE True q-system/.q-system/scripts/linear-sync.py :: q-system/.q-system/scripts/linear-sync.py: 1203 lines; has a paired test (.pr22rev/test-scratch-guard-push.sh), referenced on a wiring surface (kipi).
LIVE True q-system/.q-system/scripts/lessons-distill.py :: q-system/.q-system/scripts/lessons-distill.py: 243 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-daily-exit.sh), referenced on a wiring surface (AUTONOMOUS-SYSTEMS.md).
LIVE True q-system/.q-system/scripts/collection-gate.py :: q-system/.q-system/scripts/collection-gate.py: 162 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
LIVE True q-system/.q-system/scripts/read-first-gate.py :: q-system/.q-system/scripts/read-first-gate.py: 187 lines; has a paired test (q-system/.q-system/scripts/test_read_first_gate.py), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/memory_outcomes.py :: q-system/.q-system/scripts/memory_outcomes.py: 226 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/system_manifest.py :: q-system/.q-system/scripts/system_manifest.py: 232 lines; has a paired test (q-system/.q-system/scripts/test_system_manifest.py), referenced on a wiring surface (.claude/rules/evidence-ledger.md).
LIVE True q-system/.q-system/scripts/client-output-evidence-gate.py :: q-system/.q-system/scripts/client-output-evidence-gate.py: 122 lines; has a paired test (q-system/.q-system/scripts/test_client_output_evidence_gate.py), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/instance-automation-guard.py :: q-system/.q-system/scripts/instance-automation-guard.py: 97 lines; has a paired test (q-system/.q-system/scripts/test/test-instance-automation-guard.sh), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/sycophancy-monthly-check.py :: q-system/.q-system/scripts/sycophancy-monthly-check.py: 65 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/wiring-check.py :: q-system/.q-system/scripts/wiring-check.py: 270 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/instance-fact-inventory.py :: q-system/.q-system/scripts/instance-fact-inventory.py: 395 lines; has a paired test (q-system/.q-system/tests/separation/test_instance_fact_inventory.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/scan-draft.py :: q-system/.q-system/scripts/scan-draft.py: 208 lines; referenced on a wiring surface (validate-separation.py).
LIVE True q-system/.q-system/scripts/accept-rate.py :: q-system/.q-system/scripts/accept-rate.py: 300 lines; referenced on a wiring surface (.prd-os/issues/accept-rate-metric-script.md).
LIVE True q-system/.q-system/scripts/review-tier.py :: q-system/.q-system/scripts/review-tier.py: 444 lines; has a paired test (q-system/.q-system/scripts/test_review_tier.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/instruction-budget-audit.py :: q-system/.q-system/scripts/instruction-budget-audit.py: 221 lines; referenced on a wiring surface (AGENTS.md).
LIVE True q-system/.q-system/scripts/instance-diet.py :: q-system/.q-system/scripts/instance-diet.py: 239 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/code_claim_grounding_guard.py :: q-system/.q-system/scripts/code_claim_grounding_guard.py: 296 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/linear-queue.py :: q-system/.q-system/scripts/linear-queue.py: 225 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-queue.sh), referenced on a wiring surface (kipi).
LIVE True q-system/.q-system/scripts/containment-targets.py :: q-system/.q-system/scripts/containment-targets.py: 225 lines; has a paired test (q-system/.q-system/scripts/test/test-containment-gitlink.py), referenced on a wiring surface (validate-separation.py).
LIVE True q-system/.q-system/scripts/firecrawl-scrape.py :: q-system/.q-system/scripts/firecrawl-scrape.py: 70 lines; has a paired test (q-system/.q-system/scripts/test/test-firecrawl-scrape.sh), referenced on a wiring surface (.prd-os/prds/prd-deterministic-reading-2026-07-28.md).
LIVE True q-system/.q-system/scripts/copy-diff.py :: q-system/.q-system/scripts/copy-diff.py: 236 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
LIVE True q-system/.q-system/scripts/memory_autocapture.py :: q-system/.q-system/scripts/memory_autocapture.py: 196 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/evidence_ledger.py :: q-system/.q-system/scripts/evidence_ledger.py: 336 lines; has a paired test (q-system/.q-system/scripts/test_client_output_evidence_gate.py), referenced on a wiring surface (.claude/rules/evidence-ledger.md).
LIVE True q-system/.q-system/scripts/apply_claude_changes.py :: q-system/.q-system/scripts/apply_claude_changes.py: 1165 lines; has a paired test (q-system/.q-system/scripts/test/test-apply-claude-changes.sh), referenced on a wiring surface (q-system/.q-system/scripts/apply-claude-changes.sh).
LIVE True q-system/.q-system/scripts/ripple-verify.py :: q-system/.q-system/scripts/ripple-verify.py: 191 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).
LIVE True q-system/.q-system/scripts/changelog-write.py :: q-system/.q-system/scripts/changelog-write.py: 86 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).
LIVE True q-system/.q-system/scripts/format-lint.py :: q-system/.q-system/scripts/format-lint.py: 202 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/route-overrides-to-learn.py :: q-system/.q-system/scripts/route-overrides-to-learn.py: 201 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/schemas/copy-diffs.schema.json).
LIVE True q-system/.q-system/scripts/batch-uniformity-lint.py :: q-system/.q-system/scripts/batch-uniformity-lint.py: 213 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/synthesize-schedule.py :: q-system/.q-system/scripts/synthesize-schedule.py: 1148 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
LIVE True q-system/.q-system/scripts/propagation-leak-gate.py :: q-system/.q-system/scripts/propagation-leak-gate.py: 1255 lines; has a paired test (q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh), referenced on a wiring surface (build-template-repo.sh).
LIVE True q-system/.q-system/scripts/linear-triage.py :: q-system/.q-system/scripts/linear-triage.py: 571 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-triage.sh), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/claude-integrity-tripwire.py :: q-system/.q-system/scripts/claude-integrity-tripwire.py: 512 lines; has a paired test (q-system/.q-system/scripts/test/test-claude-write-path.sh), referenced on a wiring surface (q-system/.q-system/claude-integrity-baseline.json).
LIVE True q-system/.q-system/scripts/correction_outcome.py :: q-system/.q-system/scripts/correction_outcome.py: 84 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/scripts/memory_autocapture.py).
LIVE True q-system/.q-system/scripts/settings-template-sync-check.py :: q-system/.q-system/scripts/settings-template-sync-check.py: 173 lines; has a paired test (q-system/.q-system/scripts/test_settings_template_sync_check.py), referenced on a wiring surface (kipi-update.sh).
LIVE True q-system/.q-system/scripts/receipts-ledger-check.py :: q-system/.q-system/scripts/receipts-ledger-check.py: 170 lines; has a paired test (q-system/.q-system/scripts/test/test-receipts-ledger-check.sh), referenced on a wiring surface (lefthook.yml).
LIVE True q-system/.q-system/scripts/linear-job-migration.py :: q-system/.q-system/scripts/linear-job-migration.py: 225 lines; referenced on a wiring surface (kipi).
LIVE True q-system/.q-system/scripts/memory-scores-surface.py :: q-system/.q-system/scripts/memory-scores-surface.py: 178 lines; has a paired test (q-system/.q-system/scripts/test_memory_scores_surface.py), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/verify-containment-export.py :: q-system/.q-system/scripts/verify-containment-export.py: 556 lines; has a paired test (q-system/.q-system/tests/separation/test_containment_export.py), referenced on a wiring surface (.prd-os/issues/sdc-owner-export.md).
LIVE True q-system/.q-system/scripts/linkedin-format-lint.py :: q-system/.q-system/scripts/linkedin-format-lint.py: 285 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/capability-gate.py :: q-system/.q-system/scripts/capability-gate.py: 571 lines; has a paired test (q-system/.q-system/scripts/test_capability_gate.py), referenced on a wiring surface (fleet-capability-verify.py).
LIVE True q-system/.q-system/scripts/stat-registry-extract.py :: q-system/.q-system/scripts/stat-registry-extract.py: 245 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/provenance_vocabulary.py :: q-system/.q-system/scripts/provenance_vocabulary.py: 108 lines; has a paired test (q-system/.q-system/scripts/test_provenance_vocabulary.py), referenced on a wiring surface (.claude/rules/evidence-ledger.md).
LIVE True q-system/.q-system/scripts/md-prune.py :: q-system/.q-system/scripts/md-prune.py: 229 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/publish-reconciliation.py :: q-system/.q-system/scripts/publish-reconciliation.py: 220 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
LIVE True q-system/.q-system/scripts/prompt-only-enforcement-guard.py :: q-system/.q-system/scripts/prompt-only-enforcement-guard.py: 348 lines; has a paired test (q-system/.q-system/scripts/test_prompt_only_enforcement_guard.py), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/skill-trigger-eval.py :: q-system/.q-system/scripts/skill-trigger-eval.py: 86 lines; has a paired test (q-system/.q-system/scripts/test/test-skill-trigger-eval.sh), referenced on a wiring surface (.pr25rev/mut/q-system/.q-system/scripts/skill-trigger-eval.py).
LIVE True q-system/.q-system/scripts/temperature-scoring.py :: q-system/.q-system/scripts/temperature-scoring.py: 302 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
LIVE True q-system/.q-system/scripts/portability-lint-hook.py :: q-system/.q-system/scripts/portability-lint-hook.py: 112 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/pdf-extract.py :: q-system/.q-system/scripts/pdf-extract.py: 208 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/granola-voice-fingerprint.py :: q-system/.q-system/scripts/granola-voice-fingerprint.py: 95 lines; referenced on a wiring surface (automation/voice_refresh.py).
LIVE True q-system/.q-system/scripts/content-lint.py :: q-system/.q-system/scripts/content-lint.py: 164 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).
LIVE True q-system/.q-system/scripts/lessons_scrub.py :: q-system/.q-system/scripts/lessons_scrub.py: 89 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-scrub.sh), referenced on a wiring surface (q-system/.q-system/scripts/lessons-daily.sh).
LIVE True q-system/.q-system/scripts/decision-origin-tag-lint.py :: q-system/.q-system/scripts/decision-origin-tag-lint.py: 182 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/headline-lint.py :: q-system/.q-system/scripts/headline-lint.py: 314 lines; referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/fleet-loop-board.py :: q-system/.q-system/scripts/fleet-loop-board.py: 321 lines; referenced on a wiring surface (q-system/.q-system/scripts/fleet-board-refresh.py).
LIVE True q-system/.q-system/scripts/linear-issue-ref-check.py :: q-system/.q-system/scripts/linear-issue-ref-check.py: 153 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-issue-ref-check.sh), referenced on a wiring surface (kipi).
LIVE True q-system/.q-system/scripts/attempts-ledger.py :: q-system/.q-system/scripts/attempts-ledger.py: 410 lines; has a paired test (q-system/.q-system/scripts/test_review_tier.py), referenced on a wiring surface (kipi-dispatch.sh).
LIVE True q-system/.q-system/scripts/run-step-audit.py :: q-system/.q-system/scripts/run-step-audit.py: 91 lines; has a paired test (q-system/.q-system/scripts/test/test-open-loops-heartbeat-exit.sh), referenced on a wiring surface (q-system/.q-system/scripts/open-loops-heartbeat.sh).
LIVE True q-system/.q-system/scripts/linear-dor-drafter.py :: q-system/.q-system/scripts/linear-dor-drafter.py: 1261 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-dor-drafter-redrive.sh), referenced on a wiring surface (kipi).
LIVE True q-system/.q-system/scripts/update-preservation-manifest.py :: q-system/.q-system/scripts/update-preservation-manifest.py: 668 lines; has a paired test (q-system/.q-system/scripts/test/test-update-preservation-manifest.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True q-system/.q-system/scripts/memory-confidence-surface.py :: q-system/.q-system/scripts/memory-confidence-surface.py: 115 lines; has a paired test (q-system/.q-system/scripts/test_memory_confidence_surface.py), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/compliance-check.py :: q-system/.q-system/scripts/compliance-check.py: 354 lines; referenced on a wiring surface (q-system/.q-system/agent-pipeline/agents/step-orchestrator.md).
LIVE True q-system/.q-system/scripts/capability-overlap.py :: q-system/.q-system/scripts/capability-overlap.py: 305 lines; referenced on a wiring surface (kipi).
LIVE True q-system/.q-system/scripts/voice-substance-lint.py :: q-system/.q-system/scripts/voice-substance-lint.py: 274 lines; has a paired test (q-system/.q-system/scripts/test/test-voice-enforcement-rule-wired.sh), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/claude-path-write-guard.py :: q-system/.q-system/scripts/claude-path-write-guard.py: 291 lines; has a paired test (q-system/.q-system/scripts/test/test-claude-write-path.sh), referenced on a wiring surface (q-system/.q-system/scripts/claude-integrity-tripwire.py).
LIVE True q-system/.q-system/scripts/open-loops.py :: q-system/.q-system/scripts/open-loops.py: 150 lines; has a paired test (q-system/.q-system/scripts/test/test-open-loops-heartbeat-exit.sh), referenced on a wiring surface (settings-template.json).
LIVE True q-system/.q-system/scripts/linear-claim.py :: q-system/.q-system/scripts/linear-claim.py: 773 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
LIVE True q-system/.q-system/scripts/granola-voice-harvest.py :: q-system/.q-system/scripts/granola-voice-harvest.py: 120 lines; has a paired test (automation/test_voice_refresh_command.py), referenced on a wiring surface (plugins/kipi-core/commands/voice-refresh.md).
UNWIRED True q-system/.q-system/data/monthly-learnings.py :: q-system/.q-system/data/monthly-learnings.py: 108 lines; NO test and NO wiring reference found.
LIVE True q-system/.q-system/data/db-init.py :: q-system/.q-system/data/db-init.py: 134 lines; referenced on a wiring surface (q-system/.q-system/data/db-query.py).
LIVE True q-system/.q-system/data/db-query.py :: q-system/.q-system/data/db-query.py: 214 lines; referenced on a wiring surface (memory/MEMORY.md).
UNWIRED True plugins/kipi-design/skills/design/scripts/fetch-background.py :: plugins/kipi-design/skills/design/scripts/fetch-background.py: 317 lines; NO test and NO wiring reference found.
UNWIRED True plugins/kipi-design/skills/design/scripts/generate-slide.py :: plugins/kipi-design/skills/design/scripts/generate-slide.py: 753 lines; NO test and NO wiring reference found.
UNWIRED True plugins/kipi-core/skills/deck-ai/scripts/render_pptx.py :: plugins/kipi-core/skills/deck-ai/scripts/render_pptx.py: 557 lines; NO test and NO wiring reference found.
UNWIRED True plugins/kipi-core/kipi-mcp/tests/conftest.py :: plugins/kipi-core/kipi-mcp/tests/conftest.py: 110 lines; NO test and NO wiring reference found.
UNWIRED True plugins/prd-os/tests/conftest.py :: plugins/prd-os/tests/conftest.py: 175 lines; NO test and NO wiring reference found.
LIVE True .pr25rev/mut/q-system/.q-system/scripts/memory-confidence-validator.py :: .pr25rev/mut/q-system/.q-system/scripts/memory-confidence-validator.py: 116 lines; has a paired test (q-system/.q-system/scripts/test_memory_confidence_validator.py), referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/session_recall.py :: .pr25rev/mut/q-system/.q-system/scripts/session_recall.py: 197 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/voice-lint.py :: .pr25rev/mut/q-system/.q-system/scripts/voice-lint.py: 678 lines; has a paired test (q-system/.q-system/scripts/test_review_tier.py), referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/voice-stop-gate.py :: .pr25rev/mut/q-system/.q-system/scripts/voice-stop-gate.py: 168 lines; has a paired test (q-system/.q-system/scripts/test/test-voice-enforcement-rule-wired.sh), referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/voice-dna-loader.py :: .pr25rev/mut/q-system/.q-system/scripts/voice-dna-loader.py: 158 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/audhd-lint.py :: .pr25rev/mut/q-system/.q-system/scripts/audhd-lint.py: 283 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/fleet-health-daily.py :: .pr25rev/mut/q-system/.q-system/scripts/fleet-health-daily.py: 1633 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/canonical-digest.py :: .pr25rev/mut/q-system/.q-system/scripts/canonical-digest.py: 264 lines; referenced on a wiring surface (q-system/.q-system/scripts/canonical-digest.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/fleet-board-refresh.py :: .pr25rev/mut/q-system/.q-system/scripts/fleet-board-refresh.py: 101 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/granola-voice-synthesize.py :: .pr25rev/mut/q-system/.q-system/scripts/granola-voice-synthesize.py: 139 lines; referenced on a wiring surface (automation/voice_refresh.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/launchd-health-check.py :: .pr25rev/mut/q-system/.q-system/scripts/launchd-health-check.py: 484 lines; has a paired test (q-system/.q-system/scripts/test_launchd_health_check.py), referenced on a wiring surface (AUTONOMOUS-SYSTEMS.md).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/capability-map-gen.py :: .pr25rev/mut/q-system/.q-system/scripts/capability-map-gen.py: 535 lines; has a paired test (q-system/.q-system/scripts/test/test-capability-map-wiring.py), referenced on a wiring surface (kipi).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/memory_reflect.py :: .pr25rev/mut/q-system/.q-system/scripts/memory_reflect.py: 276 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/lessons-validator.py :: .pr25rev/mut/q-system/.q-system/scripts/lessons-validator.py: 85 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-validator.sh), referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/stat-verify.py :: .pr25rev/mut/q-system/.q-system/scripts/stat-verify.py: 802 lines; has a paired test (q-system/.q-system/scripts/tests/test-stat-verify.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/memory-freshness-check.py :: .pr25rev/mut/q-system/.q-system/scripts/memory-freshness-check.py: 96 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/plugin-version-bump-check.py :: .pr25rev/mut/q-system/.q-system/scripts/plugin-version-bump-check.py: 125 lines; has a paired test (q-system/.q-system/scripts/test_plugin_version_bump_check.py), referenced on a wiring surface (lefthook.yml).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/linear-sync.py :: .pr25rev/mut/q-system/.q-system/scripts/linear-sync.py: 989 lines; has a paired test (.pr22rev/test-scratch-guard-push.sh), referenced on a wiring surface (kipi).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/lessons-distill.py :: .pr25rev/mut/q-system/.q-system/scripts/lessons-distill.py: 243 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-daily-exit.sh), referenced on a wiring surface (AUTONOMOUS-SYSTEMS.md).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/collection-gate.py :: .pr25rev/mut/q-system/.q-system/scripts/collection-gate.py: 162 lines; referenced on a wiring surface (q-system/.q-system/scripts/collection-gate.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/memory_outcomes.py :: .pr25rev/mut/q-system/.q-system/scripts/memory_outcomes.py: 226 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/instance-automation-guard.py :: .pr25rev/mut/q-system/.q-system/scripts/instance-automation-guard.py: 77 lines; has a paired test (q-system/.q-system/scripts/test/test-instance-automation-guard.sh), referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/sycophancy-monthly-check.py :: .pr25rev/mut/q-system/.q-system/scripts/sycophancy-monthly-check.py: 65 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/wiring-check.py :: .pr25rev/mut/q-system/.q-system/scripts/wiring-check.py: 270 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/instance-fact-inventory.py :: .pr25rev/mut/q-system/.q-system/scripts/instance-fact-inventory.py: 395 lines; has a paired test (q-system/.q-system/tests/separation/test_instance_fact_inventory.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/scan-draft.py :: .pr25rev/mut/q-system/.q-system/scripts/scan-draft.py: 208 lines; referenced on a wiring surface (validate-separation.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/accept-rate.py :: .pr25rev/mut/q-system/.q-system/scripts/accept-rate.py: 300 lines; referenced on a wiring surface (.prd-os/issues/accept-rate-metric-script.md).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/instruction-budget-audit.py :: .pr25rev/mut/q-system/.q-system/scripts/instruction-budget-audit.py: 221 lines; referenced on a wiring surface (AGENTS.md).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/instance-diet.py :: .pr25rev/mut/q-system/.q-system/scripts/instance-diet.py: 239 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/code_claim_grounding_guard.py :: .pr25rev/mut/q-system/.q-system/scripts/code_claim_grounding_guard.py: 194 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/linear-queue.py :: .pr25rev/mut/q-system/.q-system/scripts/linear-queue.py: 225 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-queue.sh), referenced on a wiring surface (kipi).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/containment-targets.py :: .pr25rev/mut/q-system/.q-system/scripts/containment-targets.py: 204 lines; has a paired test (q-system/.q-system/scripts/test/test-containment-gitlink.py), referenced on a wiring surface (validate-separation.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/firecrawl-scrape.py :: .pr25rev/mut/q-system/.q-system/scripts/firecrawl-scrape.py: 70 lines; has a paired test (q-system/.q-system/scripts/test/test-firecrawl-scrape.sh), referenced on a wiring surface (.prd-os/prds/prd-deterministic-reading-2026-07-28.md).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/copy-diff.py :: .pr25rev/mut/q-system/.q-system/scripts/copy-diff.py: 236 lines; referenced on a wiring surface (q-system/.q-system/scripts/copy-diff.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/memory_autocapture.py :: .pr25rev/mut/q-system/.q-system/scripts/memory_autocapture.py: 196 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/ripple-verify.py :: .pr25rev/mut/q-system/.q-system/scripts/ripple-verify.py: 191 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/changelog-write.py :: .pr25rev/mut/q-system/.q-system/scripts/changelog-write.py: 86 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/format-lint.py :: .pr25rev/mut/q-system/.q-system/scripts/format-lint.py: 202 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/route-overrides-to-learn.py :: .pr25rev/mut/q-system/.q-system/scripts/route-overrides-to-learn.py: 201 lines; referenced on a wiring surface (q-system/.q-system/scripts/route-overrides-to-learn.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/batch-uniformity-lint.py :: .pr25rev/mut/q-system/.q-system/scripts/batch-uniformity-lint.py: 213 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/synthesize-schedule.py :: .pr25rev/mut/q-system/.q-system/scripts/synthesize-schedule.py: 1148 lines; referenced on a wiring surface (q-system/.q-system/scripts/synthesize-schedule.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/propagation-leak-gate.py :: .pr25rev/mut/q-system/.q-system/scripts/propagation-leak-gate.py: 1255 lines; has a paired test (q-system/.q-system/scripts/test/test-kipi-update-build-artifacts.sh), referenced on a wiring surface (build-template-repo.sh).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/correction_outcome.py :: .pr25rev/mut/q-system/.q-system/scripts/correction_outcome.py: 84 lines; has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/scripts/correction_outcome.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/settings-template-sync-check.py :: .pr25rev/mut/q-system/.q-system/scripts/settings-template-sync-check.py: 146 lines; has a paired test (q-system/.q-system/scripts/test_settings_template_sync_check.py), referenced on a wiring surface (kipi-update.sh).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/receipts-ledger-check.py :: .pr25rev/mut/q-system/.q-system/scripts/receipts-ledger-check.py: 170 lines; has a paired test (q-system/.q-system/scripts/test/test-receipts-ledger-check.sh), referenced on a wiring surface (lefthook.yml).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/linear-job-migration.py :: .pr25rev/mut/q-system/.q-system/scripts/linear-job-migration.py: 225 lines; referenced on a wiring surface (kipi).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/memory-scores-surface.py :: .pr25rev/mut/q-system/.q-system/scripts/memory-scores-surface.py: 178 lines; has a paired test (q-system/.q-system/scripts/test_memory_scores_surface.py), referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/verify-containment-export.py :: .pr25rev/mut/q-system/.q-system/scripts/verify-containment-export.py: 556 lines; has a paired test (q-system/.q-system/tests/separation/test_containment_export.py), referenced on a wiring surface (.prd-os/issues/sdc-owner-export.md).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/linkedin-format-lint.py :: .pr25rev/mut/q-system/.q-system/scripts/linkedin-format-lint.py: 285 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/capability-gate.py :: .pr25rev/mut/q-system/.q-system/scripts/capability-gate.py: 571 lines; has a paired test (q-system/.q-system/scripts/test_capability_gate.py), referenced on a wiring surface (fleet-capability-verify.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/stat-registry-extract.py :: .pr25rev/mut/q-system/.q-system/scripts/stat-registry-extract.py: 245 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/md-prune.py :: .pr25rev/mut/q-system/.q-system/scripts/md-prune.py: 229 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/publish-reconciliation.py :: .pr25rev/mut/q-system/.q-system/scripts/publish-reconciliation.py: 220 lines; referenced on a wiring surface (q-system/.q-system/scripts/publish-reconciliation.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/prompt-only-enforcement-guard.py :: .pr25rev/mut/q-system/.q-system/scripts/prompt-only-enforcement-guard.py: 348 lines; has a paired test (q-system/.q-system/scripts/test_prompt_only_enforcement_guard.py), referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/skill-trigger-eval.py :: .pr25rev/mut/q-system/.q-system/scripts/skill-trigger-eval.py: 86 lines; has a paired test (q-system/.q-system/scripts/test/test-skill-trigger-eval.sh), referenced on a wiring surface (q-system/.q-system/scripts/skill-trigger-eval.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/temperature-scoring.py :: .pr25rev/mut/q-system/.q-system/scripts/temperature-scoring.py: 302 lines; referenced on a wiring surface (q-system/.q-system/scripts/temperature-scoring.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/pdf-extract.py :: .pr25rev/mut/q-system/.q-system/scripts/pdf-extract.py: 208 lines; referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/granola-voice-fingerprint.py :: .pr25rev/mut/q-system/.q-system/scripts/granola-voice-fingerprint.py: 95 lines; referenced on a wiring surface (automation/voice_refresh.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/content-lint.py :: .pr25rev/mut/q-system/.q-system/scripts/content-lint.py: 164 lines; has a paired test (q-system/.q-system/scripts/test-ripple.py), referenced on a wiring surface (q-system/.q-system/commands.md).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/lessons_scrub.py :: .pr25rev/mut/q-system/.q-system/scripts/lessons_scrub.py: 89 lines; has a paired test (q-system/.q-system/scripts/test/test-lessons-scrub.sh), referenced on a wiring surface (q-system/.q-system/scripts/lessons-daily.sh).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/decision-origin-tag-lint.py :: .pr25rev/mut/q-system/.q-system/scripts/decision-origin-tag-lint.py: 182 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/headline-lint.py :: .pr25rev/mut/q-system/.q-system/scripts/headline-lint.py: 314 lines; referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/fleet-loop-board.py :: .pr25rev/mut/q-system/.q-system/scripts/fleet-loop-board.py: 321 lines; referenced on a wiring surface (q-system/.q-system/scripts/fleet-board-refresh.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/linear-issue-ref-check.py :: .pr25rev/mut/q-system/.q-system/scripts/linear-issue-ref-check.py: 153 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-issue-ref-check.sh), referenced on a wiring surface (kipi).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/run-step-audit.py :: .pr25rev/mut/q-system/.q-system/scripts/run-step-audit.py: 91 lines; has a paired test (q-system/.q-system/scripts/test/test-open-loops-heartbeat-exit.sh), referenced on a wiring surface (q-system/.q-system/scripts/open-loops-heartbeat.sh).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/linear-dor-drafter.py :: .pr25rev/mut/q-system/.q-system/scripts/linear-dor-drafter.py: 560 lines; has a paired test (q-system/.q-system/scripts/test/test-linear-dor-drafter-redrive.sh), referenced on a wiring surface (kipi).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/update-preservation-manifest.py :: .pr25rev/mut/q-system/.q-system/scripts/update-preservation-manifest.py: 668 lines; has a paired test (q-system/.q-system/scripts/test/test-update-preservation-manifest.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/memory-confidence-surface.py :: .pr25rev/mut/q-system/.q-system/scripts/memory-confidence-surface.py: 115 lines; has a paired test (q-system/.q-system/scripts/test_memory_confidence_surface.py), referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/compliance-check.py :: .pr25rev/mut/q-system/.q-system/scripts/compliance-check.py: 354 lines; referenced on a wiring surface (q-system/.q-system/scripts/compliance-check.py).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/capability-overlap.py :: .pr25rev/mut/q-system/.q-system/scripts/capability-overlap.py: 305 lines; referenced on a wiring surface (kipi).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/voice-substance-lint.py :: .pr25rev/mut/q-system/.q-system/scripts/voice-substance-lint.py: 274 lines; has a paired test (q-system/.q-system/scripts/test/test-voice-enforcement-rule-wired.sh), referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/open-loops.py :: .pr25rev/mut/q-system/.q-system/scripts/open-loops.py: 150 lines; has a paired test (q-system/.q-system/scripts/test/test-open-loops-heartbeat-exit.sh), referenced on a wiring surface (settings-template.json).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/linear-claim.py :: .pr25rev/mut/q-system/.q-system/scripts/linear-claim.py: 585 lines; has a paired test (.pr28rev/scripts/test-severity-floor.sh), referenced on a wiring surface (kipi).
LIVE True .pr25rev/mut/q-system/.q-system/scripts/granola-voice-harvest.py :: .pr25rev/mut/q-system/.q-system/scripts/granola-voice-harvest.py: 120 lines; has a paired test (automation/test_voice_refresh_command.py), referenced on a wiring surface (plugins/kipi-core/commands/voice-refresh.md).
.pr25rev/burn-66438/bin/claude
.pr25rev/burn-66438/bin/gh
.pr25rev/burn-66438/bin/python3
.pr25rev/burn-66438/notify.sh
.pr25rev/burn-66438/origin/HEAD
.pr25rev/burn-66438/origin/config
.pr25rev/burn-66438/origin/description
.pr25rev/burn-66438/origin/hooks/applypatch-msg.sample
.pr25rev/burn-66438/origin/hooks/commit-msg.sample
.pr25rev/burn-66438/origin/hooks/fsmonitor-watchman.sample
.pr25rev/burn-66438/origin/hooks/post-update.sample
.pr25rev/burn-66438/origin/hooks/pre-applypatch.sample
.pr25rev/burn-66438/origin/hooks/pre-commit.sample
.pr25rev/burn-66438/origin/hooks/pre-merge-commit.sample
.pr25rev/burn-66438/origin/hooks/pre-push.sample
.pr25rev/burn-66438/origin/hooks/pre-rebase.sample
.pr25rev/burn-66438/origin/hooks/pre-receive.sample
.pr25rev/burn-66438/origin/hooks/prepare-commit-msg.sample
.pr25rev/burn-66438/origin/hooks/push-to-checkout.sample
.pr25rev/burn-66438/origin/hooks/sendemail-validate.sample
.pr25rev/burn-66438/origin/hooks/update.sample
.pr25rev/burn-66438/origin/info/exclude
.pr25rev/burn-66438/origin/objects/4b/825dc642cb6eb9a060e54bf8d69288fbee4904
.pr25rev/burn-66438/origin/objects/50/eac4a17b28419c89551740db5c1b4942e8a4dd
.pr25rev/burn-66438/origin/refs/heads/main
.pr25rev/burn-66438/pages.txt
.pr25rev/burn-66438/run1.out
.pr25rev/burn-66438/run2.out
.pr25rev/burn-66438/run3.out
.pr25rev/burn-66438/skel
.pr25rev/burn-66438/stale-claims.json
.pr25rev/burn-66438/state/linear-worker-attempts.json
.pr25rev/burn-66438/state/linear-worker.log
.pr25rev/burn-66438/state/pr-reviews/pr-777.verdict.json
.pr25rev/burn-66438/state/worktrees/ask-aaa
.pr25rev/burn-66438/worked.txt
.pr25rev/extract.sh
.pr25rev/head/q-system/.q-system/scripts/linear-worker.sh
.pr25rev/head/q-system/.q-system/scripts/pr-verdict-lib.sh
.pr25rev/head/q-system/.q-system/scripts/test/test-severity-floor.sh
.pr25rev/mut/q-system/.q-system/scripts/accept-rate.py
.pr25rev/mut/q-system/.q-system/scripts/audhd-lint.py
.pr25rev/mut/q-system/.q-system/scripts/autocapture_config.json
.pr25rev/mut/q-system/.q-system/scripts/batch-uniformity-lint.py
.pr25rev/mut/q-system/.q-system/scripts/canonical-digest.py
.pr25rev/mut/q-system/.q-system/scripts/capability-gate.py
.pr25rev/mut/q-system/.q-system/scripts/capability-map-gen.py
.pr25rev/mut/q-system/.q-system/scripts/capability-overlap.py
.pr25rev/mut/q-system/.q-system/scripts/changelog-write.py
.pr25rev/mut/q-system/.q-system/scripts/code_claim_grounding_guard.py
.pr25rev/mut/q-system/.q-system/scripts/collection-gate.py
.pr25rev/mut/q-system/.q-system/scripts/com.kipi.fleet-health.plist
.pr25rev/mut/q-system/.q-system/scripts/com.kipi.linear-dor.plist
.pr25rev/mut/q-system/.q-system/scripts/com.kipi.openloops-heartbeat.plist
.pr25rev/mut/q-system/.q-system/scripts/compliance-check.py
.pr25rev/mut/q-system/.q-system/scripts/containment-targets.py
.pr25rev/mut/q-system/.q-system/scripts/content-lint.py
.pr25rev/mut/q-system/.q-system/scripts/converge.sh
.pr25rev/mut/q-system/.q-system/scripts/copy-diff.py
.pr25rev/mut/q-system/.q-system/scripts/correction_outcome.py
.pr25rev/mut/q-system/.q-system/scripts/decision-origin-tag-lint.py
.pr25rev/mut/q-system/.q-system/scripts/firecrawl-scrape.py
.pr25rev/mut/q-system/.q-system/scripts/fleet-board-refresh.py
.pr25rev/mut/q-system/.q-system/scripts/fleet-health-daily.py
.pr25rev/mut/q-system/.q-system/scripts/fleet-loop-board.py
.pr25rev/mut/q-system/.q-system/scripts/format-lint.py
.pr25rev/mut/q-system/.q-system/scripts/granola-voice-fingerprint.py
.pr25rev/mut/q-system/.q-system/scripts/granola-voice-harvest.py
.pr25rev/mut/q-system/.q-system/scripts/granola-voice-synthesize.py
.pr25rev/mut/q-system/.q-system/scripts/headline-lint.py
.pr25rev/mut/q-system/.q-system/scripts/init-bus-day.sh
.pr25rev/mut/q-system/.q-system/scripts/install-lessons-daily.sh
.pr25rev/mut/q-system/.q-system/scripts/install-plist.sh
.pr25rev/mut/q-system/.q-system/scripts/instance-automation-guard.py
.pr25rev/mut/q-system/.q-system/scripts/instance-diet-fix.sh
.pr25rev/mut/q-system/.q-system/scripts/instance-diet.py
.pr25rev/mut/q-system/.q-system/scripts/instance-fact-inventory.py
.pr25rev/mut/q-system/.q-system/scripts/instruction-budget-audit.py
.pr25rev/mut/q-system/.q-system/scripts/launchd-health-check.py
.pr25rev/mut/q-system/.q-system/scripts/lesson-note.sh
     419
   330	# reference; markdown is handled separately below because prose is not wiring.
   331	SURFACE_CODE_EXT = {
   332	    ".py", ".sh", ".bash", ".zsh", ".yml", ".yaml", ".toml", ".json",
   333	    ".cfg", ".ini", ".mk", ".txt",
   334	}
   335	SURFACE_DOC_EXT = {".md"}
   336	# Extensionless wiring surfaces (the kipi CLI, Makefiles, lefthook's shell blocks).
   337	SURFACE_NAMES = {"Makefile", "makefile", "kipi", "Dockerfile", "Justfile", "justfile"}
   338	
   339	# GENERATED ARTIFACTS ARE NOT WIRING SURFACES (ASK-122, caught pre-merge).
   340	#
   341	# Widening the scan repo-wide swept in q-system/output/, which holds codex
   342	# transcripts, run logs, plans and RCAs. Those name scripts constantly and run
   343	# nothing. Measured on kipi-investigations: _sync_all.py flipped to LIVE on the
   344	# strength of `q-system/output/codex-sfactivity-prd-out.txt` line 738, a bare
   345	# `find`-style listing `./plugins/.../_sync_all.py`.
   346	#
   347	# The invocation filter cannot save this: that line starts with "./" and so
   348	# matches MD_INVOCATION_RE. A log of a command that ENUMERATED files is
   349	# indistinguishable, line by line, from a runbook that INVOKES one. The only
   350	# durable separator is provenance -- who wrote the file -- so the fix is to drop
   351	# generated trees from the surface rather than to write a cleverer regex.
   352	#
   353	# q-system/output/ is the OS's generated-artifacts directory by convention; it is
   354	# also in kipi-update.sh's INSTANCE_OWNED_SUBTREES, i.e. already understood
   355	# fleet-wide as an instance's own output rather than source.
   356	GENERATED_SURFACE_PREFIXES = ("q-system/output/",)
   357	
   358	
   359	def _witness_rank(p: Path):
   360	    """Sort key that prefers a REAL caller over a scratch/hidden copy of one.
   361	
   362	    Any path component starting with "." is a review tree, a worktree or a tool
   363	    cache, never the wiring a reader should be sent to look at.
   364	    """
   365	    parts = p.parts
   366	    hidden = any(part.startswith(".") for part in parts)
   367	    return (hidden, len(parts), str(p))
   368	
   369	
   370	def is_generated_surface(p: Path, root: Path) -> bool:
   371	    """True when p is a generated artifact, so its content must not count as wiring."""
   372	    try:
   373	        rel = p.relative_to(root).as_posix()
   374	    except ValueError:
   375	        return False
   376	    return rel.startswith(GENERATED_SURFACE_PREFIXES)
   377	
   378	# A markdown line only counts as wiring if it INVOKES something. A findings doc
   379	# saying "engine_x.py left the template unfilled" names a script without keeping it
   380	# alive; a runbook line `python3 engine_x.py` does. Without this split, widening the
   381	# scan repo-wide just trades false-dead for false-alive (ASK-122).
   382	MD_INVOCATION_RE = re.compile(r"(?:python3?\s|bash\s|\bsh\s|\./|source\s|-m\s)")
   383	
   384	# Module tokens an engine can be reached by WITHOUT its .py suffix. `import x`,
   385	# `from x import y`, `python -m x`, and importlib's spec_from_file_location("x", ...)
   386	# are all real callers that a filename-only scan reads as silence. Scar: ASK-230,
   387	# where provenance_vocabulary.py had two live importers and was reported inert
   388	# because both wrote `import provenance_vocabulary` with no extension.
   389	MODULE_REF_RE = re.compile(
   390	    r"^\s*from\s+([\w.]+)\s+import\b"
   391	    r"|^\s*import\s+([\w.]+)"
   392	    r"|spec_from_file_location\(\s*[\"']([\w.\-]+)[\"']"
   393	    r"|-m\s+([\w.]+)\b",
   394	    re.M,
   395	)
   396	
   397	
   398	# `fill_sheet.2026-07-28.py` beside `fill_sheet.py` is a dated SNAPSHOT of an
   399	# engine, not a second engine. Alice's run-sweep.sh writes one before every sweep
   400	# (`cp "$GEN/fill_sheet.py" "$DIR/backups/fill_sheet.$TODAY.py"`) and copies it back
   401	# on failure, so it is live DATA on a rollback path. No static scan can ever match
   402	# it -- the caller interpolates $TODAY -- so it would report UNWIRED forever and
   403	# the only way to "fix" it is to delete a rollback artifact (ASK-122).
   404	DATED_SNAPSHOT_RE = re.compile(r"\.\d{4}-\d{2}-\d{2}$")
   405	
   406	
   407	def _is_test_file(p: Path) -> bool:
   408	    return p.name.startswith(("test_", "test-")) or "test" in p.parts or "tests" in p.parts
   409	
   410	
   411	def _iter_surface_files(root: Path):
   412	    """Every file in the repo whose content can constitute wiring.
   413	
   414	    WHY REPO-WIDE (ASK-122): the previous list walked only .claude/, plugins/ and
   415	    q-system/, so an instance whose code lives anywhere else reported its own
   416	    runners as absent. Alice flagged 22 engines UNWIRED while `regenerate.sh` ran
   417	    four of them by path and `pipeline.py` imported two more. The scan has to
   418	    follow the repo, not a layout the skeleton happens to use.
   419	    """
   420	    for p in root.rglob("*"):
   421	        if not p.is_file() or is_vendored(p):
   422	            continue
   423	        if is_generated_surface(p, root):
   424	            continue
   425	        if p.suffix.lower() in SURFACE_CODE_EXT or p.suffix.lower() in SURFACE_DOC_EXT:
   426	            yield p
   427	        elif p.name in SURFACE_NAMES:
   428	            yield p
   429	
   430	
   431	def _build_reference_index(root: Path, engines: list) -> dict:
   432	    """Map each engine path -> the set of OTHER files that reference it.
   433	
   434	    Two ways to match: the file name (`foo.py`, seen in shell/CLI invocations and
   435	    config) and the bare module name, but the bare name ONLY inside an import or
   436	    loader construct. A generic stem like `pipeline` appears in ordinary prose all
   437	    over this fleet; counting bare-word hits would mark half the repo live.
   438	    """
   439	    by_filename = {}
   440	    by_module = {}
   441	    for p in engines:
   442	        by_filename.setdefault(p.name, []).append(p)
   443	        by_module.setdefault(p.stem, []).append(p)
   444	    if not by_filename:
   445	        return {}
   446	
   447	    # One alternation, one pass per file: a per-engine regex would be
   448	    # len(engines) x len(files) scans, which is minutes on a large instance.
   449	    # The lookbehind must NOT exclude "/": the common form is path-qualified
   450	    # (`python3 "$G/fill_sheet.py"`), and blocking it hid every shell caller.
   451	    filename_re = re.compile(
   452	        r"(?<![\w.\-])(" + "|".join(re.escape(n) for n in sorted(by_filename)) + r")(?![\w\-])"
   453	    )
   454	
   455	    refs: dict = {}
   456	    for src in _iter_surface_files(root):
   457	        text = read_text(src)
   458	        if not text:
   459	            continue
   460	        if src.suffix.lower() in SURFACE_DOC_EXT:
   461	            text = "\n".join(ln for ln in text.splitlines() if MD_INVOCATION_RE.search(ln))
   462	            if not text:
   463	                continue
   464	        for match in filename_re.finditer(text):
   465	            for engine in by_filename[match.group(1)]:
   466	                if engine != src:
   467	                    refs.setdefault(engine, set()).add(src)
   468	        for match in MODULE_REF_RE.finditer(text):
   469	            token = next((g for g in match.groups() if g), None)
   470	            if not token:
   471	                continue
   472	            for part in (token, token.rsplit(".", 1)[-1]):
   473	                for engine in by_module.get(part, ()):
   474	                    if engine != src:
   475	                        refs.setdefault(engine, set()).add(src)
   476	    return refs
   477	
   478	
   479	def collect_engines(root: Path) -> list:
   480	    """Scripts that have a paired test, or that are referenced from a wiring
   481	    surface. An engine with neither is reported UNWIRED rather than assumed fine."""
   482	    caps = []
   483	    tests = {p.name for p in root.rglob("test*") if p.is_file() and not is_vendored(p)}
   484	
   485	    engines = []
   486	    for p in root.rglob("*.py"):
   487	        if is_vendored(p):
   488	            continue
   489	        if p.name.startswith(("test_", "test-")) or "test" in p.parts:
   490	            continue
   491	        # A generated tree is not a wiring surface (see is_generated_surface), so
   492	        # it must not be an ENGINE source either. Excluding it from only one of
   493	        # the two makes its contents permanently dark: still collected, but with
   494	        # every file that could reference them now off-surface, so they report
   495	        # UNWIRED with no way to ever clear it (review finding, PR #74 major;
   496	        # would have compounded sp-3761d2d9). An artifact is not an engine, so
   497	        # the coherent move is to stop reporting it at all rather than to report
   498	        # it as dead. Measured: drops 12 phantom engines in kipi-investigations.
   499	        if is_generated_surface(p, root):
   500	            continue
   501	        if DATED_SNAPSHOT_RE.search(p.stem):
   502	            continue
   503	        if len(read_text(p).splitlines()) < 40:
   504	            continue
   505	        engines.append(p)
   506	
   507	    refs = _build_reference_index(root, engines)
   508	
   509	    for p in engines:
   510	        text = read_text(p)

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "python3 - <<'PY'
import os
from pathlib import Path
cwd = Path.cwd()
for name in ['pr74-duplicate-basename-repro.py','pr74-hidden-artifact-repro.py','pr74-relative-import-repro.py']:
    p = Path(os.environ['TMPDIR']) / name
    print(p)
    print(os.path.relpath(p, cwd))
PY" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
/var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
../../../../../../var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
/var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-hidden-artifact-repro.py
../../../../../../var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-hidden-artifact-repro.py
/var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-relative-import-repro.py
../../../../../../var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-relative-import-repro.py

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
hook: PreToolUse
hook: PreToolUse Completed
apply patch
patch: completed
/var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'python3 "$TMPDIR/pr74-duplicate-basename-repro.py"' in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
dead/worker.py LIVE dead/worker.py: 47 lines; referenced on a wiring surface (run.sh).
live/worker.py LIVE live/worker.py: 47 lines; referenced on a wiring surface (run.sh).

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "wc -l q-system/lib/kipi_ingest/*.py q-system/lib/kipi_ingest/readers/*.py && python3 - <<'PY'
import json, os
from pathlib import Path
p = Path(os.environ['TMPDIR']) / 'pr74-capability-map.json'
data = json.loads(p.read_text())
for c in data['capabilities']:
    if c['layer'] == 'L5 Engines and scripts' and 'kipi_ingest' in c['entry']:
        print(c['entry'], c['status'], c['evidence'])
PY
rg -n \"from \\.|import \\..*\" q-system/lib/kipi_ingest --glob '*.py'" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
      42 q-system/lib/kipi_ingest/__init__.py
     182 q-system/lib/kipi_ingest/conformance.py
     185 q-system/lib/kipi_ingest/contract.py
     110 q-system/lib/kipi_ingest/drift_check.py
      14 q-system/lib/kipi_ingest/readers/__init__.py
      62 q-system/lib/kipi_ingest/readers/csv_reader.py
      59 q-system/lib/kipi_ingest/readers/markdown.py
      82 q-system/lib/kipi_ingest/readers/xlsx_reader.py
     736 total
q-system/lib/kipi_ingest/drift_check.py LIVE q-system/lib/kipi_ingest/drift_check.py: 110 lines; referenced on a wiring surface (q-system/lib/kipi_ingest/README.md).
q-system/lib/kipi_ingest/__init__.py LIVE q-system/lib/kipi_ingest/__init__.py: 42 lines; has a paired test (plugins/prd-os/tests/test_prd_map_runner.py).
q-system/lib/kipi_ingest/conformance.py LIVE q-system/lib/kipi_ingest/conformance.py: 182 lines; referenced on a wiring surface (q-system/lib/kipi_ingest/README.md).
q-system/lib/kipi_ingest/contract.py LIVE q-system/lib/kipi_ingest/contract.py: 185 lines; has a paired test (name-matched test file), referenced on a wiring surface (q-system/lib/kipi_ingest/__init__.py).
q-system/lib/kipi_ingest/readers/xlsx_reader.py LIVE q-system/lib/kipi_ingest/readers/xlsx_reader.py: 82 lines; referenced on a wiring surface (q-system/lib/kipi_ingest/readers/__init__.py).
q-system/lib/kipi_ingest/readers/csv_reader.py LIVE q-system/lib/kipi_ingest/readers/csv_reader.py: 62 lines; referenced on a wiring surface (q-system/lib/kipi_ingest/readers/__init__.py).
q-system/lib/kipi_ingest/readers/markdown.py LIVE q-system/lib/kipi_ingest/readers/markdown.py: 59 lines; referenced on a wiring surface (q-system/lib/kipi_ingest/readers/__init__.py).
q-system/lib/kipi_ingest/readers/markdown.py:12:from ..contract import Block, Drop, ReadResult, make_block_id
q-system/lib/kipi_ingest/readers/xlsx_reader.py:15:from ..contract import Block, Drop, ReadResult, make_block_id
q-system/lib/kipi_ingest/readers/csv_reader.py:13:from ..contract import Block, Drop, ReadResult, make_block_id
q-system/lib/kipi_ingest/__init__.py:14:from .contract import (
q-system/lib/kipi_ingest/readers/__init__.py:10:from .markdown import read_md
q-system/lib/kipi_ingest/readers/__init__.py:11:from .csv_reader import read_csv
q-system/lib/kipi_ingest/readers/__init__.py:12:from .xlsx_reader import read_xlsx  # openpyxl imported lazily inside read_xlsx

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "sed -n '1,60p' q-system/lib/kipi_ingest/__init__.py && rg -n \"contract\\.py|xlsx_reader\\.py|csv_reader\\.py|markdown\\.py\" q-system/lib/kipi_ingest --glob '*.py'" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
"""kipi_ingest -- fleet-canonical ingestion coverage contract + readers.

Import the contract from anywhere an instance has `q-system/lib` on sys.path:

    from kipi_ingest import ReadResult, Block, reconcile, ground
    from kipi_ingest.readers import read_md, read_csv

Canonical source lives in the kipi-system skeleton and propagates unchanged to
every instance via `kipi update`. Do not edit an instance's copy; edit canonical.
See PRD prd-fleet-ingestion-coverage-contract-2026-07-06.
"""
from __future__ import annotations

from .contract import (
    Block,
    Drop,
    DuplicateBlockError,
    IngestError,
    ReadResult,
    UngroundedReferenceError,
    UnreadUnitError,
    ground,
    index_blocks,
    make_block_id,
    reconcile,
)

__all__ = [
    "Block",
    "Drop",
    "DuplicateBlockError",
    "IngestError",
    "ReadResult",
    "UngroundedReferenceError",
    "UnreadUnitError",
    "ground",
    "index_blocks",
    "make_block_id",
    "reconcile",
]

__version__ = "0.1.0"
q-system/lib/kipi_ingest/drift_check.py:72:    pkg = root if (root / "contract.py").exists() else root / "kipi_ingest"

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "nl -ba kipi | sed -n '120,190p' && rg -n \"capabilities|capability-map-gen\" q-system/.q-system/scripts q-system/.q-system/*.py kipi .github --glob '"'!q-system/output/**'"' | sed -n '1,220p' && git show --stat --oneline d20f412 && git show --stat --oneline d48ad6a && git show --stat --oneline 73a8870" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
   120	    # refuses a commit that names no issue; this is how you cheaply get an issue
   121	    # to name BEFORE building, rather than minting a receipt after.
   122	    # Capture is local and offline; the Linear write happens in the agent drain,
   123	    # because no Linear API key exists for a shell to use.
   124	    shift || true
   125	    QUEUE="$KIPI_HOME/q-system/.q-system/scripts/linear-queue.py"
   126	    SYNC="$KIPI_HOME/q-system/.q-system/scripts/linear-sync.py"
   127	    # linear-claim.py resolves the tree it locks from the CALLER's cwd, not from
   128	    # $KIPI_HOME -- otherwise every instance would share the skeleton's lock.
   129	    CLAIM="$KIPI_HOME/q-system/.q-system/scripts/linear-claim.py"
   130	    sub="${1:-pending}"
   131	    shift || true
   132	    case "$sub" in
   133	      issue)
   134	        title="${1:-}"
   135	        if [ -z "$title" ]; then
   136	          echo "usage: kipi linear issue \"<title>\" [--note \"...\"]" >&2
   137	          exit 1
   138	        fi
   139	        shift || true
   140	        repo="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")"
   141	        python3 "$QUEUE" add --repo "$repo" --kind issue --title "$title" --source kipi-cli "$@"
   142	        echo ""
   143	        echo "Captured. It is not in Linear yet: run /linear-drain in a Claude session."
   144	        ;;
   145	      pending) python3 "$QUEUE" pending "$@" ;;
   146	      status)  python3 "$SYNC" status "$@" ;;
   147	      map)
   148	        # Regenerate the capability map for every registered instance + the
   149	        # skeleton. Cheap (~25s) and the only way drift gets noticed.
   150	        python3 - "$KIPI_HOME" <<'PY'
   151	import json, os, subprocess, sys
   152	home = sys.argv[1]
   153	gen = os.path.join(home, "q-system/.q-system/scripts/capability-map-gen.py")
   154	outdir = os.path.join(home, "q-system/output/capability-maps")
   155	os.makedirs(outdir, exist_ok=True)
   156	reg = json.load(open(os.path.join(home, "instance-registry.json")))["instances"]
   157	targets = reg + [{"name": "kipi-system", "path": home}]
   158	for i in targets:
   159	    out = os.path.join(outdir, i["name"].replace(" ", "_") + ".json")
   160	    r = subprocess.run(["python3", gen, "--root", i["path"], "--repo", i["name"],
   161	                        "--out", out], capture_output=True, text=True)
   162	    print(r.stdout.strip() or f"FAILED {i['name']}: {r.stderr.strip()[:120]}")
   163	PY
   164	        ;;
   165	      overlap)
   166	        python3 "$KIPI_HOME/q-system/.q-system/scripts/capability-overlap.py" \
   167	          --maps "$KIPI_HOME/q-system/output/capability-maps" \
   168	          --out "$KIPI_HOME/q-system/output/plans/capability-overlap-$(date +%F).md" \
   169	          --digest "$KIPI_HOME/q-system/output/capability-digest.json" "$@"
   170	        ;;
   171	      plan)    python3 "$SYNC" plan "$@" ;;
   172	      # Applies a plan to LIVE Linear. Dry unless --apply, because Linear
   173	      # delete/archive are hook-blocked so a duplicate is permanent.
   174	      create)  python3 "$SYNC" create "$@" ;;
   175	      remote)  python3 "$SYNC" remote "$@" ;;
   176	      # Progress belongs ON the issue: a trail the next agent can read.
   177	      progress) python3 "$SYNC" progress "$@" ;;
   178	      record)  python3 "$SYNC" record "$@" ;;
   179	      key)     python3 "$SYNC" key "$@" ;;
   180	      # Claim BEFORE creating a branch or worktree. Exit 3 means refused (another
   181	      # session holds this tree), which is the feature, not a failure.
   182	      claim)   python3 "$CLAIM" claim "$@" ;;
   183	      release) python3 "$CLAIM" release "$@" ;;
   184	      claims)  python3 "$CLAIM" status "$@" ;;
   185	      *)
   186	        echo "unknown: kipi linear $sub" >&2
   187	        echo "try: issue | pending | status | map | overlap | plan | remote | create | progress | record | key" >&2
   188	        echo "     claim | release | claims" >&2
   189	        exit 1
   190	        ;;
kipi:153:gen = os.path.join(home, "q-system/.q-system/scripts/capability-map-gen.py")
q-system/.q-system/scripts/linear-sync.py:220:        f"`capability-map-gen.py` found **{count} Python {engines}** in `{repo}` "
q-system/.q-system/scripts/linear-sync.py:240:        "python3 q-system/.q-system/scripts/capability-map-gen.py \\",
q-system/.q-system/scripts/linear-sync.py:995:    caps = cmap.get("capabilities") or []
q-system/.q-system/scripts/linear-sync.py:997:    # Collision check BEFORE anything else. Two capabilities that slugify to the
q-system/.q-system/scripts/linear-sync.py:1006:                f"       Rename one in the capability map. Two capabilities sharing a\n"
q-system/.q-system/scripts/capability-map-gen.py:59:# swallows every child's capabilities and the fleet is counted several times over
q-system/.q-system/scripts/capability-map-gen.py:60:# (first full run: 12430 capabilities, badly inflated). A nested git repo is a
q-system/.q-system/scripts/capability-map-gen.py:276:                # several events/matchers, and those are different capabilities.
q-system/.q-system/scripts/capability-map-gen.py:565:    """Two capabilities that slugify to one key would collapse into one permanent
q-system/.q-system/scripts/capability-map-gen.py:605:    instances. Those capabilities are therefore THE SAME capability, present 24
q-system/.q-system/scripts/capability-map-gen.py:649:            "Generated by q-system/.q-system/scripts/capability-map-gen.py from "
q-system/.q-system/scripts/capability-map-gen.py:662:        "capabilities": caps,
q-system/.q-system/scripts/capability-map-gen.py:672:                    help="skeleton repo root; capabilities that also exist there are "
q-system/.q-system/scripts/capability-map-gen.py:687:    print(f"{args.repo}: {len(cmap['capabilities'])} capabilities ({counts}) "
q-system/.q-system/scripts/capability-gate.py:2:"""Capability gate: diff DECLARED capabilities against ACTUAL repo state, both
q-system/.q-system/scripts/fleet-health-daily.py:1016:    capability-map-gen.py already FINDS unwired engines. Before this, that finding
q-system/.q-system/scripts/fleet-health-daily.py:1041:        unwired = [c for c in (cmap.get("capabilities") or [])
q-system/.q-system/scripts/fleet-health-daily.py:1053:                f"`capability-map-gen.py` reports **{len(unwired)} unwired engine(s)** in "
q-system/.q-system/scripts/capability-overlap.py:4:Pairs with capability-map-gen.py (which produces the inputs) and the SDLC standard
q-system/.q-system/scripts/capability-overlap.py:150:        for cap in d["capabilities"]:
q-system/.q-system/scripts/capability-overlap.py:253:    A(f"{len(orphan_local)} governance/enforcement/engine capabilities exist in "
q-system/.q-system/scripts/capability-overlap.py:260:    A("| Repo | Local-only L0/L3/L5 capabilities |")
q-system/.q-system/scripts/capability-overlap.py:274:                    "capabilities": len(d["capabilities"]),
q-system/.q-system/scripts/linear-triage.py:6:`capability-map-gen.py` reports what is wired and explicitly refuses to judge it:
q-system/.q-system/scripts/linear-triage.py:28:names actually exist. Same discipline as capability-map-gen, whose every
q-system/.q-system/scripts/test/test-kipi-update-unmanaged-instance.sh:5:# of its 28 capabilities originating from the skeleton, while every other
q-system/.q-system/scripts/test/test-capability-map-wiring.py:2:"""Wiring detection in capability-map-gen.py: what counts as "this engine is alive".
q-system/.q-system/scripts/test/test-capability-map-wiring.py:34:GEN = Path(__file__).resolve().parent.parent / "capability-map-gen.py"
q-system/.q-system/scripts/test/test-linear-sync-idempotent.sh:38:  "capabilities": [
q-system/.q-system/scripts/test/test-linear-sync-idempotent.sh:170:{"repo": "demo_repo", "capabilities": [
q-system/.q-system/scripts/evidence_ledger.py:86:    caller re-derives the path. Precedent: capability-map-gen.py:390.
q-system/.q-system/scripts/content-lint.py:12:- Talk tracks claiming capabilities not in current-state.md
d20f412 fix(capability-map): see callers outside q-system/, count importing tests, skip dated snapshots (ASK-122)
 q-system/.q-system/capability-manifest.json        |   4 +
 q-system/.q-system/scripts/capability-map-gen.py   | 153 ++++++++++++++----
 .../scripts/test/test-capability-map-wiring.py     | 172 +++++++++++++++++++++
 3 files changed, 303 insertions(+), 26 deletions(-)
d48ad6a fix(capability-map): generated artifacts are not wiring surfaces (ASK-122)
 q-system/.q-system/scripts/capability-map-gen.py   | 30 +++++++++++++++++++
 .../scripts/test/test-capability-map-wiring.py     | 34 +++++++++++++++++++---
 2 files changed, 60 insertions(+), 4 deletions(-)
73a8870 fix(capability-map): address PR #74 review, round 1 (ASK-122)
 q-system/.q-system/scripts/capability-map-gen.py | 31 ++++++++++++++++++++++--
 1 file changed, 29 insertions(+), 2 deletions(-)

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "nl -ba q-system/.q-system/scripts/fleet-health-daily.py | sed -n '1000,1085p' && nl -ba q-system/.q-system/scripts/linear-sync.py | sed -n '960,1055p' && git show 73a8870 -- q-system/.q-system/scripts/capability-map-gen.py" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
  1000	              "hand-clearing the gate is not possible."
  1001	        ),
  1002	    }]
  1003	
  1004	
  1005	# ---------------------------------------------------------------------------
  1006	# The registry. `action` and the learning leg are REQUIRED.
  1007	# ---------------------------------------------------------------------------
  1008	
  1009	def detect_untracked_unwired(_ctx) -> list:
  1010	    """A repo with UNWIRED engines but no open audit issue tracking them.
  1011	
  1012	    The founder's ask, 2026-07-26: "I am also seeing projects where it says things
  1013	    are not wired - we need to track that and have a plan for action. nothing
  1014	    should be left hanging."
  1015	
  1016	    capability-map-gen.py already FINDS unwired engines. Before this, that finding
  1017	    lived in a JSON file nobody opens. The audit issues (ASK-119..146) tracked the
  1018	    ones known on 2026-07-26; this detector is what keeps it true as maps change,
  1019	    so a newly-unwired engine cannot go untracked just because the sweep already ran.
  1020	    """
  1021	    maps_dir = QROOT / "output" / "capability-maps"
  1022	    if not maps_dir.is_dir():
  1023	        return []
  1024	    try:
  1025	        import importlib.util
  1026	
  1027	        spec = importlib.util.spec_from_file_location("ls", HERE / "linear-sync.py")
  1028	        ls = importlib.util.module_from_spec(spec)
  1029	        spec.loader.exec_module(ls)
  1030	        ledger = ls.read_ledger()
  1031	    except Exception:  # noqa: BLE001
  1032	        return []
  1033	
  1034	    out = []
  1035	    for path in sorted(maps_dir.glob("*.json")):
  1036	        try:
  1037	            cmap = json.loads(path.read_text())
  1038	        except (OSError, json.JSONDecodeError):
  1039	            continue
  1040	        repo = cmap.get("repo") or path.stem
  1041	        unwired = [c for c in (cmap.get("capabilities") or [])
  1042	                   if c.get("track", True)
  1043	                   and str(c.get("status", "")).upper() == "UNWIRED"]
  1044	        if not unwired:
  1045	            continue
  1046	        audit_key = f"{slug(repo)}/unwired-engine-audit"
  1047	        if audit_key in ledger:
  1048	            continue  # already tracked by its audit issue
  1049	        out.append({
  1050	            "subject": f"{slug(repo)}-unwired-untracked",
  1051	            "title": f"{len(unwired)} unwired engine(s) in {repo} with no audit issue",
  1052	            "body": (
  1053	                f"`capability-map-gen.py` reports **{len(unwired)} unwired engine(s)** in "
  1054	                f"`{repo}` — no paired test and no reference on any wiring surface — and "
  1055	                f"there is no open audit issue (`{audit_key}`) tracking them.\n\n"
  1056	                "Unwired does not mean dead. It means nothing in the repo *says* the code "
  1057	                "is alive, which is the position every future reader starts from.\n\n"
  1058	                "## Action\n```bash\nkipi linear remote --repo " + repo + " --out /tmp/r.json\n"
  1059	                "kipi linear plan --map q-system/output/capability-maps/" + path.name +
  1060	                " \\\n  --remote /tmp/r.json --out /tmp/p.json --filter actionable --rollup\n"
  1061	                "kipi linear create --plan /tmp/p.json --apply\n```\n"
  1062	                "That files the repo's audit issue with the full engine list, which is what "
  1063	                "this detector is checking for."
  1064	            ),
  1065	        })
  1066	    return out
  1067	
  1068	
  1069	DETECTORS = [
  1070	    {
  1071	        "id": "unwired-untracked",
  1072	        "description": "a repo has unwired engines but no audit issue tracking them",
  1073	        "detect": detect_untracked_unwired,
  1074	        "action": "file_issue",
  1075	        "lesson": "a-defect-absence-gate-is-a-floor-not-a-finish-line",
  1076	    },
  1077	    {
  1078	        "id": "launchd-dark",
  1079	        "description": "plist on disk, not loaded, not in the paused ledger",
  1080	        "detect": detect_dark_jobs,
  1081	        "action": "file_issue",
  1082	        "lesson": "a-freshness-deadman-must-live-off-the-machine-it-watches",
  1083	    },
  1084	    {
  1085	        "id": "launchd-failing",
   960	            "teamId": team_id,
   961	        }
   962	        if project:
   963	            payload["projectId"] = project["id"]
   964	        try:
   965	            data = graphql(ISSUE_CREATE, {"input": payload})
   966	        except LinearAPIError as exc:
   967	            # Stop on the first failure. Continuing would keep spending against a
   968	            # broken condition (bad auth, rate limit) and the ledger's account of
   969	            # what exists would drift from Linear.
   970	            print(f"BLOCK after {made} create(s): {exc}", file=sys.stderr)
   971	            return EXIT_USAGE
   972	        node = (data.get("issueCreate") or {}).get("issue") or {}
   973	        if not node.get("id"):
   974	            print(f"BLOCK: issueCreate returned no issue for {issue['key']}", file=sys.stderr)
   975	            return EXIT_USAGE
   976	        append_ledger([{
   977	            "key": issue["key"], "kind": "issue",
   978	            "linear_id": node["id"], "identifier": node.get("identifier"),
   979	            "source": "api-create",
   980	        }])
   981	        made += 1
   982	        print(f"  {node.get('identifier')}  {issue['title'][:70]}")
   983	
   984	    print(f"{repo}: created {made} issue(s). Ledger updated per create.")
   985	    return EXIT_OK
   986	
   987	
   988	def cmd_plan(args) -> int:
   989	    with open(args.map, "r", encoding="utf-8") as fh:
   990	        cmap = json.load(fh)
   991	    repo = cmap.get("repo")
   992	    if not repo:
   993	        print("BLOCK: capability map has no 'repo' field", file=sys.stderr)
   994	        return EXIT_USAGE
   995	    caps = cmap.get("capabilities") or []
   996	
   997	    # Collision check BEFORE anything else. Two capabilities that slugify to the
   998	    # same key would silently become one issue, and the second would look "already
   999	    # created" forever. Refuse the map instead of guessing which one wins.
  1000	    seen = {}
  1001	    for cap in caps:
  1002	        k = make_key(repo, cap.get("name", ""))
  1003	        if k in seen:
  1004	            print(
  1005	                f"BLOCK: '{cap.get('name')}' and '{seen[k]}' both slugify to {k}.\n"
  1006	                f"       Rename one in the capability map. Two capabilities sharing a\n"
  1007	                f"       dedup key would collapse into one permanent issue.",
  1008	                file=sys.stderr,
  1009	            )
  1010	            return EXIT_COLLISION
  1011	        seen[k] = cap.get("name")
  1012	
  1013	    with open(args.remote, "r", encoding="utf-8") as fh:
  1014	        remote = json.load(fh)
  1015	    remote_keys, remote_project = parse_remote(remote)
  1016	
  1017	    ledger = read_ledger()
  1018	
  1019	    # Rehydrate: anything Linear knows about that the ledger does not. This is what
  1020	    # makes a lost ledger a no-op instead of 400 duplicates.
  1021	    rehydrate = [
  1022	        {"key": k, "kind": "issue", "linear_id": v["linear_id"],
  1023	         "identifier": v["identifier"], "source": "remote-rehydrate"}
  1024	        for k, v in remote_keys.items()
  1025	        if k not in ledger
  1026	    ]
  1027	    pkey = project_key(repo)
  1028	    if remote_project and pkey not in ledger:
  1029	        rehydrate.append({
  1030	            "key": pkey, "kind": "project",
  1031	            "linear_id": remote_project.get("id"),
  1032	            "identifier": remote_project.get("name"),
  1033	            "source": "remote-rehydrate",
  1034	        })
  1035	    if rehydrate:
  1036	        append_ledger(rehydrate)
  1037	        ledger = read_ledger()
  1038	
  1039	    known = set(ledger) | set(remote_keys)
  1040	
  1041	    create_issues = []
  1042	    rolled = []
  1043	    for i, cap in enumerate(caps):
  1044	        if not cap.get("track", True):
  1045	            continue
  1046	        if args.filter == "actionable" and _state_for(cap) == "Done":
  1047	            continue
  1048	        # UNWIRED is a survey finding, not a defect: "this script has no test and
  1049	        # no caller" is ONE decision for the repo (audit them, wire them, or delete
  1050	        # them), not N decisions. Filing it per script would make the founder groom
  1051	        # 25 items to make 1 call, and every one of those issues is permanent.
  1052	        # NEEDS_WORK and BROKEN stay individual: each is a distinct defect.
  1053	        if args.rollup and str(cap.get("status", "")).upper() == "UNWIRED":
  1054	            rolled.append(cap)
  1055	            continue
commit 73a887014dc90d80cbd2aa748ea31f26fa52524e
Author: Assaf Kipnis <1494043+assafkip@users.noreply.github.com>
Date:   Sun Aug 2 18:36:55 2026 -0700

    fix(capability-map): address PR #74 review, round 1 (ASK-122)
    
    Two of three findings fixed. Verdict was REQUEST CHANGES.
    
    MAJOR -- generated trees were excluded from the wiring surface but still
    walked for ENGINE COLLECTION. Their contents stayed collected while every
    file that could reference them went off-surface, so they reported UNWIRED
    with no way to ever clear it. That is the dark-engine shape from
    sp-3761d2d9, and d48ad6a would have created 12 more of it in
    kipi-investigations. An artifact is not an engine, so the coherent move is
    to stop reporting it rather than to report it as dead. Measured after:
    0 engines under q-system/output/.
    
    MINOR -- the evidence witness used plain sorted()[0], which puts
    dot-prefixed paths first, so the citation named a review scratch tree
    (.pr42rev/, .claude/worktrees/) instead of the real caller in 163 of 785
    witnesses across five repos. New _witness_rank prefers a non-hidden,
    shallower path. Measured after: 85/558, and the remainder are engines whose
    only reference genuinely lives in a hidden dir, which is the correct
    fallback rather than a miss.
    
    NOT FIXED, deliberately: the third finding (engine collection filters
    "test" in p.parts but not "tests", so conftest.py under tests/ is collected
    and can never clear) is PRE-EXISTING on origin/main line 358, not introduced
    here, and is already captured as sp-4fdb3d50. Widening that filter changes
    counts in every repo on a PR that is already in review.
    
    Verification: 9/9 wiring cases OK, capability-gate GREEN. Net effect of the
    round: Alice UNWIRED 23 -> 16 with local actionable still 3 (the three
    dispositioned survivors are unchanged), kipi-investigations UNWIRED 36 -> 28.

diff --git a/q-system/.q-system/scripts/capability-map-gen.py b/q-system/.q-system/scripts/capability-map-gen.py
index 8c3985c..e4c9203 100644
--- a/q-system/.q-system/scripts/capability-map-gen.py
+++ b/q-system/.q-system/scripts/capability-map-gen.py
@@ -356,6 +356,17 @@ SURFACE_NAMES = {"Makefile", "makefile", "kipi", "Dockerfile", "Justfile", "just
 GENERATED_SURFACE_PREFIXES = ("q-system/output/",)
 
 
+def _witness_rank(p: Path):
+    """Sort key that prefers a REAL caller over a scratch/hidden copy of one.
+
+    Any path component starting with "." is a review tree, a worktree or a tool
+    cache, never the wiring a reader should be sent to look at.
+    """
+    parts = p.parts
+    hidden = any(part.startswith(".") for part in parts)
+    return (hidden, len(parts), str(p))
+
+
 def is_generated_surface(p: Path, root: Path) -> bool:
     """True when p is a generated artifact, so its content must not count as wiring."""
     try:
@@ -477,6 +488,16 @@ def collect_engines(root: Path) -> list:
             continue
         if p.name.startswith(("test_", "test-")) or "test" in p.parts:
             continue
+        # A generated tree is not a wiring surface (see is_generated_surface), so
+        # it must not be an ENGINE source either. Excluding it from only one of
+        # the two makes its contents permanently dark: still collected, but with
+        # every file that could reference them now off-surface, so they report
+        # UNWIRED with no way to ever clear it (review finding, PR #74 major;
+        # would have compounded sp-3761d2d9). An artifact is not an engine, so
+        # the coherent move is to stop reporting it at all rather than to report
+        # it as dead. Measured: drops 12 phantom engines in kipi-investigations.
+        if is_generated_surface(p, root):
+            continue
         if DATED_SNAPSHOT_RE.search(p.stem):
             continue
         if len(read_text(p).splitlines()) < 40:
@@ -488,8 +509,14 @@ def collect_engines(root: Path) -> list:
     for p in engines:
         text = read_text(p)
         sources = refs.get(p, set())
-        test_sources = sorted(s for s in sources if _is_test_file(s))
-        wiring_sources = sorted(s for s in sources if not _is_test_file(s))
+        # WITNESS ORDER IS NOT ALPHABETICAL (review finding, PR #74 minor).
+        # Plain sorted()[0] puts dot-prefixed paths first, so the evidence named
+        # a review scratch tree (.pr42rev/, .claude/worktrees/) instead of the
+        # real caller in 163 of 785 witnesses measured across five repos. The
+        # verdict was right and the citation was useless, which is worse than it
+        # sounds: the citation is the only part a human re-checks.
+        test_sources = sorted((s for s in sources if _is_test_file(s)), key=_witness_rank)
+        wiring_sources = sorted((s for s in sources if not _is_test_file(s)), key=_witness_rank)
         has_test = any(p.stem in t for t in tests) or bool(test_sources)
         referenced = bool(wiring_sources)
         status = "LIVE" if (has_test or referenced) else "UNWIRED"

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse Completed
apply patch
patch: completed
/var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'python3 "$TMPDIR/pr74-comment-reference-repro.py" && python3 - <<'"'PY'
import json, os
from pathlib import Path
p = Path(os.environ['TMPDIR']) / 'pr74-capability-map.json'
data = json.loads(p.read_text())
for c in data['capabilities']:
    if c['layer'] == 'L5 Engines and scripts' and c['entry'].endswith('_sync_all.py'):
        print(c['entry'], c['status'], c['evidence'])
PY" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
orphan.py LIVE orphan.py: 47 lines; referenced on a wiring surface (notes.py).
plugins/kipi-design/skills/ui-ux-pro-max/data/_sync_all.py LIVE plugins/kipi-design/skills/ui-ux-pro-max/data/_sync_all.py: 414 lines; has a paired test (q-system/.q-system/scripts/test/test-capability-map-wiring.py), referenced on a wiring surface (q-system/.q-system/scripts/capability-map-gen.py).
plugins/kipi-design/skills/ui-ux-pro-max/src/data/_sync_all.py LIVE plugins/kipi-design/skills/ui-ux-pro-max/src/data/_sync_all.py: 414 lines; has a paired test (q-system/.q-system/scripts/test/test-capability-map-wiring.py), referenced on a wiring surface (q-system/.q-system/scripts/capability-map-gen.py).

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

codex
Fresh review is complete. Three failures survived execution: hidden review trees become tracked engines, comments count as callers, and one caller blesses every same-named engine.

I’m reading round 1 now, as required. I’ll use it only to settle overlap and citation claims.
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'gh pr view 74 --comments' in /Users/founder/.config/kipi/review-trees/pr-74
 exited 1 in 26ms:
error connecting to api.github.com
check your internet connection or https://githubstatus.com

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

codex
GitHub failed again, so the round 1 comment thread is unavailable in this environment. The round 1 response is preserved in commit `73a8870`, including the severities, claimed fixes, and deferred finding. I’m using that local record to enforce the round rule, and I’ll state the limitation in the final review.
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "rg -n \"PR #74|round 1|_witness_rank|generated trees|conftest\\.py\" --hidden --glob '"'!q-system/output/**'"' --glob '"'!.git/**'"' . | sed -n '1,260p' && git log --all --format='%H%n%B%n---' --grep='PR #74\\|capability-map' -20" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 58ms:
73a887014dc90d80cbd2aa748ea31f26fa52524e
fix(capability-map): address PR #74 review, round 1 (ASK-122)

Two of three findings fixed. Verdict was REQUEST CHANGES.

MAJOR -- generated trees were excluded from the wiring surface but still
walked for ENGINE COLLECTION. Their contents stayed collected while every
file that could reference them went off-surface, so they reported UNWIRED
with no way to ever clear it. That is the dark-engine shape from
sp-3761d2d9, and d48ad6a would have created 12 more of it in
kipi-investigations. An artifact is not an engine, so the coherent move is
to stop reporting it rather than to report it as dead. Measured after:
0 engines under q-system/output/.

MINOR -- the evidence witness used plain sorted()[0], which puts
dot-prefixed paths first, so the citation named a review scratch tree
(.pr42rev/, .claude/worktrees/) instead of the real caller in 163 of 785
witnesses across five repos. New _witness_rank prefers a non-hidden,
shallower path. Measured after: 85/558, and the remainder are engines whose
only reference genuinely lives in a hidden dir, which is the correct
fallback rather than a miss.

NOT FIXED, deliberately: the third finding (engine collection filters
"test" in p.parts but not "tests", so conftest.py under tests/ is collected
and can never clear) is PRE-EXISTING on origin/main line 358, not introduced
here, and is already captured as sp-4fdb3d50. Widening that filter changes
counts in every repo on a PR that is already in review.

Verification: 9/9 wiring cases OK, capability-gate GREEN. Net effect of the
round: Alice UNWIRED 23 -> 16 with local actionable still 3 (the three
dispositioned survivors are unchanged), kipi-investigations UNWIRED 36 -> 28.

---
d48ad6a5bc4db074351caad8d4f6351cab012434
fix(capability-map): generated artifacts are not wiring surfaces (ASK-122)

Caught pre-merge by diffing old-vs-new output across five real instances
rather than trusting the unit tests. The repo-wide widening swept in
q-system/output/, which holds codex transcripts, run logs, plans and RCAs.
Those name scripts constantly and run nothing.

Measured on kipi-investigations: _sync_all.py flipped UNWIRED -> LIVE on the
strength of q-system/output/codex-sfactivity-prd-out.txt line 738, a bare
find-style listing `./plugins/.../_sync_all.py`. That script is genuinely
dead; the log of a command that ENUMERATED it made it look alive.

The invocation filter cannot fix this. That line starts with "./" and so
matches MD_INVOCATION_RE, and a transcript echoing `python3 foo.py` matches
too. A log of a command that enumerated files is indistinguishable line by
line from a runbook that invokes one. The durable separator is provenance --
who wrote the file -- so generated trees leave the surface set instead.

q-system/output/ is the OS's generated-artifacts dir by convention and is
already in kipi-update.sh's INSTANCE_OWNED_SUBTREES, i.e. understood
fleet-wide as an instance's own output rather than source.

Test: 9th case, 5th negative, built as a find-style listing whose lines DO
satisfy MD_INVOCATION_RE so it pins the reason the regex is not enough.
Mutation-checked: with the new guard forced off (validated applied, parses,
differs) exactly that one case fails. 9/9 OK with it on.

---
d20f412a7b2b6a376cf0e2cbfc67083a8b05413c
fix(capability-map): see callers outside q-system/, count importing tests, skip dated snapshots (ASK-122)

ASK-122 asked to audit 11 unwired engines in Alice. The premise was wrong:
most flagged scripts had a visible caller on disk. capability-map-gen.py
could not see them. Three detector defects, each its own false-dead class:

1. The wiring-surface scan walked only .claude/, plugins/ and q-system/.
   Alice's code lives in q-investigate/ and scripts/, so regenerate.sh
   running `python3 "$G/fill_sheet.py"` was invisible. Now repo-wide via
   _iter_surface_files() / _build_reference_index().

2. has_test substring-matched test FILENAMES only, so tests/test_extract.py
   importing geo_clues scored as no-test. An importer is the strongest
   liveness evidence there is. Recurrence of the ASK-230
   provenance_vocabulary scar, which was the same filename-vs-import miss.

3. Dated snapshots (fill_sheet.2026-07-28.py) counted as engines. Their
   writer interpolates $TODAY (run-sweep.sh:218, restored :230/:260), so no
   static scan can ever match the literal name. It would report UNWIRED
   forever, leaving "delete the rollback artifact" as the only way to clear
   the gate. Now skipped via DATED_SNAPSHOT_RE.

Widening the scan makes false-LIVE the new failure mode, so the guards are
deliberate: prose .md mentions do not count (only MD_INVOCATION_RE lines),
self-reference does not count, and bare module names count only inside
import/loader syntax (MODULE_REF_RE).

Test: q-system/.q-system/scripts/test/test-capability-map-wiring.py, 8 cases,
4 of them negatives, registered in capability-manifest.json expected_tests.
Fixtures are built in a tempdir; nothing reads a real repo.

Verified by running the new test against the pre-fix generator from
origin/main: 5 of 8 fail. Against the fixed generator: 8/8 OK. A test that
cannot fail is not a test.

Effect on Alice: UNWIRED 45 -> 23, local actionable 22 -> 3. Runtime 1.8s.

---
7383d6cf0f833ca1258cae1e9bd19c48cb2b14fd
chore: update system infrastructure

- q-system/.q-system/capability-manifest.json
- q-system/.q-system/scripts/capability-map-gen.py
- q-system/.q-system/scripts/test/test-capability-map-wiring.py

[no-issue: auto-commit safety net, unattended Stop hook]

---
87215ad49db8fe6e0de7eb0355dc6f086105babc
docs(prd): deterministic reading -- read tiers, derived manifest, one provenance vocabulary (ASK-228)

PRD prd-deterministic-reading-2026-07-28, status idea. Three coupled changes
downstream of RCA rca-conclusions-before-evidence-2026-07-28, all traced to one
cause: an LLM was choosing what to read.

P1 closes the RCA's last open action item (owner was founder, now decided).
Founder directive 2026-07-28: "Deterministic always trumps when we read. we dont
trust the llm to read." Token-discipline vs completeness was never a real
conflict; it was an artifact of letting the model pick the read set. Three tiers
-- Enumerated / Derived / Exploratory -- and caps apply only to the last. Each
tier names its own deterministic blocker in the table; a tier without one would
be the paragraph this repo bans everywhere else.

P2: system_manifest.py reads a HAND-WRITTEN manifest, repeating a lesson
capability-map-gen.py already recorded for this repo ("accurate for one
afternoon... nothing detects the drift"). A manifest missing a member makes the
grounding guard certify coverage it does not have, which is worse than reporting
nothing. Proposed: glob members resolved at check time, file members validated to
exist, external members required to carry a fingerprint and fetched_at.

P3: handoff-provenance-lint.py invented a second provenance vocabulary alongside
the one memory-confidence.md already defines and enforces. The younger one moves.

Drafted by Claude, not the owner, and the PRD says so at the top. The prd-start
skill warns this shape passes review by agreeing with itself; two of three
problems were found by Claude and Claude would implement all three. Codex review
is the independent check. The Skeptic section argues against Part 1 shipping at
all, and the open questions are marked {{UNVERIFIED}} rather than guessed.

Two prompt-only-enforcement-guard defects found while writing this, both
captured: sp-8f05a182 (wrong line number on longer files -- reported line 10, a
frontmatter delimiter; real trigger was 78) and sp-dacb04c7 (false positive on a
line naming its blocker inline; every sub-line passes in isolation, only the
assembled block trips). The PRD carries a scoped skip marker naming both.

Linear: ASK-228. The local .linear-queue.jsonl still holds the queued stub --
clearing it needs an rm, which the destructive-op hook blocks by design.

Next: /prd-review for Codex adversarial review.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>

---
347bf6740bca6b2cb9be26fc792126a1e54dccdc
fix(fleet): a registered instance that receives no skeleton propagation declares it or fails the run (ASK-117) (#32)

reddit-build-radar sat in instance-registry.json's instances[] with 0 of its
28 capabilities originating from the skeleton, while every other instance
carried 268-281. kipi update printed one quiet line -- 'SKIP: standalone' --
and exited 0, so the fleet counted 24 governed instances when one of them had
no token-guard.py, no .claude/rules/, and no capability gate. Every fleet-wide
claim about gates holding had an exception nobody could see.

It is case 1 of the two the issue named: deliberate. Confirmed by
capability-map-gen (origin_counts = {local: 28}, no skeleton key) and by
kipi-update.sh already refusing to sync a null subtree_prefix. So the fix is to
put the decision on the record and make the undeclared case impossible to miss:

- instance-registry.json: skeleton_managed=false on reddit-build-radar, with
  the note stating what it therefore does not carry and that fleet governance
  counts must exclude it.
- kipi-update.sh: the standalone skip splits in two. Declared -> named as
  declared, counted as a skip, run stays green. Undeclared -> UNDECLARED
  NON-PROPAGATING inline AND in the summary, and it fails the run. A missing
  instance path keeps its own separate message, so a moved directory does not
  read as an ungoverned instance.

Only an explicit false counts as a declaration; a missing key is the
reddit-build-radar state and must not read like a deliberate opt-out.

Test: q-system/.q-system/scripts/test/test-kipi-update-unmanaged-instance.sh
(5 assertions, registered in capability-manifest.json). Property 3 runs against
the LIVE registry, so a future entry that receives nothing and says nothing
fails the suite, not just the updater.
---
9e59493583ba0977996c2e414749afb6957ffe52
fix(fleet): a registered instance that receives no skeleton propagation declares it or fails the run (ASK-117)

reddit-build-radar sat in instance-registry.json's instances[] with 0 of its
28 capabilities originating from the skeleton, while every other instance
carried 268-281. kipi update printed one quiet line -- 'SKIP: standalone' --
and exited 0, so the fleet counted 24 governed instances when one of them had
no token-guard.py, no .claude/rules/, and no capability gate. Every fleet-wide
claim about gates holding had an exception nobody could see.

It is case 1 of the two the issue named: deliberate. Confirmed by
capability-map-gen (origin_counts = {local: 28}, no skeleton key) and by
kipi-update.sh already refusing to sync a null subtree_prefix. So the fix is to
put the decision on the record and make the undeclared case impossible to miss:

- instance-registry.json: skeleton_managed=false on reddit-build-radar, with
  the note stating what it therefore does not carry and that fleet governance
  counts must exclude it.
- kipi-update.sh: the standalone skip splits in two. Declared -> named as
  declared, counted as a skip, run stays green. Undeclared -> UNDECLARED
  NON-PROPAGATING inline AND in the summary, and it fails the run. A missing
  instance path keeps its own separate message, so a moved directory does not
  read as an ungoverned instance.

Only an explicit false counts as a declaration; a missing key is the
reddit-build-radar state and must not read like a deliberate opt-out.

Test: q-system/.q-system/scripts/test/test-kipi-update-unmanaged-instance.sh
(5 assertions, registered in capability-manifest.json). Property 3 runs against
the LIVE registry, so a future entry that receives nothing and says nothing
fails the suite, not just the updater.

---
fbc9404c5fb5c2cf44da4e3a32eae5e9ff842340
chore: update project files

- .pr23rev/repro-a-work/a2
- .pr25rev/extract.sh
- .pr25rev/head/q-system/.q-system/scripts/linear-worker.sh
- .pr25rev/head/q-system/.q-system/scripts/pr-verdict-lib.sh
- .pr25rev/head/q-system/.q-system/scripts/test/test-severity-floor.sh
- .pr25rev/mut/q-system/.q-system/scripts/accept-rate.py
- .pr25rev/mut/q-system/.q-system/scripts/audhd-lint.py
- .pr25rev/mut/q-system/.q-system/scripts/autocapture_config.json
- .pr25rev/mut/q-system/.q-system/scripts/batch-uniformity-lint.py
- .pr25rev/mut/q-system/.q-system/scripts/canonical-digest.py
- .pr25rev/mut/q-system/.q-system/scripts/capability-gate.py
- .pr25rev/mut/q-system/.q-system/scripts/capability-map-gen.py
- .pr25rev/mut/q-system/.q-system/scripts/capability-overlap.py
- .pr25rev/mut/q-system/.q-system/scripts/changelog-write.py
- .pr25rev/mut/q-system/.q-system/scripts/code_claim_grounding_guard.py
- .pr25rev/mut/q-system/.q-system/scripts/collection-gate.py
- .pr25rev/mut/q-system/.q-system/scripts/com.kipi.fleet-health.plist
- .pr25rev/mut/q-system/.q-system/scripts/com.kipi.linear-dor.plist
- .pr25rev/mut/q-system/.q-system/scripts/com.kipi.openloops-heartbeat.plist
- .pr25rev/mut/q-system/.q-system/scripts/compliance-check.py
- ... and 295 more files

[no-issue: auto-commit safety net, unattended Stop hook]

---
40a322fc8f4367e55a833c89f46f28cb70e0c420
feat(health): detector for unwired engines with no audit issue (ASK-113)

Founder, 2026-07-26: "I am also seeing projects where it says things are not
wired - we need to track that and have a plan for action. nothing should be left
hanging."

capability-map-gen.py already FOUND unwired engines; the finding lived in a JSON
file nobody opens. The audit issues created earlier today (ASK-118..146) track
every repo that had them as of this morning. This detector is what keeps that
true as the maps change, so a newly-unwired engine cannot go untracked merely
because the one-time sweep already ran.

Reports 0 right now, which is the correct answer and the point: all 15 repos with
unwired engines carry an open audit issue. Coverage is no longer a claim, it is a
daily check.

Also filed, from the reddit-radar investigation:
- ASK-149: reddit-build-radar stops producing tomorrow. It is scheduled twice; the
  script DETECTS the cron trigger and no-ops it (23 real sends, 3 no-ops in
  daily.log), and the LaunchAgent was paused at 11:40 -- AFTER today's 08:00 run.
  So today's report went out and tomorrow's will not, with nothing to say so.
- ASK-150: cron cannot run `claude -p`. The retired probe recorded
  keychain_read_rc=44 and is_error:true -- cron has no keychain access, so
  subscription auth fails. launchd does. Filed as a standing design constraint
  because the autonomous worker depends on headless claude runs, and building any
  part of it on cron would fail at runtime with an opaque auth error.

Not done, blocked: removing the two dead crontab lines. `crontab <file>` hangs
from an agent shell (macOS wants an interactive permission grant); two attempts,
both timed out at 5 min. Stopped rather than retry a third time. Handed to the
founder, tracked in ASK-149.

Verification: test-fleet-health-daily.py 12 checks, 5 detectors; capability-gate
GREEN ran=63.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>

---
a6ba923d824fa7af1aae4e0eb200aa6ef26fa220
fix(skeleton): drop instance identity from two scar comments (ASK-113)

Unblocks two of the three validate-separation gates that surfaced once the
capability gate stopped failing first: "No <BRAND> references in scripts" and
"Full skeleton sweep: zero <BRAND>/hardcoded refs", both 2 files.

All four hits were in COMMENTS, not code -- scar notes naming a real instance
and three home-directory paths. The skeleton propagates to every instance, so
instance identity must not ride along; the lesson is what has value, the
identity is what leaks. Rewrote each to keep the scar and drop the name:

  capability-map-gen.py:411  <BRAND>_strategy -> "one registered instance"
  test-kipi-update-safety.sh:252  a real /Users path -> "one registered
    instance's path is the PARENT of ten others"
  test-kipi-update-safety.sh:312  an old-username home path -> "a home
    directory under an old, long-dead username"
  test-kipi-update-safety.sh:466  two instance names + the dissolved cluster ->
    "one registered instance is the parent of five others" / "a dissolved
    former cluster"

Verified: validate-separation.py Phase 1 goes 3 FAIL -> 1 FAIL (PASS 66 -> 68),
and test-kipi-update-safety.sh still passes (comment-only edits).

The one remaining failure is pre-existing and owned elsewhere (ASK-58/ASK-59):
semantic containment, 11789 findings = 11743 `unclassified_populated_record`
plus 46 in blocking classes (source_identity 25, pricing 11, client_identity 4,
sourced_interaction 3, case_proof_gap 3).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>

---
7ba0cfaa34976073c067e081179dc4c6995d0e4a
feat(linear): deterministic capability-map generator for every fleet repo (ASK-113)

Structural recon per repo instead of 24 hand-written maps that drift the moment a
command is added. Every evidence string is a fact read off disk, and status is
derived from wiring rather than from claims in prose.

Three recon bugs found and fixed by running it, not by reading it:

  - a virtualenv under 4_points_consulting/q-investigate/ admitted 5450
    site-packages files as capabilities. Directory-NAME filtering was not enough;
    now pyvenv.cfg and path markers are checked too.
  - nested instance repos were swallowed by their parent. ASK_AI_consultant is
    ~/projects/consulting, which contains 12 other instances; gtm-partner
    contains 5. A nested git repo now gets its own map.
  - engines were reported UNWIRED because the wiring-surface list was narrower
    than capability-gate.py's, so python-calls-python was invisible.

Fleet total went 12430 -> 7996 capabilities and 895 -> 347 actionable as those
were fixed. The inflated numbers were the bug, not the fleet.

Origin tagging is the fleet-homogeneity slice: a capability that also exists in
the skeleton is a kipi update propagation, so it is recorded in the instance map
but tracked ONCE, in kipi-system. Filing skeleton rules 24 times would have been
the exact duplication this work exists to find.

---

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc "python3 q-system/.q-system/scripts/capability-gate.py --help | sed -n '1,160p' && sed -n '1,120p' q-system/.q-system/scripts/capability-gate.py && rg -n \"capability-gate.py\" lefthook.yml validate-separation.py build-template-repo.sh q-system/.q-system/scripts/test --glob '*.sh' --glob '*.py' | sed -n '1,200p'" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
usage: capability-gate.py [-h] [--repo-root REPO_ROOT] [--check-only]

Capability gate: diff DECLARED capabilities against ACTUAL repo state, both

options:
  -h, --help            show this help message and exit
  --repo-root REPO_ROOT
                        repo root (default: cwd)
  --check-only          structure/diff/wiring/data checks only; skip test
                        execution
#!/usr/bin/env python3
"""Capability gate: diff DECLARED capabilities against ACTUAL repo state, both
directions, then run every in-scope test artifact.

Why this exists (scar, 2026-07-23, prd-silent-absence-capability-gate): 38 test
artifacts existed under q-system/.q-system/scripts while CI ran 4 by hardcoded
allowlist — 89.5% never executed anywhere; an 802-line stat-verify engine
sat unwired for months; a skeleton-only test shipped to 24 instances and
crashed in 23. Nothing declared what was supposed to exist, so nothing could
detect what was missing. Silent absences are invisible to exit codes; this
gate makes absence loud in both directions.

Manifest: q-system/.q-system/capability-manifest.json (canonical, synced).
Overlay:  <repo-root>/capability-manifest.local.json (instance-local, ADD-only).

Exit codes: 0 green, 1 red, 3 refused (worktree copy).
"""

import argparse
import datetime
import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

SCHEMA_VERSION = 1
ALLOWED_TOP_KEYS = {
    "schema_version", "expected_tests", "required_data",
    "skeleton_only", "declared_inert", "uncovered_known",
}
OVERLAY_ALLOWED_KEYS = {"expected_tests", "required_data"}
TEST_PATTERNS = ("test_*.py", "test-*.py", "test-*.sh")
# Both contracted roots: scripts/ recursive, plus top-level .q-system test
# files (finding-9/adversarial: token-guard-adjacent tests may land there).
SCAN_ROOTS = ("q-system/.q-system/scripts", "q-system/.q-system")
DEFAULT_TIMEOUT_S = 60
TIMEOUT_MIN_S, TIMEOUT_MAX_S = 5, 600

# Wiring surfaces for the inert-engine check (F2 class). Textual-reference
# heuristic, declared as such in the PRD: a false "inert" is resolved by a
# declared_inert entry or a real call site — both loud, neither silent.
WIRING_SURFACES = (
    ".claude/settings.json",
    "settings-template.json",
    "validate-separation.py",
    # lefthook is this repo's pre-commit enforcement layer (gitleaks,
    # blocked-paths, instruction-budget, linear-issue-ref). A script wired ONLY
    # there was reported inert, which is backwards: a commit-blocking hook is
    # the strongest wiring a script can have. Added 2026-07-26 when
    # receipts-ledger-check.py, wired in lefthook and nowhere else, was flagged.
    "lefthook.yml",
)
WIRING_SURFACE_GLOBS = (
    "plugins/*/hooks/hooks.json",
    "plugins/*/hooks.json",
    ".github/workflows/*.yml",
    "kipi*",
    "*.sh",
    "q-system/.q-system/scripts/*.sh",
    "q-system/hooks/*",
    ".claude/**/*.md",
    "plugins/**/*.md",
    "q-system/.q-system/**/*.md",
    "q-system/.q-system/**/*.py",
    "q-system/.q-system/*.py",
)


def refuse_if_worktree(root):
    """A .claude/worktrees copy is a parallel checkout; gating it double-reports
    and its registry state is not authoritative. Refuse, do not guess."""
    if "/.claude/worktrees/" in str(root.resolve()) + "/":
        print("REFUSED: run the capability gate from the primary checkout, "
              "not a .claude/worktrees copy.", file=sys.stderr)
        sys.exit(3)


def detect_mode(root, errors):
    """skeleton iff instance-registry.json exists at repo root. A present but
    unparseable registry is RED, never silently instance mode (finding-13)."""
    reg = root / "instance-registry.json"
    if not reg.is_file():
        return "instance"
    try:
        json.loads(reg.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        errors.append(f"instance-registry.json present but unreadable: {exc}")
    return "skeleton"


def load_manifest(root, errors):
    path = root / "q-system/.q-system/capability-manifest.json"
    if not path.is_file():
        errors.append(f"manifest missing: {path.relative_to(root)}")
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        errors.append(f"manifest malformed JSON: {exc}")
        return None
    validate_manifest(data, errors)
    return data


def unsafe_path(p):
    """Manifest/overlay paths are repo-root-relative only. An absolute path or
    a .. escape would let a declaration point OUTSIDE the repo (adversarial
    finding: overlay entry naming /etc/... must be RED, not silently checked)."""
    if not isinstance(p, str) or not p:
        return True
    if p.startswith(("/", "~")) or "\\" in p:
        return True
    return ".." in p.split("/")


def validate_test_entry(entry, seen, errors):
    """One validator for canonical AND overlay entries (finding: overlay
validate-separation.py:759:    # One implementation, two callers: CI invokes capability-gate.py directly
validate-separation.py:773:        gate_script = os.path.join(SCRIPT_DIR, "q-system", ".q-system", "scripts", "capability-gate.py")
q-system/.q-system/scripts/test/test-kipi-update-hook-contract.sh:64:    > "$skeleton/q-system/.q-system/scripts/capability-gate.py"
q-system/.q-system/scripts/test/test-capability-gate-reap.sh:21:GATE="$ROOT/q-system/.q-system/scripts/capability-gate.py"
q-system/.q-system/scripts/test/test-capability-gate-reap.sh:27:[ -f "$GATE" ] || fail "capability-gate.py does not exist at $GATE"
q-system/.q-system/scripts/test/test-capability-gate-reap.sh:124:  || fail "capability-gate.py does not parse"
q-system/.q-system/scripts/test/test-instance-ownership-contract.py:388:        candidate = "q-system/.q-system/scripts/capability-gate.py"
q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh:142:  > "$SKELETON/q-system/.q-system/scripts/capability-gate.py"
q-system/.q-system/scripts/test/test-kipi-update-dry-final-state.sh:198:    > q-system/.q-system/scripts/capability-gate.py
q-system/.q-system/scripts/test/test-linear-dor-failure-reporting.py:15:plus this test file, registered in capability-manifest.json so capability-gate.py

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'python3 q-system/.q-system/scripts/capability-gate.py --repo-root . --check-only' in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
capability-gate mode=skeleton
  declared: 107 tests (0 quarantined), 17 skeleton-only, 16 declared-inert
  DECLARED-INERT (sp-cc33bdb0): q-system/.q-system/scripts/accept-rate.py — sycophancy pi metric script with no caller on any wiring surface
  DECLARED-INERT (sp-cc33bdb0): q-system/.q-system/scripts/granola-voice-synthesize.py — ad-hoc founder tool, no wiring surface references; wire-or-delete is a founder decision
  DECLARED-INERT (sp-cc33bdb0): q-system/.q-system/scripts/instance-diet.py — one-off maintenance tool, no wiring surface references
  DECLARED-INERT (sp-0f773063): q-system/.q-system/scripts/instance-fact-inventory.py — built for prd-skeleton-data-containment and never wired; its only references are that PRD's specs and its own test
  DECLARED-INERT (sp-fb332466): q-system/.q-system/scripts/linear-collapse-jobmigration.py — one-shot family collapse: it absorbed the 32-member job-migration family into ASK-151 on 2026-07-28 and has no second family to run on. ASK-226 generalises it; retire this one when that lands
  DECLARED-INERT (sp-cc33bdb0): q-system/.q-system/scripts/pdf-extract.py — ad-hoc research tool (AI Index comparison), invoked manually
  DECLARED-INERT (sp-f0f0fc7e): q-system/.q-system/scripts/review-tier.py — deterministic review-tier classifier: built, tested (55 checks incl. a mutation layer), and DELIBERATELY unwired. Not a hook, so .claude/settings.json is the wrong surface -- its contract is `review-tier.py ... || run_independent_review`, making the call site pr-review-agent.sh or linear-worker.sh. Picking between them changes behaviour (one saves a Codex call, the other a whole worker run) and is its own design decision. Held back on purpose: this classifier decides WHO GETS REVIEWED, so it must not arm itself in the same PR that has not yet been reviewed
  DECLARED-INERT (sp-72b60bff): q-system/.q-system/scripts/stat-registry-extract.py — sibling extractor of the stat-verify engine, same founder decision
  DECLARED-INERT (sp-72b60bff): q-system/.q-system/scripts/stat-verify.py — 802-line stat verification engine; zero hook wiring and its stat-registry.json data file exists in exactly one instance — wiring it is a founder product decision
  DECLARED-INERT (sp-0f773063): q-system/.q-system/scripts/update-preservation-manifest.py — built for prd-fail-closed-fleet-updater and never wired; the updater carries its own inline preservation path
  DECLARED-INERT (sp-0f773063): q-system/.q-system/scripts/verify-containment-export.py — built for prd-skeleton-data-containment's export/quarantine flow and never wired
capability-gate: GREEN

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'python3 q-system/.q-system/scripts/capability-map-gen.py --root . --repo pr-74-review --out "$TMPDIR/pr74-real-map.json" --skeleton . >/dev/null && python3 - <<'"'PY'
import json, os
from pathlib import Path
root = Path('.')
manifest = json.loads((root/'q-system/.q-system/capability-manifest.json').read_text())
known_inert = {x['path'] for x in manifest['declared_inert']}
cmap = json.loads((Path(os.environ['TMPDIR'])/'pr74-real-map.json').read_text())
for c in cmap['capabilities']:
    if c['entry'] in known_inert and c['status'] == 'LIVE':
        print(c['entry'], '=>', c['status'], '=>', c['evidence'].split('; ',1)[1])
PY" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 1463ms:
q-system/.q-system/scripts/session_recall.py => LIVE => has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
q-system/.q-system/scripts/granola-voice-synthesize.py => LIVE => referenced on a wiring surface (automation/voice_refresh.py).
q-system/.q-system/scripts/linear-collapse-jobmigration.py => LIVE => referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
q-system/.q-system/scripts/memory_reflect.py => LIVE => has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
q-system/.q-system/scripts/stat-verify.py => LIVE => has a paired test (q-system/.q-system/scripts/tests/test-stat-verify.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
q-system/.q-system/scripts/memory_outcomes.py => LIVE => has a paired test (q-system/.q-system/scripts/test_autocapture_e2e.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
q-system/.q-system/scripts/instance-fact-inventory.py => LIVE => has a paired test (q-system/.q-system/tests/separation/test_instance_fact_inventory.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
q-system/.q-system/scripts/accept-rate.py => LIVE => referenced on a wiring surface (.prd-os/issues/accept-rate-metric-script.md).
q-system/.q-system/scripts/review-tier.py => LIVE => has a paired test (q-system/.q-system/scripts/test_review_tier.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
q-system/.q-system/scripts/instance-diet.py => LIVE => referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
q-system/.q-system/scripts/linear-triage.py => LIVE => has a paired test (q-system/.q-system/scripts/test/test-linear-triage.sh), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
q-system/.q-system/scripts/verify-containment-export.py => LIVE => has a paired test (q-system/.q-system/tests/separation/test_containment_export.py), referenced on a wiring surface (.prd-os/issues/sdc-owner-export.md).
q-system/.q-system/scripts/stat-registry-extract.py => LIVE => referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
q-system/.q-system/scripts/pdf-extract.py => LIVE => referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
q-system/.q-system/scripts/update-preservation-manifest.py => LIVE => has a paired test (q-system/.q-system/scripts/test/test-update-preservation-manifest.py), referenced on a wiring surface (q-system/.q-system/capability-manifest.json).

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'for f in plugins/kipi-design/skills/design/scripts/cip/core.py plugins/kipi-design/skills/design/scripts/logo/core.py plugins/kipi-design/skills/ui-ux-pro-max/scripts/core.py plugins/kipi-design/skills/ui-ux-pro-max/src/scripts/core.py; do echo "$f"; rg -n "(''^|[/'"'\\\" ])core\\.py|from .*core|import core\" \""'$(dirname "$f")" --glob '"'*.py' --glob '*.sh' --glob '*.md' | sed -n '1,30p'; done
rg -n \"design/scripts/logo/core\\.py|design/scripts/cip/core\\.py|ui-ux-pro-max/src/scripts/core\\.py|ui-ux-pro-max/scripts/core\\.py\" --hidden --glob '"'!q-system/output/**'"' --glob '"'!.git/**'"' . | sed -n '1,160p'" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 0ms:
plugins/kipi-design/skills/design/scripts/cip/core.py
plugins/kipi-design/skills/design/scripts/cip/search.py:14:from core import search, search_all, get_cip_brief, CSV_CONFIG
plugins/kipi-design/skills/design/scripts/cip/render-html.py:20:from core import search, get_cip_brief
plugins/kipi-design/skills/design/scripts/cip/generate.py:26:from core import search, get_cip_brief
plugins/kipi-design/skills/design/scripts/logo/core.py
plugins/kipi-design/skills/design/scripts/logo/search.py:12:from core import CSV_CONFIG, MAX_RESULTS, search, search_all
plugins/kipi-design/skills/ui-ux-pro-max/scripts/core.py
plugins/kipi-design/skills/ui-ux-pro-max/scripts/search.py:20:from core import CSV_CONFIG, AVAILABLE_STACKS, MAX_RESULTS, search, search_stack
plugins/kipi-design/skills/ui-ux-pro-max/scripts/design_system.py:21:from core import search, DATA_DIR
plugins/kipi-design/skills/ui-ux-pro-max/scripts/design_system.py:921:    from core import search
plugins/kipi-design/skills/ui-ux-pro-max/src/scripts/core.py
plugins/kipi-design/skills/ui-ux-pro-max/src/scripts/search.py:20:from core import CSV_CONFIG, AVAILABLE_STACKS, MAX_RESULTS, search, search_stack
plugins/kipi-design/skills/ui-ux-pro-max/src/scripts/design_system.py:21:from core import search, DATA_DIR
plugins/kipi-design/skills/ui-ux-pro-max/src/scripts/design_system.py:921:    from core import search

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

codex
Round 1 overlap is now settled from commit `73a8870`.

- The generated `q-system/output/` fix is live. I’m not raising it again.
- The deferred `tests/` collection bug is unchanged and already tracked. I’m dropping it.
- The hidden-path finding has a new reproduced consequence. Round 1 fixed citation ordering only. The current code still emits hidden review artifacts as tracked engines, including four false `UNWIRED` entries. That falsifies the claim that hidden paths are “never wiring.”
hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'git diff --check origin/main...HEAD && git status --porcelain=v1 && python3 q-system/.q-system/scripts/test/test-capability-map-wiring.py && python3 q-system/.q-system/scripts/capability-gate.py --repo-root . --check-only | tail -2' in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 542ms:
test_dated_snapshot_is_not_an_engine (__main__.TestWiringDetection.test_dated_snapshot_is_not_an_engine) ... ok
test_evidence_names_the_referencing_file (__main__.TestWiringDetection.test_evidence_names_the_referencing_file) ... ok
test_fenced_invocation_in_markdown_counts (__main__.TestWiringDetection.test_fenced_invocation_in_markdown_counts) ... ok
test_generated_output_is_not_wiring (__main__.TestWiringDetection.test_generated_output_is_not_wiring) ... ok
test_importing_test_counts_even_with_mismatched_filename (__main__.TestWiringDetection.test_importing_test_counts_even_with_mismatched_filename) ... ok
test_orphan_stays_unwired (__main__.TestWiringDetection.test_orphan_stays_unwired) ... ok
test_prose_mention_is_not_wiring (__main__.TestWiringDetection.test_prose_mention_is_not_wiring) ... ok
test_self_reference_is_not_wiring (__main__.TestWiringDetection.test_self_reference_is_not_wiring) ... ok
test_shell_caller_outside_qsystem_counts (__main__.TestWiringDetection.test_shell_caller_outside_qsystem_counts) ... ok

----------------------------------------------------------------------
Ran 9 tests in 0.037s

OK
  DECLARED-INERT (sp-0f773063): q-system/.q-system/scripts/verify-containment-export.py — built for prd-skeleton-data-containment's export/quarantine flow and never wired
capability-gate: GREEN

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'python3 q-system/.q-system/scripts/capability-map-gen.py --root . --repo pr-74-review --out "$TMPDIR/pr74-hidden.json" --skeleton . >/dev/null && python3 -c '"'import json,os,pathlib; d=json.load(open(pathlib.Path(os.environ[\"TMPDIR\"])/\"pr74-hidden.json\")); [print(c[\"entry\"], c[\"status\"], \"track=\"+str(c[\"track\"])) for c in d[\"capabilities\"] if c[\"status\"]==\"UNWIRED\" and c[\"track\"] and any(x.startswith(\".\") for x in pathlib.Path(c[\"entry\"]).parts)]'" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 1571ms:
.pr24rev/mutate.py UNWIRED track=True
.review-tmp-pr11/repro_B_update_path_crashes_run.py UNWIRED track=True
.review-tmp-pr11/repro_C_ledger_only_key_all_clear.py UNWIRED track=True
.review-tmp-pr11/repro_A_linear_unreachable_silent.py UNWIRED track=True
.review-tmp-pr11/repro_D_matcher_corpus.py UNWIRED track=True
q-system/.q-system/data/monthly-learnings.py UNWIRED track=True

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'python3 q-system/.q-system/scripts/capability-map-gen.py --root . --repo pr-74-review --out "$TMPDIR/pr74-hidden.json" --skeleton . >/dev/null && python3 -c '"'import json,os,pathlib; d=json.load(open(pathlib.Path(os.environ[\"TMPDIR\"])/\"pr74-hidden.json\")); [print(c[\"entry\"], c[\"status\"], \"track=\"+str(c[\"track\"])) for c in d[\"capabilities\"] if c[\"status\"]==\"UNWIRED\" and c[\"track\"] and c[\"entry\"].startswith((\".pr\", \".review\"))]'" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 1389ms:
.pr24rev/mutate.py UNWIRED track=True
.review-tmp-pr11/repro_B_update_path_crashes_run.py UNWIRED track=True
.review-tmp-pr11/repro_C_ledger_only_key_all_clear.py UNWIRED track=True
.review-tmp-pr11/repro_A_linear_unreachable_silent.py UNWIRED track=True
.review-tmp-pr11/repro_D_matcher_corpus.py UNWIRED track=True

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: PreToolUse
hook: PreToolUse
hook: PreToolUse Completed
hook: PreToolUse Completed
exec
/bin/zsh -lc 'python3 q-system/.q-system/scripts/capability-map-gen.py --root . --repo pr-74-review --out "$TMPDIR/pr74-comments.json" --skeleton . >/dev/null && python3 -c '"'import json,os,pathlib; d=json.load(open(pathlib.Path(os.environ[\"TMPDIR\"])/\"pr74-comments.json\")); [print(c[\"entry\"], c[\"status\"], c[\"evidence\"].split(\"; \",1)[1]) for c in d[\"capabilities\"] if c[\"entry\"]==\"q-system/.q-system/scripts/instance-diet.py\"]' && python3 q-system/.q-system/scripts/capability-gate.py --repo-root . --check-only | grep 'instance-diet.py'" in /Users/founder/.config/kipi/review-trees/pr-74
 succeeded in 1769ms:
q-system/.q-system/scripts/instance-diet.py LIVE referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
  DECLARED-INERT (sp-cc33bdb0): q-system/.q-system/scripts/instance-diet.py — one-off maintenance tool, no wiring surface references

hook: PostToolUse
hook: PostToolUse
hook: PostToolUse Completed
hook: PostToolUse Completed
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

codex
Round 1 comparison used commit `73a8870` because GitHub was unreachable after two `gh pr view` attempts.

- The generated-output fix passed. Dropped.
- The existing `tests/` bug is already tracked. Dropped.
- Round 1’s hidden-path citation fix only changes sorting. The executed repro below falsifies its “never wiring” claim and exposes a new consequence: tracked false engines.

## Findings

### MAJOR: Hidden review artifacts are collected as real, trackable engines, producing false unattended audit findings.

File: `q-system/.q-system/scripts/capability-map-gen.py:486`

Reproducer:

```bash
python3 q-system/.q-system/scripts/capability-map-gen.py \
  --root . \
  --repo pr-74-review \
  --out "$TMPDIR/pr74-hidden.json" \
  --skeleton . >/dev/null &&
python3 -c 'import json,os,pathlib; d=json.load(open(pathlib.Path(os.environ["TMPDIR"])/"pr74-hidden.json")); [print(c["entry"], c["status"], "track="+str(c["track"])) for c in d["capabilities"] if c["status"]=="UNWIRED" and c["track"] and c["entry"].startswith((".pr", ".review"))]'
```

Real output:

```text
.pr24rev/mutate.py UNWIRED track=True
.review-tmp-pr11/repro_B_update_path_crashes_run.py UNWIRED track=True
.review-tmp-pr11/repro_C_ledger_only_key_all_clear.py UNWIRED track=True
.review-tmp-pr11/repro_A_linear_unreachable_silent.py UNWIRED track=True
.review-tmp-pr11/repro_D_matcher_corpus.py UNWIRED track=True
```

This cries wolf on every map run and feeds the permanent Linear audit path. A human must investigate and close findings for review fixtures, not product engines.

### MAJOR: A filename inside a comment or declaration counts as an executable caller, so known inert engines are reported LIVE.

File: `q-system/.q-system/scripts/capability-map-gen.py:464`

Reproducer:

```bash
python3 q-system/.q-system/scripts/capability-map-gen.py \
  --root . \
  --repo pr-74-review \
  --out "$TMPDIR/pr74-comments.json" \
  --skeleton . >/dev/null &&
python3 -c 'import json,os,pathlib; d=json.load(open(pathlib.Path(os.environ["TMPDIR"])/"pr74-comments.json")); [print(c["entry"], c["status"], c["evidence"].split("; ",1)[1]) for c in d["capabilities"] if c["entry"]=="q-system/.q-system/scripts/instance-diet.py"]'
```

Real output:

```text
q-system/.q-system/scripts/instance-diet.py LIVE referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
```

The manifest explicitly declares this script inert. Naming an engine in metadata is not wiring. The detector silently suppresses the finding it exists to produce.

### MAJOR: One caller marks every engine sharing the same basename LIVE, including engines at unrelated paths.

File: `q-system/.q-system/scripts/capability-map-gen.py:465`

Reproducer:

```bash
python3 "$TMPDIR/pr74-duplicate-basename-repro.py"
```

The fixture creates `live/worker.py`, `dead/worker.py`, and a caller for only `live/worker.py`.

Real output:

```text
dead/worker.py LIVE dead/worker.py: 47 lines; referenced on a wiring surface (run.sh).
live/worker.py LIVE live/worker.py: 47 lines; referenced on a wiring surface (run.sh).
```

This is a real repo shape. The checkout contains repeated names such as `core.py`, `search.py`, and `_sync_all.py`. A human must manually audit every duplicate because the generated LIVE status cannot be trusted.

## What is sound

The code survived these attacks:

- Shell callers outside `q-system/` are detected.
- Importing tests with unrelated filenames are detected.
- Markdown prose-only mentions remain UNWIRED.
- Self-references remain UNWIRED.
- `q-system/output/` artifacts are excluded as surfaces and engines.
- Dated snapshots are omitted.
- The nine new wiring tests pass.
- `capability-gate.py --check-only` is green.
- `git diff --check` passes and the worktree remains clean.

## Verdict

**VERDICT: REQUEST CHANGES**

Fix hidden and review-artifact exclusion first. It currently creates false tracked findings that flow into the permanent Linear audit path.

FINDINGS:
major|Hidden review artifacts are collected as real, trackable engines, producing false unattended audit findings.|q-system/.q-system/scripts/capability-map-gen.py:486
major|A filename inside a comment or declaration counts as an executable caller, so known inert engines are reported LIVE.|q-system/.q-system/scripts/capability-map-gen.py:464
major|One caller marks every engine sharing the same basename LIVE, including engines at unrelated paths.|q-system/.q-system/scripts/capability-map-gen.py:465
END FINDINGS
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..f91219271fd62e16e0561752207c38a088be592e
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-comment-reference-repro.py
@@ -0,0 +1,21 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "orphan.py").write_text(body)
+    (root / "notes.py").write_text("# orphan.py is dead and must not count as wired\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])
diff --git a//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
new file mode 100644
index 0000000000000000000000000000000000000000..26be198225a5dbacbdc2ecdfab15ec060ba59809
--- /dev/null
+++ b//var/folders/th/ty0kb7r56dvfrkgkrcbx9fv00000gn/T/pr74-duplicate-basename-repro.py
@@ -0,0 +1,24 @@
+#!/usr/bin/env python3
+import importlib.util
+import os
+import tempfile
+from pathlib import Path
+
+GEN = Path("/Users/founder/.config/kipi/review-trees/pr-74/q-system/.q-system/scripts/capability-map-gen.py")
+spec = importlib.util.spec_from_file_location("capability_map_gen", GEN)
+mod = importlib.util.module_from_spec(spec)
+spec.loader.exec_module(mod)
+mod._NESTED_REPOS = set()
+
+body = '#!/usr/bin/env python3\n"""fixture"""\n' + "\n".join(
+    f"# line {i}" for i in range(45)
+)
+with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as td:
+    root = Path(td)
+    (root / "live").mkdir()
+    (root / "dead").mkdir()
+    (root / "live" / "worker.py").write_text(body)
+    (root / "dead" / "worker.py").write_text(body)
+    (root / "run.sh").write_text("python3 live/worker.py\n")
+    for cap in mod.collect_engines(root):
+        print(cap["entry"], cap["status"], cap["evidence"])

hook: Stop
hook: Stop
hook: Stop Completed
hook: Stop Completed
tokens used
192,753
Round 1 comparison used commit `73a8870` because GitHub was unreachable after two `gh pr view` attempts.

- The generated-output fix passed. Dropped.
- The existing `tests/` bug is already tracked. Dropped.
- Round 1’s hidden-path citation fix only changes sorting. The executed repro below falsifies its “never wiring” claim and exposes a new consequence: tracked false engines.

## Findings

### MAJOR: Hidden review artifacts are collected as real, trackable engines, producing false unattended audit findings.

File: `q-system/.q-system/scripts/capability-map-gen.py:486`

Reproducer:

```bash
python3 q-system/.q-system/scripts/capability-map-gen.py \
  --root . \
  --repo pr-74-review \
  --out "$TMPDIR/pr74-hidden.json" \
  --skeleton . >/dev/null &&
python3 -c 'import json,os,pathlib; d=json.load(open(pathlib.Path(os.environ["TMPDIR"])/"pr74-hidden.json")); [print(c["entry"], c["status"], "track="+str(c["track"])) for c in d["capabilities"] if c["status"]=="UNWIRED" and c["track"] and c["entry"].startswith((".pr", ".review"))]'
```

Real output:

```text
.pr24rev/mutate.py UNWIRED track=True
.review-tmp-pr11/repro_B_update_path_crashes_run.py UNWIRED track=True
.review-tmp-pr11/repro_C_ledger_only_key_all_clear.py UNWIRED track=True
.review-tmp-pr11/repro_A_linear_unreachable_silent.py UNWIRED track=True
.review-tmp-pr11/repro_D_matcher_corpus.py UNWIRED track=True
```

This cries wolf on every map run and feeds the permanent Linear audit path. A human must investigate and close findings for review fixtures, not product engines.

### MAJOR: A filename inside a comment or declaration counts as an executable caller, so known inert engines are reported LIVE.

File: `q-system/.q-system/scripts/capability-map-gen.py:464`

Reproducer:

```bash
python3 q-system/.q-system/scripts/capability-map-gen.py \
  --root . \
  --repo pr-74-review \
  --out "$TMPDIR/pr74-comments.json" \
  --skeleton . >/dev/null &&
python3 -c 'import json,os,pathlib; d=json.load(open(pathlib.Path(os.environ["TMPDIR"])/"pr74-comments.json")); [print(c["entry"], c["status"], c["evidence"].split("; ",1)[1]) for c in d["capabilities"] if c["entry"]=="q-system/.q-system/scripts/instance-diet.py"]'
```

Real output:

```text
q-system/.q-system/scripts/instance-diet.py LIVE referenced on a wiring surface (q-system/.q-system/capability-manifest.json).
```

The manifest explicitly declares this script inert. Naming an engine in metadata is not wiring. The detector silently suppresses the finding it exists to produce.

### MAJOR: One caller marks every engine sharing the same basename LIVE, including engines at unrelated paths.

File: `q-system/.q-system/scripts/capability-map-gen.py:465`

Reproducer:

```bash
python3 "$TMPDIR/pr74-duplicate-basename-repro.py"
```

The fixture creates `live/worker.py`, `dead/worker.py`, and a caller for only `live/worker.py`.

Real output:

```text
dead/worker.py LIVE dead/worker.py: 47 lines; referenced on a wiring surface (run.sh).
live/worker.py LIVE live/worker.py: 47 lines; referenced on a wiring surface (run.sh).
```

This is a real repo shape. The checkout contains repeated names such as `core.py`, `search.py`, and `_sync_all.py`. A human must manually audit every duplicate because the generated LIVE status cannot be trusted.

## What is sound

The code survived these attacks:

- Shell callers outside `q-system/` are detected.
- Importing tests with unrelated filenames are detected.
- Markdown prose-only mentions remain UNWIRED.
- Self-references remain UNWIRED.
- `q-system/output/` artifacts are excluded as surfaces and engines.
- Dated snapshots are omitted.
- The nine new wiring tests pass.
- `capability-gate.py --check-only` is green.
- `git diff --check` passes and the worktree remains clean.

## Verdict

**VERDICT: REQUEST CHANGES**

Fix hidden and review-artifact exclusion first. It currently creates false tracked findings that flow into the permanent Linear audit path.

FINDINGS:
major|Hidden review artifacts are collected as real, trackable engines, producing false unattended audit findings.|q-system/.q-system/scripts/capability-map-gen.py:486
major|A filename inside a comment or declaration counts as an executable caller, so known inert engines are reported LIVE.|q-system/.q-system/scripts/capability-map-gen.py:464
major|One caller marks every engine sharing the same basename LIVE, including engines at unrelated paths.|q-system/.q-system/scripts/capability-map-gen.py:465
END FINDINGS
