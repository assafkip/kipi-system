<!-- prompt-only-enforcement-skip: this handoff DESCRIBES state and names the executables,
     commits and issues holding each claim. It asserts no enforcement of its own. -->
# Last handoff

**Session:** 2026-09-11 late evening, chief question lane (background job 30531a6d, ASK-1494). A typed question in #chief-of-staff now gets a short answer read from the client's own instance. Fourteen commits on chief main 1534bba to e79664f, pushed; 492 tests green per commit; four live rounds verified by script and by hand against the instance files. The SOW rows and the CRM ledger's promises are out of every bot (the brief, the follow-ups, prep, the question lane).

## Where things stand

**Owner of everything open: Sana.** ASK-1494 is labelled owner:sana and needs-triage; her ruling and the two follow-up comments (the one deviation, the direction change) are on it. `provenance: standing rule`

### Shipped (chief main, verified live at 21:27 to 21:31 PT)
- A question is decided in code before any model call (`talk.is_question`, `talk.QUESTION_WORDS`, `talk.ACTION_WORDS`, a bot's intent names on the first word); the reply is six lines with a `Read:` line last (`answer.cap`, `ANSWER_LINES`, `LINE_CHARS`), a trailing question back at him cut. `[verified: "what do I have to do today?" answered in 2 body lines, no interpreter call; tests/test_talk.py, nineteen messages parametrized plus a mutation test]`
- A client question reads the client's own instance: `chief/instance.py` reads `q-<name>/memory/last-handoff.md`, the `.active-case`, `dashboard.md`, `investigation-state.md` and the newest cases (six files, 16k chars) and runs the instance's `knowledge-inject.py` as a subprocess. The pack leads with STATE and KNOWLEDGE; SOW rows and the CRM ledger's promises are out of the lane. `[verified: "what do I owe pure spectrum?" at 21:28 is line for line q-pure/memory/last-handoff.md "In flight" and "The one check that matters next"; the founder rejected the ledger and SOW answers at 21:15]`
- The SOW reader and Chief's ledger collector are retired (265268e): `state.derive` yields no `owed` kind in any bot, Chief's promise rows are his own (`own_promises`, typed or debrief), prep carries an `Instance (...)` line from the client's handoff. `[verified: dry-run brief on main prints the meeting, the ceo@centfm.com reply and the Portant intro report as rows 1 to 3; tests/test_bots.py over the real bots dir]`
- A typed word resolves against every open promise, due or not (615ddf7). `[verified: "let go the Sheehy promise" confirmed by name at 21:41; founder_close and let_go rows on cid ac36b29087660d9e]`
- Every bot's respond poll scans the last day's threads for a reply the listener missed, answers it in its thread once, and 'ignore it' in a thread is let_go (a4eb162, f5cb66a). `[verified: listener unloaded, thread reply typed, poll by hand acted 1 then 0, reply "Let go: pure-spectrum: promised six-check memo, due Fri 18 Sep"]`
- Every bot names its truth repos in `bot.toml [truth]` and answers like a session opened there: the repo's newest q-dir handoff and dashboard in the pack, its own knowledge reader run on the question, Grep over the repo (e79664f). `[verified: #triage answered from kipi-system's handoff and #prs from consulting's at 22:15, every id in the reply present in the file by grep; tests/test_bots.py holds the repos exist on disk]`
- THIS WEEK (effective closes, mail he sent tagged by client, Chief's sends, commits per client, issues moved, meetings held on his calendars, cancelled skipped) for a question carrying week, accomplish, did, built or shipped. `[verified: the 21:31 reply; 3 closes, 36 mails, 201 commits, 3 meetings match the script]`
- Lint over the last replies: messages 4 then 1, thread walls 0, max lines 0, engine words 0, em dashes 0. `[verified: slack-audhd-lint.py pull --since 1789187200 and 1789187400, then lint]`

### Records written
- Plan record addendum with the four replies verbatim and the hand check: `q-system/output/plans/grokbot-bot-evaluation-2026-09-10.md`, "2026-09-11 evening addendum: the question lane (ASK-1494)".
- Memory: `project_grokbot_vs_kipi_research.md` updated (the founder's direction on the source of truth, verbatim).

### Open, and the next command for each
- **sp-4a8bf988**: fixed by a4eb162 and f5cb66a (the poll reads threads; 'ignore it' is let_go); resolves in the ledger once ASK-1494 closes.
- **sp-2a389b7a**: fixed by 265268e (the SOW rows are out of the brief); the ledger resolves it once ASK-1494 closes.
- **The instance reader returns zero bytes for a bare client name** (its own contract); KNOWLEDGE fills only when the question names a person or proper noun the index knows. The model keeps Grep over the instance folder and the prompt starts it there.
- **"what do I owe all points?"** read the instance's stale handoff (2026-08-24) and case-043's state (2026-09-04): the instance's own files are the source, and they are as fresh as his last /q-end there.
- Carried from the previous session: the 28 first touches cross the 5-day rung Tue 15 Sep; consulting docs PR #119; sp-236a280e, sp-4f6f086e; the ASK-1488 Reddit ping commit in `~/projects/consulting-ask1488`.

## Read this before touching Chief
- The client's own instance is the source of truth for what he owes (founder-directed 2026-09-11): `q-<name>/memory/last-handoff.md` and `dashboard.md`, plus the knowledge reader. The `q-system/` copy of the handoff is months stale in every instance. Never the CRM ledger, never the SOW rows.
- Verify a bot live: eleven defects came from four live rounds tonight, none from 497 green tests. Type the question in the channel, pull the thread with Chief's token, check every fact by script, then paste.
- Restart `com.chief.listen` after every merge (`launchctl kickstart -k gui/501/com.chief.listen`); the poll job reads main on its own.
- The pre-commit suite runs the whole working tree: stash a red test file before committing the commit that precedes its fix.
- Plain `git commit` only (lefthook); the worktree is `~/projects/chief-fold` on `fold`, ff-only into `~/projects/chief` main.
