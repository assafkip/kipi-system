# 1 year of prompts. A 21-byte file fixed it.

I spent a year trying to solve AI memory with better prompts. I tried system prompts, custom instructions, memory rules pinned to every conversation. None of it stuck. The model forgot my client mid-session. By Tuesday, it had forgotten which of five projects I was on.

That's prompt theater. You write the rules. The model agrees. Three turns later the rules are gone.

Then I tried something different.

My consulting practice resolves "which client am I on" through a single text file. It's 21 bytes, named `.active-case`. The slug inside is something like `case-014-trump-coin`. That's it.

Twenty-four custom skills read that file. Each one resolves the active case by checking that one string before doing anything else.

The first time it worked across sessions, I realized I'd had the architecture backwards for a year.

## LLM is the interpreter. Filesystem is the contract.

Context window is rented memory. You pay for it in tokens. It evaporates when you close the tab.

Filesystem is your memory. It survives reboots, audits, and the eventual collapse of any AI vendor. Every Unix tool you've used already knows how to read it.

Most people treat AI as the brain and the filesystem as backup. It's the opposite. Filesystem is the brain. AI is a pattern-matcher you call in when you need text generated against a context the filesystem hands it.

## Hooks are contracts. Prompts are aspirations.

Last week I ran four research agents in parallel against systems I built on this skeleton. All four hit a hard stop at exactly fifty tool calls. Not because of a system prompt asking the agent nicely. Because a Python script called `token-guard.py` exited non-zero on the fifty-first call.

The agent had no choice. Its instructions said to use as many tools as it needed. The hook fired anyway and the session ended.

A skill that says "don't list things in threes" is a hope. A Python script that catches three consecutive sentences with the same first word is the wall.

Anything that has to be true gets enforced by code. Not by a markdown file asking politely.

## The model becomes useful because it can read.

A year ago I thought building an AI system meant prompt engineering. It doesn't.

It means deciding what shape your work actually has. Naming the unit. Pinning the state to disk where the model can read it.

What's in your context window right now that isn't on disk?
