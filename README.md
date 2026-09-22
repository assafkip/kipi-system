# Kipi

**Give your AI the right knowledge, at the moment it needs it.**

Kipi turns the scattered knowledge around your work into context that follows you across AI sessions: decisions, conversations, projects, people, commitments, lessons, documents, history.

You do not have to remember which file holds something, or tell Claude what to read. Ask a question. Kipi works out what you are asking about, reads the sources that matter for that kind of question, and puts the evidence in front of the model before it answers. Then it tells you what it found, which file and line each piece came from, which sources were empty, and which ones it could not read.

The result is an AI that does not start from zero every conversation. Your brain, externalized, with the plumbing that gets the right memory into active thought.

It runs in Claude Code. Plain markdown all the way down. No vector database, no black box. You can open every fact with `cat` and diff it with `git`.

---

## Memory is not useful if the AI never receives it

Saving information is the easy part. The hard part is getting the right information to the model when it matters.

Kipi's own history is the proof. Every store in the system had a writer and a hook guarding it. The fact graph refused to close a session if it had fallen behind. The commitment ledger dropped any promise it could not quote verbatim. The decision log refused an entry without a tag saying who decided. And nothing read any of it when a question arrived. A question naming a client got none of the client's facts. Careful storage, zero delivery.

So Kipi treats knowledge as a supply chain. Capture. Organize. Retrieve. Deliver. Prove what was delivered.

```mermaid
flowchart LR
    subgraph capture ["Capture"]
        C1["a debrief after a conversation"]
        C2["a handoff at session end"]
        C3["a mistake, and why it happened"]
    end
    subgraph organize ["Organize"]
        O1[("canonical: positioning, decisions, objections")]
        O2[("a dated fact graph: people, companies, pushback")]
        O3[("commitments, meetings, open follow-ups")]
        O4[("lessons, shared across every copy")]
    end
    subgraph retrieve ["Retrieve"]
        R["your question names a person,<br/>a project, or a kind of work"]
    end
    subgraph deliver ["Deliver"]
        D["verbatim lines, each with<br/>file, line, date and status"]
    end
    subgraph prove ["Prove"]
        P["a receipt per source: read, empty,<br/>unreadable or skipped.<br/>First line: FULL, PARTIAL or NONE"]
    end
    C1 --> O1
    C1 --> O2
    C2 --> O3
    C3 --> O4
    C4["the project's own documents,<br/>one knowledge base per case"] --> O5[("docs and sub-stores")]
    O1 --> R
    O2 --> R
    O3 --> R
    O4 --> R
    O5 --> R
    R --> D --> P
```

Ask about a person, and Kipi pulls their relationship history, the decisions that involved them, the commitments made to them, recent meetings, and the open follow-ups. Ask about a project, and a different set of sources becomes relevant. Ask it to build something, and the lessons from previous failures are placed in front of it before it starts.

The reader reads the project's own folder, never a template. Three things make that true:

- Sub-stores. A project can hold many knowledge bases, one per case or engagement, each with the same layout. Name one in a question and the search scopes to it. Name none and it searches all of them. A name that appears in several cases comes back as one block per case, never collapsed into the last one.
- The project's own documents. Eight declared folder names (`output`, `research`, `inputs`, `investigation`, `build`, `docs`, `notes`, `memory`) are searched under the project root and under every sub-store, one pass per question, every excerpt with its file and line. The list is data, not code: it is the `folders` key of `q-system/.q-system/knowledge-sources.json`, so a project can change what counts as a document folder.
- Candidates from the question itself. A capitalized word the index does not know is looked up in those documents. A hit makes it an entity. A word found in more than four knowledge bases is treated as common vocabulary, dropped, and the receipt says so.

The model never has to remember to go looking.

---

## It knows when it does not know

An empty search result is not proof that nothing exists. Most retrieval treats it that way.

Kipi's supply step writes a receipt. Every source the question needed is recorded as read, empty, unreadable, or cut short. The first line of what the model receives says `COVERAGE: FULL`, or `COVERAGE: PARTIAL` with the missing sources named, or `COVERAGE: NONE` when not one declared source could be read.

Where the line is drawn, precisely, because this is the sentence a reader trusts hardest. Only a source the manifest marks `required` can move the verdict. A deadline or a byte cap that cuts a required source short drops it to `COVERAGE: PARTIAL` and names the source. The same truncation on an optional source is written into that source's receipt row as `partially searched (...)` and leaves the verdict alone. In the shipped manifest the document scan is optional in all five task classes, so a truncated document pass can sit under `COVERAGE: FULL` with the truncation one line down in the receipt. If you want it to move the verdict, set `"required": true` for `docs` in `q-system/.q-system/knowledge-sources.json`, which is what the investigation manifest does. One function computes the verdict, in `q-system/.q-system/scripts/knowledge_supply.py`.

```mermaid
flowchart TB
    Q["ask about a client"] --> S{"each source the question needs"}
    S -->|"read, has lines"| A["supplied verbatim, with file and line"]
    S -->|"read, nothing there"| B["recorded: searched, empty"]
    S -->|"file missing or corrupt"| C["recorded: could not read"]
    S -->|"cut short, source is required"| D["recorded: partially searched"]
    S -->|"cut short, source is optional"| E["recorded: partially searched"]
    A --> F["COVERAGE: FULL"]
    B --> F
    E --> F
    C --> P["COVERAGE: PARTIAL, missing sources named"]
    D --> P
    C -. "every declared source unreadable" .-> N["COVERAGE: NONE"]
```

So there is a difference between these two sentences, and the system says which one is true.

"We searched the relevant sources and found nothing."

"We could not read two of the sources that might hold the answer."

Those should not produce the same confidence. Now they cannot.

---

## Why this is not search-and-paste

Technical readers will file this under retrieval-augmented generation. The retrieval is the boring half. What Kipi cares about is what the retrieval knew.

- Every excerpt is verbatim, with its file and line. There is no summarize step, because a summary is a copy that goes stale while the source moves.
- Every fact carries a status: known, stale, conflicting, or unvalidated. The newest fact on a subject wins. The older one is marked stale, never deleted.
- Every question leaves a receipt naming what was searched and what was not.
- Every name in a question that the index could not resolve goes to a misses ledger. That ledger is the data the next improvement runs on.
- Everything is a file. Open it, grep it, diff it, delete it.

---

## The more you work with it, the more useful its knowledge becomes

It learns in two ways.

**It learns about your world.** People, projects, decisions, preferences, relationships, commitments, terminology, history. A debrief after a conversation writes the facts. A handoff at the end of a session writes what tomorrow needs. Both are files, so both survive.

**It learns from what went wrong.** When the system makes a mistake and you work out why, the lesson becomes durable knowledge supplied to future work. Kipi used to show the model a list of lesson titles and hope it opened one. It did not. It hit the exact failure one of those titles described. Now the relevant lesson bodies are placed in the prompt before the work starts. And where a script can catch the mistake, the lesson becomes a check that refuses it.

```mermaid
flowchart LR
    subgraph world ["It learns about your world"]
        DB["a debrief after a conversation"] --> G["a dated fact graph,<br/>newest fact wins"]
        E["end of session"] --> HO["a handoff note, every claim<br/>labelled measured, stated or guessed"]
    end
    subgraph wrong ["It learns from what went wrong"]
        M["a mistake, and why it happened"] --> L["a lesson, shared across every copy,<br/>client data scrubbed"]
        M -. "when a script can catch it" .-> K["a check that refuses<br/>the same mistake"]
    end
    G -->|"a question naming someone"| S["the next session"]
    HO -->|"session start"| S
    L -->|"a request to build something"| S
    K -->|"every action"| S
```

It grades itself too. A newer fact supersedes an older one. A handoff line says whether it was measured, stated or guessed. A memory that never gets opened stops being trusted. A source that could not be read is recorded, never assumed empty.

Honest boundary: the lessons path proves the lesson entered the context. It cannot prove the model read it, or that it changed the work that followed. It is stronger than a promise, because a promise leaves no artifact. It is weaker than proof of application, and nothing here claims otherwise.

---

## What makes the knowledge trustworthy

Everything above rests on one thing: the model receives files it cannot talk its way past. That takes machinery. Here is the machinery.

```mermaid
flowchart LR
    F(["You"]) -->|"type"| CC["Claude Code session"]
    CC <-->|"small scripts run on every action"| H["Guardrails"]
    CC <-->|"reads and writes"| K[("Your knowledge:<br/>plain files on disk")]
    CC <-->|"deterministic tools"| M["Local tool server"]
    CC -->|"opens"| G["Pull requests + Linear issues"]
    J["Scheduled jobs on your machine"] -->|"review, merge, report"| G
    J --> K
    S[("One template repo")] -->|"one command"| I["Many copies,<br/>one per project"]
    I -. "each one is" .-> CC
```

You type into a Claude Code session. Before, during and after every action, small scripts
called hooks run. They add context the AI would otherwise forget, they block actions that
would break a rule, and they record what happened. The session reads and writes plain
files that hold what you know. A local tool server gives the AI checks that return the
same answer every time. Work leaves through pull requests and issues, where scheduled jobs
review, merge and report without you in the loop. All of it lives in one template
repository and is copied to every project you run.

### The ideas underneath

**1. Assume the AI is unreliable.** It invents facts, forgets what it read, agrees with
whoever is talking, and says "done" before anything ran. Nothing here makes it accurate.
Everything here makes its mistakes findable, so a wrong answer leaves a trail and a right
one carries its evidence.

**2. Files are receipts.** A chat transcript is folklore with a timestamp. A file can be
opened tomorrow, searched by a script, diffed, and dated. If you told the system something
and it did not make it into a file, it does not exist the next morning.

**3. Guardrails, not reminders.** A reminder is a sentence the AI is supposed to remember.
A guardrail is a script that runs whether or not anyone remembers. Anything a script can
check is checked by a script that can say no.

**4. You are never the next step.** Engineering signals go to a queue an agent drains. You
decide three things: publish, spend, delete. Everything else has a machine that owns it.

**5. One skeleton, many instances.** Improvements are made once and fanned out. Each copy
keeps its own facts; the template owns the machinery.

### What happens in one turn

```mermaid
sequenceDiagram
    participant Y as You
    participant S as Session
    participant H as Hooks
    participant A as AI
    Y->>S: open a session
    H-->>S: yesterday's handoff, open follow-ups, lessons learned, memories to doubt
    Y->>S: ask a question
    H-->>S: the facts behind any person or client you named, with a coverage line
    H-->>S: your writing voice if you are drafting, the relevant lessons if you are building
    S->>A: question plus that context
    A->>S: wants to edit a file or run a command
    alt a rule would break
        H-->>A: refused, with the reason
    else allowed
        S->>S: the tool runs
        H-->>A: findings on what was written, or nothing
    end
    A->>S: finishes
    H-->>A: refused if the answer claims something never checked
    H-->>S: commit the work, score the memories, log the effort
```

When you open a session, hooks put yesterday's handoff, your open follow-ups and the
lessons the whole fleet has learned in front of the AI. When you ask something, they add
the facts behind anyone you named, your writing voice if you are drafting, and the relevant
lessons if you are building. Before a tool runs, a hook can refuse it. After a file is
written, checks run on it. When the AI finishes, a last check can refuse the answer itself
if it asserts something it never opened. Then the work is committed and the session is
scored.

### How work leaves without you

```mermaid
sequenceDiagram
    participant D as A detector, or you
    participant L as Linear
    participant W as Worker
    participant R as Reviewer
    participant M as Merge
    D->>L: an issue is filed and labelled
    L->>L: triaged as worked, parked, or voided, with the reason recorded
    W->>L: claims a ready issue, one agent at a time
    W->>R: opens a pull request
    R->>R: a fresh-eyes review, verdict posted as a status
    alt changes requested
        R-->>W: findings, each reproduced
        W->>R: fixes, each with a test that fails without it
    else approved
        M->>M: checks green, merged automatically
    end
    M-->>L: issue closed with the command that proves it
```

Issues arrive from detectors or from you and are labelled so a machine-filed issue is
distinguishable from a human one. A triage pass records a decision on each so the board
does not only grow. A worker claims an issue under a lock, does the work on a branch and
opens a pull request. A reviewer that has never seen the code reads the diff and posts a
verdict. Fixes carry a test that fails without them. When every check is green, it merges
itself. Red states have machine consumers. When they cannot cope, a ticket says so in an
agent's queue, not yours.

### One template, many copies

```mermaid
flowchart LR
    SK[("kipi-system: the template")] -->|"kipi update"| U{"the updater"}
    REG["a registry of every copy"] --> U
    U -->|"dry run first, then apply"| I1["Copy A: your chief of staff"]
    U --> I2["Copy B: a client engagement"]
    U --> I3["Copy C: an investigation"]
    U -. "never touches" .-> OWN["each copy's own facts, contacts, memory"]
    I1 -->|"git commit before and after"| RB["one-command rollback"]
    I2 --> RB
    I3 --> RB
```

Every project is a full copy with its own facts and the same machinery. The updater has a
dry run that prints exactly what would be copied and removed per copy, and an apply that
fans the machinery out and leaves each copy's facts untouched. The apply has no prompt of
its own. It is a destructive operation, so an agent cannot run it: the hook that guards
destructive commands refuses it, and a person runs it after reading the dry run. It
commits before and after so any sync can be reverted alone. A copy with uncommitted work
refuses the sync rather than committing someone else's changes.

---

## The roles it runs today

Every copy shares the same skeleton and differs only in what it knows. Six roles are live right now.

- **Chief of staff.** Tracks conversations, talk tracks, decisions, positioning. Drafts updates, debriefs, follow-ups.
- **PM for a client engagement.** Coordinates multiple projects, logs every decision, drafts deliverables, tracks stakeholder context.
- **Lawyer.** Generates separation packages, contract redlines, compliance memos. Citations to relevant code on every position.
- **Investigator.** Manages active OSINT cases, evidence artifacts, published intel reports.
- **Operator for a consulting business.** Pipeline tracking, content cadence, deliverable production.
- **Architect for itself.** Manages its own PRDs, issues, reviews. The system builds the system.

---

## The full explanation

A handbook is in review as [PR #306](https://github.com/assafkip/kipi-system/pull/306): six short pages for anyone, each with a
drawing and a "what this means for you" section; fifteen deeper pages, one per part of the
system, each with two drawings and every script listed with what it does and the mistake
that made it exist; generated catalogs of every tool, hook, job and rule; and a coverage
check that fails, naming the gap, if any part of the code is missing from the docs. It
lands at `docs/README.md` when that review closes.

---

## Install

```bash
npm install -g @anthropic-ai/claude-code
git clone https://github.com/assafkip/kipi-system.git
cd kipi-system && claude
```

Setup walks you through who you are, what you work on, how you write, and who you know. Takes about 20 minutes. After that the system runs.

The scheduled jobs are a separate step. Nothing above arms them:

```bash
./kipi install-jobs
```

`install-plist.sh --all` enumerates every committed `com.kipi.*.plist` with `git ls-files`, renders each one against your checkout, loads it, and prints `N installed, N skipped, N failed (of N committed)`. Two jobs (`com.kipi.lessons-daily`, `com.kipi.lessons-drift`) are skipped outside the skeleton by design, because they shell the fleet updater; the run names them when it skips them. It exits non-zero and names any committed job it could not install, so a partial install is not silence.

---

## What else is in the box

The pages above are the knowledge half. The rest of the repo, with the command that counts each one:

- **A CLI with 23 verbs** (`grep -cE '^  [a-z][a-z0-9|_-]*\)' kipi`). `./kipi help` prints them. `check` runs the validation harness. `list` shows every copy. `health` finds dark or failing jobs, double schedules and open spillover. `work` and `converge` take a ready issue to an approved pull request. `judgment` freezes the context behind a triage decision so it can be replayed.
- **A local MCP server with 73 tools** (`grep -c '@mcp.tool' plugins/kipi-core/kipi-mcp/src/kipi_mcp/server.py`): deterministic linters and scorers, morning-routine step logging, follow-up loop tracking, backup, export, import.
- **21 namespaced slash commands**, listed above. Six in `kipi-core`, six in `kipi-dsse`, nine in `prd-os`.
- **65 hook entries** in `settings-template.json` (`grep -o '"command": "[^"]*"' settings-template.json | wc -l`), plus seven more in the plugins' own `hooks.json`. Every copy gets the same switches, because they ship as one file.
- **Six plugins** under `plugins/`, all six listed in `.claude-plugin/marketplace.json`.
- **16 launchd jobs** committed as plists. `./kipi install-jobs` enumerates them with `git ls-files`, so a plist outside the scripts directory is still reached; run `bash q-system/.q-system/scripts/install-plist.sh` with no arguments to see the label list it will install.

---

## Commands

Optional. Most usage is just talking to the system in Claude Code.

Two kinds, and the difference matters when you type one.

The `/q-*` names are **conventions**, not registered slash commands. No file under a `commands/` directory backs them. They are documented in `q-system/.q-system/commands.md`, the model reads that file, and saying one puts the session in that mode.

| Convention | What it does |
|---|---|
| `/q-debrief` | Extract insights from a conversation. Pasting a transcript runs it without being asked |
| `/q-draft` | Quick email, DM, or content draft in your voice |
| `/q-engage` | Generate engagement on someone else's post |
| `/q-research` | Citation-only research mode |
| `/q-morning` | The day brief: your calendar, mail needing an answer, your board. Also runs itself at 07:40 as the `com.kipi.morning-brief` job |
| `/q-wrap` | End-of-day health check |
| `/q-handoff` | Save context for next session |

The **registered** commands ship inside the plugins and are namespaced. Three of the six plugins carry them. `find plugins/*/commands -name '*.md'` lists all 21; the table names the shapes rather than every row, because the list is one command away and a front page is not a manifest.

| Command | What it does |
|---|---|
| `/kipi-core:wiring-check` | End-of-task gate: prove every change is connected |
| `/kipi-core:rca-start`, `/kipi-core:rca-check` | Scaffold a root-cause analysis, then lint it against the template |
| `/kipi-core:say` | Read the last answer back as audio |
| `/kipi-core:voice-refresh` | Rebuild the voice model from new meeting transcripts |
| `/kipi-core:linear-drain` | File the issues that were captured while offline |
| nine `/prd-os:*` | Rough idea to reviewed PRD to one issue spec per unit of work |
| six `/kipi-dsse:*` | Execute one issue under scope enforcement, with receipts |

---

## Connects to

Works standalone with local files. Each integration adds capability.

| Tool | Adds |
|---|---|
| Notion | CRM, project tracking |
| Google Calendar | Meeting detection, auto-prep |
| Gmail | Email monitoring |
| Linear | Issue tracking, the autonomous work queue |
| Slack | The morning brief |
| Chrome (DevTools MCP) | Web automation, LinkedIn |
| Apify | X/Twitter scraping |
| Reddit | Search and post tracking |

---

## ADHD-aware, not ADHD-only

I have AUDHD. Some design choices reflect that. Friction-ordered actions. No shame language. Effort tracking. Decision elimination. If you have executive function challenges, the system removes a lot of cognitive load by default.

If you don't, you still get an AI that doesn't make you decide who to contact, what order to do things in, or how to phrase the message.

---

## Security

- `.env`, credentials, and key files blocked from read/write
- PreToolUse hooks intercept dangerous operations
- No secrets in committed files
- Nine Bash denials, identical in both shipped settings files: `sudo`, force-push, hard reset, rebase, world-writable chmod, piped `curl` and `wget` installers, and the recursive remove at the filesystem root and on dot directories. Read the list yourself in the `permissions.deny` block of `settings-template.json`.
- The wider destructive-command guard (recursive removes anywhere, branch deletion, the fleet-wide sync, with a one-time approval token only a human shell can supply) runs on my machine and is **not shipped here in a form you can switch on**. The repo carries one copy, `q-system/.q-system/tests/fixtures/destructive-op-deny.reference.sh`, non-executable and named `.reference.` on purpose so it cannot be mistaken for the live gate. No installer writes it to a hook path: `install-capability-token.sh` patches a hook that already exists and exits without one when it does not. Read it and wire your own, or run without it.

---

## Origin

I'm [Assaf Kipnis](https://www.linkedin.com/in/assafkipnis/). 12 years in threat intelligence at LinkedIn, Google, Meta, and ElevenLabs. I burned out fighting the same problems over and over. Left corporate. Started [KTLYST](https://ktlystlabs.com), a security product that turns threat reports into governed, deployable artifacts.

Running a company solo with ADHD meant my brain couldn't hold everything it needed to hold. So I built a second one. It manages my work, writes in my voice, remembers what I forget, and compounds what I learn.

Right now it runs as six roles across every copy of my work. This repo is the general-purpose version. Fork it and teach it yours.
