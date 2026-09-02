# Kipi Research Brief: Business Use

## Core Position

Kipi is a persistent operating system around Claude Code.

It is not just a prompt pack, chatbot, or notes vault.

The useful claim is simple:

> Kipi remembers.

More precisely, it stores business context in files, brings that context into new sessions, and gives Claude a reliable trail to search before answering.

The system does not remember because the model has a magical memory. It remembers because the business record survives outside the model.

## The Knowledge Base

The knowledge base is the project's memory layer.

It is not one giant document. It is a set of connected records that Claude can search and use:

- conversations and debriefs
- decisions and promises
- relationship history
- current priorities and open loops
- drafts, reports, and other outputs

The important part is that the knowledge base lives with the project. It can be read, searched, versioned, and corrected. The model does not have to invent the history from a blank session.

That is what makes questions like "What did I promise this company?" useful. The answer has a place to come from.

## The Business Demo

The strongest explanation is not the architecture. It is what Assaf can ask from a project folder:

- What did Gaurav last say?
- What did I last promise this company?
- What do I need to do today?

These questions are useful because they match the moments where people stop trusting AI:

- The AI forgets a conversation.
- The AI loses the commitment made in a meeting.
- The AI cannot tell the founder what matters today.

With Kipi, Assaf opens Claude in the project folder and asks. The answer comes from the project's saved conversations, debriefs, decisions, relationship records, current state, and open loops.

Gaurav is a user-provided example here, not a verified record in this brief.

## The Precise Claim

Avoid saying that Kipi remembers everything in the human sense.

Say this instead:

> Kipi remembers the business context because the context lives in the project, not in a temporary chat window.

Or:

> I can open Claude in the project folder and ask what someone last said, what I promised, or what I need to do today. The system has a record to search.

The distinction matters:

- The model is not trusted to retain the business history.
- The project files are the memory.
- Claude reads the memory and reasons over it.
- Hooks and validation make parts of the process enforceable.

## How Kipi Works

### Files remember

Business knowledge lives in plain Markdown, JSONL, and Git-managed files.

Important layers include:

- `canonical/`: decisions, positioning, frameworks, and durable knowledge.
- `memory/`: working notes, outcomes, and earned-trust signals.
- `my-project/`: founder profile, relationships, current state, and priorities.
- `output/`: drafts, reports, schedules, and other artifacts.

### Sessions recover context

`q-system/hooks/session-start.py` loads handoffs, unconfirmed action cards, open loops, and morning status.

`q-system/hooks/post-compact.sh` restores mode, loop state, pipeline progress, positioning, and validation reminders after context compaction.

### Workflows turn memory into action

The agent pipeline splits larger routines into focused phases. Agents communicate through dated JSON bus files instead of relying on one long conversation.

That makes the system easier to inspect and easier to resume.

### Hooks check the work

Deterministic hooks validate paths, claims, voice, lessons, and dangerous operations.

The model can still make mistakes. The system makes those mistakes easier to find.

### Learning compounds

Memory outcomes are recorded as useful, dead-end, or corrected events. A deterministic scorer applies time decay and keeps earned trust separate from declared confidence.

Lessons can move across instances only after distillation, client-data scrubbing, and semantic verification. Failed checks hold the lesson instead of publishing it.

## Strongest Thesis

Kipi is not a second brain.

It is a durable business trail that Claude can read.

A second brain suggests storage and recall. Kipi adds workflow, validation, provenance, and action.

The sharp version:

> Files remember. Skills generate. Hooks check. Git propagates. Logs prove.

The architecture document says it even better:

> Trust moves from the model to the trail.

## Comparison With Claudesidian

Claudesidian is an Obsidian PARA second-brain starter kit for Claude Code. It focuses on thinking mode, writing mode, vault organization, skill discovery, Git, upgrades, and optional web and document tools.

The KB comparison found that Claudesidian's main useful gap for Kipi was skill-trigger measurement. The current Kipi repo now contains `q-system/.q-system/scripts/skill-trigger-eval.py`, so that distinction has changed.

Kipi currently goes further on:

- Operational workflows.
- Deterministic enforcement.
- Fleet propagation across instances.
- Memory outcomes and earned trust.
- Cross-instance lesson publication with client-data gates.

Source: `projects/Alice/q-system/output/plans/claudesidian-canonical-brief-2026-06-19.md`.

## Current Repo Corrections

The older research brief was stale in several places.

Current files confirm:

- The registry contains 25 instances, 24 `subtree` and 1 `standalone`.
- `kipi-rollback.sh` exists.
- `kipi update --dry` uses itemized `rsync -ain`.
- The updater checkpoints and restores untracked files in its write scope.
- Firecrawl scrape-to-file exists and is wired into research mode.
- The cross-instance lessons pipeline exists.
- Memory autocapture and earned-trust scoring exist.
- The skill-trigger evaluator exists.

Claims that still need qualification:

- `README.md` says six deployments, while the current registry says 25.
- "Remembers everything" is positioning language, not literal proof that every interaction is retained.
- The 30 to 50 percent token reduction is a documented estimate, not a measured result in this research pass.
- Cross-instance learning depends on the lesson pipeline and schedule. It is not instant after every message.
- Some voice-lint top-ups and benchmark work remain incomplete or need direct status verification.

## Proposed Instructional Post

### Recommended title

`I Did Not Build a Second Brain. I Built a Business Trail.`

### Opening

Start with the practical moment:

> I open Claude in the project folder and ask, "What did Gaurav last say?"

Then:

> Or, "What did I promise this company?" Or, "What do I need to do today?"

The point is not that Claude is clever. The point is that the project has a record.

### Sections

1. The trust problem: people do not trust AI to remember business context.
2. The simple fix: keep the memory in the project, outside the chat window.
3. The three questions: last conversation, last promise, today's work.
4. The system underneath: canonical files, memory, handoffs, open loops, and outputs.
5. The reliability layer: hooks, gates, provenance, and logs.
6. The compounding layer: useful memories become more trusted, and general lessons move across instances safely.
7. What Kipi is not: not a chatbot, not a prompt pack, and not only an Obsidian vault.
8. How to build the smallest version: one project folder, one canonical file, one handoff, one open-loop list, and one validation check.

### Central message

> Your AI does not need to remember by itself. Your business needs a memory it can read.

That is the argument. The architecture is there to prove it.

## ICP Clarification

The post should speak to small and medium-sized teams, especially founders and operators carrying too many projects at once.

The target reader has problems like:

- Projects falling behind because nobody has a reliable operating record.
- Hours lost re-reading old conversations and reconstructing context.
- Promises and follow-ups getting buried.
- Too many tools that require constant manual maintenance.
- More work coming in than the team can comfortably manage.
- A need to automate recurring work without becoming an AI systems builder.

This is not written for operators who are already building agent fleets, retrieval systems, or company brains.

It is written for people who have the same operating problems Assaf has:

- multiple projects
- competing commitments
- limited hours
- too much context to hold in one head
- a need to automate work without adding another complicated system

The reader should recognize the problem before hearing the architecture.

The commercial positioning is not "build a company brain because this technology is interesting."

It is:

> You are already losing time because the business context is scattered. A small project-based system can remember the work, surface what matters, and remove repeated explanation.

The post should sell relief and capacity, not technical sophistication.

## Next Research Phase: Popular X Posts

Assaf will provide popular X posts from the same space. Analyze them for:

- Why they received interaction.
- Which pain, tension, story, claim, or format made people respond.
- Whether the interaction came from usefulness, identity, controversy, novelty, status, or distribution.
- What readers believed they would gain by replying, reposting, or saving.
- Which parts are attention mechanics and which parts represent real system value.

Then compare each post with Kipi:

- What the post claims or demonstrates.
- What Kipi actually does.
- Where Kipi is different.
- Where Kipi is stronger.
- Where the post is stronger at attention or explanation.
- What Kipi should borrow in framing without copying the claim.
- What Kipi should not claim because the evidence does not support it.

The comparison must separate two questions:

1. Why did this post get interaction?
2. Why is Kipi a different or better system for business continuity?

High interaction is not proof of better product value. Treat it as evidence about attention, framing, audience pain, and distribution.

The output should produce:

- A post-by-post interaction analysis.
- Repeated patterns across the sample.
- A Kipi differentiation map.
- Messaging opportunities for the instructional post.
- Claims to avoid.
- A final positioning statement grounded in the strongest evidence.

## Status

- Research brief saved.
- Business-use framing added.
- X-post comparison phase saved and ready for source material.
- Article not drafted yet.
- Gaurav remains an illustrative example supplied by Assaf, not a verified record in this brief.
