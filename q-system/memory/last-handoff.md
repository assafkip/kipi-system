<!-- prompt-only-enforcement-skip: this handoff DESCRIBES state and names the executables,
     commits and issues holding each claim. It asserts no enforcement of its own. -->
# Last handoff

**Session:** 2026-09-14, the Research bot. The founder asked for a bot called research: type a Linear id or a question, an agent researches it, and a summary lands in the thread. Built, live, and reshaped the same day after his feedback on the output. Sana built all of it; this session wrote the spec, filed the issues, verified, and relayed.

## Where things stand

**Owner of everything open: Sana.** `provenance: standing rule`

### Shipped (chief main 49a9958)
- `bots/research/`, channel #research C0C1RP7RYUE. A top-level message is a new ask (a Linear id or a question); a thread reply is the next round on it. Runs detached on Sonnet 5, web only. `[verified: python3 -m chief.bots status prints "research: channel C0C1RP7RYUE ... jobs watch every 2m ... watch 2026-09-14 delivered"; launchctl list shows com.research.respond and com.research.watch]`
- Research commits on chief main today, ASK-1696 to ASK-1701. `[verified: git log origin/main --since 2026-09-14 in ~/projects/chief, 8 of 12 commits carry research or those ids, c3ed266 to 49a9958]`
- Citation law in code: a finding stays only if its URL came back from a tool call the run made, or (since ASK-1700) a finding an earlier round in the same thread kept. A brand-new URL never opened is still dropped. `[verified: check_report on a reused prior url with seen="" returned refused=True on e5bc23f, before the fix; Sana's post-fix test and mutation per her report]`
- The post is an answer (ASK-1701, founder 2026-09-14: "I want an answer, and then if I want more information, I'll ask."): a plain paragraph, then "Reply here for the sources or more detail." Sources appear only when a follow-up asks for them, decided in code from his words. The Linear comment keeps its links. `{{UNVERIFIED}}` by this session; live proof is Sana's, on thread 1789423914.970359.
- ASK-1697: `talk.interpret` crashed on every threaded reply with nothing pending, in every bot that owns a channel. Fixed in efa5571. `[verified: commit efa5571 on chief main]`
- ASK-1699: the chief README bot table lists every bot, with `tests/test_readme.py` holding it. `[verified: 11 folders under bots/ and 11 bot rows in README.md, counted by grep]`
- ASK-1534 (the Radar-filed research ask) is Done: cited findings in `consulting/q-consult/my-project/competitive-landscape.md` via consulting PR #123. `{{UNVERIFIED}}` by this session; per Sana's report.

### Records written
- Plan: `q-system/output/plans/research-bot-2026-09-14.md`. `provenance: observed`
- Memory: `project_research_bot.md`.

### Open, and the next step for each
- **ASK-1702** (Sana): the model's own counts in answers were wrong live ("Six vendors" with five named, "Six sources" above seven). The citation check does not look at numbers.
- **Sana's worktrees** `~/projects/_wt/chief-ask1700` and `~/projects/_wt/chief-ask1699` still exist; both branches merged. Hers to clean.
- **Fleet loop board is stale** (SessionStart said so): `python3 q-system/.q-system/scripts/fleet-loop-board.py`, republish to its artifact, then `fleet-board-refresh.py --mark-published`.
- **`.claude/` drift tripwire** at SessionStart: `.claude/output-styles/founder.md` modified and `.claude/rules/voice-loop-anywhere.md` removed, unsanctioned per `claude-integrity-tripwire.py`. Not touched this session.
- Carried from the 2026-09-11 handoff, not re-checked today: the 28 first touches cross the 5-day rung Tue 15 Sep; consulting docs PR #119; sp-236a280e, sp-4f6f086e; the ASK-1488 Reddit ping commit in `~/projects/consulting-ask1488`. `{{UNVERIFIED}}`

## Read this before touching the Research bot
- It runs a fresh process per message, so a merge needs no restart for research runs. The listener (`com.chief.listen`) still needs `launchctl kickstart -k gui/501/com.chief.listen` after an engine merge. `provenance: imported` (Sana's report and the 2026-09-11 handoff)
- Runs are web only on purpose: reading a repo while reading untrusted pages, with WebFetch as a way out, is a leak path (Sana's override, recorded on ASK-1696).
- Verify live, never only in pytest: five defects came from live rounds that the suite missed, per Sana's ASK-1696 report.
- Other sessions commit to chief main (radar landed #17 between Sana's passes). Work in a worktree. `[verified: git log origin/main shows e5bc23f (#17) between 61cc6a5 and bcea8fc]`
